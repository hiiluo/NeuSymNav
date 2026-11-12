#!/usr/bin/env python3
"""Read an existing Spark-DSG export and report object geometry capabilities."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def probe(graph_path: Path, manifest_path: Path) -> dict:
    graph_path, manifest_path = graph_path.resolve(), manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    graph_hash = sha256(graph_path)
    manifest_matches = (manifest.get('graph_sha256') == graph_hash
                        and manifest.get('graph_bytes') == graph_path.stat().st_size)
    from spark_dsg import DynamicSceneGraph
    graph = DynamicSceneGraph.load(str(graph_path))
    mesh = graph.mesh
    vertices = np.asarray(mesh.get_vertices())
    vertex_count = int(mesh.num_vertices())
    point_xyz = vertices[:3, :].T if vertices.ndim == 2 and vertices.shape[0] >= 3 else np.empty((0, 3))
    mesh_xyz_finite = bool(point_xyz.shape == (vertex_count, 3) and np.isfinite(point_xyz).all())

    object_nodes = []
    for layer in graph.layers:
        if int(layer.id) != 2:
            continue
        for node in layer.nodes:
            attrs = node.attributes
            bbox = getattr(attrs, 'bounding_box', None)
            raw_connections = getattr(attrs, 'mesh_connections', None)
            connections = [] if raw_connections is None else [int(value) for value in raw_connections]
            dimensions = None if bbox is None else np.asarray(bbox.dimensions, dtype=float).reshape(-1)
            center = None if bbox is None else np.asarray(bbox.world_P_center, dtype=float).reshape(-1)
            bbox_valid = bool(dimensions is not None and center is not None
                              and dimensions.shape == (3,) and center.shape == (3,)
                              and np.isfinite(dimensions).all() and np.isfinite(center).all()
                              and np.all(dimensions >= 0))
            valid_connections = bool(connections and min(connections) >= 0
                                     and max(connections) < vertex_count)
            object_nodes.append({
                'native_id': str(node.id),
                'mesh_connection_count': len(connections),
                'mesh_connections_unique': len(connections) == len(set(connections)),
                'mesh_connections_in_vertex_range': valid_connections,
                'bounding_box_type': None if bbox is None else str(bbox.type),
                'bounding_box_valid': bbox_valid,
                'bounding_box_center_xyz': None if not bbox_valid else center.tolist(),
                'bounding_box_dimensions_xyz': None if not bbox_valid else dimensions.tolist(),
                'semantic_label': (int(attrs.semantic_label)
                                   if isinstance(getattr(attrs, 'semantic_label', None), (int, np.integer)) else None),
            })

    return {
        'schema_version': 1,
        'artifact': {
            'graph_path': str(graph_path), 'graph_sha256': graph_hash,
            'graph_bytes': graph_path.stat().st_size, 'manifest_path': str(manifest_path),
            'manifest_matches_graph': manifest_matches,
            'complete': bool(manifest.get('complete')),
            'episode_id': manifest.get('episode_id'), 'run_id': manifest.get('run_id'),
            'graph_revision': manifest.get('graph_revision'),
            'input_prefix_sha256': manifest.get('input_prefix_sha256'),
            'source_sha256': manifest.get('source_sha256'),
            'build_sha256': manifest.get('build_sha256'),
        },
        'graph': {
            'node_count': int(graph.num_nodes()), 'edge_count': int(graph.num_edges()),
            'mesh_vertex_count': vertex_count, 'mesh_face_count': int(mesh.num_faces()),
            'mesh_xyz_finite': mesh_xyz_finite,
            'mesh_api': 'spark_dsg.Mesh.get_vertices()[0:3,:], get_faces(), num_vertices()',
        },
        'object_support': {
            'object_count': len(object_nodes),
            'mesh_connections_available': bool(object_nodes) and all(x['mesh_connection_count'] > 0 for x in object_nodes),
            'mesh_connections_valid_for_this_asset': bool(object_nodes) and all(x['mesh_connections_in_vertex_range'] for x in object_nodes),
            'bounding_boxes_available': bool(object_nodes) and all(x['bounding_box_valid'] for x in object_nodes),
            'units': 'meters_by_HydraFrame_metric_contract; Spark-DSG artifact has no explicit unit tag',
            'pose_correction_history': 'not_exposed_in_single_final_graph_export',
            'mesh_index_stability_across_revisions': 'not_verified; only one final graph generation is persisted',
            'objects': object_nodes,
        },
        'association': {
            'frame_ack_proves_detection_to_object_identity': False,
            'candidate_debug_only': True,
            'native_lineage_available': False,
            'reason': 'mesh support exists, but this export contains no per-detection source/mask lineage or native association record',
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--graph', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = probe(args.graph, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n'
    args.output.write_text(encoded, encoding='utf-8')
    print(json.dumps({
        'output': str(args.output.resolve()),
        'manifest_matches_graph': report['artifact']['manifest_matches_graph'],
        'object_count': report['object_support']['object_count'],
        'mesh_connections_valid': report['object_support']['mesh_connections_valid_for_this_asset'],
        'bounding_boxes_available': report['object_support']['bounding_boxes_available'],
        'pose_correction_history': report['object_support']['pose_correction_history'],
        'mesh_index_stability': report['object_support']['mesh_index_stability_across_revisions'],
        'candidate_debug_only': report['association']['candidate_debug_only'],
    }, sort_keys=True))
    return 0 if report['artifact']['manifest_matches_graph'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
