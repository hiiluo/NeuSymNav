"""Offline (evaluator-side) look at episodes that ended without a decision (max_steps / frontiers_exhausted):
did the candidate memory hold an object near a true goal, and what had happened to it?

python3 tools/objectnav/b3/endgame_diag.py RUN [RUN ...]
Uses the dataset goal positions (semantic GT) only here, never in the policy.
Policy world frame: (x, y) = (habitat x, -habitat z).
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from neusymnav.objectnav.episodes import load_episode_set  # noqa: E402

episodes = {e.uid: e for e in load_episode_set('hm3d_v2', 'val')}
near_m = 1.0
tally = Counter()
for run in sys.argv[1:]:
    d = ROOT / 'runs/objectnav' / run
    outs = {json.loads(l)['uid']: json.loads(l) for l in open(d / 'trajectories+evidence-outcomes.jsonl')}
    for line in open(d / 'trajectories.jsonl'):
        r = json.loads(line)
        end = r['diagnostics']['end_reason'].split(':')[-1]
        if end not in ('max_steps', 'frontiers_exhausted') or outs[r['uid']]['success']:
            continue
        ep, p = episodes[r['uid']], r['diagnostics']['policy']
        goals = [(g.position[0], -g.position[2]) for g in ep.goals]
        clip = {e['cid']: e for e in p.get('clip_verify', []) if e.get('scores')}
        rows = []
        for c in p['candidates']:
            n = c['views'].get(p['target'], 0)
            if not n:
                continue
            dist = min(math.dist(c['centroid_xy'], g) for g in goals)
            rows.append((dist, c['cid'], n, c['best'][p['target']], c['rejected'], c['confirmed'],
                         clip.get(c['cid'], {}).get('top')))
        rows.sort()
        hit = [x for x in rows if x[0] <= near_m]
        kind = 'no_target_candidate' if not rows else ('near_goal_candidate' if hit else 'only_far_candidates')
        tally[(end, kind)] += 1
        if hit:
            tally[('near_goal_state', str(hit[0][4]) if hit[0][4] else ('confirmed' if hit[0][5] else 'unconfirmed'))] += 1
        print('%-28s %-10s %-19s %-20s cands=%d %s' % (r['uid'].split('val/')[1], p['target'], end, kind, len(rows),
              ' | '.join('d=%.1f cid=%d n=%d best=%.2f rej=%s conf=%s clip=%s' % x for x in rows[:3])))
print()
for k, v in sorted(tally.items()):
    print(k, v)
