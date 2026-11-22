"""Offline (evaluator-side): label every SigLIP crop check of B3 runs as true / wrong object by the
candidate's distance to the dataset goals, and print the gap distribution per target.

python3 tools/objectnav/b3/clip_gap_diag.py RUN [RUN ...]
gap = best confusable score - best target score (> 0: rejected at reject_margin 0). Goal positions
are semantic GT: used here only, never in the policy. Policy frame (x, y) = (habitat x, -habitat z).
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from neusymnav.objectnav.episodes import load_episode_set  # noqa: E402

TRUE_M, WRONG_M = 1.0, 2.0
episodes = {e.uid: e for e in load_episode_set('hm3d_v2', 'val')}
rows = defaultdict(list)
seen = set()
for run in sys.argv[1:]:
    for line in open(ROOT / 'runs/objectnav' / run / 'trajectories.jsonl'):
        r = json.loads(line)
        if r['uid'] in seen:
            continue
        seen.add(r['uid'])
        p = r['diagnostics']['policy']
        goals = [(g.position[0], -g.position[2]) for g in episodes[r['uid']].goals]
        cents = {c['cid']: c['centroid_xy'] for c in p['candidates']}
        for e in p.get('clip_verify', []):
            if not e.get('scores') or e['cid'] not in cents:
                continue
            d = min(math.dist(cents[e['cid']], g) for g in goals)
            label = 'true' if d <= TRUE_M else ('wrong' if d >= WRONG_M else 'unclear')
            gap = e.get('gap')
            if gap is None:
                s = e['scores']
                gap = max(s[1:]) - s[0]
            rows[p['target']].append((round(gap, 4), label, e['top'], r['uid'].split('val/')[1]))
for target, xs in sorted(rows.items()):
    xs.sort()
    print('== %s: %d checks' % (target, len(xs)))
    for label in ('true', 'wrong', 'unclear'):
        g = [x[0] for x in xs if x[1] == label]
        print('  %-7s n=%-3d gaps %s' % (label, len(g), ' '.join('%+.3f' % v for v in g)))
    for thr in (0.0, 0.005, 0.01, 0.02, 0.03):
        kt = sum(1 for x in xs if x[1] == 'true' and x[0] < thr if thr > 0) + sum(
            1 for x in xs if x[1] == 'true' and x[0] <= 0 and thr == 0)
        rw = sum(1 for x in xs if x[1] == 'wrong' and (x[0] >= thr if thr > 0 else x[0] > 0))
        print('  reject at gap >= %.3f: keeps %d/%d true, rejects %d/%d wrong' % (
            thr, kt, sum(1 for x in xs if x[1] == 'true'), rw, sum(1 for x in xs if x[1] == 'wrong')))
