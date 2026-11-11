#!/usr/bin/env python3
"""Phase 2, step 1: render RGB-D + semantic views on the DEV scenes (Habitat interpreter).

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/detector_eval/sample_views.py \
        --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --out-dir runs/objectnav/detector_eval/views

Evaluator-only: uses the annotated scene config and the navmesh. Camera = the
runner's primary sensor (640x480, hfov 90, 1.2 m), body on the robot navmesh.

View sets per scene:
  path  poses every --path-step m along the robot-navmesh shortest path from
        each dev episode start to its nearest goal view point, heading along
        the path and +-45 deg;
  scan  --scan-points random navigable points x --headings headings.

Writes frames/<frame_id>.npz (rgb uint8, depth_mm uint16, semantic uint32),
views.jsonl (pose, visible goal instances with pixels and median depth) and
scenes.json (goal instance ids and semantic.txt names, alignment check).
Ground-truth instances are the episodes' goals_by_category object ids.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.evaluation.quality_semantic_gt import ALIGNMENT_POLICY, parse_annotations, validate_alignment  # noqa: E402
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, read_manifest  # noqa: E402

WIDTH, HEIGHT, HFOV, CAMERA_Y = 640, 480, 90.0, 1.2
MIN_PIXELS = 100


def open_sim(scene_path, dataset_config, robot, *, semantic, gpu_device_id=-1):
    import habitat_sim
    cfg = habitat_sim.SimulatorConfiguration()
    # Same renderer selection as the runtime sensor worker (configs/objectnav/lockstep-b0.json:
    # gpu_device_id -1). Device 0 means "CUDA device 0", which this laptop does not have.
    cfg.gpu_device_id = int(gpu_device_id)
    cfg.scene_id = scene_path
    cfg.scene_dataset_config_file = dataset_config
    cfg.enable_physics = False
    cfg.load_semantic_mesh = bool(semantic)
    specs = []
    kinds = [('rgb', habitat_sim.SensorType.COLOR), ('depth', habitat_sim.SensorType.DEPTH)]
    if semantic:
        kinds.append(('semantic', habitat_sim.SensorType.SEMANTIC))
    for uuid, kind in kinds:
        spec = habitat_sim.CameraSensorSpec()
        spec.uuid, spec.sensor_type = uuid, kind
        spec.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
        spec.resolution = [HEIGHT, WIDTH]
        spec.position = [0.0, CAMERA_Y, 0.0]
        spec.orientation = [0.0, 0.0, 0.0]
        spec.hfov = HFOV
        spec.near, spec.far = 0.1, 10.0
        if uuid == 'depth':
            spec.normalize_depth = False
        specs.append(spec)
    agent = habitat_sim.agent.AgentConfiguration()
    agent.radius, agent.height = float(robot['radius_m']), float(robot['height_m'])
    agent.sensor_specifications = specs
    sim = habitat_sim.Simulator(habitat_sim.Configuration(cfg, [agent]))
    settings = sim.pathfinder.nav_mesh_settings
    if settings is None:
        settings = habitat_sim.NavMeshSettings()
        settings.set_defaults()
    settings.agent_radius, settings.agent_height = agent.radius, agent.height
    if not sim.recompute_navmesh(sim.pathfinder, settings):
        sim.close()
        raise RuntimeError('robot navmesh recomputation failed')
    return sim


def yaw_from_heading(dx, dz):
    return math.atan2(-dx, -dz)          # Habitat agents look along -z at yaw 0


def render(sim, position, yaw):
    import habitat_sim
    from habitat_sim.utils.common import quat_from_angle_axis
    state = habitat_sim.AgentState()
    state.position = np.asarray(position, dtype=np.float32)
    state.rotation = quat_from_angle_axis(float(yaw), np.array([0.0, 1.0, 0.0]))
    sim.get_agent(0).set_state(state, reset_sensors=True)
    return sim.get_sensor_observations()


def path_poses(sim, episode, step_m):
    import habitat_sim
    pf = sim.pathfinder
    start = np.asarray(pf.snap_point(np.asarray(episode.start_position, np.float32)), np.float64)
    ends = [np.asarray(pf.snap_point(np.asarray(v, np.float32)), np.float32) for v in episode.view_points]
    ends = [e for e in ends if np.isfinite(e).all()]
    if not np.isfinite(start).all() or not ends:
        return []
    path = habitat_sim.MultiGoalShortestPath()
    path.requested_start, path.requested_ends = start.astype(np.float32), ends
    if not pf.find_path(path) or len(path.points) < 2:
        return []
    points = [np.asarray(p, np.float64) for p in path.points]
    poses, carried = [], 0.0
    for a, b in zip(points, points[1:]):
        seg = b - a
        length = float(np.hypot(seg[0], seg[2]))
        if length < 1e-6:
            continue
        yaw = yaw_from_heading(seg[0], seg[2])
        d = carried
        while d < length:
            p = a + seg * (d / length)
            for offset in (0.0, math.radians(45), -math.radians(45)):
                poses.append((p.tolist(), yaw + offset))
            d += step_m
        carried = d - length
    final = points[-1]
    last_seg = points[-1] - points[-2]
    poses.append((final.tolist(), yaw_from_heading(last_seg[0], last_seg[2])))
    return poses


def scan_poses(sim, count, headings, seed):
    pf = sim.pathfinder
    pf.seed(seed)
    poses = []
    for _ in range(count * 3):
        if len(poses) >= count * headings:
            break
        p = np.asarray(pf.get_random_navigable_point(), np.float64)
        if not np.isfinite(p).all():
            continue
        for k in range(headings):
            poses.append((p.tolist(), 2 * math.pi * k / headings))
    return poses


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--runner-config', type=Path, default=ROOT / 'configs/objectnav/lockstep-b0.json')
    ap.add_argument('--path-step', type=float, default=0.5)
    ap.add_argument('--scan-points', type=int, default=40)
    ap.add_argument('--headings', type=int, default=12)
    ap.add_argument('--max-frames-per-scene', type=int, default=700)
    ap.add_argument('--alignment-frames', type=int, default=20)
    ap.add_argument('--seed', type=int, default=20261111)
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    a = ap.parse_args(argv)
    if (a.out_dir / 'views.jsonl').exists():
        raise SystemExit('refusing to overwrite %s' % (a.out_dir / 'views.jsonl'))
    runner_config = json.loads(a.runner_config.read_text())
    robot = runner_config['robot']
    gpu = int(runner_config['sensor'].get('gpu_device_id', -1))
    all_eps = load_episode_set(a.episode_set, a.split, a.habitat_data)
    dev = read_manifest(a.manifest, all_eps)
    dev_by_scene = defaultdict(list)
    for e in dev:
        dev_by_scene[e.scene_short].append(e)
    (a.out_dir / 'frames').mkdir(parents=True, exist_ok=True)
    scenes_meta = {}
    rng = np.random.RandomState(a.seed)
    with open(a.out_dir / 'views.jsonl', 'w') as views:
        for scene in sorted(dev_by_scene):
            scene_eps = [e for e in all_eps if e.scene_short == scene]
            ref = scene_eps[0]
            if not ref.eval_dataset_config or not ref.runtime_dataset_config:
                raise SystemExit('scene %s has no annotated/basis dataset config' % scene)
            goals = {}
            for e in scene_eps:
                for g in e.goals:
                    goals[int(g.object_id)] = e.object_category
            annotation = Path(ref.scene_path.replace('.basis.glb', '.semantic.txt'))
            names = parse_annotations(annotation)
            sim = open_sim(ref.scene_path, ref.eval_dataset_config, robot, semantic=True, gpu_device_id=gpu)
            try:
                poses = []
                for e in sorted(dev_by_scene[scene], key=lambda e: e.uid):
                    poses += [(p, y, e) for p, y in path_poses(sim, e, a.path_step)]
                scan = [(p, y, None) for p, y in scan_poses(sim, a.scan_points, a.headings, a.seed)]
                kept, seen = [], set()
                for p, y, e in poses + scan:
                    key = (round(p[0], 1), round(p[1], 1), round(p[2], 1), int(round(math.degrees(y) / 15)) % 24)
                    if key not in seen:
                        seen.add(key)
                        kept.append((p, y, e))
                if len(kept) > a.max_frames_per_scene:
                    path_part = [k for k in kept if k[2] is not None]
                    scan_part = [k for k in kept if k[2] is None]
                    take = max(0, a.max_frames_per_scene - len(path_part))
                    if take < len(scan_part):
                        idx = sorted(rng.choice(len(scan_part), take, replace=False))
                        scan_part = [scan_part[i] for i in idx]
                    kept = (path_part + scan_part)[:a.max_frames_per_scene]
                seen_goals = set()
                # Alignment reference: keep the annotated render of a few poses in memory and
                # re-render them later with the runtime config. Only ONE simulator may exist at
                # a time in this process (two live GL contexts abort Habitat).
                stride = max(1, len(kept) // a.alignment_frames) if a.alignment_frames else 0
                check = set(range(0, len(kept), stride)[:a.alignment_frames]) if stride else set()
                reference = []
                for i, (pos, yaw, episode) in enumerate(kept):
                    obs = render(sim, pos, yaw)
                    rgb = np.asarray(obs['rgb'])[..., :3].astype(np.uint8)
                    depth = np.asarray(obs['depth'], dtype=np.float32)
                    if i in check:
                        reference.append((pos, yaw, rgb.copy(), depth.copy()))
                    sem = np.asarray(obs['semantic']).astype(np.uint32)
                    ids, counts = np.unique(sem, return_counts=True)
                    visible = []
                    for oid, n in zip(ids.tolist(), counts.tolist()):
                        if oid in goals and n >= MIN_PIXELS:
                            mask = sem == oid
                            d = depth[mask & (depth > 0)]
                            visible.append(dict(object_id=int(oid), category=goals[oid], pixels=int(n),
                                                depth_m=float(np.median(d)) if d.size else float('nan')))
                            seen_goals.add(int(oid))
                    frame_id = '%s-%05d' % (scene, i)
                    np.savez_compressed(a.out_dir / 'frames' / (frame_id + '.npz'), rgb=rgb,
                                        depth_mm=np.clip(np.round(depth * 1000), 0, 65535).astype(np.uint16),
                                        semantic=sem)
                    views.write(json.dumps(dict(
                        frame_id=frame_id, scene=scene, kind='path' if episode is not None else 'scan',
                        episode_uid=None if episode is None else episode.uid,
                        episode_category=None if episode is None else episode.object_category,
                        position=[float(v) for v in pos], yaw_rad=float(yaw), goals_visible=visible)) + '\n')
            finally:
                sim.close()
            alignment = dict(frames=0, passed=0, failures=[])
            if reference:
                basis = open_sim(ref.scene_path, ref.runtime_dataset_config, robot, semantic=False, gpu_device_id=gpu)
                try:
                    for pos, yaw, rgb, depth in reference:
                        y = render(basis, pos, yaw)
                        alignment['frames'] += 1
                        try:
                            validate_alignment(rgb, depth, depth > 0,
                                               np.asarray(y['rgb'])[..., :3].astype(np.uint8),
                                               np.asarray(y['depth'], np.float32))
                            alignment['passed'] += 1
                        except ValueError as exc:
                            alignment['failures'].append(str(exc)[:300])
                finally:
                    basis.close()
            by_cat = defaultdict(list)
            for oid, cat in goals.items():
                by_cat[cat].append(dict(object_id=oid, name=names.get(oid, '<missing in semantic.txt>'),
                                        seen=oid in seen_goals))
            scenes_meta[scene] = dict(frames=len(kept), path_frames=sum(k[2] is not None for k in kept),
                                      goal_instances=dict(by_cat), alignment=alignment,
                                      names={str(k): v for k, v in names.items()})
            print('%s: %d frames, goal instances seen %d/%d, alignment %d/%d' % (
                scene, len(kept), len(seen_goals), len(goals), alignment['passed'], alignment['frames']), flush=True)
    (a.out_dir / 'scenes.json').write_text(json.dumps(dict(
        schema_version=1, manifest=str(a.manifest), camera=dict(width=WIDTH, height=HEIGHT, hfov_deg=HFOV, height_m=CAMERA_Y),
        robot=robot, min_visible_pixels=MIN_PIXELS, alignment_policy=ALIGNMENT_POLICY, seed=a.seed,
        scenes=scenes_meta), indent=1) + '\n')
    print('done:', a.out_dir)


if __name__ == '__main__':
    main()
