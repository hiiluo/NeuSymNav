#!/usr/bin/env python3
"""Phase 3, step 1: where must B0 stop to succeed? (Habitat interpreter, evaluator only, DEV split)

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/stop_calibration.py \
        --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --out runs/objectnav/b0/stop_calibration.json

Success in habitat-lab ObjectNav = STOP within 0.1 m (geodesic) of a goal VIEW
POINT. B0 stops when its centre is within D of the object's OBSERVED points.
This tool measures the same quantity offline, on the robot body's navmesh
(r 0.2 m, h 1.5 m, recomputed exactly like the sensor worker):

  object points  every goal object is rendered (depth + semantic, the
                 runner's 640x480 / hfov 90 / 1.2 m camera) from up to
                 --views of its view points, facing the object; pixels of
                 its semantic id are unprojected (heights 0.03-2.0 m above
                 the view point floor), i.e. the surface a robot sees;
  band           P(success) of robot-navigable points by distance d to
                 those points (0.1 m bins);
  entry          for each D, the first point a robot coming from the episode
                 start reaches inside the D-ring (geodesically closest) and
                 whether it is a success: the ceiling of "stop at D";
  ceiling        per DEV episode: does ANY goal have a success point on the
                 start floor (the planar motion adapter keeps the launch
                 height, so B0 cannot change floors) reachable from the start.

Success here = horizontal distance < 0.1 m to a view point on the same floor
(the scorer uses the geodesic on the challenge navmesh; within 0.1 m both
agree except through walls). Privileged, offline only; nothing reaches the robot.
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

from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, read_manifest  # noqa: E402

SUCCESS_M = 0.1
GRID_M = 0.05
MAX_RING_M = 1.5
FLOOR_TOL_M = 0.3
BINS = [round(0.1 * i, 1) for i in range(16)]
ENTRY_D = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
WIDTH, HEIGHT, HFOV, CAMERA_Y = 640, 480, 90.0, 1.2
MAX_OBJECT_POINTS = 600


def open_sim(scene_path, dataset_config, robot, gpu_device_id):
    """The phase-2 renderer (rgb + depth + semantic, robot navmesh), proven to see goal ids."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('sample_views', ROOT / 'tools/objectnav/detector_eval/sample_views.py')
    views = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(views)
    return views.open_sim(scene_path, dataset_config, robot, semantic=True, gpu_device_id=gpu_device_id)


def unproject(depth, position, yaw):
    """Depth image (metres, axial) at agent ``position``/``yaw`` -> world points (H, W, 3)."""
    f = (WIDTH / 2.0) / math.tan(math.radians(HFOV) / 2)
    u, v = np.meshgrid(np.arange(WIDTH) - (WIDTH - 1) / 2.0, np.arange(HEIGHT) - (HEIGHT - 1) / 2.0)
    xc, yc, zc = u / f * depth, -v / f * depth, -depth
    c, s = math.cos(yaw), math.sin(yaw)
    x = c * xc + s * zc
    z = -s * xc + c * zc
    return np.stack((x + position[0], yc + position[1] + CAMERA_Y, z + position[2]), axis=-1)


DIAGNOSE = [5]          # print why the first objects have no points


def object_points(sim, object_id, goal_position, view_points, n_views):
    """Visible surface points of one object seen from its view points (x, y, z world)."""
    import habitat_sim
    from habitat_sim.utils.common import quat_from_angle_axis
    vps = np.asarray(view_points, float).reshape(-1, 3)
    if not len(vps):
        return np.zeros((0, 3))
    order = [int(np.argmin(np.hypot(vps[:, 0] - goal_position[0], vps[:, 2] - goal_position[2])))]
    while len(order) < min(n_views, len(vps)):          # farthest-point spread around the object
        d = np.min(np.hypot(vps[:, None, 0] - vps[None, order, 0], vps[:, None, 2] - vps[None, order, 2]), axis=1)
        order.append(int(np.argmax(d)))
    pts = []
    for i in order:
        p = vps[i]
        yaw = math.atan2(-(goal_position[0] - p[0]), -(goal_position[2] - p[2]))
        state = habitat_sim.AgentState()
        state.position = p.astype(np.float32)
        state.rotation = quat_from_angle_axis(float(yaw), np.array([0.0, 1.0, 0.0]))
        sim.get_agent(0).set_state(state, reset_sensors=True)
        obs = sim.get_sensor_observations()
        sem, depth = np.asarray(obs['semantic']).astype(np.int64), np.asarray(obs['depth'], np.float64)
        mask = (sem == int(object_id)) & (depth > 0.1)
        if not mask.any() and DIAGNOSE[0] > 0:
            DIAGNOSE[0] -= 1
            ids, counts = np.unique(sem, return_counts=True)
            top = sorted(zip(counts.tolist(), ids.tolist()), reverse=True)[:6]
            print('DIAG object %d view %s yaw %.2f goal %s: semantic shape %s top ids %s depth [%.2f, %.2f]' % (
                object_id, np.round(p, 2).tolist(), yaw, np.round(goal_position, 2).tolist(), sem.shape, top,
                float(depth.min()), float(depth.max())), flush=True)
        if mask.any():
            world = unproject(depth, p, yaw)[mask]
            h = world[:, 1] - p[1]
            pts.append(world[(h > 0.03) & (h < 2.0)])
    pts = np.concatenate(pts) if pts else np.zeros((0, 3))
    if len(pts) > MAX_OBJECT_POINTS:
        pts = pts[np.random.RandomState(0).choice(len(pts), MAX_OBJECT_POINTS, replace=False)]
    return pts


