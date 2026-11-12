#!/usr/bin/env python3
"""Summarize genuine Hydra extraction traces, preserving geometry and provenance."""
import argparse, hashlib, json
from collections import Counter
from pathlib import Path

ROI = (-0.9, 0.4, -2.8, -0.8)
STAGES = ('before_merge', 'after_merge', 'final')
def roi(p):
    return p is not None and ROI[0] <= p[0] <= ROI[1] and ROI[2] <= p[1] <= ROI[3]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def gidx(g): return tuple(g['index'])
def counts(records):
    out={}
    for stage in STAGES:
        x=[r for r in records if r.get('stage') == stage]
        out[stage]={}
        for kind in ('gvd','compressed','place'):
            a=[r for r in x if r['kind']==kind]
            b=[r for r in a if roi(r.get('xyz'))]
            out[stage][kind]={'all':len(a),'roi':len(b)}
            if kind=='gvd':
                out[stage][kind].update(eligible_all=sum(v['eligible_clearance'] for v in a), eligible_roi=sum(v['eligible_clearance'] for v in b))
            if kind=='compressed':
                out[stage][kind].update(in_graph_all=sum(v['graph_has_node'] for v in a), in_graph_roi=sum(v['graph_has_node'] for v in b))
    upd=[r for r in records if r['kind']=='updated_gvd']
    merge=[r for r in records if r['kind']=='merge']
    out['updates']={'all':len(upd),'roi':sum(roi(x['xyz']) for x in upd),'roi_isolated_at_visit':sum(roi(x['xyz']) and x['isolated_at_visit'] for x in upd),'roi_below_clearance':sum(roi(x['xyz']) and not x['eligible_clearance'] for x in upd)}
    out['merges']=len(merge)
    out['roi_place_records']={s:[{'id':r['id'], 'xyz':r['xyz'], 'clearance':r['clearance'], 'basis':r['basis']} for r in records if r['kind']=='place' and r.get('stage')==s and roi(r['xyz'])] for s in STAGES}
    pre={r['id']:r for r in records if r['kind']=='compressed' and r.get('stage')=='before_merge'}
    out['roi_merge_events']=[]
    out['all_merge_events']=[]
    for m in merge:
        left=pre.get(m['from_compressed_id']); right=pre.get(m['to_compressed_id'])
        if left and right:
            event={'from_id':left['id'],'from_xyz':left.get('xyz'),'from_basis':left.get('basis'),'from_active_refs':left['active_refs'],'from_archived_refs':left['archived_refs'], 'to_id':right['id'],'to_xyz':right.get('xyz'),'to_basis':right.get('basis'),'to_active_refs':right['active_refs'],'to_archived_refs':right['archived_refs']}
            out['all_merge_events'].append(event)
            if roi(left.get('xyz')) or roi(right.get('xyz')): out['roi_merge_events'].append(event)
    return out

def analyze(path):
    frames=[]; current=None; last=None; errors=[]; n=0
    with path.open() as f:
        for n,line in enumerate(f,1):
            try: r=json.loads(line)
            except Exception as e: errors.append(f'line {n}: {e}'); break
            k=r.get('kind')
            if k=='begin':
                if current is not None: errors.append(f'line {n}: nested begin')
                current=[r]
            elif current is None: errors.append(f'line {n}: {k} outside extract')
            else:
                current.append(r)
                if r.get('timestamp_ns')!=current[0]['timestamp_ns']: errors.append(f'line {n}: timestamp mismatch')
                if k=='end':
                    stages=counts(current)
                    frames.append({'ordinal':len(frames)+1,'timestamp_ns':r['timestamp_ns'],'config':current[0], **stages})
                    last=current; current=None
    if current is not None: errors.append('incomplete final extract')
    if not last: raise ValueError(f'no complete extract in {path}')
    ts=[x['timestamp_ns'] for x in frames]
    if any(b<a for a,b in zip(ts,ts[1:])): errors.append('nonmonotonic timestamps')
    result={'schema':1,'trace_path':str(path.resolve()),'trace_sha256':sha(path),'lines':n,'roi_xy':ROI,'complete_extracts':len(frames),'errors':errors,'duplicate_adjacent_timestamps':sum(a==b for a,b in zip(ts,ts[1:])), 'frames':frames}
    result['last_records']=[r for r in last if r.get('kind') in ('gvd','compressed','place','merge','updated_gvd')]
    return result

