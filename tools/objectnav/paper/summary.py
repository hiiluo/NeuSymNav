#!/usr/bin/env python3
"""Summary of a paper-protocol run, optionally paired with a reference run (EVALUATOR-ONLY).

    python3 tools/objectnav/paper/summary.py runs/objectnav/<run> [--ref runs/objectnav/<ref>]

Reads the best scored outcomes (with offline evidence if present) and the trajectories:
SR / SPL / OSR, failure modes, end reasons, steps and collisions; with --ref, the paired
wins / losses, exact McNemar p and the keep rule (net >= +3, docs/objectnav/policy-branch-rules.md).
"""
import argparse
import json
import math
import statistics as st
from collections import Counter
from pathlib import Path


def outcomes(run: Path) -> dict:
    for name in ('trajectories+evidence-outcomes.jsonl', 'trajectories-outcomes.jsonl'):
        if (run / name).exists():
            return {d['uid']: d for d in (json.loads(l) for l in (run / name).open() if l.strip())}
    raise SystemExit('%s is not scored yet' % run)


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('run', type=Path)
    ap.add_argument('--ref', type=Path)
    a = ap.parse_args(argv)
    out = outcomes(a.run)
    traj = {d['uid']: d for d in (json.loads(l) for l in (a.run / 'trajectories.jsonl').open() if l.strip())}
    n = len(out)
    sr = sum(o['success'] for o in out.values())
    spl = sum(o['spl'] for o in out.values()) / n
    osr = sum(bool(o.get('oracle_success')) for o in out.values())
    print('%s: n=%d SR %d/%d (%.3f) SPL %.3f OSR %d/%d' % (a.run.name, n, sr, n, sr / n, spl, osr, n))
    print('failure modes:', dict(Counter(o['failure_mode'] for o in out.values() if not o['success']).most_common()))
    print('end reasons:', dict(Counter(t['diagnostics']['end_reason'] for t in traj.values()).most_common()))
    steps = [t['steps'] for t in traj.values()]
    coll = [t['diagnostics'].get('collisions', 0) for t in traj.values()]
    print('steps median %d max %d; collisions median %d max %d; path median %.1f m' % (
        st.median(steps), max(steps), st.median(coll), max(coll),
        st.median(t['diagnostics'].get('path_m', 0) for t in traj.values())))
    walls = [t.get('wall_time_s') or 0 for t in traj.values()]
    print('wall per episode: median %.0f s, total %.1f h' % (st.median(walls), sum(walls) / 3600))
    if a.ref:
        ref = outcomes(a.ref)
        common = sorted(set(out) & set(ref))
        wins = [u for u in common if out[u]['success'] and not ref[u]['success']]
        losses = [u for u in common if ref[u]['success'] and not out[u]['success']]
        print('paired vs %s (n=%d): SR %d -> %d, wins %d, losses %d, net %+d, exact McNemar p = %.3f, keep rule: %s' % (
            a.ref.name, len(common), sum(ref[u]['success'] for u in common), sum(out[u]['success'] for u in common),
            len(wins), len(losses), len(wins) - len(losses), mcnemar(len(wins), len(losses)),
            'PASS' if len(wins) - len(losses) >= 3 else 'FAIL'))
        for tag, rows in (('win', wins), ('loss', losses)):
            for u in rows:
                print('  %-4s %-28s %-10s ref %-18s new %s' % (tag, u.split('/', 2)[-1], traj[u].get('diagnostics', {}).get(
                    'policy', {}).get('target', ''), ref[u]['failure_mode'] or 'OK', out[u]['failure_mode'] or 'OK'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
