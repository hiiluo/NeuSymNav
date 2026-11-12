#!/usr/bin/env python3
"""Extract native observed place support and score only pinned offline room GT."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from neusymnav.evaluation.room_quality import RoomSupportSnapshot, evaluate_room_geometry


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def extract_support(graph_path: Path, manifest_path: Path) -> tuple[dict, RoomSupportSnapshot]:
    graph_path, manifest_path = graph_path.resolve(), manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    graph_sha = sha256(graph_path)
    if manifest.get('graph_sha256') != graph_sha or manifest.get('graph_bytes') != graph_path.stat().st_size:
        raise ValueError('graph does not match export manifest')
    if not manifest.get('complete'):
        raise ValueError('Hydra export manifest is incomplete')
    from spark_dsg import DynamicSceneGraph
    graph = DynamicSceneGraph.load(str(graph_path))
    nodes = []
    by_symbol_value = {}
    for layer in graph.layers:
        for node in layer.nodes:
            native_id = str(node.id)
            symbol_value = getattr(node.id, 'value', None)
            if type(symbol_value) is int:
                by_symbol_value[symbol_value] = native_id
            nodes.append((int(layer.id), node, native_id, symbol_value))
    native_by_id = {native_id: (layer_id, node, symbol_value)
                    for layer_id, node, native_id, symbol_value in nodes}

    support = {}
    assignments = {}
    for layer_id, node, native_id, _ in nodes:
        if layer_id != 3:
            continue
        position = np.asarray(getattr(node.attributes, 'position', ()), dtype=float).reshape(-1)
        if position.shape != (3,) or not np.isfinite(position).all():
            continue
        support[native_id] = tuple(float(value) for value in position)
        parent = node.get_parent() if callable(getattr(node, 'get_parent', None)) else None
        seen = {native_id}
        room_id = None
        while parent is not None:
            parent_id = by_symbol_value.get(parent) if type(parent) is int else str(parent)
            if parent_id is None or parent_id in seen or parent_id not in native_by_id:
                break
            seen.add(parent_id)
            parent_layer, parent_node, parent_value = native_by_id[parent_id]
            if parent_layer == 4:
                room_id = parent_id
                break
            parent = parent_node.get_parent() if callable(getattr(parent_node, 'get_parent', None)) else None
        assignments[native_id] = room_id

    snapshot = RoomSupportSnapshot(
        episode_id=manifest['episode_id'], run_id=manifest['run_id'],
        graph_revision=manifest['graph_revision'], frame_convention='canonical_z_up_m_v1',
        observed_support=support, support_domain='place_points', room_assignments=assignments,
        unassigned=tuple(key for key, room in assignments.items() if room is None),
        source_hashes={'graph': graph_sha, 'input_prefix': manifest['input_prefix_sha256'],
                       'manifest': sha256(manifest_path)},
    )
    details = {'graph_path': str(graph_path), 'graph_sha256': graph_sha,
        'manifest_path': str(manifest_path), 'manifest_matches': True,
        'episode_id': snapshot.episode_id, 'run_id': snapshot.run_id,
        'graph_revision': snapshot.graph_revision,
        'place_support_count': len(support),
        'assigned_place_count': sum(value is not None for value in assignments.values()),
        'unassigned_place_count': len(snapshot.unassigned),
        'native_room_count': len({value for value in assignments.values() if value is not None}),
        'support_domain': snapshot.support_domain}
    return details, snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--annotation', type=Path,
                        help='Pinned independent annotation JSON; absent means quality unavailable')
    parser.add_argument('--protocol', default='room-point-partition-v1')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    details, snapshot = extract_support(args.graph, args.manifest)
    annotation = None if args.annotation is None else json.loads(args.annotation.read_text(encoding='utf-8'))
    report = evaluate_room_geometry(snapshot, annotation, protocol=args.protocol)
    value = {'schema_version': 1, 'source': details,
        'annotation_path': None if args.annotation is None else str(args.annotation.resolve()),
        'annotation_sha256': None if args.annotation is None else sha256(args.annotation),
        'support_snapshot': {'frame_convention': snapshot.frame_convention,
            'support_domain': snapshot.support_domain,
            'observed_support': {key: list(point) for key, point in snapshot.observed_support.items()},
            'room_assignments': dict(snapshot.room_assignments),
            'unassigned': list(snapshot.unassigned), 'source_hashes': dict(snapshot.source_hashes)},
        'quality_report': report.to_dict()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'quality_status': report.status,
        'reasons': list(report.reasons), **details}, sort_keys=True))
    return 0 if report.status == 'available' else 3


if __name__ == '__main__':
    raise SystemExit(main())
