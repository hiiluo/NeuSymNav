#!/usr/bin/env python3
"""Offline factorial RoomFinder experiment. Never changes production defaults."""
from __future__ import annotations
import argparse
import copy
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import yaml
from neusymnav.evaluation.room_diagnostics import diagnose_room_finder_result, render_room_overlay_svg


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def variant_config(config, component, room):
    value=copy.deepcopy(config)
    finder=value['backend']['update_functors']['rooms']['room_finder']
    finder['min_component_size']=component
    finder['min_room_size']=room
    return value


def partition_comparison(reference, candidate):
    if reference.keys()!=candidate.keys():
        raise ValueError('comparison requires same place IDs')
    pairs=len(reference)*(len(reference)-1)//2
    choose2=lambda n:n*(n-1)//2
    reference_same=sum(choose2(n) for n in Counter(v for v in reference.values() if v is not None).values())
    candidate_same=sum(choose2(n) for n in Counter(v for v in candidate.values() if v is not None).values())
    intersection=Counter((reference[i],candidate[i]) for i in reference if reference[i] is not None and candidate[i] is not None)
    disagreements=reference_same+candidate_same-2*sum(choose2(n) for n in intersection.values())
    return {'pair_count':pairs,'pair_disagreement_count':disagreements,
            'pair_disagreement_fraction':disagreements/pairs if pairs else 0.,
            'unassigned_count':sum(v is None for v in candidate.values()),
            'scope':'same_graph_label_invariant_parameter_sensitivity_not_accuracy_or_temporal_stability'}


def memberships(native):
    labels={p['id']:None for p in native['places']}
    for c in native['room_finder']['post_neighbor_clusters']:
        if c['accepted_as_room']:
            for pid in c['place_ids']:labels[pid]=c['room_id']
    return labels


def support(native):
    points=native['places']
    roi=[p for p in points if -.9<=p['position_xyz'][0]<=.4 and -2.8<=p['position_xyz'][1]<=-.8]
    roi_ids={p['id'] for p in roi}
    cells=lambda pp:len({tuple(math.floor(x/.25) for x in p['position_xyz'][:2]) for p in pp})
    rf=native['room_finder'];labels=memberships(native)
    local_rooms=sorted({labels[i] for i in roi_ids if labels[i] is not None})
    return {'qualitative_roi_not_GT':True,'roi_xy_m':[[-.9,-2.8],[.4,-.8]],
            'place_count':len(points),'edge_count':len(native['edges']),
            'roi_place_count':len(roi),'xy_cells_0p25m':cells(points),'roi_xy_cells_0p25m':cells(roi),
            'roi_raw_component_sizes':[c['size'] for c in rf['raw_components'] if roi_ids.intersection(c['place_ids'])],
            'roi_retained_seed_sizes':[c['size'] for c in rf['seeds_before_neighbors'] if roi_ids.intersection(c['place_ids'])],
            'roi_assigned_room_ids':local_rooms,
            'roi_room_total_sizes':[c['size'] for c in rf['post_neighbor_clusters'] if c['accepted_as_room'] and c['room_id'] in local_rooms],
            'roi_unassigned_count':sum(labels[i] is None for i in roi_ids)}


