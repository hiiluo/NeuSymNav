#!/usr/bin/env python3
"""Validation agents for the ObjectNav scorer (privileged, never a result).

Run with the Habitat interpreter from the worktree root:

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/scripted_agents.py \
        --set hm3d_v2 --split val_mini --agent oracle_path --out runs/objectnav/validation/oracle_path.jsonl

Agents (discrete Habitat actions: forward 0.25 m, turn 30 deg, <= 500 steps):
  oracle_path    follows the navmesh shortest path exactly to the nearest view
                 point, then STOP. Expected: SR = 1, SPL ~ 1 (checks the scorer).
  oracle_greedy  habitat_sim GreedyGeodesicFollower with discrete actions,
                 re-targeting the nearest view point each step; STOP once inside
                 0.09 m of any view point. Expected: SR high, SPL < 1.
  random         uniform forward/left/right for 500 steps, then STOP.
                 Expected: SR ~ 0.

Writes one JSON line per episode: uid, agent, positions (Habitat world frame,
start first), called_stop, steps. Score with tools/objectnav/score_trajectories.py.
"""
import argparse
import json
import random
import sys
import zlib
from itertools import groupby
from pathlib import Path

from neusymnav.objectnav import habitat_tools as ht
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, select

ACTIONS = ('move_forward', 'turn_left', 'turn_right')
STOP_RADIUS_M = 0.09   # a little inside the 0.1 m success radius


def run_oracle_path(sim, episode):
    start = ht.agent_position(sim)
    points = ht.shortest_path(sim, start, episode.view_points)
    if not points:
        return [start], False, 0
    positions = [start] + [p for p in points if p != start]
    return positions, True, len(points) - 1


def run_oracle_greedy(sim, episode, max_steps):
    """Discrete-action oracle: re-target the nearest view point every step and STOP
    as soon as the geodesic distance to ANY view point is below the success radius
    (all view points count, as in the scorer)."""
    import habitat_sim
    positions = [ht.agent_position(sim)]
    follower = habitat_sim.nav.GreedyGeodesicFollower(
        sim.pathfinder, sim.get_agent(0), goal_radius=ht.FORWARD_STEP_M, stop_key='stop',
        forward_key='move_forward', left_key='turn_left', right_key='turn_right')
    steps = 0
    while steps < max_steps:
        here = positions[-1]
        if ht.distance_to_goal(sim, here, episode.view_points) < STOP_RADIUS_M:
            return positions, True, steps
        points = ht.shortest_path(sim, here, episode.view_points)
        if not points:
            return positions, True, steps
        try:
            action = follower.next_action_along(points[-1])
        except habitat_sim.errors.GreedyFollowerError:
            return positions, True, steps          # stops where it is
        if action == 'stop':
            # Within one step of the nearest view point but not yet inside the
            # success radius: creep forward toward it once, else stop here.
            action = 'move_forward'
        sim.step(action)
        steps += 1
        positions.append(ht.agent_position(sim))
    return positions, False, steps


def run_random(sim, episode, max_steps, seed):
    rng = random.Random(seed ^ zlib.crc32(episode.uid.encode()))
    positions = [ht.agent_position(sim)]
    for _ in range(max_steps):
        sim.step(rng.choice(ACTIONS))
        positions.append(ht.agent_position(sim))
    return positions, True, max_steps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--set', required=True, dest='episode_set')
    ap.add_argument('--split', required=True)
    ap.add_argument('--agent', required=True, choices=('oracle_path', 'oracle_greedy', 'random'))
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--max-steps', type=int, default=ht.MAX_STEPS)
    a = ap.parse_args(argv)
    episodes = select(load_episode_set(a.episode_set, a.split, a.habitat_data), limit=a.limit)
    if a.out.exists():
        raise SystemExit('refusing to overwrite %s' % a.out)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with open(a.out, 'w') as stream:
        for scene, group in groupby(sorted(episodes, key=lambda e: (e.scene_path, e.uid)), key=lambda e: e.scene_path):
            group = list(group)
            sim = ht.open_scene(scene, group[0].runtime_dataset_config)
            try:
                for episode in group:
                    ht.place_agent(sim, episode.start_position, episode.start_rotation_xyzw)
                    if a.agent == 'oracle_path':
                        positions, stop, steps = run_oracle_path(sim, episode)
                    elif a.agent == 'oracle_greedy':
                        positions, stop, steps = run_oracle_greedy(sim, episode, a.max_steps)
                    else:
                        positions, stop, steps = run_random(sim, episode, a.max_steps, a.seed)
                    stream.write(json.dumps({'schema_version': 1, 'uid': episode.uid, 'agent': a.agent,
                                             'positions': positions, 'called_stop': stop,
                                             'steps': steps, 'sim_time_s': None}) + '\n')
                    done += 1
            finally:
                sim.close()
            print('%s: %d episodes' % (Path(scene).name, len(group)), file=sys.stderr)
    print('wrote %d trajectories to %s' % (done, a.out))


if __name__ == '__main__':
    main()