def min_dist_xz(px, pz, obj):
    return float(np.min(np.hypot(obj[:, 0] - px, obj[:, 2] - pz)))


def geodesic(sim, a, b):
    import habitat_sim
    path = habitat_sim.ShortestPath()
    path.requested_start = np.asarray(a, np.float32)
    path.requested_end = np.asarray(b, np.float32)
    return float(path.geodesic_distance) if sim.pathfinder.find_path(path) else math.inf


def ring_points(sim, obj, floor_y, island):
    pf = sim.pathfinder
    lo, hi = obj.min(axis=0), obj.max(axis=0)
    out = []
    for x in np.arange(lo[0] - MAX_RING_M, hi[0] + MAX_RING_M + 1e-9, GRID_M):
        for z in np.arange(lo[2] - MAX_RING_M, hi[2] + MAX_RING_M + 1e-9, GRID_M):
            d = min_dist_xz(x, z, obj)
            if d > MAX_RING_M:
                continue
            s = np.asarray(pf.snap_point(np.array([x, floor_y, z], np.float32)), np.float64)
            if (not np.isfinite(s).all() or math.hypot(s[0] - x, s[2] - z) > GRID_M * 0.5
                    or abs(s[1] - floor_y) > FLOOR_TOL_M or pf.get_island(s.astype(np.float32)) != island):
                continue
            out.append((s, d))
    return out


def success_at(p, vps):
    near = vps[np.abs(vps[:, 1] - p[1]) <= 0.5]
    return bool(len(near)) and float(np.min(np.hypot(near[:, 0] - p[0], near[:, 2] - p[2]))) < SUCCESS_M


def summarize(rows):
    band = defaultdict(lambda: [0, 0])
    entry = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        for b, (s, n) in r['band'].items():
            band[b][0] += s
            band[b][1] += n
        for d, e in r['entry'].items():
            entry[d][2] += 1
            if e is not None:
                entry[d][1] += 1
                entry[d][0] += e['success']
    return dict(objects=len(rows),
                band={b: dict(success=v[0], points=v[1], p=v[0] / v[1] if v[1] else None)
                      for b, v in sorted(band.items(), key=lambda kv: float(kv[0]))},
                entry={d: dict(success=v[0], with_entry=v[1], objects=v[2], p=v[0] / v[2] if v[2] else None,
                               p_given_entry=v[0] / v[1] if v[1] else None) for d, v in sorted(entry.items())})


