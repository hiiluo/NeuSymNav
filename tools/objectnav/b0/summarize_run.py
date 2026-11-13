#!/usr/bin/env python3
"""Phase 3: one readable report for a scored B0 run (project venv; no Habitat).

    .venv/bin/python tools/objectnav/b0/summarize_run.py runs/objectnav/b0/dev1

Reads <run>/trajectories.jsonl, the scorer output for the evidence-merged
trajectories (<run>/trajectories+evidence-summary.json / -outcomes.jsonl, or
the plain ones) and <run>/trajectories-evidence.jsonl; writes <run>/report.md
and prints it.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()] if Path(path).exists() else []


def fmt(v, nd=3):
    return '—' if v is None else ('%.*f' % (nd, v))


def ci(block, key):
    lo, hi = block[key + '_ci95']
    return '%s [%s, %s]' % (fmt(block[key]), fmt(lo), fmt(hi))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('run_dir', type=Path)
    a = ap.parse_args(argv)
    run = a.run_dir
    prefix = run / 'trajectories+evidence'
    if not Path(str(prefix) + '-summary.json').exists():
        prefix = run / 'trajectories'
    summary = json.loads(Path(str(prefix) + '-summary.json').read_text())
    outcomes = {o['uid']: o for o in load_jsonl(str(prefix) + '-outcomes.jsonl')}
    records = {r['uid']: r for r in load_jsonl(run / 'trajectories.jsonl')}
    evidence = {e['uid']: e['evidence'] for e in load_jsonl(run / 'trajectories-evidence.jsonl')}
    info = json.loads((run / 'run.json').read_text()) if (run / 'run.json').exists() else {}
    o = summary['overall']
    out = ['# B0 run report: %s' % run.name, '',
           'Run %s, policy %s, b0 config %s (sha %s…), git %s%s, max_sim_s %s.' % (
               info.get('run_id'), info.get('policy'), info.get('b0_config'), (info.get('b0_config_sha256') or '')[:10],
               (info.get('git_commit') or '')[:7], ' (dirty)' if info.get('git_dirty') else '', info.get('max_sim_s')), '',
           '## Overall', '',
           '| Episodes | SR [95% CI] | SPL [95% CI] | SoftSPL | DTG end (m) | STOP rate | invalid |',
           '|---|---|---|---|---|---|---|',
           '| %d | %s | %s | %s | %s | %s | %d |' % (o['episodes'], ci(o, 'success_rate'), ci(o, 'spl'), fmt(o['soft_spl']),
                                                   fmt(o['dtg_m'], 2), fmt(o['stop_rate'], 2), summary['invalid_episodes']),
           '', '## By category', '', '| Category | Episodes | SR | SPL | SoftSPL | DTG end (m) |', '|---|---|---|---|---|---|']
    for cat, b in summary['by_category'].items():
        out.append('| %s | %d | %s | %s | %s | %s |' % (cat, b['episodes'], fmt(b['success_rate']), fmt(b['spl']),
                                                       fmt(b['soft_spl']), fmt(b['dtg_m'], 2)))
    out += ['', '## By scene', '', '| Scene | Episodes | SR | SPL |', '|---|---|---|---|']
    for sc, b in summary['by_scene'].items():
        out.append('| %s | %d | %s | %s |' % (sc, b['episodes'], fmt(b['success_rate']), fmt(b['spl'])))
    out += ['', '## Failure modes (scorer, with offline evidence)', '', '| Mode | Episodes |', '|---|---|']
    for mode, n in sorted(summary['failure_modes'].items(), key=lambda kv: -kv[1]):
        out.append('| %s | %d |' % (mode, n))
    ends, wrong, floors, notes = Counter(), Counter(), Counter(), Counter()
    funnel = Counter()
    stages, walls, sims, frames = defaultdict(float), [], [], []
    for uid, r in records.items():
        d = r['diagnostics']
        pol = d.get('policy') or {}
        ends[d.get('end_reason')] += 1
        floors[(d.get('floor') or {}).get('method')] += 1
        for e in pol.get('events', []):
            if e['note'].startswith(('reject:', 'fallback', 'arrived')):
                notes[e['note']] += 1
        ev = evidence.get(uid, {})
        so = ev.get('stop_object') or {}
        if so and so.get('is_goal') is False:
            wrong[so.get('name') or '<unknown>'] += 1
        funnel['episodes'] += 1
        funnel['target seen (<= 3 m)'] += bool(ev.get('target_seen'))
        funnel['target detected (IoU >= 0.1)'] += bool(ev.get('target_detected'))
        funnel['a goal instance confirmed'] += bool(ev.get('confirmed_goal'))
        funnel['STOP called'] += bool(r.get('called_stop'))
        funnel['STOP on a goal instance'] += bool(so.get('is_goal'))
        funnel['success'] += bool(outcomes.get(uid, {}).get('success'))
        for k, v in (d.get('wall_s_by_stage') or {}).items():
            stages[k] += v
        walls.append(r.get('wall_time_s') or 0.0)
        sims.append(r.get('sim_time_s') or 0.0)
        frames.append(d.get('primary_frames') or 0)
    out += ['', '## Funnel (episodes)', '', '| Step | Episodes |', '|---|---|']
    out += ['| %s | %d |' % (k, funnel[k]) for k in ('episodes', 'target seen (<= 3 m)', 'target detected (IoU >= 0.1)',
                                                     'a goal instance confirmed', 'STOP called',
                                                     'STOP on a goal instance', 'success')]
    out += ['', '## How episodes ended', '', '| End reason | Episodes |', '|---|---|']
    out += ['| %s | %d |' % kv for kv in ends.most_common()]
    out += ['', 'Policy events: %s.' % dict(notes.most_common()),
            '', 'Wrong objects B0 stopped at (semantic name): %s.' % (dict(wrong.most_common()) or 'none'),
            '', 'Floor measurement methods: %s.' % dict(floors)]
    n = max(1, len(records))
    total = sum(walls)
    out += ['', '## Cost', '',
            'Wall time %.1f min total, %.1f s per episode; simulated %.1f s per episode; %.0f detection frames per episode.' % (
                total / 60, total / n, sum(sims) / n, sum(frames) / n),
            '', '| Stage | Wall s per episode | Share |', '|---|---|---|']
    for k, v in sorted(stages.items(), key=lambda kv: -kv[1]):
        out.append('| %s | %.1f | %.0f %% |' % (k, v / n, 100 * v / total if total else 0))
    text = '\n'.join(out) + '\n'
    (run / 'report.md').write_text(text)
    print(text)


if __name__ == '__main__':
    main()
