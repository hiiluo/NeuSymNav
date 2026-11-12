#!/usr/bin/env python3
"""Can a body of radius r / height h stand on a goal view point? (Habitat interpreter, evaluator only)

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/footprint_ceiling.py \
        --manifest runs/objectnav/b0/dev4h-diag/manifest.json --out runs/objectnav/b0/footprint-20261113/footprint_ceiling-dev9.json \
        [--outcomes runs/objectnav/b0/dev4h-diag/oracle-v2-outcomes.jsonl ...]

Success = STOP with geodesic DTG < 0.1 m to a goal VIEW POINT. View points come
from the habitat-lab challenge agent (r 0.18 m, h 0.88 m). B0's planner only
admits centre cells clear of observed obstacles by radius + margin (0.20 + 0.05
m), and the robot body is 1.5 m tall. For each body (r, h) the scene navmesh is
recomputed exactly like the sensor worker (NavMeshSettings defaults, agent
radius/height replaced); for every goal view point of the episode's category:

  gap   horizontal distance from the view point to its snapped navmesh point
        when that point is on the same floor (|dy| < 0.3 m) and reachable from
        the snapped episode start; inf otherwise.
  ok    gap < 0.1 m: the body can stand within the success radius of that
        view point (a geodesic upper bound is the same 0.1 m within a floor).

Per episode: best_gap = min gap over all view points, n_ok = view points with
ok. best_gap >= 0.1 m means no stop of that body can be a success: a ceiling
set by the body, not by the policy. With --outcomes the run's min-DTG is
printed beside it. Privileged data; nothing here reaches the robot.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav import habitat_tools as ht  # noqa: E402
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, read_manifest  # noqa: E402

SUCCESS_M = 0.1
FLOOR_TOL_M = 0.3
# (label, radius_m, height_m): challenge agent, robot navmesh (sensor worker),
# planner footprint (radius + margin), start-footprint pad (+0.75 cell of 0.05 m).
BODIES = (('challenge r0.18 h0.88', 0.18, 0.88),
          ('robot r0.20 h1.5', 0.20, 1.5),
          ('planner r0.25 h1.5', 0.25, 1.5),
          ('planner+pad r0.2875 h1.5', 0.2875, 1.5),
          ('planner r0.25 h0.88', 0.25, 0.88))


def recompute(sim, radius, height):
    import habitat_sim
    settings = habitat_sim.NavMeshSettings()
    settings.set_defaults()
    settings.agent_radius = radius
    settings.agent_height = height
    if not sim.recompute_navmesh(sim.pathfinder, settings):
        raise RuntimeError('navmesh recomputation failed r=%s h=%s' % (radius, height))


def reachable(sim, a, b):
    import habitat_sim
    path = habitat_sim.ShortestPath()
    path.requested_start = np.asarray(a, np.float32)
    path.requested_end = np.asarray(b, np.float32)
    return sim.pathfinder.find_path(path) and math.isfinite(path.geodesic_distance)


def probe(sim, ep):
    start = np.asarray(sim.pathfinder.snap_point(np.asarray(ep.start_position, np.float32)))
    start_ok = bool(np.all(np.isfinite(start)) and abs(start[1] - ep.start_position[1]) < FLOOR_TOL_M)
    gaps = []
    for goal in ep.goals:
        for vp in goal.view_points:
            vp = np.asarray(vp, np.float32)
            s = np.asarray(sim.pathfinder.snap_point(vp))
            if not start_ok or not np.all(np.isfinite(s)) or abs(s[1] - vp[1]) >= FLOOR_TOL_M:
                gaps.append(math.inf)
                continue
            gap = float(math.hypot(s[0] - vp[0], s[2] - vp[2]))
            gaps.append(gap if reachable(sim, start, s) else math.inf)
    finite = [g for g in gaps if math.isfinite(g)]
    return {'start_on_navmesh': start_ok, 'view_points': len(gaps),
            'n_ok': sum(1 for g in gaps if g < SUCCESS_M),
            'best_gap_m': min(finite) if finite else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--outcomes', type=Path, action='append', default=[])
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit('refusing to overwrite %s' % a.out)
    episodes = read_manifest(a.manifest, load_episode_set(a.episode_set, a.split, a.habitat_data))
    observed = {}
    for path in a.outcomes:
        for line in path.read_text().splitlines():
            if line.strip():
                o = json.loads(line)
                observed.setdefault(o['uid'], {})[path.parent.name] = o.get('dtg_min_m')
    rows = []
    by_scene = {}
    for ep in episodes:
        by_scene.setdefault((ep.scene_path, ep.runtime_dataset_config), []).append(ep)
    for (scene, config), eps in sorted(by_scene.items()):
        sim = ht.open_scene(scene, config, with_actions=False)
        try:
            results = {ep.uid: {} for ep in eps}
            for label, radius, height in BODIES:
                recompute(sim, radius, height)
                for ep in eps:
                    results[ep.uid][label] = probe(sim, ep)
        finally:
            sim.close()
        for ep in eps:
            rows.append({'uid': ep.uid, 'category': ep.object_category,
                         'bodies': results[ep.uid], 'observed_min_dtg_m': observed.get(ep.uid, {})})
    summary = {}
    for label, _, _ in BODIES:
        ok = [r for r in rows if r['bodies'][label]['n_ok'] > 0]
        summary[label] = {'episodes': len(rows), 'success_possible': len(ok)}
    a.out.write_text(json.dumps({'schema_version': 1, 'manifest': str(a.manifest), 'success_m': SUCCESS_M,
                                 'bodies': [dict(label=l, radius_m=r, height_m=h) for l, r, h in BODIES],
                                 'summary': summary, 'episodes': rows}, indent=2) + '\n')
    fmt = lambda g: '  inf' if g is None else '%5.2f' % g
    print('%-26s %-10s ' % ('episode', 'category') + ' '.join('%-24s' % l for l, _, _ in BODIES) + ' observed min-DTG')
    for r in rows:
        cells = ['gap %s ok %3d/%-3d' % (fmt(r['bodies'][l]['best_gap_m']), r['bodies'][l]['n_ok'],
                                         r['bodies'][l]['view_points']) for l, _, _ in BODIES]
        obs = ' '.join('%s=%.2f' % (k, v) for k, v in sorted(r['observed_min_dtg_m'].items()) if v is not None)
        print('%-26s %-10s ' % (r['uid'][12:], r['category']) + ' '.join('%-24s' % c for c in cells) + ' ' + obs)
    print('success possible:', {l: '%d/%d' % (s['success_possible'], s['episodes']) for l, s in summary.items()})
    print('wrote', a.out, file=sys.stderr)


if __name__ == '__main__':
    main()
