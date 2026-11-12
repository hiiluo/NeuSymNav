"""Bounded, revision-pinned text context built from native room membership."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Mapping

from ..backends.hydra.query import HydraSceneGraphQuery
from ..contracts._base import Contract, digest
from ..contracts.hydra_evidence import EvidencePage


MAX_CONTEXT_OBJECTS = 64


@dataclass(frozen=True)
class RoomObjectContext(Contract):
    native_id: str
    category: str
    semantic_id: int
    membership_status: str
    association_status: str
    evidence_count: int
    evidence_hashes: tuple[str, ...]


@dataclass(frozen=True)
class RoomContext(Contract):
    episode_id: str
    run_id: str
    room_id: str
    geometry_revision: int
    geometry_hash: str | None
    geometry_status: str
    membership_status: str
    input_evidence_hash: str
    objects: tuple[RoomObjectContext, ...]
    distinct_object_count: int
    total_object_count: int
    truncated: bool
    source_hashes: Mapping[str, str]


def _evidence_hash(ref) -> str:
    value = {'source': ref.source.to_dict(), 'detection_id': ref.detection_id,
        'rgb_sha256': ref.rgb_sha256, 'mask_sha256': ref.mask_sha256,
        'depth_sha256': ref.depth_sha256, 'detector_hash': ref.detector_hash,
        'input_prefix_sha256': ref.input_prefix_sha256, 'link_method': ref.link_method,
        'link_status': ref.link_status}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build_room_context(query: HydraSceneGraphQuery, evidence: Mapping[str, EvidencePage] | None,
                       room_support: Mapping | None, room_id: str) -> RoomContext:
    """Build context from distinct native object IDs; labels never alter graph geometry."""
    if not isinstance(query, HydraSceneGraphQuery):
        raise TypeError('query must be HydraSceneGraphQuery')
    if not isinstance(room_id, str) or not room_id:
        raise ValueError('room_id is required')
    projection = query._projection
    if evidence is not None and not isinstance(evidence, Mapping):
        raise TypeError('evidence must map native IDs to EvidencePage')
    if room_support is not None:
        if not isinstance(room_support, Mapping):
            raise TypeError('room_support must be a mapping or None')
        if (room_support.get('episode_id') != projection.episode_id
                or room_support.get('run_id') != projection.run_id
                or room_support.get('geometry_revision') != projection.graph_revision):
            raise ValueError('room support episode/run/revision mismatch')
        support_prefix = room_support.get('input_prefix_sha256')
        if support_prefix is not None and support_prefix != projection.input_prefix_sha256:
            raise ValueError('room support input prefix mismatch')
        geometry_hash = room_support.get('geometry_hash')
        if geometry_hash is not None:
            digest(geometry_hash, 'room support geometry hash')
        geometry_status = room_support.get('status', 'unavailable')
        if geometry_status not in {'available', 'unavailable', 'stale'}:
            raise ValueError('room support status is invalid')
        if geometry_status == 'available' and geometry_hash is None:
            raise ValueError('available room support requires a geometry hash')
        for name, value in (room_support.get('source_hashes') or {}).items():
            if not isinstance(name, str):
                raise ValueError('room support source hash names must be text')
            digest(value, f'room_support.source_hashes.{name}')
    else:
        geometry_hash = None
        geometry_status = 'unavailable'
    if not query.usable_for_targeting:
        geometry_status = 'stale'

    candidates = [item for item in query.objects() if item.room_id == room_id]
    candidates.sort(key=lambda item: item.native_id)
    distinct = {}
    for item in candidates:
        distinct.setdefault(item.native_id, item)
    rows = []
    for native_id, item in distinct.items():
        page = None if evidence is None else evidence.get(native_id)
        if page is not None and not isinstance(page, EvidencePage):
            raise TypeError('evidence values must be EvidencePage')
        refs = () if page is None or page.status != 'available' else page.refs
        # Replayed/duplicate frames are one source+detection item each.
        unique = {}
        for ref in refs:
            token = (ref.source, ref.detection_id)
            unique.setdefault(token, ref)
        hashes = tuple(sorted({_evidence_hash(ref) for ref in unique.values()}))
        statuses = {ref.link_status for ref in unique.values()}
        if 'ambiguous' in statuses:
            association_status = 'ambiguous'
        elif 'native_confirmed' in statuses:
            association_status = 'native_confirmed'
        elif 'geometric_candidate' in statuses:
            association_status = 'geometric_candidate'
        elif page is not None and page.status in {'not_recorded', 'evicted', 'corrupt'}:
            association_status = page.status
        else:
            association_status = 'not_recorded'
        rows.append(RoomObjectContext(native_id, item.category, item.semantic_id,
            item.membership_status, association_status, len(unique), hashes))

    total = len(rows)
    selected = tuple(rows[:MAX_CONTEXT_OBJECTS])
    hash_input = {'room_id': room_id, 'geometry_hash': geometry_hash,
        'geometry_status': geometry_status,
        'objects': [{'native_id': row.native_id, 'category': row.category,
            'semantic_id': row.semantic_id, 'membership_status': row.membership_status,
            'association_status': row.association_status, 'evidence_hashes': list(row.evidence_hashes)}
            for row in selected]}
    context_hash = hashlib.sha256(json.dumps(hash_input, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    sources = {} if room_support is None else dict(room_support.get('source_hashes') or {})
    return RoomContext(projection.episode_id, projection.run_id, room_id,
        projection.graph_revision, geometry_hash, geometry_status,
        'assigned' if selected and all(row.membership_status == 'assigned' for row in selected)
        else 'ambiguous' if selected else 'unavailable', context_hash,
        selected, len(distinct), total, total > len(selected), MappingProxyType(sources))
