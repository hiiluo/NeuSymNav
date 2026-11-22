"""B1 analysis (usage: python3 tools/objectnav/b1/redetect_at_stop.py runs/objectnav/RUN). For each confirmed stop: was the stop candidate re-detected (target goal) in frames since FACE started?"""
import gzip, json, sys
from collections import Counter
run = sys.argv[1]
out = {json.loads(l)['uid']: json.loads(l) for l in open(run + '/trajectories+evidence-outcomes.jsonl')}
rows = []
for l in open(run + '/trajectories.jsonl'):
    r = json.loads(l); p = r['diagnostics']['policy']
    st = p.get('stop') or {}
    if not st or 'confirmed' not in str(st.get('note')):
        continue
    cid = st['cid']; ev = p['events']
    face = [e['step'] for e in ev if e['state'] == 'FACE' and e['target'] == cid]
    t0 = face[-1] if face else st['step']
    cands = {c['cid']: c for c in p['candidates']}
    ids = {cid} | set(cands.get(cid, {}).get('merged_from', []))
    f = run + '/evidence/' + r['uid'].replace('/', '_').replace('#', '_') + '.jsonl.gz'
    best_near, best_last5 = 0.0, 0.0
    for x in map(json.loads, gzip.open(f, 'rt')):
        for d in x['detections']:
            if d.get('cid') in ids and d.get('goal') == p['target']:
                if x['step'] >= t0: best_near = max(best_near, d['score'])
                if x['step'] >= st['step'] - 5: best_last5 = max(best_last5, d['score'])
    o = out[r['uid']]
    rows.append((r['uid'][12:], p['target'], o['failure_mode'] or 'OK', round(best_near, 2), round(best_last5, 2), st['step'] - t0))
for row in sorted(rows, key=lambda x: (x[2] == 'OK', x[1])): print(*row)
c = Counter((x[2] == 'OK', x[4] > 0) for x in rows); print('(success, redetected in last 6 steps):', dict(c))