def final_summary(data, backend=None):
    rec=data['last_records']; stage=lambda s,k:[x for x in rec if x.get('stage')==s and x['kind']==k]
    gd=stage('final','gvd'); gmap={x['id']:x for x in gd}
    cs={s:stage(s,'compressed') for s in STAGES}; ps={s:stage(s,'place') for s in STAGES}
    byid={s:{x['id']:x for x in cs[s]} for s in STAGES}
    relevant=set()
    for s in STAGES:
        for c in cs[s]:
            if roi(c.get('xyz')) or any(roi(gmap[i]['xyz']) for i in c['active_refs']+c['archived_refs'] if i in gmap): relevant.add(c['id'])
    merges=[x for x in rec if x['kind']=='merge']
    relevant |= {x['to_compressed_id'] for x in merges if x['from_compressed_id'] in relevant}
    relevant |= {x['from_compressed_id'] for x in merges if x['to_compressed_id'] in relevant}
    enriched_merges=[]
    for m in merges:
        left=byid['before_merge'].get(m['from_compressed_id']); right=byid['before_merge'].get(m['to_compressed_id'])
        if left is None or right is None: raise ValueError('merge missing pre-merge compressed node')
        enriched_merges.append({'from':left,'to':right,'from_roi':roi(left.get('xyz')),'to_roi':roi(right.get('xyz'))})
    result={'timestamp_ns':data['frames'][-1]['timestamp_ns'],
      'roi_gvd':[g for g in gd if roi(g['xyz'])],
      'roi_places':{s:[p for p in ps[s] if roi(p['xyz'])] for s in STAGES},
      'relevant_compressed':{s:[c for c in cs[s] if c['id'] in relevant] for s in STAGES},
      'relevant_merges':[m for m in merges if m['from_compressed_id'] in relevant or m['to_compressed_id'] in relevant],
      'all_merges':merges, 'merge_details':enriched_merges}
    hidden=[]
    for c in cs['final']:
        if not roi(c.get('xyz')) or c['graph_has_node']: continue
        events=[{'ordinal':f['ordinal'],'timestamp_ns':f['timestamp_ns'],**e} for f in data['frames'] for e in f['all_merge_events'] if e['from_id']==c['id']]
        refs=[gmap[i] for i in c['active_refs']+c['archived_refs'] if i in gmap]
        hidden.append({'compressed':c,'support_gvd':refs,'support_eligible':sum(g['eligible_clearance'] for g in refs),'support_roi':sum(roi(g['xyz']) for g in refs),'most_recent_losing_merge':events[-1] if events else None})
    result['hidden_roi_representatives']=hidden
    if backend:
        b=json.loads(backend.read_text()); places=b['places']
        # NodeSymbol('p', n): category byte occupies top 8 bits.
        front={f"p({p['id'] & ((1<<56)-1)})":p for p in ps['final']}
        back={p['id']:p for p in places}
        common=front.keys() & back.keys()
        diffs=[{'id':i,'front_xyz':front[i]['xyz'],'backend_xyz':back[i]['position_xyz']} for i in sorted(common) if any(abs(a-b)>1e-6 for a,b in zip(front[i]['xyz'],back[i]['position_xyz']))]
        result['backend_comparison']={'source':str(backend.resolve()), 'sha256':sha(backend), 'front_count':len(front),'backend_count':len(back),'common_ids':len(common), 'front_only':sorted(front.keys()-back.keys()),'backend_only':sorted(back.keys()-front.keys()),'same_id_moved_gt_1e-6':diffs,'front_roi':sorted(i for i,p in front.items() if roi(p['xyz'])),'backend_roi':[p for p in places if roi(p['position_xyz'])]}
    return result

