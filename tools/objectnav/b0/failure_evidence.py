#!/usr/bin/env python3
"""Phase 3, step 4: offline failure evidence for a B0 run (Habitat interpreter, evaluator only).

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/failure_evidence.py \
        runs/objectnav/b0/dev1 --set hm3d_v2 --split val

For every episode B0 recorded its detection frames (camera pose, intrinsics,
goal-category detections with masks) in <run>/evidence/<uid>.jsonl.gz. This
tool re-renders the SEMANTIC view of the annotated scene at each of those
camera poses and derives, per episode:

  target_seen        a goal instance of the episode covers >= 100 pixels
                     within 3 m in at least one detection frame;
  target_detected    a detection of the target category (any score kept by
                     the runtime, >= 0.25) overlaps a goal instance with
                     IoU >= 0.1 in some frame;
  stop_object        for a STOP on a candidate: the semantic instance that
                     dominates that candidate's masks, its name, and whether
                     it is a goal instance (stop_near_false_detection = not a goal);
  confirmed_goal     whether any confirmed candidate was a goal instance.

Writes <run>/trajectories-evidence.jsonl (uid -> evidence) and
<run>/trajectories+evidence.jsonl (trajectories with the evidence merged, for
tools/objectnav/score_trajectories.py). Semantic ground truth stays offline.
"""
import argparse
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.detector_eval.masks import dominant_instance, iou, rle_decode  # noqa: E402
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set  # noqa: E402

MIN_PIXELS = 100
NEAR_M = 3.0
LOOSE_IOU = 0.1
CAMERA_Y = 1.2
WIDTH, HEIGHT, HFOV = 640, 480, 90.0


def habitat_camera(T_world_camera):
    """Canonical z-up camera pose (optical x right, y down, z forward) -> Habitat agent position + yaw."""
    T = np.asarray(T_world_camera, float)
    t, forward = T[:3, 3], T[:3, 2]
    position = np.array([t[0], t[2] - CAMERA_Y, -t[1]])          # canonical (x, y, z) -> habitat (x, z, -y)
    fx, fz = forward[0], -forward[1]                                 # habitat forward x, z
    return position, math.atan2(-fx, -fz)


