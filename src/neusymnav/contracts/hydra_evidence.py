"""Immutable, revision-pinned Hydra object evidence contracts.

Evidence links are candidate-debug metadata. These contracts do not assign
native IDs or claim that frame-level Hydra acceptance proves object identity.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath

from ._base import Contract, choice, digest, integer, text
from .observations import FrameKey, _key


@dataclass(frozen=True)
class HydraObjectKey(Contract):
    episode_id: str
    run_id: str
    native_id: str
    graph_revision: int

    def __post_init__(self):
        for name in ('episode_id', 'run_id', 'native_id'):
            text(getattr(self, name), name)
        integer(self.graph_revision, 'graph_revision')


@dataclass(frozen=True)
class ObservationEvidence(Contract):
    """A detection's source and sidecar hashes, independent of graph revision."""

    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    detection_id: str
    asset_key: str
    rgb_sha256: str
    mask_sha256: str
    depth_sha256: str | None
    bbox_xyxy: tuple[int, int, int, int]
    calibration_id: str
    calibration_hash: str
    pose_version: int
    detector_profile_id: str
    detector_hash: str
    vocabulary_id: str
    input_prefix_sha256: str
    link_method: str
    link_status: str
    native_lineage_sha256: str | None = None

    def __post_init__(self):
        _key(self.source)
        integer(self.capture_monotonic_ns, 'capture_monotonic_ns')
        for name in ('clock_domain', 'detection_id', 'asset_key', 'calibration_id',
                     'detector_profile_id', 'vocabulary_id', 'link_method'):
            text(getattr(self, name), name)
        asset_path = PurePosixPath(self.asset_key)
        if asset_path.is_absolute() or '..' in asset_path.parts or '\\' in self.asset_key:
            raise ValueError('asset_key must be a safe relative POSIX path')
        for name in ('rgb_sha256', 'mask_sha256', 'calibration_hash',
                     'detector_hash', 'input_prefix_sha256'):
            digest(getattr(self, name), name)
        if self.depth_sha256 is not None:
            digest(self.depth_sha256, 'depth_sha256')
        if self.native_lineage_sha256 is not None:
            digest(self.native_lineage_sha256, 'native_lineage_sha256')
        integer(self.pose_version, 'pose_version')
        box = tuple(self.bbox_xyxy)
        if len(box) != 4 or any(type(v) is not int for v in box):
            raise ValueError('bbox_xyxy must contain four integer pixel edges')
        x0, y0, x1, y1 = box
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError('bbox_xyxy must be a nonempty nonnegative XYXY box')
        object.__setattr__(self, 'bbox_xyxy', box)
        choice(self.link_status, {'geometric_candidate', 'ambiguous', 'native_confirmed',
                                  'unavailable', 'not_recorded'}, 'link_status')
        if self.link_status == 'native_confirmed' and self.native_lineage_sha256 is None:
            raise ValueError('native confirmation requires explicit lineage provenance')
        if self.link_status != 'native_confirmed' and self.native_lineage_sha256 is not None:
            raise ValueError('native lineage provenance is only valid for native confirmation')


@dataclass(frozen=True)
class EvidencePage(Contract):
    status: str
    refs: tuple[ObservationEvidence, ...]
    next_cursor: int | None
    reasons: tuple[str, ...] = ()
    native_confirmed: bool = False

    def __post_init__(self):
        choice(self.status, {'available', 'no_evidence', 'not_recorded', 'unavailable',
                             'evicted', 'corrupt'}, 'status')
        refs = tuple(self.refs)
        if any(not isinstance(ref, ObservationEvidence) for ref in refs):
            raise ValueError('refs must contain ObservationEvidence')
        object.__setattr__(self, 'refs', refs)
        if self.next_cursor is not None:
            integer(self.next_cursor, 'next_cursor')
        reasons = tuple(self.reasons)
        for reason in reasons:
            text(reason, 'reason')
        object.__setattr__(self, 'reasons', reasons)
        if type(self.native_confirmed) is not bool:
            raise ValueError('native_confirmed must be bool')
        if self.native_confirmed and (not refs or any(r.link_status != 'native_confirmed' for r in refs)):
            raise ValueError('native-confirmed page requires lineage for every listed reference')


class HydraEvidenceIndex:
    """Bounded in-memory index; exact object revisions never inherit links."""

    MAX_PAGE_SIZE = 64

    def __init__(self, *, run_id: str, episode_id: str, max_entries: int = 8192,
                 recording_status: str = 'recorded'):
        self.run_id = text(run_id, 'run_id')
        self.episode_id = text(episode_id, 'episode_id')
        self.max_entries = integer(max_entries, 'max_entries', minimum=1)
        choice(recording_status, {'recorded', 'not_recorded'}, 'recording_status')
        self.recording_status = recording_status
        self._entries: OrderedDict[tuple[HydraObjectKey, str], ObservationEvidence] = OrderedDict()
        self._evicted: dict[HydraObjectKey, int] = {}

    def add(self, key: HydraObjectKey, ref: ObservationEvidence) -> None:
        if not isinstance(key, HydraObjectKey) or not isinstance(ref, ObservationEvidence):
            raise TypeError('add requires HydraObjectKey and ObservationEvidence')
        if key.run_id != self.run_id:
            raise ValueError('object key belongs to a different run')
        if key.episode_id != self.episode_id:
            raise ValueError('object key belongs to a different episode')
        if key.episode_id != ref.source.episode_id:
            raise ValueError('evidence source episode differs from object key')
        identity = (key, ref.asset_key)
        if identity in self._entries:
            return
        self._evicted.pop(key, None)
        self._entries[identity] = ref
        while len(self._entries) > self.max_entries:
            (old_key, _), _ = self._entries.popitem(last=False)
            self._evicted[old_key] = self._evicted.get(old_key, 0) + 1

    def resolve(self, key: HydraObjectKey, *, limit: int = 64,
                cursor: int | None = None) -> EvidencePage:
        if not isinstance(key, HydraObjectKey):
            raise TypeError('key must be HydraObjectKey')
        if key.run_id != self.run_id:
            return EvidencePage('unavailable', (), None, ('run_mismatch',))
        if key.episode_id != self.episode_id:
            return EvidencePage('unavailable', (), None, ('episode_mismatch',))
        if type(limit) is not int or not 1 <= limit <= self.MAX_PAGE_SIZE:
            raise ValueError('limit must be between 1 and 64')
        if cursor is not None and (type(cursor) is not int or cursor < 0):
            raise ValueError('cursor must be a nonnegative integer or None')
        if self.recording_status == 'not_recorded':
            return EvidencePage('not_recorded', (), None, ('evidence_sidecar_absent',))
        refs = tuple(ref for (owner, _), ref in self._entries.items() if owner == key)
        evicted_count = self._evicted.get(key, 0)
        if not refs:
            if evicted_count:
                return EvidencePage('evicted', (), None, ('index_quota_evicted_refs',))
            return EvidencePage('no_evidence', (), None)
        start = 0 if cursor is None else cursor
        if start >= len(refs):
            return EvidencePage('available', (), None)
        page = refs[start:start + limit]
        next_cursor = start + len(page) if start + len(page) < len(refs) else None
        confirmed = bool(page) and all(ref.link_status == 'native_confirmed' for ref in page)
        reasons = ('some_refs_evicted_by_index_quota',) if evicted_count else ()
        return EvidencePage('available', page, next_cursor, reasons, confirmed)
