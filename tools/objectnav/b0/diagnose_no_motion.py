#!/usr/bin/env python3
"""Phase 3: why did the simulator not move the body for an accepted pulse? (Habitat interpreter; offline)

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/diagnose_no_motion.py \
        runs/objectnav/b0/dev3-diag --set hm3d_v2 --split val --runner-config configs/objectnav/lockstep-b0-v2.json

Reads diagnostics.no_progress_samples (runner: accepted pulses whose body pose did
not change) and, at each distinct spot, asks the simulator's step filter on
the robot-body navmesh what the commanded pulse and 16 headings of 5 cm do,
classified as in diagnose_stuck.py ('ok', 'height>5cm', 'height>10cm',
'slide', 'blocked', 'partial'). Also: navmesh height and xz offset under the
body, is_navigable, distance to the closest navmesh obstacle. Read-only.
"""
import argparse
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set  # noqa: E402


def classify(start, cand, end, anchor):
    dy = abs(cand[1] - anchor)
    delta = end[[0, 2]] - start[[0, 2]]
    offset = cand[[0, 2]] - start[[0, 2]]
    frac = float(offset @ delta / (delta @ delta))
    proj = start[[0, 2]] + max(0., min(1., frac)) * delta
    if frac <= 1e-6 and np.linalg.norm(offset) <= 1e-6:
        kind = 'blocked'
    elif np.linalg.norm(cand[[0, 2]] - proj) > 1e-4:
        kind = 'slide'
    else:
        kind = 'ok' if frac > 0.999 else 'partial'
    if dy > 0.10:
        return 'height>10cm'
    if dy > 0.05:
        return kind + '+height5-10cm'
    return kind


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dir', type=Path)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--runner-config', type=Path, default=ROOT / 'configs/objectnav/lockstep-b0-v2.json')
    a = ap.parse_args(argv)
    runner = json.loads(a.runner_config.read_text())
    records = [json.loads(l) for l in (a.run_dir / 'trajectories.jsonl').read_text().splitlines() if l.strip()]
    episodes = {e.uid: e for e in load_episode_set(a.episode_set, a.split, a.habitat_data)}
    by_scene = defaultdict(list)
    for r in records:
        if r['diagnostics'].get('no_progress_samples'):
            by_scene[episodes[r['uid']].scene_path].append(r)
    spec = importlib.util.spec_from_file_location('stop_calibration', ROOT / 'tools/objectnav/b0/stop_calibration.py')
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    rows = []
    for scene, group in sorted(by_scene.items()):
        ep0 = episodes[group[0]['uid']]
        sim = cal.open_sim(scene, ep0.eval_dataset_config, runner['robot'], int(runner['sensor'].get('gpu_device_id', -1)))
        try:
            pf = sim.pathfinder
            for r in group:
                anchor = float(r['positions'][0][1])          # planar adapter keeps the launch height
                spots = {}
                for s in r['diagnostics']['no_progress_samples']:
                    spots.setdefault((tuple(s['xy']), s['yaw']), []).append(s)
                for (xy, yaw), samples in spots.items():
                    pos = np.array([xy[0], anchor, -xy[1]], float)       # canonical (x, y) -> Habitat (x, y, -y)
                    snapped = np.asarray(pf.snap_point(pos.astype(np.float32)), float)

                    def step(t, dist):
                        end = pos + dist * np.array([math.cos(t), 0., -math.sin(t)])
                        cand = np.asarray(sim.step_filter(pos.astype(np.float32), end.astype(np.float32)), float)
                        return classify(pos, cand, end, anchor), cand

                    lin = samples[0]['linear_mps']
                    cmd_kind, cand = step(yaw, max(lin * 0.3, 0.01))
                    heads = Counter(step(2 * math.pi * k / 16, 0.05)[0] for k in range(16))
                    row = dict(uid=r['uid'], xy=list(xy), yaw=yaw, samples=len(samples), decision=samples[0]['decision'],
                               commanded=cmd_kind, commanded_dy_m=round(float(cand[1] - anchor), 3),
                               is_navigable=bool(pf.is_navigable(pos.astype(np.float32))),
                               navmesh_y_minus_anchor_m=round(float(snapped[1] - anchor), 3) if np.isfinite(snapped).all() else None,
                               navmesh_xz_offset_m=round(float(np.hypot(*(snapped - pos)[[0, 2]])), 3) if np.isfinite(snapped).all() else None,
                               distance_to_obstacle_m=round(float(pf.distance_to_closest_obstacle(pos.astype(np.float32), 2.0)), 3),
                               headings_16=dict(heads))
                    rows.append(row)
                    print(json.dumps(row))
        finally:
            sim.close()
    (a.run_dir / 'no_motion_diagnosis.json').write_text(json.dumps(rows, indent=1) + '\n')
    print('spots', len(rows), 'commanded pulse:', dict(Counter(r['commanded'] for r in rows)))


if __name__ == '__main__':
    main()
