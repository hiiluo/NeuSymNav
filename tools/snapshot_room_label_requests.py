#!/usr/bin/env python3
"""Create immutable room-label requests from one exported native Hydra revision."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
from neusymnav.backends.hydra.labels import HydraLabelRasterizer
from neusymnav.backends.hydra.query import HydraSceneGraphQuery
from neusymnav.contracts.observations import Taxonomy
from neusymnav.rooms.requests import RoomLabelRequest, make_room_label_request


def build_room_label_requests(revision_record: dict, replay_manifest: dict,
        profile: dict, taxonomy_path: str | Path) -> tuple[RoomLabelRequest, ...]:
    summary = revision_record.get('summary')
    if not isinstance(summary, dict):
        raise ValueError('revision record has no native graph summary')
    revision = summary.get('graph_revision')
    prefix = summary.get('input_prefix_sha256')
    if revision_record.get('graph_revision') != revision:
        raise ValueError('revision record graph revision mismatch')
    if revision_record.get('input_prefix_sha256') != prefix:
        raise ValueError('revision record input prefix mismatch')
    selected = [item for item in replay_manifest.get('selected_inputs', [])
        if item.get('graph_revision') == revision]
    if len(selected) != 1:
        raise ValueError('replay manifest must contain exactly one input for graph revision')
    source_entry = selected[0]
    source = source_entry.get('source')
    if source_entry.get('input_prefix_sha256') != prefix:
        raise ValueError('selected input input prefix mismatch')
    if not isinstance(source, dict) or source.get('episode_id') != replay_manifest.get('episode_id'):
        raise ValueError('selected input episode provenance mismatch')

    taxonomy_data = json.loads(Path(taxonomy_path).read_text())
    if taxonomy_data.get('schema_version') != 1:
        raise ValueError('unsupported taxonomy schema')
    taxonomy = Taxonomy(taxonomy_data['vocabulary_id'], tuple(taxonomy_data['categories']),
        taxonomy_data.get('aliases', {}), taxonomy_data['provenance'])
    rasterizer = HydraLabelRasterizer(taxonomy)
    calibration = profile.get('sensor_config', {}).get('primary', {}).get('calibration', {})
    calibration_id = calibration.get('calibration_id')
    convention = calibration.get('coordinate_convention')
    calibration_hash = revision_record.get('calibration_hash')
    if not _sha256(calibration_hash) or convention not in (None, 'canonical_z_up_v1'):
        raise ValueError('profile calibration provenance is missing or mismatched')
    # Some locked Habitat profiles pin the calibrated sensor model by their
    # exact source hash but do not carry a separate calibration ID. Preserve
    # that provenance explicitly instead of inventing an unrelated identity.
    recorded_calibration_id = revision_record.get('calibration_id')
    if calibration_id and recorded_calibration_id and calibration_id != recorded_calibration_id:
        raise ValueError('profile calibration ID differs from revision source')
    calibration_id = calibration_id or recorded_calibration_id or f'hydra-calibration-sha256:{calibration_hash}'
    convention = convention or 'canonical_z_up_v1'
    if source.get('vocabulary_id') != taxonomy.vocabulary_id:
        raise ValueError('source vocabulary differs from pinned taxonomy')
    if source.get('labelspace_id') != rasterizer.LABELSPACE_ID or source.get('labelspace_hash') != rasterizer.labelspace_hash:
        raise ValueError('source labelspace differs from pinned taxonomy')

    episode_id = replay_manifest.get('episode_id')
    run_id = replay_manifest.get('run_id')
    if not isinstance(episode_id, str) or not isinstance(run_id, str):
        raise ValueError('replay manifest episode/run identity is missing')
    transform = {'calibration_id':calibration_id,'calibration_hash':calibration_hash,
        'coordinate_convention':convention}
    projection = HydraGraphAdapter.project(summary, episode_id=episode_id, run_id=run_id,
        stale=False, replay_required=False, failure_reason=None, last_source=source,
        native_metadata={'last_transform':transform})
    semantic_labels = {node['native_id']:node.get('semantic_label')
        for node in summary['nodes'] if node.get('layer_id') == 2}
    query = HydraSceneGraphQuery(projection, taxonomy, labelspace_id=rasterizer.LABELSPACE_ID,
        labelspace_hash=rasterizer.labelspace_hash, semantic_labels=semantic_labels,
        calibration_id=calibration_id)
    geometry_hash = _geometry_membership_hash(summary)
    source_hashes = {
        'native_graph_sha256':revision_record.get('graph_sha256'),
        'native_build_sha256':revision_record.get('build_sha256'),
        'native_config_sha256':revision_record.get('config_sha256'),
        'source_geometry_sha256':revision_record.get('source_geometry_hash'),
        'taxonomy_sha256':_sha256_file(Path(taxonomy_path)),
    }
    if any(not _sha256(value) for value in source_hashes.values()):
        raise ValueError('revision record lacks pinned graph/build/config/geometry provenance')
    room_support = {'episode_id':episode_id,'run_id':run_id,'geometry_revision':revision,
        'input_prefix_sha256':prefix,'geometry_hash':geometry_hash,'status':'available',
        'source_hashes':source_hashes}
    requests = make_room_label_request(query, evidence=None, room_support=room_support)
    manifest_hash = replay_manifest.get('source_manifest_sha256')
    return tuple(replace(request, source_manifest={**dict(request.source_manifest),
        'native_graph_sha256':revision_record['graph_sha256'],
        'native_build_sha256':revision_record['build_sha256'],
        'native_config_sha256':revision_record['config_sha256'],
        'replay_source_manifest_sha256':manifest_hash,
        'source_graph_revision':revision,
        'semantic_source':'recorded_hydra_semantic_labels',
        'visual_evidence_status':'not_recorded_in_this_snapshot'}) for request in requests)


def _geometry_membership_hash(summary: dict) -> str:
    payload = {'nodes':[{'native_id':n['native_id'],'layer_id':n['layer_id'],
            'position':n.get('position'),'parent_native_id':n.get('parent_native_id')}
        for n in sorted(summary['nodes'],key=lambda x:x['native_id'])],
        'edges':sorted(summary.get('edges',[]),key=lambda e:(e.get('source_native_id',''),
            e.get('target_native_id',''),e.get('kind','')))}
    raw = json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
    return hashlib.sha256(b'NeuSymNav:room-label-geometry-membership:v1\0'+raw).hexdigest()


def _sha256(value):
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision-json',required=True)
    parser.add_argument('--replay-manifest',required=True)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--taxonomy',default='configs/taxonomy-v1.json')
    parser.add_argument('--out-dir',required=True)
    args=parser.parse_args(argv)
    values=[json.loads(Path(path).read_text()) for path in
        (args.revision_json,args.replay_manifest,args.profile)]
    requests=build_room_label_requests(*values,args.taxonomy)
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    index={'schema_version':1,'request_count':len(requests),'requests':[]}
    for number,request in enumerate(requests):
        path=out/f'request-{number:03d}.json'
        path.write_text(request.to_json()+'\n')
        index['requests'].append({'path':path.name,'request_id':request.request_id,
            'request_key':request.key.to_dict(),'context_hash':request.key.context_hash,
            'object_count':request.context.distinct_object_count,
            'inference_block_reason':request.inference_block_reason})
    (out/'index.json').write_text(json.dumps(index,indent=2,sort_keys=True)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
