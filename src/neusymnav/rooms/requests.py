"""Exact-key room-label jobs built from one read-only Hydra projection."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Mapping

from ..backends.hydra.query import HydraSceneGraphQuery
from ..contracts._base import Contract, digest, integer, text
from .context import RoomContext, build_room_context


@dataclass(frozen=True, slots=True)
class RoomLabelRequestKey(Contract):
    episode_id: str
    run_id: str
    room_id: str
    graph_revision: int
    input_prefix_sha256: str
    geometry_hash: str | None
    context_hash: str
    world_epoch: str | None = None

    def __post_init__(self):
        for name in ('episode_id', 'run_id', 'room_id'):
            text(getattr(self, name), name)
        integer(self.graph_revision, 'graph_revision')
        digest(self.input_prefix_sha256, 'input_prefix_sha256')
        if self.geometry_hash is not None:
            digest(self.geometry_hash, 'geometry_hash')
        digest(self.context_hash, 'context_hash')
        if self.world_epoch is not None:
            text(self.world_epoch, 'world_epoch')

    @property
    def request_id(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(b'NeuSymNav:room-label-request:v1\0' + encoded.encode()).hexdigest()

    def matches_current(self, current: 'RoomLabelRequestKey') -> bool:
        return isinstance(current, RoomLabelRequestKey) and self == current


@dataclass(frozen=True, slots=True)
class NativeRoomRelation(Contract):
    subject_native_id: str
    relation: str
    object_native_id: str

    def __post_init__(self):
        text(self.subject_native_id, 'subject_native_id')
        text(self.relation, 'relation')
        text(self.object_native_id, 'object_native_id')


@dataclass(frozen=True, slots=True)
class RoomLabelRequest(Contract):
    key: RoomLabelRequestKey
    context: RoomContext
    relations: tuple[NativeRoomRelation, ...]
    source_manifest: Mapping[str, object]

    def __post_init__(self):
        if not isinstance(self.key, RoomLabelRequestKey) or not isinstance(self.context, RoomContext):
            raise ValueError('request needs a key and RoomContext')
        if (self.key.episode_id != self.context.episode_id or self.key.run_id != self.context.run_id
                or self.key.room_id != self.context.room_id
                or self.key.graph_revision != self.context.geometry_revision
                or self.key.geometry_hash != self.context.geometry_hash
                or self.key.context_hash != self.context.input_evidence_hash):
            raise ValueError('request key does not bind its room context')
        relations = tuple(self.relations)
        if any(not isinstance(item, NativeRoomRelation) for item in relations):
            raise ValueError('relations must be native room relations')
        object.__setattr__(self, 'relations', relations)
        if not isinstance(self.source_manifest, Mapping):
            raise ValueError('source_manifest must be a mapping')
        object.__setattr__(self, 'source_manifest', MappingProxyType(dict(self.source_manifest)))

    @property
    def request_id(self) -> str:
        return self.key.request_id

    @property
    def inference_block_reason(self) -> str | None:
        if self.context.geometry_status == 'stale':
            return 'geometry_stale'
        if self.context.geometry_status != 'available' or self.key.geometry_hash is None:
            return 'room_geometry_unavailable'
        if self.context.truncated:
            return 'context_object_cap_exceeded'
        if not self.context.objects:
            return 'no_semantic_objects'
        if any(row.membership_status != 'assigned' for row in self.context.objects):
            return 'ambiguous_room_membership'
        return None


def _native_relations(query: HydraSceneGraphQuery, context: RoomContext) -> tuple[NativeRoomRelation, ...]:
    projection = query._projection
    by_id = {node.node_id: node for node in projection.nodes}
    by_native = {node.native_id: node for node in projection.nodes}
    rows: set[tuple[str, str, str]] = set()
    for item in context.objects:
        node = by_native.get(item.native_id)
        seen = set()
        while node is not None and node.parent_id is not None and node.node_id not in seen:
            seen.add(node.node_id)
            parent = by_id.get(node.parent_id)
            if parent is None:
                break
            rows.add((node.native_id, 'parent', parent.native_id))
            node = parent
    return tuple(NativeRoomRelation(*row) for row in sorted(rows))


def make_room_label_request(query: HydraSceneGraphQuery,
        evidence: Mapping[str, object] | None, room_support: Mapping | None,
        world_epoch: str | None = None) -> tuple[RoomLabelRequest, ...]:
    """Create deterministic exact-revision requests for native room IDs.

    Requests are returned even when host preflight must abstain; callers must
    check ``inference_block_reason`` before invoking a model.
    """
    if not isinstance(query, HydraSceneGraphQuery):
        raise TypeError('query must be HydraSceneGraphQuery')
    if world_epoch is not None:
        text(world_epoch, 'world_epoch')
    projection = query._projection
    room_ids = sorted(node.node_id for node in projection.nodes if node.layer_id == 4)
    requests = []
    for room_id in room_ids:
        context = build_room_context(query, evidence, room_support, room_id)
        key = RoomLabelRequestKey(projection.episode_id, projection.run_id, room_id,
            projection.graph_revision, projection.input_prefix_sha256,
            context.geometry_hash, context.input_evidence_hash, world_epoch)
        relations = _native_relations(query, context)
        source = projection.last_source or {}
        manifest = {
            'projection_status': projection.status,
            'geometry_status': context.geometry_status,
            'geometry_hash': context.geometry_hash,
            'input_prefix_sha256': projection.input_prefix_sha256,
            'source_hashes': dict(context.source_hashes),
            'vocabulary_id': source.get('vocabulary_id'),
            'labelspace_id': source.get('labelspace_id'),
            'labelspace_hash': source.get('labelspace_hash'),
            'calibration_id': query._calibration_id,
            'calibration_hash': query._calibration_hash,
            'canonical_categories': tuple(sorted(query._taxonomy.categories)),
            'relations_available': bool(relations),
        }
        requests.append(RoomLabelRequest(key, context, relations, manifest))
    return tuple(requests)
