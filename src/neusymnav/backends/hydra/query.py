"""Read-only query view over one provenance-pinned Hydra graph projection.

This adapter consumes an already-created immutable projection and explicit
native semantic IDs. It does not call Hydra, assign identity, or assess
traversability.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

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


class HydraSceneGraphQuery:
    """Query layer-2 nodes without changing graph state or owning new IDs.

    ``semantic_labels`` maps each native node ID to the explicit integer
    semantic label captured in the graph's pinned labelspace. Reserved labels
    zero (unknown) and one (invalid) are never converted to categories.
    """

    def __init__(self, projection: HydraGraphProjection, taxonomy: Taxonomy, *,
                 labelspace_id: str, labelspace_hash: str,
                 semantic_labels: Mapping[str, int | None], calibration_id: str,
                 evidence_index: HydraEvidenceIndex | None = None):
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

    @property
    def status(self) -> str:
        """Return the graph-level availability state from the pinned projection."""
        return self._projection.status

    @property
    def graph_revision(self) -> int:
        return self._projection.graph_revision

    @property
    def usable_for_targeting(self) -> bool:
        """Graph state only; this does not certify a map path or goal reachability."""
        return (self._projection.status == 'available' and not self._projection.stale and
                not self._projection.replay_required and self._projection.failure_reason is None)

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
        for node in sorted(self._projection.nodes, key=lambda item: item.native_id):
            if node.layer_id != 2:
                continue
            semantic_id = self._semantic_labels.get(node.native_id)
            selected_category = self._category_by_label.get(semantic_id)
            if selected_category is None or (canonical is not None and selected_category != canonical):
                continue
            candidates.append(self._candidate(node, semantic_id, selected_category))
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
                   category: str) -> HydraObjectCandidate:
        parent_chain, room_id, membership_status = self._parent_chain(node)
        position = node.position
        position_valid = (position is not None and len(position) == 3 and
                          all(math.isfinite(value) for value in position))
        if position_valid:
            position_xyz = tuple(float(value) for value in position)
        else:
            position_xyz = None
        usable = self.usable_for_targeting and position_xyz is not None
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
            graph_status=self._projection.status,
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
