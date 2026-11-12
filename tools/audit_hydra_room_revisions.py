#!/usr/bin/env python3
"""Audit actual native room memberships exported by offline per-revision replay."""
import argparse,csv,json,math,subprocess,time,hashlib
from pathlib import Path
from neusymnav.evaluation.room_temporal_audit import audit_revisions,_partition_pairs


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--revision-dir',required=True,type=Path);p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--config',required=True,type=Path);p.add_argument('--native-binary',required=True,type=Path);args=p.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    paths=sorted(args.revision_dir.glob('[0-9][0-9][0-9][0-9].json'));frames=[json.loads(path.read_text()) for path in paths]
    if not frames or frames[0]['graph_revision']!=1 or frames[-1]['graph_revision']!=len(frames):raise ValueError('fullhistory revisions1..N required')
    config_sha=hashlib.sha256(args.config.read_bytes()).hexdigest()
    for frame in frames:
        if frame['config_sha256']!=config_sha:raise ValueError('revision config differs from reconstruction config')
        if hashlib.sha256(Path(frame['graph_path']).read_bytes()).hexdigest()!=frame['graph_sha256']:raise ValueError('revision graph integrity mismatch')
    report=audit_revisions(frames)
    seeds=[]
    for frame in frames:
        revision=frame['graph_revision'];out=args.output_dir/f'{revision:04d}';out.mkdir()
        cmd=[str(args.native_binary.resolve()),'--graph',frame['graph_path'],'--config',str(args.config.resolve()),'--filtration-log',str((out/'filtration').resolve())]
        with (out/'native-result.json').open('w') as stdout,(out/'native.stderr').open('w') as stderr:
            result=subprocess.run(cmd,stdout=stdout,stderr=stderr,timeout=30)
        (out/'native.exit').write_text(str(result.returncode)+'\n')
        if result.returncode:raise RuntimeError('native reconstruction failed')
        native=json.loads((out/'native-result.json').read_text());rf=native['room_finder'];roi={p['id'] for p in native['places'] if -.9<=p['position_xyz'][0]<=.4 and -2.8<=p['position_xyz'][1]<=-.8}
        actual={p['id']:p['recorded_room_id'] for p in native['places']};reconstructed=dict.fromkeys(actual)
        for cluster in rf['post_neighbor_clusters']:
            if cluster['accepted_as_room']:
                for pid in cluster['place_ids']:reconstructed[pid]=cluster['room_id']
        seeds.append({'actual_vs_fresh_partition':_partition_pairs(actual,reconstructed),'graph_revision':revision,'scope':'fresh_RoomFinder_reconstruction_on_current_actual_export; IDs_may_differ_from_actual_history','selected_threshold_m':rf['selected_threshold_m'],'seed_sizes':[c['size'] for c in rf['seeds_before_neighbors']],'roi_seed_sizes':[c['size'] for c in rf['seeds_before_neighbors'] if roi.intersection(c['place_ids'])],'raw_roi_component_sizes':[c['size'] for c in rf['raw_components'] if roi.intersection(c['place_ids'])]})
    report['native_seed_reconstruction']=seeds
    report['cost_scope']='native process_frame including original summary, diagnostic export excluded; trace library times not valid for clean budget comparison'
    def stats(values):
        values=sorted(values);return {'count':len(values),'p50_ms':values[math.ceil(.5*len(values))-1],'p95_ms':values[math.ceil(.95*len(values))-1],'max_ms':max(values)}
    report['process_cost']=stats([f['native_process_including_existing_summary_ms'] for f in frames]);report['export_cost']=stats([f['diagnostic_export_ms'] for f in frames])
    (args.output_dir/'temporal-audit.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    fields=['graph_revision','place_count','room_count','room_sizes','unassigned_count','qualitative_roi_place_count','roi_room_ids']
    with (args.output_dir/'revisions.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(report['revisions'])
    summary={'revisions':len(frames),'last':report['revisions'][-1], 'raw_id_changes':sum(t['raw_room_id_change_count'] for t in report['transitions']),'split_events':sum(len(t['split_events']) for t in report['transitions']),'merge_events':sum(len(t['merge_events']) for t in report['transitions']),'transitions_with_partition_change_including_assignment':sum((t['pair_disagreement_fraction'] or 0)>0 for t in report['transitions']),'transitions_with_assigned_partition_change':sum((t['both_assigned_comparison']['pair_disagreement_fraction'] or 0)>0 for t in report['transitions']),'last_seed':seeds[-1],'process_cost':report['process_cost'],'export_cost':report['export_cost']}
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='last'},sort_keys=True))


if __name__=='__main__':main()