def run_case(binary,graph,config_path,out):
    out.mkdir(parents=True,exist_ok=False)
    cmd=[str(binary.resolve()),'--graph',str(graph.resolve()),'--config',str(config_path.resolve()),
         '--filtration-log',str((out/'filtration').resolve())]
    (out/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    start=time.monotonic()
    with (out/'native-result.json').open('w') as stdout,(out/'native.stderr').open('w') as stderr:
        proc=subprocess.run(cmd,stdout=stdout,stderr=stderr,timeout=60,
                            env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'))
    (out/'exit').write_text(str(proc.returncode)+'\n')
    if proc.returncode:raise RuntimeError(f'native case failed: {out}')
    result=json.loads((out/'native-result.json').read_text())
    report=diagnose_room_finder_result(result)
    (out/'room-overlay.svg').write_text(render_room_overlay_svg(result))
    rf=result['room_finder']
    summary={'selected_threshold_m':rf['selected_threshold_m'],
             'raw_component_sizes':[c['size'] for c in rf['raw_components']],
             'retained_seed_sizes':[c['size'] for c in rf['seeds_before_neighbors']],
             'post_cluster_sizes':[c['size'] for c in rf['post_neighbor_clusters']],
             'accepted_room_sizes':[c['size'] for c in rf['post_neighbor_clusters'] if c['accepted_as_room']],
             'room_count':rf['room_count'],'support':support(result),'elapsed_s':time.monotonic()-start,
             'quality_claim':report['quality_claim']}
    return result,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-binary',type=Path,required=True)
    parser.add_argument('--graph',type=Path,required=True)
    parser.add_argument('--expected-graph-sha256',required=True)
    parser.add_argument('--config',type=Path,default=Path('configs/hydra/config/datasets/neusymnav.yaml'))
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    initial_sha=sha(args.graph);config_sha=sha(args.config)
    if initial_sha!=args.expected_graph_sha256:raise ValueError('frozen graph SHA mismatch')
    config=yaml.safe_load(args.config.read_text());out=args.output_dir
    out.mkdir(parents=True,exist_ok=True)
    rows=[];baseline=None;native_geometry=None
    matrix=[(c,r) for c in (10,5,3) for r in (10,5)]+[(10,10)]
    for index,(c,r) in enumerate(matrix):
        name=f'c{c}-r{r}'+('-repeat' if index==6 else '')
        case_config=out/(name+'.yaml')
        case_config.write_text(yaml.safe_dump(variant_config(config,c,r),sort_keys=False))
        result,row=run_case(args.native_binary,args.graph,case_config,out/name)
        geometry=json.dumps({'places':result['places'],'edges':result['edges']},sort_keys=True)
        if baseline is None:baseline=result;native_geometry=geometry
        if geometry!=native_geometry:raise ValueError('input place/edge attributes changed across size variants')
        row.update(case=name,min_component_size=c,min_room_size=r,config_sha256=sha(case_config),
                   comparison_to_baseline=partition_comparison(memberships(baseline),memberships(result)))
        if index==6:
            row['repeat_exact_algorithm_output']=result['room_finder']==baseline['room_finder']
            if not row['repeat_exact_algorithm_output']:raise ValueError('baseline native output not repeatable')
        rows.append(row)
    if sha(args.graph)!=initial_sha or sha(args.config)!=config_sha:raise ValueError('source changed during experiment')
    linked=subprocess.check_output(['ldd',str(args.native_binary.resolve())],text=True)
    library_hashes={}
    for line in linked.splitlines():
        if any(name in line for name in ('libhydra.so','libspark_dsg.so','libconfig_utilities.so')):
            path=line.split('=>',1)[1].strip().split()[0]
            library_hashes[path]=sha(path)
    if not any('libhydra.so' in path for path in library_hashes):raise ValueError('native Hydra linked-library provenance unavailable')
    source_hashes={str(p):sha(p) for p in [Path(__file__).resolve(),Path('tools/native/hydra_room_diagnostic.cpp'),Path('src/neusymnav/evaluation/room_diagnostics.py'),Path('.runtime/hydra_ws/src/hydra/src/rooms/room_finder.cpp'),Path('.runtime/hydra_ws/src/hydra/src/rooms/graph_clustering.cpp')]}
    summary={'source_sha256':source_hashes,'linked_library_sha256':library_hashes,'ldd':linked,'schema_version':1,'scope':'experimental_offline_size_factorial','production_defaults_changed':False,
             'graph_sha256':initial_sha,'baseline_config_sha256':config_sha,'binary_sha256':sha(args.native_binary),
             'source_graph':str(args.graph),'native_input_geometry_identical_across_cases':True,
             'independent_annotation_available':False,'rows':rows}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    fields=['case','min_component_size','min_room_size','selected_threshold_m','raw_component_sizes','retained_seed_sizes','accepted_room_sizes','room_count']
    with (out/'summary.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    print((out/'summary.csv').read_text())


if __name__=='__main__':main()