def markdown(summary, per_category, ceiling, notes, spacing):
    fmt = lambda v: '—' if v is None else '%.2f' % v
    cats = sorted(per_category)
    out = ['# B0 stop calibration (DEV)', '',
           'Objects reachable on a start floor: %d (goal occurrences without visible points: %d). Distances are to the object points seen from its view points.' % (
               summary['objects'], notes.get('no_object_points', 0)), '',
           '## Episode ceiling for the planar robot body', '',
           'Episodes with a success point on the start floor reachable from the start: %d/%d (%s).' % (
               ceiling['reachable'], ceiling['episodes'], fmt(ceiling['p'])),
           'By category: ' + ', '.join('%s %d/%d' % (c, v[0], v[1]) for c, v in sorted(ceiling['by_category'].items())), '',
           '## P(success) by distance to the object points (robot-navigable points, start floor)', '',
           '| d (m) | points | P(success) |', '|---|---|---|']
    for b, v in summary['band'].items():
        out.append('| %s–%.1f | %d | %s |' % (b, float(b) + 0.1, v['points'], fmt(v['p'])))
    out += ['', '## "Stop at the first point within D" coming from the episode start', '',
            'Cell = P(success) over objects reachable on the start floor (objects with no point within D count as failures); in brackets P(success | some point within D).', '',
            '| D (m) | all | ' + ' | '.join(cats) + ' |', '|---|---|' + '---|' * len(cats)]
    for d, v in summary['entry'].items():
        cells = ['%s (%s)' % (fmt(per_category[c]['entry'][d]['p']), fmt(per_category[c]['entry'][d]['p_given_entry']))
                 for c in cats]
        out.append('| %s | %s (%s) | %s |' % (d, fmt(v['p']), fmt(v['p_given_entry']), ' | '.join(cells)))
    out += ['', 'Notes: %s; median view-point spacing %s m.' % (notes, fmt(spacing))]
    return '\n'.join(out) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--views', type=int, default=8)
    ap.add_argument('--runner-config', type=Path, default=ROOT / 'configs/objectnav/lockstep-b0.json')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    a = ap.parse_args(argv)
    runner = json.loads(a.runner_config.read_text())
    robot, gpu = runner['robot'], int(runner['sensor'].get('gpu_device_id', -1))
    dev = read_manifest(a.manifest, load_episode_set(a.episode_set, a.split, a.habitat_data))
    by_scene = defaultdict(list)
    for e in dev:
        by_scene[e.scene_short].append(e)
    rows, notes, episodes_ceiling, spacing = [], defaultdict(int), [], []
    for scene in sorted(by_scene):
        eps = by_scene[scene]
        sim = open_sim(eps[0].scene_path, eps[0].eval_dataset_config, robot, gpu)
        try:
            pf = sim.pathfinder
            cache, rings, done = {}, {}, set()     # object points; ring points per start floor; rows made
            for e in eps:
                start = np.asarray(pf.snap_point(np.asarray(e.start_position, np.float32)), np.float64)
                if not np.isfinite(start).all():
                    notes['start_not_on_robot_navmesh'] += 1
                    episodes_ceiling.append((e.object_category, False))
                    continue
                island = pf.get_island(start.astype(np.float32))
                reachable_episode = False
                for g in e.goals:
                    oid = int(g.object_id)
                    vps = np.asarray(g.view_points, float).reshape(-1, 3)
                    if oid not in cache:
                        cache[oid] = object_points(sim, oid, np.asarray(g.position, float), vps, a.views)
                        if len(vps) > 1:
                            d = np.hypot(vps[:, None, 0] - vps[None, :, 0], vps[:, None, 2] - vps[None, :, 2])
                            np.fill_diagonal(d, np.inf)
                            spacing.append(float(np.median(d.min(axis=1))))
                    obj = cache[oid]
                    if not len(obj):
                        notes['no_object_points'] += 1
                        continue
                    if abs(float(np.median(vps[:, 1])) - start[1]) > FLOOR_TOL_M + 0.2:
                        notes['goal_on_other_floor'] += 1
                        continue                      # planar body: unreachable floor
                    ck = (oid, island, round(float(start[1]), 1))
                    if ck not in rings:
                        pts = ring_points(sim, obj, float(start[1]), island)
                        rings[ck] = (pts, [success_at(p, vps) for p, _ in pts])
                    pts, succ = rings[ck]
                    key = (scene, oid)
                    if key in done:
                        if not reachable_episode:      # ceiling only: any reachable success point
                            reachable_episode = any(math.isfinite(geodesic(sim, start, p))
                                                    for (p, _), ok in zip(pts, succ) if ok)
                        continue
                    geo = [geodesic(sim, start, p) if (d <= max(ENTRY_D) or ok) else math.inf
                           for (p, d), ok in zip(pts, succ)]
                    reachable_obj = any(ok and math.isfinite(gd) for ok, gd in zip(succ, geo))
                    reachable_episode |= reachable_obj
                    if not reachable_obj:
                        continue                      # band/entry once per object, from a start that reaches it
                    done.add(key)
                    band = defaultdict(lambda: [0, 0])
                    for (p, d), ok in zip(pts, succ):
                        b = str(BINS[min(int(d / 0.1), len(BINS) - 1)])
                        band[b][0] += ok
                        band[b][1] += 1
                    entry = {}
                    for D in ENTRY_D:
                        best = None
                        for (p, d), ok, gd in zip(pts, succ, geo):
                            if d <= D and math.isfinite(gd) and (best is None or gd < best[0]):
                                best = (gd, ok)
                        entry[str(D)] = None if best is None else dict(geodesic_m=round(best[0], 3), success=bool(best[1]))
                    rows.append(dict(scene=scene, object_id=oid, category=e.object_category, view_points=int(len(vps)),
                                     object_points=int(len(obj)), ring_points=len(pts), success_points=int(sum(succ)),
                                     band={k: tuple(v) for k, v in band.items()}, entry=entry))
                    print('%s obj %4d %-10s vps=%3d objpts=%3d ring=%4d succ=%4d entry@0.6=%s' % (
                        scene, oid, e.object_category, len(vps), len(obj), len(pts), sum(succ), entry['0.6']), flush=True)
                episodes_ceiling.append((e.object_category, reachable_episode))
        finally:
            sim.close()
    summary = summarize(rows)
    per_cat = {c: summarize([r for r in rows if r['category'] == c]) for c in sorted({r['category'] for r in rows})}
    by_cat = defaultdict(lambda: [0, 0])
    for cat, ok in episodes_ceiling:
        by_cat[cat][0] += ok
        by_cat[cat][1] += 1
    reach = sum(ok for _, ok in episodes_ceiling)
    ceiling = dict(episodes=len(episodes_ceiling), reachable=reach,
                   p=reach / len(episodes_ceiling) if episodes_ceiling else None,
                   by_category={c: tuple(v) for c, v in by_cat.items()})
    med = float(np.median(spacing)) if spacing else None
    result = dict(schema_version=2, manifest=str(a.manifest), robot=robot, success_m=SUCCESS_M, grid_m=GRID_M,
                  views=a.views, notes=dict(notes), view_point_spacing_median_m=med, ceiling=ceiling,
                  summary=summary, per_category=per_cat, objects=rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1) + '\n')
    md = markdown(summary, per_cat, ceiling, dict(notes), med)
    a.out.with_suffix('.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
