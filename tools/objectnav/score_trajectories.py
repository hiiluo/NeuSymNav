#!/usr/bin/env python3
"""Score ObjectNav trajectories offline (SR, SPL, SoftSPL, DTG; Habitat-lab definitions).

Run with the Habitat interpreter from the worktree root:

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/score_trajectories.py \
        runs/objectnav/validation/oracle_path.jsonl --set hm3d_v2 --split val_mini

Input: JSON lines {uid, positions [[x,y,z], ...] (Habitat world frame, start
first), called_stop, steps, sim_time_s?, evidence?}. ``evidence`` may hold
target_seen / target_detected / stop_near_false_detection / stuck for the
failure classification. Writes <input>-outcomes.jsonl and <input>-summary.json
next to the input unless --out-prefix is given. Geodesics use the scene's
runtime (basis) dataset config and its navmesh; the episode's stored
geodesic is kept for reference only.
"""
import argparse
import json
import sys
from itertools import groupby
from pathlib import Path

from neusymnav.evaluation.objectnav_metrics import classify_failure, score_episode, summarize
from neusymnav.objectnav import habitat_tools as ht
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('trajectories', type=Path)
    ap.add_argument('--set', required=True, dest='episode_set')
    ap.add_argument('--split', required=True)
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--out-prefix', type=Path)
    a = ap.parse_args(argv)
    records = [json.loads(line) for line in a.trajectories.read_text().splitlines() if line.strip()]
    if not records:
        raise SystemExit('no trajectories')
    episodes = {e.uid: e for e in load_episode_set(a.episode_set, a.split, a.habitat_data)}
    unknown = [r['uid'] for r in records if r['uid'] not in episodes]
    if unknown:
        raise SystemExit('%d trajectories name unknown episodes, e.g. %s' % (len(unknown), unknown[0]))
    if len({r['uid'] for r in records}) != len(records):
        raise SystemExit('duplicate trajectory uids')
    prefix = a.out_prefix or a.trajectories.with_suffix('')
    outcomes = []
    key = lambda r: episodes[r['uid']].scene_path
    for scene, group in groupby(sorted(records, key=lambda r: (key(r), r['uid'])), key=key):
        group = list(group)
        sim = ht.open_scene(scene, episodes[group[0]['uid']].runtime_dataset_config, with_actions=False)
        try:
            for rec in group:
                ep = episodes[rec['uid']]
                outcome = score_episode(
                    uid=ep.uid, scene=ep.scene_short, category=ep.object_category,
                    positions=rec['positions'], called_stop=bool(rec['called_stop']),
                    distance_to_goal=lambda p, vps=ep.view_points: ht.distance_to_goal(sim, p, vps),
                    steps=int(rec['steps']), sim_time_s=rec.get('sim_time_s'),
                    stored_geodesic_m=ep.stored_geodesic_m)
                ev = rec.get('evidence') or {}
                mode = classify_failure(outcome, target_seen=ev.get('target_seen'),
                                        target_detected=ev.get('target_detected'),
                                        stop_near_false_detection=ev.get('stop_near_false_detection'),
                                        stuck=bool(ev.get('stuck', False)),
                                        start_not_navigable=bool(ev.get('start_not_navigable', False)))
                outcomes.append(outcome.__class__(**{**outcome.to_json(), 'failure_mode': mode}))
        finally:
            sim.close()
    out_rows = Path(str(prefix) + '-outcomes.jsonl')
    out_sum = Path(str(prefix) + '-summary.json')
    for path in (out_rows, out_sum):
        if path.exists():
            raise SystemExit('refusing to overwrite %s' % path)
    out_rows.write_text(''.join(json.dumps(o.to_json()) + '\n' for o in outcomes))
    summary = summarize(outcomes)
    summary.update(trajectories=str(a.trajectories), episode_set=a.episode_set, split=a.split,
                   agents=sorted({r.get('agent', '?') for r in records}))
    out_sum.write_text(json.dumps(summary, indent=2) + '\n')
    o = summary['overall']
    print('%s  episodes=%d  SR=%.3f [%.3f, %.3f]  SPL=%.3f [%.3f, %.3f]  SoftSPL=%.3f  DTG=%.2f m  invalid=%d' % (
        ','.join(summary['agents']), o['episodes'], o['success_rate'], *o['success_rate_ci95'],
        o['spl'], *o['spl_ci95'], o['soft_spl'], o['dtg_m'], summary['invalid_episodes']))
    print('failure modes:', summary['failure_modes'])
    print('wrote', out_rows, 'and', out_sum, file=sys.stderr)


if __name__ == '__main__':
    main()
