"""Read-only query view over one provenance-pinned Hydra graph projection.

This adapter consumes an already-created immutable projection and explicit
native semantic IDs. It does not call Hydra, assign identity, or assess
traversability.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
import hashlib
import math
import re
from types import MappingProxyType
from typing import Mapping

from ...contracts.hydra_graph import (HydraPage, HydraReadResult, HydraReadToken,
                                      NativeDetailRequest, NativeNodeRef)
from ...contracts.observations import Taxonomy
from ...contracts.hydra_evidence import EvidencePage, HydraEvidenceIndex, HydraObjectKey
from ...geometry.frames import CANONICAL_Z_UP
from .graph_adapter import HydraDisplayNode, HydraGraphProjection
from .labels import HydraLabelRasterizer


@dataclass(frozen=True, slots=True)
class HydraObjectCandidate:
    """A semantic graph hypothesis with graph-level, not per-object, lineage."""

    node_id: str
    native_id: str
    layer_id: int
    name: str | None
    semantic_id: int
    category: str
    position_xyz_m: tuple[float, float, float] | None
    parent_id: str | None
    parent_chain: tuple[str, ...]
    room_id: str | None
    membership_status: str
    membership_kind: str
    graph_revision: int
    graph_status: str
    input_prefix_sha256: str
    last_source: Mapping[str, object]
    vocabulary_id: str
    labelspace_id: str
    labelspace_hash: str
    calibration_id: str
    calibration_hash: str
    coordinate_convention: str
    provenance_scope: str
    confidence: None
    verified: None
    lifecycle: None
    per_object_evidence_refs: None
    navigability: str
    usable_for_targeting: bool


@dataclass(frozen=True, slots=True)
class HydraNodeDetail:
    ref: NativeNodeRef
    position_xyz_m: tuple[float, float, float] | None
    native: HydraReadResult


@dataclass(frozen=True, slots=True)
class HydraObjectDetail(HydraNodeDetail):
    room: NativeNodeRef | None
    graph_capture_ns: int | None
    graph_published_ns: int | None
    graph_published_clock_domain: str | None
    clock_domain: str | None
    verified_last_seen_ns: int | None


@dataclass(frozen=True, slots=True)
class HydraRoomDetail(HydraNodeDetail):
    place_count: int
    object_count: int
    adjacent_rooms: HydraPage
    label: object | None = None


@dataclass(frozen=True, slots=True)
class HydraStructuralEdge:
    source: NativeNodeRef
    target: NativeNodeRef
    kind: str
    weighted: bool | None = None
    weight: float | None = None
    weight_kind: str = 'not_recorded'


@dataclass(frozen=True, slots=True)
class HydraSubgraph:
    nodes: tuple[NativeNodeRef, ...]
    edges: tuple[HydraStructuralEdge, ...]
    truncated: bool


def _page(items, token, scope, limit, cursor):
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('page limit must be between 1 and 64')
    stamp = hashlib.sha256(repr((token, scope, limit)).encode()).hexdigest()
    offset = 0
    if cursor is not None:
        match = re.fullmatch(r'([a-f0-9]{64}):([0-9]{1,8})', cursor) if isinstance(cursor, str) else None
        if match is None or match[1] != stamp or int(match[2]) >= len(items):
            raise ValueError('invalid or mismatched Hydra query cursor')
        offset = int(match[2])
    end = offset + limit
    return HydraPage(tuple(items[offset:end]), f'{stamp}:{end}' if end < len(items) else None)


class HydraSceneGraphQuery:
    """Query layer-2 nodes without changing graph state or owning new IDs.

    ``semantic_labels`` maps each native node ID to the explicit integer
    semantic label captured in the graph's pinned labelspace. Reserved labels
    zero (unknown) and one (invalid) are never converted to categories.
    """

    def __init__(self, projection: HydraGraphProjection, taxonomy: Taxonomy, *,
                 labelspace_id: str, labelspace_hash: str,
                 semantic_labels: Mapping[str, int | None], calibration_id: str,
                 evidence_index: HydraEvidenceIndex | None = None,
                 detail_reader=None, relationship_reader=None, room_publications=None,
                 room_request_keys=None, room_label_reader=None, live_token=None, feature_reader=None):
        if not isinstance(projection, HydraGraphProjection):
            raise TypeError('projection must be HydraGraphProjection')
        if not isinstance(taxonomy, Taxonomy):
            raise TypeError('taxonomy must be Taxonomy')
        if not isinstance(semantic_labels, Mapping):
            raise TypeError('semantic_labels must map native IDs to semantic IDs')
        if not isinstance(calibration_id, str) or not calibration_id.strip():
            raise ValueError('calibration_id is required')

        rasterizer = HydraLabelRasterizer(taxonomy)
        if labelspace_id != rasterizer.LABELSPACE_ID or labelspace_hash != rasterizer.labelspace_hash:
            raise ValueError('query labelspace does not match the pinned taxonomy labelspace')

        source = projection.last_source
        if not isinstance(source, Mapping):
            raise ValueError('Hydra graph query requires source-bound vocabulary and labelspace metadata')
        if source.get('vocabulary_id') != taxonomy.vocabulary_id:
            raise ValueError('Hydra graph source vocabulary mismatch')
        if (source.get('labelspace_id') != rasterizer.LABELSPACE_ID or
                source.get('labelspace_hash') != rasterizer.labelspace_hash):
            raise ValueError('Hydra graph source labelspace mismatch')
        source_copy = MappingProxyType(dict(source))

        transform = projection.native_metadata.get('last_transform')
        if not isinstance(transform, Mapping):
            raise ValueError('Hydra graph query requires source transform metadata')
        if transform.get('calibration_id') != calibration_id:
            raise ValueError('Hydra graph calibration ID mismatch')
        calibration_hash = transform.get('calibration_hash')
        if (not isinstance(calibration_hash, str) or len(calibration_hash) != 64 or
                any(char not in '0123456789abcdef' for char in calibration_hash)):
            raise ValueError('Hydra graph calibration hash is missing or invalid')
        coordinate_convention = transform.get('coordinate_convention')
        if coordinate_convention != CANONICAL_Z_UP:
            raise ValueError('Hydra graph query requires canonical Z-up coordinates')

        nodes_by_native = {node.native_id: node for node in projection.nodes}
        if len(nodes_by_native) != len(projection.nodes):
            raise ValueError('Hydra graph projection has duplicate native IDs')
        labels: dict[str, int | None] = {}
        allowed_ids = {0, 1, *rasterizer.class_to_label.values()}
        for native_id, semantic_id in semantic_labels.items():
            if not isinstance(native_id, str) or not native_id:
                raise ValueError('semantic mapping native ID must be nonempty text')
            if native_id not in nodes_by_native:
                raise ValueError(f'semantic mapping native ID is absent from projection: {native_id}')
            if semantic_id is not None and (type(semantic_id) is not int or semantic_id not in allowed_ids):
                raise ValueError(f'semantic label is outside the pinned labelspace: {native_id}')
            labels[native_id] = semantic_id

        self._projection = projection
        if evidence_index is not None and not isinstance(evidence_index, HydraEvidenceIndex):
            raise TypeError('evidence_index must be HydraEvidenceIndex or None')
        self._evidence_index = evidence_index
        self._taxonomy = taxonomy
        self._rasterizer = rasterizer
        self._source = source_copy
        self._calibration_id = calibration_id
        self._calibration_hash = calibration_hash
        self._coordinate_convention = coordinate_convention
        self._nodes_by_id = MappingProxyType({node.node_id: node for node in projection.nodes})
        self._nodes_by_native = MappingProxyType(nodes_by_native)
        self._semantic_labels = MappingProxyType(labels)
        self._category_by_label = MappingProxyType({
            label_id: category for category, label_id in rasterizer.class_to_label.items()
        })

        metadata = projection.native_metadata
        self.read_token = HydraReadToken(
            projection.episode_id, projection.run_id, projection.graph_revision,
            projection.input_prefix_sha256, metadata.get('graph_world_epoch'),
            metadata.get('source_sha256'), metadata.get('build_sha256'), metadata.get('config_sha256'),
        )
        self._detail_reader = detail_reader
        self._relationship_reader = relationship_reader
        self._feature_reader = feature_reader
        self._room_publications = dict(room_publications or {})
        self._room_request_keys = dict(room_request_keys or {})
        self._room_label_reader = room_label_reader
        self._live_token = live_token
        self._topology = None

    @property
    def projection(self) -> HydraGraphProjection:
        """The existing summary, with its original v1 shape."""
        return self._projection

    @property
    def historical(self) -> bool:
        return bool(getattr(self._detail_reader, 'historical', False))

    def node_ref(self, native_id: str) -> NativeNodeRef:
        node = self._nodes_by_native.get(native_id)
        if node is None:
            raise ValueError('native node does not exist in this graph')
        return self._ref(node)

    def _ref(self, node):
        return NativeNodeRef(self.read_token, node.native_id, node.layer_id)

    def _read_status(self):
        status = self.status
        if status == 'stale':
            return HydraReadResult('stale', reason='graph_no_longer_current')
        if status != 'available':
            return HydraReadResult('unavailable', reason='graph_unavailable')
        return None

    def _check_ref(self, ref, layer=None):
        status = self._read_status()
        if status is not None:
            return status
        if not isinstance(ref, NativeNodeRef):
            raise TypeError('expected a native node reference')
        if ref.token != self.read_token:
            return HydraReadResult('stale', reason='graph_token_mismatch')
        node = self._nodes_by_native.get(ref.native_id)
        if node is None or node.layer_id != ref.layer_id or (layer is not None and layer != ref.layer_id):
            return HydraReadResult('unavailable', reason='node_or_layer_mismatch')
        return None

    def _details(self, ref, kind, *, offset=0, limit=64, target=None):
        request = NativeDetailRequest(ref, kind, offset, limit, target)
        if self._detail_reader is None:
            return HydraReadResult('not_recorded', reason='detail_reader_not_connected')
        result = self._detail_reader.read(request)
        return self._read_status() or result

    def _index(self):
        if self._topology is None:
            by_layer, by_room, adjacency = defaultdict(list), defaultdict(list), defaultdict(list)
            refs = {node.node_id: self._ref(node) for node in self._projection.nodes}
            for node in sorted(self._projection.nodes, key=lambda item: item.native_id):
                ref = refs[node.node_id]
                by_layer[node.layer_id].append(ref)
                if node.layer_id in (2, 3):
                    _, room_id, _ = self._parent_chain(node)
                    if room_id is not None:
                        by_room[room_id, node.layer_id].append(ref)
            for edge in self._projection.edges:
                source = refs[edge.source]
                target = refs[edge.target]
                adjacency[edge.source].append(HydraStructuralEdge(source, target, edge.kind))
                if edge.target != edge.source:
                    adjacency[edge.target].append(HydraStructuralEdge(target, source, edge.kind))
            for items in adjacency.values():
                items.sort(key=lambda edge: (edge.target.native_id, edge.kind))
            self._topology = (dict(by_layer), dict(by_room), dict(adjacency))
        return self._topology

    def _page(self, items, scope, limit, cursor):
        page = _page(items, self.read_token, scope, limit, cursor)
        return self._read_status() or HydraReadResult('available', page)

    def rooms(self, *, limit=64, cursor=None):
        status = self._read_status()
        if status is not None:
            return status
        items = self._index()[0].get(4, ())
        return self._page(items, ('rooms',), limit, cursor)

    def places(self, room=None, *, limit=64, cursor=None):
        status = self._read_status() if room is None else self._check_ref(room, 4)
        if status is not None:
            return status
        by_layer, by_room, _ = self._index()
        items = by_layer.get(3, ()) if room is None else by_room.get(
            (self._nodes_by_native[room.native_id].node_id, 3), ())
        return self._page(items, ('places', room), limit, cursor)

    def room_members(self, room, layer_id, *, limit=64, cursor=None):
        if layer_id not in (2, 3) or type(layer_id) is not int:
            raise ValueError('room members must be objects or places')
        status = self._check_ref(room, 4)
        if status is not None:
            return status
        node = self._nodes_by_native[room.native_id]
        return self._page(self._index()[1].get((node.node_id, layer_id), ()),
                          ('room_members', room, layer_id), limit, cursor)

    def room_detail(self, room, *, limit=64, cursor=None):
        status = self._check_ref(room, 4)
        if status is not None:
            return status
        node = self._nodes_by_native[room.native_id]
        _, by_room, adjacency = self._index()
        adjacent = tuple(dict.fromkeys(edge.target for edge in adjacency.get(node.node_id, ())
                                      if edge.target.layer_id == 4 and edge.target != room))
        publication = self._room_publications.get(node.node_id)
        request = self._room_request_keys.get(node.node_id)
        label = None
        if (publication is not None and request is not None
                and (request.episode_id, request.run_id, request.room_id, request.graph_revision,
                     request.input_prefix_sha256, request.world_epoch) ==
                    (self.read_token.episode_id, self.read_token.run_id, node.node_id,
                     self.read_token.graph_revision, self.read_token.input_prefix_sha256,
                     self.read_token.world_epoch)
                and publication.matches_current(request)):
            label = publication
        if label is None and self._room_label_reader is not None:
            label = self._room_label_reader(node.node_id)
        page = _page(adjacent, self.read_token, ('room_adjacent', room), limit, cursor)
        native = self._details(room, 'attributes')
        return self._read_status() or HydraReadResult('available', HydraRoomDetail(
            room, node.position, native, len(by_room.get((node.node_id, 3), ())),
            len(by_room.get((node.node_id, 2), ())), page, label))

    def object_detail(self, key: HydraObjectKey):
        if not isinstance(key, HydraObjectKey):
            raise TypeError('expected a HydraObjectKey')
        status = self._read_status()
        if status is not None:
            return status
        if (key.episode_id, key.run_id, key.graph_revision) != (
                self.read_token.episode_id, self.read_token.run_id, self.read_token.graph_revision):
            return HydraReadResult('stale', reason='graph_key_mismatch')
        ref = NativeNodeRef(self.read_token, key.native_id, 2)
        status = self._check_ref(ref, 2)
        if status is not None:
            return status
        node = self._nodes_by_native[key.native_id]
        _, room, _ = self._parent_chain(node)
        clock = self._source.get('clock_domain')
        capture_ns = self._source.get('capture_monotonic_ns')
        seen = None
        if self._evidence_index is not None and clock is not None and type(capture_ns) is int:
            seen = self._evidence_index.last_confirmed_capture(key, clock, capture_ns)
        native = self._details(ref, 'attributes')
        return self._read_status() or HydraReadResult('available', HydraObjectDetail(
            ref, node.position, native, None if room is None else self._ref(self._nodes_by_id[room]),
            capture_ns, self._projection.native_metadata.get('published_monotonic_ns'),
            self._projection.native_metadata.get('published_clock_domain'), clock, seen,
        ))

    def place_detail(self, ref):
        status = self._check_ref(ref, 3)
        if status is not None:
            return status
        native = self._details(ref, 'attributes')
        return self._read_status() or HydraReadResult('available', HydraNodeDetail(
            ref, self._nodes_by_native[ref.native_id].position, native))

    def geometry(self, ref, kind, *, offset=0, limit=64, cursor=None):
        status = self._check_ref(ref)
        if status is not None:
            return status
        if kind == 'room_support':
            if offset:
                raise ValueError('room support pages use a revision-bound cursor')
            return self.room_members(ref, 3, limit=limit, cursor=cursor)
        if cursor is not None or kind not in ('bbox', 'mesh'):
            raise ValueError('unsupported Hydra geometry kind')
        return self._details(ref, kind, offset=offset, limit=limit)

    def read_asset(self, ref, asset):
        """Explicit IO-lane decode. The regular snapshot and query methods do not decode payloads."""
        status = self._check_ref(ref)
        if status is not None:
            return status
        read = getattr(self._detail_reader, 'read_asset', None)
        if read is None:
            return HydraReadResult('not_recorded', reason='detail_asset_reader_not_connected')
        result = read(ref, asset)
        return self._read_status() or result

    def features(self, ref, *, spec_id=None):
        status = self._check_ref(ref)
        if status is not None:
            return status
        if self._feature_reader is not None:
            result = self._feature_reader(ref, spec_id)
            return self._read_status() or result
        result = self._details(ref, 'feature')
        if (spec_id is not None and result.status == 'available'
                and getattr(result.value, 'spec_id', None) != spec_id):
            return HydraReadResult('not_recorded', reason='no_compatible_feature_spec')
        return result

    def neighbors(self, ref, edge_kinds=None, *, limit=64, cursor=None):
        status = self._check_ref(ref)
        if status is not None:
            return status
        node = self._nodes_by_native[ref.native_id]
        kinds = None if edge_kinds is None else frozenset(edge_kinds)
        all_edges = self._index()[2].get(node.node_id, ())
        items = all_edges if kinds is None else [edge for edge in all_edges if edge.kind in kinds]
        scope = ('neighbors', ref, None if kinds is None else tuple(sorted(kinds)))
        return self._page(items, scope, limit, cursor)

    def edge_detail(self, subject, target):
        status = self._check_ref(subject) or self._check_ref(target)
        if status is not None:
            return status
        node = self._nodes_by_native[subject.native_id]
        if not any(edge.target == target for edge in self._index()[2].get(node.node_id, ())):
            return HydraReadResult('missing', reason='no_structural_edge')
        return self._details(subject, 'edge', target=target)

    def relationships(self, subject, target, *, kind='structural', limit=64, cursor=None):
        status = self._check_ref(subject) or self._check_ref(target)
        if status is not None:
            return status
        if kind == 'structural':
            node = self._nodes_by_native[subject.native_id]
            items = [edge for edge in self._index()[2].get(node.node_id, ()) if edge.target == target]
            return self._page(items, ('relationships', subject, target, kind), limit, cursor)
        if kind not in ('geometric', 'visual'):
            raise ValueError('unsupported Hydra relationship kind')
        if self._relationship_reader is None:
            return HydraReadResult('not_recorded', reason='relation_sidecar_not_connected')
        result = self._relationship_reader(subject, target, kind, limit, cursor)
        return self._read_status() or result

    def subgraph(self, seed_keys, *, edge_kinds=None, max_hops=2, max_nodes=64, max_edges=128):
        status = self._read_status()
        if status is not None:
            return status
        for value, low, high in ((max_hops, 0, 8), (max_nodes, 1, 256), (max_edges, 0, 512)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('subgraph budget exceeds cap')
        if not isinstance(seed_keys, (list, tuple)) or not 1 <= len(seed_keys) <= max_nodes:
            raise ValueError('seed list is empty or exceeds the node budget')
        for seed in seed_keys:
            status = self._check_ref(seed)
            if status is not None:
                return status
        seen = dict.fromkeys(sorted(seed_keys, key=lambda ref: ref.native_id))
        todo = deque((seed, 0) for seed in seen)
        adjacency = self._index()[2]
        kinds = None if edge_kinds is None else frozenset(edge_kinds)
        edges = {}
        truncated = False
        while todo:
            ref, depth = todo.popleft()
            node = self._nodes_by_native[ref.native_id]
            for edge in adjacency.get(node.node_id, ()):
                if kinds is not None and edge.kind not in kinds:
                    continue
                if edge.target not in seen:
                    if depth == max_hops or len(seen) == max_nodes:
                        truncated = True
                        continue
                    seen[edge.target] = None
                    todo.append((edge.target, depth + 1))
                ids = tuple(sorted((ref.native_id, edge.target.native_id)))
                key = (*ids, edge.kind)
                if key not in edges:
                    if len(edges) == max_edges:
                        truncated = True
                    else:
                        edges[key] = edge
        return self._read_status() or HydraReadResult('available', HydraSubgraph(
            tuple(sorted(seen, key=lambda ref: ref.native_id)), tuple(edges[k] for k in sorted(edges)), truncated))

    @property
    def status(self) -> str:
        """Return the graph-level availability state from the pinned projection."""
        if (self._projection.stale or self._projection.replay_required or self._projection.failure_reason
                or (self._live_token is not None and not self._live_token(self.read_token))):
            return 'stale'
        return self._projection.status

    @property
    def graph_revision(self) -> int:
        return self._projection.graph_revision

    @property
    def usable_for_targeting(self) -> bool:
        """Graph state only; this does not certify a map path or goal reachability."""
        return self.status == 'available'

    def objects(self, category: str | None = None) -> tuple[HydraObjectCandidate, ...]:
        """Return semantically labeled layer-2 candidates in native-ID order.

        Unknown, invalid and missing labels are omitted rather than inferred
        from display names. A stale projection may be inspected, but candidates
        from it always have ``usable_for_targeting=False``.
        """
        canonical = None
        if category is not None:
            if not isinstance(category, str) or not category.strip():
                raise ValueError('category must be nonempty text or None')
            canonical = self._taxonomy.canonicalize(category)
            if canonical is None:
                return ()

        candidates = []
        status = self.status
        for node in sorted(self._projection.nodes, key=lambda item: item.native_id):
            if node.layer_id != 2:
                continue
            semantic_id = self._semantic_labels.get(node.native_id)
            selected_category = self._category_by_label.get(semantic_id)
            if selected_category is None or (canonical is not None and selected_category != canonical):
                continue
            candidates.append(self._candidate(node, semantic_id, selected_category, status=status))
        if status != 'stale' and self.status == 'stale':
            return tuple(replace(candidate, graph_status='stale', usable_for_targeting=False)
                         for candidate in candidates)
        return tuple(candidates)

    def get(self, node_id: str, *, expected_revision: int | None = None) -> HydraObjectCandidate:
        """Return one current candidate or fail closed on stale identity/revision."""
        if expected_revision is not None:
            if type(expected_revision) is not int or expected_revision != self._projection.graph_revision:
                raise ValueError('Hydra graph revision mismatch')
        if not isinstance(node_id, str) or not node_id:
            raise ValueError('Hydra node ID must be nonempty text')
        node = self._nodes_by_id.get(node_id)
        if node is None or node.layer_id != 2:
            raise ValueError('Hydra object candidate not found in this graph revision')
        semantic_id = self._semantic_labels.get(node.native_id)
        category = self._category_by_label.get(semantic_id)
        if category is None:
            raise ValueError('Hydra object candidate has no queryable semantic label')
        return self._candidate(node, semantic_id, category)

    def evidence(self, key: HydraObjectKey, *, limit: int = 64,
                 cursor: int | None = None) -> EvidencePage:
        """Resolve refs only for this exact graph generation and object ID."""
        if not isinstance(key, HydraObjectKey):
            raise TypeError('key must be HydraObjectKey')
        if (key.episode_id, key.run_id) != (self._projection.episode_id, self._projection.run_id):
            return EvidencePage('unavailable', (), None, ('episode_or_run_mismatch',))
        if key.graph_revision != self._projection.graph_revision:
            return EvidencePage('unavailable', (), None, ('graph_revision_mismatch',))
        node = next((item for item in self._projection.nodes
                     if item.native_id == key.native_id and item.layer_id == 2), None)
        if node is None:
            return EvidencePage('unavailable', (), None, ('object_not_in_graph_revision',))
        if not self.usable_for_targeting:
            return EvidencePage('unavailable', (), None, ('graph_stale_or_replay_required',))
        if self._evidence_index is None:
            return EvidencePage('not_recorded', (), None, ('evidence_sidecar_not_connected',))
        return self._evidence_index.resolve(key, limit=limit, cursor=cursor)

    def _candidate(self, node: HydraDisplayNode, semantic_id: int,
                   category: str, *, status: str | None = None) -> HydraObjectCandidate:
        parent_chain, room_id, membership_status = self._parent_chain(node)
        position = node.position
        position_valid = (position is not None and len(position) == 3 and
                          all(math.isfinite(value) for value in position))
        if position_valid:
            position_xyz = tuple(float(value) for value in position)
        else:
            position_xyz = None
        status = self.status if status is None else status
        usable = status == 'available' and position_xyz is not None
        return HydraObjectCandidate(
            node_id=node.node_id,
            native_id=node.native_id,
            layer_id=node.layer_id,
            name=node.name,
            semantic_id=semantic_id,
            category=category,
            position_xyz_m=position_xyz,
            parent_id=node.parent_id,
            parent_chain=parent_chain,
            room_id=room_id,
            membership_status=membership_status,
            membership_kind='structural_not_navigation',
            graph_revision=self._projection.graph_revision,
            graph_status=status,
            input_prefix_sha256=self._projection.input_prefix_sha256,
            last_source=self._source,
            vocabulary_id=self._taxonomy.vocabulary_id,
            labelspace_id=self._rasterizer.LABELSPACE_ID,
            labelspace_hash=self._rasterizer.labelspace_hash,
            calibration_id=self._calibration_id,
            calibration_hash=self._calibration_hash,
            coordinate_convention=self._coordinate_convention,
            provenance_scope='graph_input_prefix_only',
            confidence=None,
            verified=None,
            lifecycle=None,
            per_object_evidence_refs=None,
            navigability='unvalidated',
            usable_for_targeting=usable,
        )

    def _parent_chain(self, node: HydraDisplayNode) -> tuple[tuple[str, ...], str | None, str]:
        """Return structural ancestry; expose a room only for a complete acyclic chain."""
        chain: list[str] = []
        seen = {node.node_id}
        current = node
        room_id = None
        while current.parent_id is not None:
            parent_id = current.parent_id
            if parent_id in seen:
                return tuple(chain), None, 'unavailable'
            parent = self._nodes_by_id.get(parent_id)
            if parent is None:
                return tuple(chain), None, 'unavailable'
            chain.append(parent_id)
            seen.add(parent_id)
            if parent.layer_id == 4 and room_id is None:
                room_id = parent.node_id
            current = parent
        if room_id is None:
            return tuple(chain), None, 'unavailable'
        return tuple(chain), room_id, 'assigned'
