"""(run from the repo root) Paired DEV167 gate: python3 tools/objectnav/paper/dev167_gate.py NEW_RUN[,NEW_RUN...] [--ref paper-b0-dev60,paper-b0-devx107]
Earlier runs in the list win for a uid (e.g. a plant/sofa subset run before the full-split runs)."""
import json, sys, math
from collections import Counter
R = 'runs/objectnav/'
def outs(names):
    d = {}
    for n in names.split(','):
        for l in open(R + n + '/trajectories+evidence-outcomes.jsonl'):
            r = json.loads(l); d.setdefault(r['uid'], r)
    return d
new = outs(sys.argv[1]); ref = outs(sys.argv[sys.argv.index('--ref') + 1] if '--ref' in sys.argv else 'paper-b0-dev60,paper-b0-devx107')
uids = sorted(set(ref) & set(new))
w = [u for u in uids if new[u]['success'] and not ref[u]['success']]
l = [u for u in uids if ref[u]['success'] and not new[u]['success']]
n = len(w) + len(l); k = min(len(w), len(l))
p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
sr = lambda d: sum(d[u]['success'] for u in uids)
spl = lambda d: sum(d[u]['spl'] for u in uids) / len(uids)
print('n=%d (missing in new: %d)  SR %d -> %d  SPL %.3f -> %.3f  wins %d losses %d net %+d  p=%.3f  gate %s' % (
    len(uids), len(set(ref) - set(new)), sr(ref), sr(new), spl(ref), spl(new), len(w), len(l), len(w) - len(l), p,
    'PASS' if len(w) - len(l) >= 3 else 'FAIL'))
for tag, us in (('win', w), ('loss', l)):
    for u in us: print(' ', tag, u[12:], new[u]['category'], ref[u]['failure_mode'], '->', new[u]['failure_mode'] or 'OK')
print('failure modes new:', dict(Counter(new[u]['failure_mode'] for u in uids if not new[u]['success'])))
