#!/usr/bin/env python3
"""P2 check of the paper-protocol simulator (EVALUATOR-ONLY, privileged; never a policy result).

Drives the exact simulator configuration of ``objectnav/paper/sim_worker.py`` (scene navmesh,
0.88 x 0.18 m body, forward 0.25 m, turn 30 deg, allow_sliding false) with a geodesic oracle and
writes trajectories for ``tools/objectnav/score_trajectories.py``. Expected: oracle_greedy SR close
to 1 (failures only where the no-sliding greedy follower gets stuck), proving that the paper
simulator and the frozen scorer agree on navmesh, positions and success.

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/paper/oracle_check.py \
        --manifest runs/objectnav/b1r-fxboth-dev60/manifest.json --out runs/objectnav/paper-oracle-dev60/trajectories.jsonl

Rendering is skipped (agent.act on the same agent configuration): the check is about motion.
"""
import argparse
import importlib.util
import json
import sys
from itertools import groupby
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from neusymnav.evaluation.objectnav_metrics import snap_view_points  # noqa: E402
from neusymnav.objectnav import habitat_tools as ht  # noqa: E402
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, read_manifest  # noqa: E402

STOP_RADIUS_M = 0.09


def _paper_sim_class():
    spec = importlib.util.spec_from_file_location(
        'paper_sim_worker', ROOT / 'src/neusymnav/objectnav/paper/sim_worker.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PaperSim


def _protocol(path):
    # protocol.py is Python 3.9 compatible; import it by file to avoid the package __init__ chain
    spec = importlib.util.spec_from_file_location('paper_protocol', ROOT / 'src/neusymnav/objectnav/paper/protocol.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PaperProtocol.load(path)


def run_greedy(sim, agent, episode, max_steps):
    import habitat_sim
    pos = lambda: [float(v) for v in agent.get_state().position]  # noqa: E731
    positions, collisions = [pos()], 0
    goals = snap_view_points(episode.view_points, lambda v: sim.pathfinder.snap_point(np.asarray(v, np.float32)))[0]
    follower = habitat_sim.nav.GreedyGeodesicFollower(
        sim.pathfinder, agent, goal_radius=0.25, stop_key='stop', forward_key='move_forward',
        left_key='turn_left', right_key='turn_right')
    steps = 0
    while steps < max_steps - 1:                 # leave one step for STOP (STOP counts)
        here = positions[-1]
        if ht.distance_to_goal(sim, here, goals) < STOP_RADIUS_M:
            break
        points = ht.shortest_path(sim, here, goals)
        if not points:
            break
        try:
            action = follower.next_action_along(points[-1])
        except habitat_sim.errors.GreedyFollowerError:
            break
        if action == 'stop':
            action = 'move_forward'
        collisions += bool(agent.act(action))
        steps += 1
        positions.append(pos())
    return positions, steps + 1, collisions


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--protocol', type=Path, default=ROOT / 'configs/objectnav/paper-hm3d-v1.json')
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--manifest', type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    a = ap.parse_args(argv)
    protocol = _protocol(a.protocol)
    episodes = load_episode_set(a.episode_set, a.split, a.habitat_data)
    if a.manifest:
        episodes = read_manifest(a.manifest, episodes)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    PaperSim = _paper_sim_class()
    paper = PaperSim(protocol.worker_config(), 'oracle-check')
    try:
        with open(a.out, 'w') as stream:
            for scene, group in groupby(sorted(episodes, key=lambda e: (e.scene_path, e.uid)), key=lambda e: e.scene_path):
                group = list(group)
                paper._build(scene, group[0].runtime_dataset_config)
                for episode in group:
                    ht.place_agent(paper.sim, episode.start_position, episode.start_rotation_xyzw)
                    positions, steps, collisions = run_greedy(paper.sim, paper.agent, episode, protocol.max_steps)
                    stream.write(json.dumps(dict(schema_version=1, uid=episode.uid, agent='paper_oracle_greedy',
                                                 positions=positions, called_stop=True, steps=steps,
                                                 sim_time_s=None, diagnostics=dict(collisions=collisions,
                                                 protocol_sha256=protocol.sha256))) + '\n')
                print('%s: %d episodes' % (Path(scene).name, len(group)), file=sys.stderr)
    finally:
        paper.close()
    print('wrote', a.out)


if __name__ == '__main__':
    main()