def compare(a,b):
    def maps(d):
        gs={gidx(g):g for g in d['last_records'] if g['kind']=='gvd' and g.get('stage')=='final' and roi(g['xyz'])}
        return gs
    x,y=maps(a),maps(b); common=x.keys()&y.keys()
    attrs=['xyz','clearance','basis','eligible_clearance']
    changed=[{'index':i,'a':{k:x[i][k] for k in attrs},'b':{k:y[i][k] for k in attrs}} for i in sorted(common) if any(x[i][k]!=y[i][k] for k in attrs)]
    def reps(d,stage):
        return {tuple(r['index']):r for r in d['last_records'] if r['kind']=='compressed' and r.get('stage')==stage and r['graph_has_node'] and roi(r.get('xyz')) and 'index' in r}
    rep_comparison={}
    for stage in STAGES:
        r1,r2=reps(a,stage),reps(b,stage)
        rep_comparison[stage]={'a_count':len(r1),'b_count':len(r2),'shared_indices':[list(i) for i in sorted(r1.keys() & r2.keys())], 'a_only':[r1[i] for i in sorted(r1.keys()-r2.keys())], 'b_only':[r2[i] for i in sorted(r2.keys()-r1.keys())]}
    def groups(d):
        g={r['id']:r for r in d['last_records'] if r['kind']=='gvd' and r.get('stage')=='final'}
        result=[]
        for c in (r for r in d['last_records'] if r['kind']=='compressed' and r.get('stage')=='final'):
            refs=[g[i] for i in c['active_refs']+c['archived_refs'] if i in g]
            if roi(c.get('xyz')) or any(roi(r['xyz']) for r in refs):
                result.append((c,{gidx(r) for r in refs}))
        return result
    groups_a,groups_b=groups(a),groups(b)
    overlap=[]
    for c,ids in groups_a:
        matches=[]
        for d,jds in groups_b:
            intersect=ids&jds
            if intersect: matches.append({'id':d['id'],'xyz':d.get('xyz'),'graph_has_node':d['graph_has_node'],'shared_voxel_indices':[list(i) for i in sorted(intersect)],'shared_count':len(intersect),'b_support_count':len(jds)})
        matches.sort(key=lambda m:-m['shared_count'])
        overlap.append({'a_id':c['id'],'a_xyz':c.get('xyz'),'a_graph_has_node':c['graph_has_node'],'a_support_count':len(ids),'matches':matches})
    return {'compressed_support_overlap_by_physical_index':overlap,'roi_representative_comparison':rep_comparison,'roi_gvd_a':len(x),'roi_gvd_b':len(y),'shared_indices':len(common),'a_only':sorted(x.keys()-y.keys()),'b_only':sorted(y.keys()-x.keys()),'same_index_changed_attributes':changed,'same_timestamp':a['frames'][-1]['timestamp_ns']==b['frames'][-1]['timestamp_ns'], 'timestamps_a':[f['timestamp_ns'] for f in a['frames']], 'timestamps_b':[f['timestamp_ns'] for f in b['frames']]}

def main():
    p=argparse.ArgumentParser(); p.add_argument('traces',nargs='+',type=Path); p.add_argument('--backend',action='append',type=Path,default=[]); p.add_argument('--revisions',action='append',type=Path,default=[]); p.add_argument('--output',required=True,type=Path); args=p.parse_args()
    if len(args.backend) not in (0,len(args.traces)): p.error('provide either zero or one backend per trace')
    if len(args.revisions) not in (0,len(args.traces)): p.error('provide either zero or one revision directory per trace')
    datasets=[analyze(t) for t in args.traces]
    for i,d in enumerate(datasets):
        if args.revisions:
            revs=[json.loads(f.read_text()) for f in sorted(args.revisions[i].glob('[0-9]*.json'))]
            tr=[f['timestamp_ns'] for f in d['frames']]; rt=[r['capture_monotonic_ns'] for r in revs]
            d['revision_comparison']={'directory':str(args.revisions[i].resolve()), 'revision_count':len(revs), 'extract_count':len(tr), 'timestamps_equal_in_order':tr==rt, 'final_frame_index':revs[-1]['frame_index'] if revs else None,'final_input_prefix_sha256':revs[-1]['input_prefix_sha256'] if revs else None}
            if tr != rt: d['errors'].append('extract/revision timestamps differ')
    out={'traces':[{k:v for k,v in d.items() if k!='last_records'} for d in datasets], 'final':[final_summary(d,args.backend[i] if args.backend else None) for i,d in enumerate(datasets)]}
    if len(datasets)==2: out['physical_gvd_comparison']=compare(*datasets)
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
    if any(d['errors'] for d in datasets): raise SystemExit(1)
if __name__=='__main__':main()
