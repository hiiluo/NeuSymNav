"""Bounded namespace projection for native Spark-DSG graph summaries."""
from __future__ import annotations

from dataclasses import dataclass
import math
import hashlib
import json
from types import MappingProxyType
from typing import Mapping


MAX_NODES = 100_000
MAX_EDGES = 300_000
KNOWN_LAYERS = frozenset(range(8))


@dataclass(frozen=True, slots=True)
class HydraDisplayNode:
    node_id: str
    native_id: str
    layer_id: int
    name: str | None
    position: tuple[float, float, float] | None
    parent_id: str | None


@dataclass(frozen=True, slots=True)
class HydraDisplayEdge:
    source: str
    target: str
    kind: str


@dataclass(frozen=True, slots=True)
class HydraGraphProjection:
    schema_version: int
    episode_id: str
    run_id: str
    graph_revision: int
    input_prefix_sha256: str
    nodes: tuple[HydraDisplayNode, ...]
    edges: tuple[HydraDisplayEdge, ...]
    node_counts: Mapping[str, int]
    last_source: Mapping | None
    stale: bool
    replay_required: bool
    failure_reason: str | None
    status: str
    provenance: Mapping
    native_metadata: Mapping


class HydraGraphAdapter:
    """Validate a complete native summary; replace snapshots, never merge IDs."""

    @staticmethod
    def project(summary: Mapping, *, episode_id: str, run_id: str, stale: bool,
                replay_required: bool, failure_reason: str | None,
                last_source: Mapping | None, native_metadata: Mapping | None = None) -> HydraGraphProjection:
        if not isinstance(summary, Mapping) or summary.get('schema_version') != 1:
            raise ValueError('unsupported Hydra graph summary schema')
        revision = summary.get('graph_revision')
        prefix = summary.get('input_prefix_sha256')
        if type(revision) is not int or revision < 0:
            raise ValueError('Hydra graph revision must be nonnegative')
        if not _sha256(prefix):
            raise ValueError('Hydra graph input prefix SHA-256 is required')
        if not isinstance(episode_id, str) or not episode_id or not isinstance(run_id, str) or not run_id:
            raise ValueError('Hydra projection episode/run identity is required')
        if type(stale) is not bool or type(replay_required) is not bool:
            raise ValueError('Hydra stale and replay flags must be booleans')

        raw_nodes, raw_edges = summary.get('nodes'), summary.get('edges')
        if not isinstance(raw_nodes, list) or len(raw_nodes) > MAX_NODES:
            raise ValueError('Hydra node summary is missing or exceeds its node cap')
        if not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
            raise ValueError('Hydra edge summary is missing or exceeds its edge cap')
        native_to_id: dict[str, str] = {}
        nodes: list[HydraDisplayNode] = []
        for raw in raw_nodes:
            if not isinstance(raw, Mapping):
                raise ValueError('Hydra node entry must be a mapping')
            native_id, layer = raw.get('native_id'), raw.get('layer_id')
            if not isinstance(native_id, str) or not native_id or len(native_id) > 256:
                raise ValueError('Hydra native node ID is invalid')
            if type(layer) is not int or layer not in KNOWN_LAYERS:
                raise ValueError('Hydra node has an unknown layer')
            if native_id in native_to_id:
                raise ValueError('Hydra native node ID is duplicated')
            node_id = f'hydra:{run_id}:{layer}:{native_id}'
            native_to_id[native_id] = node_id
            name = raw.get('name')
            if name is not None and (not isinstance(name, str) or len(name) > 256):
                raise ValueError('Hydra node name is invalid')
            position = _position(raw.get('position'))
            nodes.append(HydraDisplayNode(node_id, native_id, layer, name, position, None))
        by_native = {node.native_id: node for node in nodes}
        projected: list[HydraDisplayNode] = []
        for node, raw in zip(nodes, raw_nodes):
            parent = raw.get('parent_native_id')
            if parent is not None and (not isinstance(parent, str) or parent not in native_to_id):
                raise ValueError('Hydra node parent endpoint is missing')
            projected.append(HydraDisplayNode(node.node_id, node.native_id, node.layer_id,
                node.name, node.position, None if parent is None else native_to_id[parent]))
        edges: list[HydraDisplayEdge] = []
        for raw in raw_edges:
            if not isinstance(raw, Mapping):
                raise ValueError('Hydra edge entry must be a mapping')
            source, target = raw.get('source_native_id'), raw.get('target_native_id')
            if source not in native_to_id or target not in native_to_id:
                raise ValueError('Hydra edge endpoint is missing')
            kind = raw.get('kind', 'native')
            if not isinstance(kind, str) or not kind or len(kind) > 128:
                raise ValueError('Hydra edge kind is invalid')
            edges.append(HydraDisplayEdge(native_to_id[source], native_to_id[target], kind))
        counts = summary.get('layer_counts')
        if not isinstance(counts, Mapping) or len(counts) > len(KNOWN_LAYERS):
            raise ValueError('Hydra layer counts are invalid')
        normalized_counts = {}
        for key, value in counts.items():
            if not isinstance(key, str) or not key.isdigit() or int(key) not in KNOWN_LAYERS:
                raise ValueError('Hydra layer count references an unknown layer')
            if type(value) is not int or value < 0:
                raise ValueError('Hydra layer count must be a nonnegative integer')
            normalized_counts[key] = value
        if any(normalized_counts.get(str(layer), 0) < sum(node.layer_id == layer for node in projected)
               for layer in KNOWN_LAYERS):
            raise ValueError('Hydra layer count is smaller than projected node count')
        if last_source is not None and not isinstance(last_source, Mapping):
            raise ValueError('Hydra last_source must be a mapping or None')
        status = 'stale' if stale or replay_required or failure_reason else 'available'
        provenance = MappingProxyType(dict(input_prefix_sha256=prefix,
            graph_revision=revision, last_source=None if last_source is None else dict(last_source)))
        metadata=dict(native_metadata or {})
        # Explicit semantics from this very summary, never reconstructed from display names.
        semantic={raw['native_id']:raw.get('semantic_label') for raw in raw_nodes if raw['layer_id']==2}
        semantic={key:value if type(value) is int and 0<=value<2**32 else None for key,value in semantic.items()}
        transform=metadata.get('last_transform') or {}
        source=last_source or {}
        payload={'revision':revision,'prefix':prefix,'world_epoch':metadata.get('graph_world_epoch'),
            'nodes':[(n.node_id,n.layer_id,n.name,n.position,n.parent_id,semantic.get(n.native_id)) for n in projected],
            'edges':[(e.source,e.target,e.kind) for e in edges],
            'semantic_domain':[(source.get(k)) for k in ('vocabulary_id','labelspace_id','labelspace_hash')],
            'transform_domain':[transform.get(k) for k in ('calibration_id','calibration_hash','coordinate_convention','pose_version')]}
        snapshot_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        metadata['room_label_input']=MappingProxyType(dict(schema_version=1,graph_revision=revision,
            input_prefix_sha256=prefix,semantic_labels=MappingProxyType(semantic),snapshot_sha256=snapshot_hash))
        native_metadata=MappingProxyType(metadata)
        return HydraGraphProjection(1, episode_id, run_id, revision, prefix,
            tuple(projected), tuple(edges), MappingProxyType(normalized_counts),
            None if last_source is None else MappingProxyType(dict(last_source)),
            stale, replay_required, failure_reason, status, provenance,native_metadata)


def _sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _position(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('Hydra node position must be XYZ or None')
    if any(type(item) not in (int, float) or not math.isfinite(item) for item in value):
        raise ValueError('Hydra node position must be finite XYZ')
    return tuple(float(item) for item in value)
