#!/usr/bin/env python3
"""Phase 3: why did B0 get stuck? (Habitat interpreter; offline diagnosis only)

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/diagnose_stuck.py \
        runs/objectnav/b0/dev1-diag --set hm3d_v2 --split val

For every episode that ended with B0's 'stuck' stop:

* the robot's own map around the final pose (evidence/<uid>.stuck.npz written
  by B0) rendered to evidence/<uid>.stuck.png: free light, occupied black,
  unknown grey, robot footprint red, heading blue;
* the simulator side at the final pose, on the robot-body navmesh
  (r 0.2 m, h 1.5 m): navmesh height under the robot vs the planar anchor
  height, distance to the closest navmesh obstacle, and the simulator step
  filter for a 5 cm step in 16 headings, classified like the planar adapter
  (habitat_worker.py): 'ok', 'height>5cm' (navmesh height off the anchor by
  more than 5 cm), 'slide' (filter moved the body off the straight segment),
  'blocked' (no motion);
* the last runner cycles (decision / guard / worker reasons).
"""
import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set  # noqa: E402

STEP_M = 0.05


def classify_step(start, candidate, end, anchor):
    if abs(candidate[1] - anchor) > 0.05:
        return 'height>5cm'
    delta = end[[0, 2]] - start[[0, 2]]
    offset = candidate[[0, 2]] - start[[0, 2]]
    fraction = float(offset @ delta / (delta @ delta))
    projected = start[[0, 2]] + max(0., min(1., fraction)) * delta
    if fraction <= 1e-6:
        return 'blocked'
    if np.linalg.norm(candidate[[0, 2]] - projected) > 1e-4:
        return 'slide'
    return 'ok' if fraction > 0.999 else 'partial'


def render(npz_path, png_path):
    d = np.load(npz_path)
    states = d['states']
    res, (ox, oy) = float(d['resolution_m']), d['origin_xy']
    x, y = d['robot_xy']
    counts = {name: int((states == v).sum()) for name, v in (('free', 0), ('occupied', 100), ('unknown', -1))}
    k = int(round(0.3 / res))
    r, c = int((y - oy) / res), int((x - ox) / res)
    disc = states[max(0, r - k):r + k + 1, max(0, c - k):c + k + 1]
    near = {name: int((disc == v).sum()) for name, v in (('free', 0), ('occupied', 100), ('unknown', -1))}
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return counts, near
    rgb = np.full(states.shape + (3,), 150, np.uint8)            # unknown
    rgb[states == 0] = (235, 235, 225)                             # free
    rgb[states == 100] = (20, 20, 20)                              # occupied
    rgb = rgb[::-1]                                               # rows grow with +y: flip for display
    scale = 6
    img = Image.fromarray(rgb).resize((rgb.shape[1] * scale, rgb.shape[0] * scale), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    px, py = (x - ox) / res * scale, (states.shape[0] - (y - oy) / res) * scale
    rad = 0.25 / res * scale
    draw.ellipse([px - rad, py - rad, px + rad, py + rad], outline=(220, 30, 30), width=2)
    yaw = float(d['yaw_rad'])
    draw.line([px, py, px + 2 * rad * math.cos(yaw), py - 2 * rad * math.sin(yaw)], fill=(30, 60, 220), width=3)
    img.save(png_path)
    return counts, near


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dir', type=Path)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--runner-config', type=Path, default=ROOT / 'configs/objectnav/lockstep-b0.json')
    a = ap.parse_args(argv)
    runner = json.loads(a.runner_config.read_text())
    records = [json.loads(l) for l in (a.run_dir / 'trajectories.jsonl').read_text().splitlines() if l.strip()]
    stuck = [r for r in records if r['diagnostics'].get('end_reason') == 'policy_stop:stuck']
    episodes = {e.uid: e for e in load_episode_set(a.episode_set, a.split, a.habitat_data)}
    by_scene = defaultdict(list)
    for r in stuck:
        by_scene[episodes[r['uid']].scene_path].append(r)
    import importlib.util
    spec = importlib.util.spec_from_file_location('stop_calibration', ROOT / 'tools/objectnav/b0/stop_calibration.py')
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    summary = []
    for scene, group in sorted(by_scene.items()):
        ep0 = episodes[group[0]['uid']]
        sim = cal.open_sim(scene, ep0.eval_dataset_config, runner['robot'], int(runner['sensor'].get('gpu_device_id', -1)))
        try:
            pf = sim.pathfinder
            for r in group:
                import re
                tag = re.sub(r'[^A-Za-z0-9_.-]', '_', r['uid'])
                pos = np.asarray(r['positions'][-1], float)
                anchor = float(pos[1])
                npz = a.run_dir / 'evidence' / (tag + '.stuck.npz')
                row = dict(uid=r['uid'], path_m=r['diagnostics']['path_m'],
                           accepted_no_motion=r['diagnostics'].get('blocked_moves'))
                if npz.exists():
                    counts, disc = render(npz, npz.with_suffix('.png'))
                    row.update(map_counts=counts, footprint_cells=disc, png=str(npz.with_suffix('.png')))
                snapped = np.asarray(pf.snap_point(pos.astype(np.float32)), float)
                row['navmesh_y_minus_anchor_m'] = round(float(snapped[1] - anchor), 3) if np.isfinite(snapped).all() else None
                row['navmesh_xz_offset_m'] = round(float(np.hypot(*(snapped - pos)[[0, 2]])), 3) if np.isfinite(snapped).all() else None
                row['distance_to_obstacle_m'] = round(float(pf.distance_to_closest_obstacle(pos.astype(np.float32), 2.0)), 3)
                steps = Counter()
                for k in range(16):
                    t = 2 * math.pi * k / 16
                    end = pos + STEP_M * np.array([math.cos(t), 0., math.sin(t)])
                    cand = np.asarray(sim.step_filter(pos.astype(np.float32), end.astype(np.float32)), float)
                    steps[classify_step(pos, cand, end, anchor)] += 1
                row['step_filter_16_headings'] = dict(steps)
                row['reason_tail'] = r['diagnostics'].get('reason_tail', [])[-8:]
                summary.append(row)
                print(json.dumps(row))
        finally:
            sim.close()
    (a.run_dir / 'stuck_diagnosis.json').write_text(json.dumps(summary, indent=1) + '\n')
    agg = Counter()
    for row in summary:
        s = row['step_filter_16_headings']
        agg['all 16 headings blocked by height>5cm' if s.get('height>5cm', 0) == 16 else
            'no free heading (height/slide/blocked)' if not s.get('ok') else 'some heading steps ok'] += 1
    print('episodes', len(summary), dict(agg))


if __name__ == '__main__':
    main()