def open_semantic_sim(scene_path, dataset_config, robot, gpu_device_id=-1):
    """The phase-2 renderer (rgb + depth + semantic): a semantic sensor without an
    RGB sensor renders nothing in this Habitat build."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('sample_views', ROOT / 'tools/objectnav/detector_eval/sample_views.py')
    views = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(views)
    return views.open_sim(scene_path, dataset_config, robot, semantic=True, gpu_device_id=gpu_device_id)


def render(sim, position, yaw):
    import habitat_sim
    from habitat_sim.utils.common import quat_from_angle_axis
    state = habitat_sim.AgentState()
    state.position = np.asarray(position, np.float32)
    state.rotation = quat_from_angle_axis(float(yaw), np.array([0.0, 1.0, 0.0]))
    sim.get_agent(0).set_state(state, reset_sensors=True)
    obs = sim.get_sensor_observations()
    return np.asarray(obs['semantic']).astype(np.uint32), np.asarray(obs['depth'], np.float64)


def names_from_semantic_txt(scene_path):
    path = Path(scene_path.replace('.basis.glb', '.semantic.txt'))
    names = {}
    if path.is_file():
        for line in path.read_text().splitlines()[1:]:
            parts = line.split(',')
            if len(parts) >= 3 and parts[0].strip().isdigit():
                names[int(parts[0])] = parts[2].strip().strip('"')
    return names


def episode_evidence(frames, goal_ids, target, record, render_fn, names):
    seen = detected = False
    aligned = checked = 0
    stop_masks, confirmed_masks = [], defaultdict(list)
    stop = ((record['diagnostics'].get('policy') or {}).get('stop') or {})
    stop_cid = stop.get('cid')
    cand_rows = (record['diagnostics'].get('policy') or {}).get('candidates', [])
    confirmed = {c['cid'] for c in cand_rows if c.get('confirmed')}
    for row in frames:
        dets = row['detections']
        if seen and not any(d['goal'] == target for d in dets):
            continue                        # nothing left to learn from this frame
        sem, depth = render_fn(row['T_world_camera'])
        small = row.get('depth_small_cm')
        if small is not None:                # pose check: runtime depth vs re-rendered depth
            ref = np.asarray(small, float) / 100.0
            got = depth[10::20, 10::20][:ref.shape[0], :ref.shape[1]]
            ok = (ref > 0.2) & (got > 0.2)
            if ok.sum() >= 20:
                checked += 1
                aligned += float(np.median(np.abs(ref[ok] - got[ok]))) < 0.05
        for gid in goal_ids:
            m = sem == gid
            if m.sum() >= MIN_PIXELS and float(np.median(depth[m])) <= NEAR_M:
                seen = True
                break
        for d in dets:
            if d['goal'] != target:
                continue
            mask = rle_decode(d['rle'])
            if not detected and any(iou(mask, sem == gid) >= LOOSE_IOU for gid in goal_ids):
                detected = True
            if d['cid'] is not None and d['cid'] == stop_cid:
                stop_masks.append(dominant_instance(sem, mask))
            if d['cid'] in confirmed:
                confirmed_masks[d['cid']].append(dominant_instance(sem, mask))

    def dominant(pairs):
        votes = Counter(i for i, share in pairs if i and share >= 0.3)
        return votes.most_common(1)[0][0] if votes else None

    out = dict(target_seen=seen, target_detected=detected, frames=len(frames),
               pose_check=dict(checked=checked, aligned=aligned))
    if stop_cid is not None:
        inst = dominant(stop_masks)
        out.update(stop_object=dict(cid=stop_cid, instance=inst, name=names.get(inst) if inst else None,
                                    is_goal=bool(inst in goal_ids) if inst else None, masks=len(stop_masks)),
                   stop_near_false_detection=(inst is not None and inst not in goal_ids))
    out['confirmed_candidates'] = {str(cid): dict(instance=dominant(p), is_goal=dominant(p) in goal_ids,
                                                  name=names.get(dominant(p)))
                                   for cid, p in confirmed_masks.items()}
    out['confirmed_goal'] = any(v['is_goal'] for v in out['confirmed_candidates'].values())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dir', type=Path)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--runner-config', type=Path, default=ROOT / 'configs/objectnav/lockstep-b0.json')
    a = ap.parse_args(argv)
    records = [json.loads(l) for l in (a.run_dir / 'trajectories.jsonl').read_text().splitlines() if l.strip()]
    episodes = {e.uid: e for e in load_episode_set(a.episode_set, a.split, a.habitat_data)}
    by_scene = defaultdict(list)
    for r in records:
        by_scene[episodes[r['uid']].scene_path].append(r)
    evidence = {}
    for scene, group in sorted(by_scene.items()):
        ep0 = episodes[group[0]['uid']]
        runner = json.loads(a.runner_config.read_text())
        sim = open_semantic_sim(scene, ep0.eval_dataset_config, runner['robot'],
                                int(runner['sensor'].get('gpu_device_id', -1)))
        names = names_from_semantic_txt(scene)
        try:
            for r in group:
                ep = episodes[r['uid']]
                base = dict(r.get('evidence') or {})
                pol = (r['diagnostics'].get('policy') or {})
                path = pol.get('evidence_file')
                if not path or not Path(path).exists():
                    evidence[r['uid']] = dict(base, evidence_missing=True)
                    continue
                with gzip.open(path, 'rt') as stream:
                    frames = [json.loads(l) for l in stream if l.strip()]
                goal_ids = {int(g.object_id) for g in ep.goals}
                ev = episode_evidence(frames, goal_ids, ep.object_category, r,
                                      lambda T: render(sim, *habitat_camera(T)), names)
                evidence[r['uid']] = dict(base, **ev)
                print('%s %-10s seen=%s detected=%s pose=%s stop=%s' % (
                    r['uid'], ep.object_category, ev['target_seen'], ev['target_detected'], ev['pose_check'],
                    ev.get('stop_object')), flush=True)
        finally:
            sim.close()
    out = a.run_dir / 'trajectories-evidence.jsonl'
    out.write_text(''.join(json.dumps(dict(uid=u, evidence=v)) + '\n' for u, v in sorted(evidence.items())))
    merged = a.run_dir / 'trajectories+evidence.jsonl'
    merged.write_text(''.join(json.dumps(dict(r, evidence=evidence.get(r['uid'], r.get('evidence')))) + '\n'
                              for r in records))
    counts = Counter()
    for v in evidence.values():
        counts['seen'] += bool(v.get('target_seen'))
        counts['detected'] += bool(v.get('target_detected'))
        counts['stop_on_goal'] += bool((v.get('stop_object') or {}).get('is_goal'))
        counts['stop_on_wrong'] += bool(v.get('stop_near_false_detection'))
        counts['confirmed_goal'] += bool(v.get('confirmed_goal'))
        pc = v.get('pose_check') or {}
        counts['pose_frames_checked'] += pc.get('checked', 0)
        counts['pose_frames_aligned'] += pc.get('aligned', 0)
    print('episodes %d: %s' % (len(evidence), dict(counts)))
    print('wrote', out, 'and', merged)


if __name__ == '__main__':
    main()
