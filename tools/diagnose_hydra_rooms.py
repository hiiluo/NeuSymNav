#!/usr/bin/env python3
"""Read-only native RoomFinder reconstruction and source-pinned diagnostic export."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from neusymnav.evaluation.room_diagnostics import diagnose_room_finder_result, render_room_overlay_svg


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-binary',required=True,type=Path)
    parser.add_argument('--graph',type=Path);parser.add_argument('--manifest',type=Path)
    parser.add_argument('--config',type=Path,default=Path('configs/hydra/config/datasets/neusymnav.yaml'))
    parser.add_argument('--synthetic-fixture',action='store_true')
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args()
    if args.synthetic_fixture and (args.graph or args.manifest):parser.error('synthetic input must be separate from recorded input')
    if not args.synthetic_fixture and not(args.graph and args.manifest):parser.error('recorded input requires --graph and --manifest')
    provenance={'binary_sha256':sha(args.native_binary),'config_sha256':sha(args.config),
                'scope':'offline_final_graph_reconstruction_not_original_per_frame_trace','synthetic':args.synthetic_fixture}
    if not args.synthetic_fixture:
        manifest=json.loads(args.manifest.read_text())
        if not manifest.get('complete') or args.graph.stat().st_size!=manifest['graph_bytes'] or sha(args.graph)!=manifest['graph_sha256']:
            raise ValueError('graph/manifest integrity mismatch')
        if provenance['config_sha256']!=manifest['config_sha256']:raise ValueError('recorded room config hash mismatch')
        provenance.update(graph_sha256=manifest['graph_sha256'],manifest_sha256=sha(args.manifest),episode_id=manifest['episode_id'],run_id=manifest['run_id'],graph_revision=manifest['graph_revision'],input_prefix_sha256=manifest['input_prefix_sha256'],source_sha256=manifest['source_sha256'],build_sha256=manifest['build_sha256'])
    args.output_dir.mkdir(parents=True,exist_ok=True)
    cmd=[str(args.native_binary.resolve()),'--config',str(args.config.resolve()),'--filtration-log',str((args.output_dir/'native-filtration').resolve())]
    cmd+=['--synthetic-two-room'] if args.synthetic_fixture else ['--graph',str(args.graph.resolve())]
    (args.output_dir/'command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    with (args.output_dir/'native-result.json').open('w') as out,(args.output_dir/'native.stderr').open('w') as err:
        p=subprocess.run(cmd,stdout=out,stderr=err,timeout=30,env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'))
    (args.output_dir/'native.exit').write_text(str(p.returncode)+'\n')
    if p.returncode:raise RuntimeError('native diagnostic failed; see native.stderr')
    resultpath=args.output_dir/'native-result.json'
    if resultpath.stat().st_size>128*1024*1024:raise ValueError('native diagnostic output exceeds byte budget')
    result=json.loads(resultpath.read_text());report=diagnose_room_finder_result(result);report['provenance']=provenance
    if not args.synthetic_fixture:
        if sha(args.graph)!=manifest['graph_sha256']:raise ValueError('input graph changed during diagnostic')
        parity=result['recorded_membership'];report['membership_parity']=parity
        if parity['assigned_count']!=parity['exactly_matching_reconstruction']:raise ValueError('reconstruction differs from recorded membership; requires investigation')
    (args.output_dir/'room-diagnostic.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    (args.output_dir/'room-overlay.svg').write_text(render_room_overlay_svg(result))
    print(json.dumps(report['diagnosis'],sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
