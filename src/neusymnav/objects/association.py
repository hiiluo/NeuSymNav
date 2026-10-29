"""Port of NewOH3DSG association/matching.py (hash in runs/p04/source-hashes.json).

Geometry/Hungarian/ambiguity/cannot-link thresholds retained. Spatial buckets
use canonical XY, detection IDs are strings; one pinned primary sensor per owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import OrderedDict
from functools import wraps
import gc
import hashlib
import math
from types import MappingProxyType
from typing import Callable, Mapping
import uuid

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree

from .fusion import VoxelCloud
from .appearance import fuse_visual, normalize_visual


WallPredicate = Callable[[tuple[float, float, float], tuple[float, float, float]], bool]
EventKey = tuple[str, int, str, str]


def _defer_cyclic_gc(function):
    """Keep process-wide cyclic GC outside one short fusion-owner transaction."""
    @wraps(function)
    def run(*args, **kwargs):
        was_enabled = gc.isenabled()
        if was_enabled:
            gc.disable()
        try:
            return function(*args, **kwargs)
        finally:
            if was_enabled:
                gc.enable()

    return run


def _immutable(array: np.ndarray) -> np.ndarray:
    value = np.ascontiguousarray(array, dtype=np.float64)
    return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)


@dataclass(frozen=True)
class AssociationObservation:
    episode_id: str
    frame_id: int
    detection_id: str
    floor_id: str
    evidence_kind: str
    label: str
    score: float
    points_world: np.ndarray
    camera_position_world: tuple[float, float, float]
    source_geometry_sha256: str | None = None
    source_payload_sha256: str | None = None
    visual_embedding: np.ndarray | None = None
    track_id: str | None = None
    centroid_world: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.episode_id or not self.floor_id or self.frame_id < 0 or not isinstance(self.detection_id, str) or not self.detection_id:
            raise ValueError("association observation needs valid episode, floor, and source IDs")
        if self.evidence_kind not in {"detected", "tracked", "refined"}:
            raise ValueError("unsupported association evidence kind")
        if not self.label or not math.isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError("association label and score must be valid")
        points = np.asarray(self.points_world, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0 or not np.isfinite(points).all():
            raise ValueError("association cloud must contain finite xyz points")
        object.__setattr__(self, "points_world", _immutable(points))
        object.__setattr__(self, "centroid_world", _immutable(np.median(points, axis=0)))
        camera = tuple(self.camera_position_world)
        if len(camera) != 3 or not all(math.isfinite(v) for v in camera):
            raise ValueError("camera position must be finite xyz")
        object.__setattr__(self, "camera_position_world", camera)
        if self.source_geometry_sha256 is not None and (
            len(self.source_geometry_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_geometry_sha256)
        ):
            raise ValueError("source geometry fingerprint must be SHA-256")
        if self.source_payload_sha256 is not None and (
            len(self.source_payload_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_payload_sha256)
        ):
            raise ValueError("source payload fingerprint must be SHA-256")
        if self.visual_embedding is not None:
            embedding = np.asarray(self.visual_embedding, dtype=np.float64)
            if embedding.ndim != 1 or not len(embedding) or not np.isfinite(embedding).all():
                raise ValueError("visual embedding must be a finite vector")
            object.__setattr__(self, "visual_embedding", normalize_visual(embedding))

    @property
    def event_key(self) -> EventKey:
        return self.episode_id, self.frame_id, self.detection_id, self.evidence_kind

    @property
    def centroid(self) -> np.ndarray:
        return self.centroid_world



@dataclass(frozen=True)
class TrackSnapshot:
    id: str
    floor_id: str
    centroid_world: tuple[float, float, float]
    point_count: int
    labels: Mapping[str, int]
    detected_count: int
    distinct_views: int
    first_seen_s: float
    last_seen_s: float
    status: str


@dataclass(frozen=True)
class AssociationResult:
    object_ids: tuple[str | None, ...]
    tracks: Mapping[str, TrackSnapshot]
    ambiguous_indices: tuple[int, ...]
    ambiguous_event_keys: tuple[EventKey, ...]


@dataclass
class _Track:
    id: str
    floor_id: str
    slot: int
    cannot_link_bits: int
    points_world: np.ndarray
    voxel_cloud: VoxelCloud
    centroid_world: np.ndarray
    labels: dict[str, int]
    detected_count: int
    camera_positions: list[tuple[float, float, float]]
    first_seen_s: float
    last_seen_s: float
    last_detected_s: float | None
    status: str = "candidate"
    visual_embedding: np.ndarray | None = None
    track_id: str | None = None
    visual_weight: int = 0

    @property
    def centroid(self) -> np.ndarray:
        return self.centroid_world


@dataclass(frozen=True)
class _ScoreGeometry:
    minimum: np.ndarray
    maximum: np.ndarray
    diagonal: float
    sample: np.ndarray
    tree: cKDTree

    @classmethod
    def from_points(cls, points: np.ndarray) -> "_ScoreGeometry":
        minimum = points.min(axis=0)
        maximum = points.max(axis=0)
        sample = points[:512]
        return cls(minimum, maximum, float(np.linalg.norm(maximum - minimum)), sample, cKDTree(sample))


class AssociationEngine:
    """Assign each new frame once; ambiguous matches remain unresolved."""

    MAX_CAMERA_POSITIONS = 16

    def __init__(self, episode_id: str, *, max_tracks: int = 1000, max_ambiguous: int = 256,
                 event_lookup: Callable[[EventKey], tuple[str | None, str] | None] | None = None,
                 max_hot_events: int = 256,
                 prune_callback: Callable[[set[str], Mapping[str, dict]], None] | None = None,
                 association_mode: str = "geometry") -> None:
        if not episode_id or max_tracks <= 0 or max_ambiguous <= 0:
            raise ValueError("association engine needs episode and positive track cap")
        if association_mode not in {"semantic", "geometry", "geometry_appearance"}:
            raise ValueError("association_mode must be semantic, geometry or geometry_appearance")
        self.episode_id = episode_id
        self.association_mode = association_mode
        self.max_tracks = max_tracks
        self.max_ambiguous = max_ambiguous
        self._tracks: dict[str, _Track] = {}
        self._events: OrderedDict[EventKey, tuple[str | None, str]] = OrderedDict()
        self._event_lookup = event_lookup
        self._prune_callback = prune_callback
        self.max_hot_events = max_hot_events
        self._ambiguous_events: OrderedDict[EventKey, AssociationObservation] = OrderedDict()
        # Slots are recycled only after pruning clears their bits from every
        # surviving track. This keeps exact cannot-link history within the cap.
        self._free_slots: list[int] = []
        self._next_slot = 0

    def fork(self) -> "AssociationEngine":
        """Copy transaction-mutable state without copying immutable cloud arrays.

        Track updates replace point/centroid arrays and voxel centers rather
        than mutating them in place. A failed graph transaction can therefore
        discard this fork without altering the live association engine.
        """
        trial = AssociationEngine(
            self.episode_id, max_tracks=self.max_tracks,
            max_ambiguous=self.max_ambiguous, event_lookup=self._event_lookup,
            max_hot_events=self.max_hot_events, prune_callback=self._prune_callback,
            association_mode=self.association_mode,
        )
        trial._tracks = {
            key: replace(
                track,
                voxel_cloud=track.voxel_cloud.fork(),
                labels=dict(track.labels),
                camera_positions=list(track.camera_positions),
            )
            for key, track in self._tracks.items()
        }
        trial._events = OrderedDict(self._events)
        trial._ambiguous_events = OrderedDict(self._ambiguous_events)
        trial._free_slots = list(self._free_slots)
        trial._next_slot = self._next_slot
        return trial

    def can_merge(self, first_id: str, second_id: str) -> bool:
        if first_id == second_id:
            return False
        if first_id not in self._tracks or second_id not in self._tracks:
            raise ValueError("cannot compare absent object IDs")
        first = self._tracks[first_id]
        second = self._tracks[second_id]
        return not (first.cannot_link_bits & (1 << second.slot) or
                    second.cannot_link_bits & (1 << first.slot))

    def merge_tracks(self, first_id: str, second_id: str) -> str:
        """Fuse two live tracks in this engine transaction; return the stable ID.

        Callers should merge on a fork and publish that fork only with their
        graph and alias-journal transaction. The engine stores no aliases.
        """
        if first_id == second_id or first_id not in self._tracks or second_id not in self._tracks:
            raise ValueError("merge needs two distinct live object IDs")
        survivor_id, retired_id = sorted((first_id, second_id))
        survivor, retired = self._tracks[survivor_id], self._tracks[retired_id]
        if survivor.floor_id != retired.floor_id:
            raise ValueError("cannot merge tracks across floors")
        if not self.can_merge(first_id, second_id):
            raise ValueError("cannot merge simultaneous objects")
        left, right = survivor.voxel_cloud, retired.voxel_cloud
        if (left.voxel_m, left.max_voxels, left.max_weight) != (right.voxel_m, right.max_voxels, right.max_weight):
            raise ValueError("cannot merge incompatible voxel grids")

        # Build the fused value before changing any live object. Each center is
        # immutable, and fork() copies the mutable voxel table.
        cloud = left.fork()
        cloud.truncated_voxel_count += right.truncated_voxel_count
        for key, (right_center, right_weight) in sorted(right._voxels.items()):
            prior = cloud._voxels.get(key)
            if prior is None:
                if len(cloud._voxels) < cloud.max_voxels:
                    cloud._voxels[key] = (right_center, right_weight)
                else:
                    cloud.truncated_voxel_count += 1
            else:
                left_center, left_weight = prior
                total = left_weight + right_weight
                cloud._voxels[key] = (_immutable((left_center * left_weight + right_center * right_weight) / total),
                                      min(total, cloud.max_weight))
        points = cloud.points_world()
        labels = dict(survivor.labels)
        for label, count in retired.labels.items():
            labels[label] = labels.get(label, 0) + count
        cameras = list(survivor.camera_positions)
        for camera in retired.camera_positions:
            if len(cameras) >= self.MAX_CAMERA_POSITIONS:
                break
            if all(np.linalg.norm(np.subtract(camera, prior)) >= 0.3 for prior in cameras):
                cameras.append(camera)
        visual, visual_weight = fuse_visual(survivor.visual_embedding, survivor.visual_weight,
            retired.visual_embedding, retired.visual_weight)
        merged_count = survivor.detected_count + retired.detected_count
        merged_bits = (survivor.cannot_link_bits | retired.cannot_link_bits) & ~(
            (1 << survivor.slot) | (1 << retired.slot))
        merged = replace(
            survivor, voxel_cloud=cloud, points_world=points,
            centroid_world=_immutable(np.median(points, axis=0)), labels=labels,
            detected_count=merged_count, camera_positions=cameras,
            first_seen_s=min(survivor.first_seen_s, retired.first_seen_s),
            last_seen_s=max(survivor.last_seen_s, retired.last_seen_s),
            last_detected_s=max((stamp for stamp in (survivor.last_detected_s, retired.last_detected_s)
                                 if stamp is not None), default=None),
            status="active" if (survivor.status == "active" or retired.status == "active" or
                                (merged_count >= 2 and len(cameras) >= 2)) else "candidate",
            visual_embedding=visual, visual_weight=visual_weight,
            track_id=survivor.track_id if survivor.track_id == retired.track_id else None,
            cannot_link_bits=merged_bits,
        )

        # Rewrite all reverse links before exposing the retired slot for reuse.
        for object_id, track in self._tracks.items():
            if object_id in (survivor_id, retired_id):
                continue
            had_retired_link = bool(track.cannot_link_bits & (1 << retired.slot))
            track.cannot_link_bits &= ~(1 << retired.slot)
            if had_retired_link or merged_bits & (1 << track.slot):
                track.cannot_link_bits |= 1 << survivor.slot
        self._tracks[survivor_id] = merged
        del self._tracks[retired_id]
        self._events = OrderedDict(
            (key, (survivor_id if object_id == retired_id else object_id, digest))
            for key, (object_id, digest) in self._events.items()
        )
        self._free_slots.append(retired.slot)
        return survivor_id

    def attach_visual(self, object_id: str, vector: np.ndarray) -> None:
        """Owner calls once per durable accepted DETECTED event on a fork."""
        track = self._tracks[object_id]
        value = normalize_visual(vector)
        track.visual_embedding, track.visual_weight = fuse_visual(
            track.visual_embedding, track.visual_weight, value, 1)

    def track_cloud(self, object_id: str) -> np.ndarray:
        """Return a read-only snapshot of bounded fused geometry."""
        return _immutable(self._tracks[object_id].points_world)

    @_defer_cyclic_gc
    def ingest(
        self,
        observations: tuple[AssociationObservation, ...],
        *,
        now_s: float | None = None,
        blocked_by_wall: WallPredicate | None = None,
    ) -> AssociationResult:
        observations = tuple(observations)
        if any(not isinstance(obs, AssociationObservation) for obs in observations):
            raise TypeError("all observations must be AssociationObservation")
        if any(obs.episode_id != self.episode_id for obs in observations):
            raise ValueError("association episode mismatch")
        if observations and len({obs.frame_id for obs in observations}) != 1:
            raise ValueError("one ingest call must contain one source frame")
        if len({obs.event_key for obs in observations}) != len(observations):
            raise ValueError("duplicate detection ID in one frame")
        stamp = float(observations[0].frame_id if now_s is None and observations else (now_s or 0.0))
        if not math.isfinite(stamp) or stamp < 0:
            raise ValueError("association time must be finite and nonnegative")

        answers: list[str | None] = [None] * len(observations)
        fresh_indices = []
        for index, obs in enumerate(observations):
            digest = self._digest(obs)
            prior = self._events.get(obs.event_key)
            if prior is None and self._event_lookup is not None:
                prior = self._event_lookup(obs.event_key)
            if prior is not None:
                if prior[1] != digest:
                    raise ValueError("conflicting duplicate association event")
                answers[index] = prior[0]
            else:
                fresh_indices.append(index)

        # Rebuild a small spatial hash from bounded active tracks. Candidate
        # radius never exceeds 1.5 m, so the 3x3 neighboring 1.5 m buckets
        # cover every possible match without scoring distant objects.
        bucket_width = 1.5
        buckets: dict[tuple[str, int, int], set[str]] = {}
        for track in self._tracks.values():
            center = track.centroid
            key = (track.floor_id, math.floor(center[0] / bucket_width), math.floor(center[1] / bucket_width))
            buckets.setdefault(key, set()).add(track.id)
        local_ids: list[set[str]] = []
        for index in fresh_indices:
            obs = observations[index]
            center = obs.centroid
            bx, bz = math.floor(center[0] / bucket_width), math.floor(center[1] / bucket_width)
            neighbors = set()
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbors.update(buckets.get((obs.floor_id, bx + dx, bz + dz), ()))
            local_ids.append(neighbors)
        candidate_ids = set().union(*local_ids) if local_ids else set()
        existing = tuple(self._tracks[id] for id in sorted(candidate_ids))
        scores = np.full((len(fresh_indices), len(existing)), -math.inf)
        observation_geometry: dict[int, _ScoreGeometry] = {}
        track_geometry: dict[str, _ScoreGeometry] = {}
        for row, index in enumerate(fresh_indices):
            for col, track in enumerate(existing):
                if track.id not in local_ids[row]:
                    continue
                if index not in observation_geometry:
                    observation_geometry[index] = _ScoreGeometry.from_points(observations[index].points_world)
                if track.id not in track_geometry:
                    track_geometry[track.id] = _ScoreGeometry.from_points(track.points_world)
                obs_shape = observation_geometry[index]
                track_shape = track_geometry[track.id]
                value = self._score(observations[index], track, blocked_by_wall, obs_shape, track_shape)
                if value is not None:
                    scores[row, col] = value

        ambiguous_rows = set()
        for row in range(len(fresh_indices)):
            eligible = sorted((float(v) for v in scores[row] if v >= 0.55), reverse=True)
            if len(eligible) >= 2 and eligible[0] - eligible[1] < 0.08:
                ambiguous_rows.add(row)

        # One dummy column per observation lets the global assignment leave
        # any observation unmatched. An ambiguous row cannot claim a track.
        costs = np.full((len(fresh_indices), len(existing) + len(fresh_indices)), 1000.0)
        for row in range(len(fresh_indices)):
            if row not in ambiguous_rows:
                costs[row, :len(existing)] = np.where(scores[row] >= 0.55, 1.0 - scores[row], 1000.0)
            costs[row, len(existing) + row] = 0.45
        matched: dict[int, int] = {}
        if fresh_indices:
            rows, cols = linear_sum_assignment(costs)
            matched = {int(row): int(col) for row, col in zip(rows, cols) if col < len(existing) and costs[row, col] <= 0.45}

        new_detected = sum(
            observations[index].evidence_kind == "detected"
            for row, index in enumerate(fresh_indices)
            if row not in matched and row not in ambiguous_rows
        )
        if len(self._tracks) + new_detected > self.max_tracks:
            raise ValueError("association hot-track cap exceeded")
        if self._event_lookup is None and len(self._ambiguous_events) + len(ambiguous_rows) > self.max_ambiguous:
            raise ValueError("ambiguous observation bucket cap exceeded")
        for row, index in enumerate(fresh_indices):
            obs = observations[index]
            if row in ambiguous_rows:
                self._events[obs.event_key] = (None, self._digest(obs))
                self._ambiguous_events[obs.event_key] = obs
                continue
            if row in matched:
                track = existing[matched[row]]
                self._update(track, obs, stamp)
            elif obs.evidence_kind != "detected":
                self._events[obs.event_key] = (None, self._digest(obs))
                continue
            else:
                namespace = uuid.uuid5(uuid.NAMESPACE_URL,
                    'NeuSymNav:canonical-object:v1:' + self.episode_id)
                object_id = str(uuid.uuid5(namespace, repr(obs.event_key)))
                voxel_cloud = VoxelCloud()
                voxel_cloud.integrate(obs.points_world)
                slot = self._free_slots.pop() if self._free_slots else self._next_slot
                if slot == self._next_slot:
                    self._next_slot += 1
                track = _Track(
                    id=object_id,
                    floor_id=obs.floor_id,
                    slot=slot,
                    cannot_link_bits=0,
                    points_world=voxel_cloud.points_world(),
                    voxel_cloud=voxel_cloud,
                    centroid_world=obs.centroid.copy(),
                    labels={obs.label: 1},
                    detected_count=int(obs.evidence_kind == "detected"),
                    camera_positions=[obs.camera_position_world] if obs.evidence_kind == "detected" else [],
                    first_seen_s=stamp,
                    last_seen_s=stamp,
                    last_detected_s=stamp if obs.evidence_kind == "detected" else None,
                    visual_embedding=obs.visual_embedding if obs.evidence_kind == "detected" else None,
                    visual_weight=int(obs.visual_embedding is not None and obs.evidence_kind == "detected"),
                    track_id=obs.track_id,
                )
                self._tracks[object_id] = track
            answers[index] = track.id
            self._events[obs.event_key] = (track.id, self._digest(obs))
        assigned = tuple(dict.fromkeys(object_id for object_id in answers if object_id is not None))
        if len(assigned) >= 2:
            group_bits = sum(1 << self._tracks[object_id].slot for object_id in assigned)
            for object_id in assigned:
                track = self._tracks[object_id]
                track.cannot_link_bits |= group_bits & ~(1 << track.slot)
        if self._event_lookup is not None:
            while len(self._events) > self.max_hot_events:
                self._events.popitem(last=False)
            while len(self._ambiguous_events) > self.max_ambiguous:
                self._ambiguous_events.popitem(last=False)
        return self._result(tuple(answers), tuple(fresh_indices[row] for row in sorted(ambiguous_rows)))

    def advance_time(self, now_s: float) -> AssociationResult:
        """Age only one-view candidates; established identities remain searchable."""
        if not math.isfinite(now_s) or now_s < 0:
            raise ValueError("association time must be finite and nonnegative")
        removed = set()
        dormant = set()
        for track in self._tracks.values():
            if track.status == "active":
                continue
            age_s = max(0.0, now_s - (track.last_detected_s if track.last_detected_s is not None else track.first_seen_s))
            if age_s >= 60.0:
                removed.add(track.id)
            elif age_s >= 15.0 and track.status != "dormant":
                dormant.add(track.id)
        removed_bits = sum(1 << self._tracks[object_id].slot for object_id in removed)
        if (removed or dormant) and self._prune_callback is not None:
            persisted_ids = set(self._tracks) - removed if removed else dormant
            persisted = self.export_active_state(persisted_ids)
            for object_id, state in persisted.items():
                state["cannot_link_bits"] &= ~removed_bits
                if object_id in dormant:
                    state["status"] = "dormant"
            self._prune_callback(removed, persisted)
        for object_id in dormant:
            self._tracks[object_id].status = "dormant"
        if removed:
            for object_id in removed:
                self._free_slots.append(self._tracks.pop(object_id).slot)
            for track in self._tracks.values():
                track.cannot_link_bits &= ~removed_bits
            self._events = OrderedDict({
                key: (None if object_id in removed else object_id, digest)
                for key, (object_id, digest) in self._events.items()
            })
        return self._result((), ())

    def export_active_state(self, object_ids: set[str] | None = None) -> dict[str, dict]:
        """Versioned JSON state for durable active tracks; no executable pickle."""
        result = {}
        for object_id, track in self._tracks.items():
            if object_ids is not None and object_id not in object_ids:
                continue
            result[object_id] = {
                "schema_version": 1, "id": track.id, "floor_id": track.floor_id,
                "slot": track.slot, "cannot_link_bits": track.cannot_link_bits,
                "labels": track.labels, "detected_count": track.detected_count,
                "camera_positions": track.camera_positions,
                "first_seen_s": track.first_seen_s, "last_seen_s": track.last_seen_s,
                "last_detected_s": track.last_detected_s, "status": track.status,
                "visual_embedding": None if track.visual_embedding is None else track.visual_embedding.tolist(),
                "track_id": track.track_id,
                "visual_weight": track.visual_weight,
                "voxel_m": track.voxel_cloud.voxel_m,
                "max_voxels": track.voxel_cloud.max_voxels,
                "max_weight": track.voxel_cloud.max_weight,
                "truncated_voxel_count": track.voxel_cloud.truncated_voxel_count,
                "voxels": [[*key, *center.tolist(), weight]
                           for key, (center, weight) in sorted(track.voxel_cloud._voxels.items())],
            }
        return result

    def restore_active_state(self, states: Mapping[str, dict]) -> None:
        """Restore only validated internal state from the episode ledger."""
        if self._tracks:
            raise ValueError("cannot restore into a nonempty association engine")
        if len(states) > self.max_tracks:
            raise ValueError("association hot-track cap exceeded")
        tracks = {}
        used_slots = set()
        for object_id, raw in states.items():
            if raw.get("schema_version") != 1 or raw.get("id") != object_id:
                raise ValueError("invalid association checkpoint schema or ID")
            if set(raw) - {"visual_weight"} != {
                "schema_version", "id", "floor_id", "slot", "cannot_link_bits", "labels",
                "detected_count", "camera_positions", "first_seen_s", "last_seen_s",
                "last_detected_s", "status", "visual_embedding", "track_id", "voxel_m",
                "max_voxels", "max_weight", "truncated_voxel_count", "voxels",
            }:
                raise ValueError("invalid association checkpoint fields")
            slot = raw["slot"]
            if not isinstance(slot, int) or slot < 0 or slot in used_slots:
                raise ValueError("invalid association checkpoint slot")
            used_slots.add(slot)
            voxels = VoxelCloud(voxel_m=raw["voxel_m"], max_voxels=raw["max_voxels"], max_weight=raw["max_weight"])
            if len(raw["voxels"]) > voxels.max_voxels:
                raise ValueError("association checkpoint voxel cap exceeded")
            for entry in raw["voxels"]:
                if len(entry) != 7 or not all(math.isfinite(v) for v in entry[3:6]):
                    raise ValueError("invalid association checkpoint voxel")
                key = tuple(int(v) for v in entry[:3])
                weight = int(entry[6])
                if weight < 1 or weight > voxels.max_weight or key in voxels._voxels:
                    raise ValueError("invalid association checkpoint voxel weight")
                voxels._voxels[key] = (_immutable(np.asarray(entry[3:6])), weight)
            voxels.truncated_voxel_count = int(raw["truncated_voxel_count"])
            points = voxels.points_world()
            if not len(points):
                raise ValueError("association checkpoint track has no voxels")
            if raw["status"] not in {"candidate", "active", "dormant"} or not raw["floor_id"]:
                raise ValueError("invalid association checkpoint track status")
            if not raw["labels"] or any(not isinstance(label, str) or not label or
                                         not isinstance(count, int) or count < 0
                                         for label, count in raw["labels"].items()):
                raise ValueError("invalid association checkpoint labels")
            times = (raw["first_seen_s"], raw["last_seen_s"])
            if not all(math.isfinite(value) and value >= 0 for value in times) or times[1] < times[0]:
                raise ValueError("invalid association checkpoint times")
            if raw["last_detected_s"] is not None and not math.isfinite(raw["last_detected_s"]):
                raise ValueError("invalid association checkpoint detection time")
            cameras = raw["camera_positions"]
            if not isinstance(cameras, list) or any(
                not isinstance(camera, (list, tuple)) or len(camera) != 3 or
                not all(isinstance(value, (int, float)) and math.isfinite(value) for value in camera)
                for camera in cameras[:self.MAX_CAMERA_POSITIONS]
            ):
                raise ValueError("invalid association checkpoint camera positions")
            visual = raw["visual_embedding"]
            visual_weight = raw.get("visual_weight", 0)
            if type(visual_weight) is not int or visual_weight < 0:
                raise ValueError("invalid association checkpoint appearance weight")
            if visual is not None:
                visual = np.asarray(visual, dtype=float)
                if visual.ndim != 1 or not len(visual) or not np.isfinite(visual).all() or np.linalg.norm(visual) <= 0:
                    raise ValueError("invalid association checkpoint appearance vector")
                if "visual_weight" in raw and (not visual_weight or not np.isclose(np.linalg.norm(visual), 1.)):
                    raise ValueError("invalid association checkpoint appearance normalization")
            tracks[object_id] = _Track(
                id=object_id, floor_id=raw["floor_id"], slot=slot,
                cannot_link_bits=int(raw["cannot_link_bits"]), points_world=points,
                voxel_cloud=voxels, centroid_world=np.median(points, axis=0),
                labels=dict(raw["labels"]), detected_count=int(raw["detected_count"]),
                camera_positions=[tuple(v) for v in cameras[:self.MAX_CAMERA_POSITIONS]],
                first_seen_s=float(raw["first_seen_s"]), last_seen_s=float(raw["last_seen_s"]),
                last_detected_s=None if raw["last_detected_s"] is None else float(raw["last_detected_s"]),
                status=raw["status"],
                visual_embedding=None if visual is None else _immutable(np.asarray(visual)),
                track_id=raw["track_id"], visual_weight=visual_weight,
            )
        self._tracks = tracks
        allowed_bits = sum(1 << slot for slot in used_slots)
        if any(track.cannot_link_bits < 0 or track.cannot_link_bits & ~allowed_bits or
               track.cannot_link_bits & (1 << track.slot) for track in tracks.values()):
            raise ValueError("invalid association checkpoint cannot-link state")
        self._next_slot = max(used_slots, default=-1) + 1
        self._free_slots = [slot for slot in range(self._next_slot) if slot not in used_slots]

    def _result(self, ids: tuple[str | None, ...], ambiguous: tuple[int, ...]) -> AssociationResult:
        snapshots = {
            track.id: TrackSnapshot(
                id=track.id,
                floor_id=track.floor_id,
                centroid_world=tuple(float(v) for v in track.centroid),
                point_count=len(track.points_world),
                labels=MappingProxyType(dict(track.labels)),
                detected_count=track.detected_count,
                distinct_views=len(track.camera_positions),
                first_seen_s=track.first_seen_s,
                last_seen_s=track.last_seen_s,
                status=track.status,
            )
            for track in self._tracks.values()
        }
        return AssociationResult(ids, MappingProxyType(snapshots), ambiguous, tuple(sorted(self._ambiguous_events)))

    def _score(
        self,
        obs: AssociationObservation,
        track: _Track,
        blocked_by_wall: WallPredicate | None,
        obs_shape: _ScoreGeometry,
        track_shape: _ScoreGeometry,
    ) -> float | None:
        if obs.floor_id != track.floor_id:
            return None
        a, b = obs.centroid, track.centroid
        if blocked_by_wall is not None and blocked_by_wall(tuple(b), tuple(a)):
            return None
        obs_min, obs_max = obs_shape.minimum, obs_shape.maximum
        track_min, track_max = track_shape.minimum, track_shape.maximum
        obs_diag, track_diag = obs_shape.diagonal, track_shape.diagonal
        radius = float(np.clip(0.25 + 0.5 * (obs_diag + track_diag), 0.4, 1.5))
        distance = float(np.linalg.norm(a - b))
        if distance > radius:
            return None
        if np.any(obs_max + 0.1 < track_min) or np.any(track_max + 0.1 < obs_min):
            return None
        points_a = obs_shape.sample
        points_b = track_shape.sample
        overlap = 0.5 * (
            np.mean(track_shape.tree.query(points_a, k=1)[0] < 0.08)
            + np.mean(obs_shape.tree.query(points_b, k=1)[0] < 0.08)
        )
        sigma = max(0.15, 0.25 * track_diag)
        geometry = math.exp(-(distance * distance) / (2 * sigma * sigma))
        intersection = np.maximum(0.0, np.minimum(obs_max, track_max) - np.maximum(obs_min, track_min))
        intersection_volume = float(np.prod(intersection))
        union = float(np.prod(obs_max - obs_min) + np.prod(track_max - track_min) - intersection_volume)
        bbox_iou = intersection_volume / union if union > 0 else 0.0
        geometry_weighted = 0.30 * overlap + 0.20 * geometry + 0.10 * bbox_iou
        if self.association_mode in {"geometry", "geometry_appearance"}:
            if (self.association_mode == "geometry_appearance" and obs.visual_embedding is not None
                    and track.visual_embedding is not None):
                if obs.visual_embedding.shape != track.visual_embedding.shape:
                    raise ValueError("appearance feature space/dimension mismatch")
                visual = float(np.clip((np.dot(obs.visual_embedding, track.visual_embedding) - 0.2) / 0.6, 0.0, 1.0))
                return (geometry_weighted + 0.20 * visual) / 0.80
            return geometry_weighted / 0.60
        aliases = {"chair": "seat", "seat": "seat", "couch": "sofa", "sofa": "sofa"}
        label_group = aliases.get(obs.label, obs.label)
        label_match = 1.0 if any(aliases.get(label, label) == label_group for label in track.labels) else 0.2
        weighted = 0.30 * overlap + 0.20 * geometry + 0.10 * bbox_iou + 0.15 * label_match
        available = 0.75
        if obs.visual_embedding is not None and track.visual_embedding is not None and len(obs.visual_embedding) == len(track.visual_embedding):
            visual = float(np.clip((np.dot(obs.visual_embedding, track.visual_embedding) - 0.2) / 0.6, 0.0, 1.0))
            weighted += 0.20 * visual
            available += 0.20
        if obs.track_id is not None and track.track_id is not None:
            weighted += 0.05 * float(obs.track_id == track.track_id)
            available += 0.05
        return weighted / available

    @staticmethod
    def _update(track: _Track, obs: AssociationObservation, stamp: float) -> None:
        if obs.evidence_kind == "detected":
            track.detected_count += 1
            track.labels[obs.label] = track.labels.get(obs.label, 0) + 1
            track.last_detected_s = max(track.last_detected_s if track.last_detected_s is not None else stamp, stamp)
        track.last_seen_s = max(track.last_seen_s, stamp)
        track.first_seen_s = min(track.first_seen_s, stamp)
        if obs.evidence_kind == "detected" and len(track.camera_positions) < AssociationEngine.MAX_CAMERA_POSITIONS and all(
            np.linalg.norm(np.subtract(obs.camera_position_world, prior)) >= 0.3
            for prior in track.camera_positions
        ):
            track.camera_positions.append(obs.camera_position_world)
        if track.detected_count >= 2 and len(track.camera_positions) >= 2:
            track.status = "active"
        elif track.status == "dormant" and obs.evidence_kind == "detected":
            track.status = "candidate"
        if obs.visual_embedding is not None and obs.evidence_kind == "detected":
            track.visual_embedding, track.visual_weight = fuse_visual(
                track.visual_embedding, track.visual_weight, obs.visual_embedding, 1)
        if obs.track_id is not None:
            track.track_id = obs.track_id
        if obs.evidence_kind != "tracked":
            track.voxel_cloud.integrate(obs.points_world)
            track.points_world = track.voxel_cloud.points_world()
            track.centroid_world = np.median(track.points_world, axis=0)

    @staticmethod
    def _digest(obs: AssociationObservation) -> str:
        digest = hashlib.sha256(repr((obs.event_key, obs.floor_id, obs.label, obs.score, obs.camera_position_world, obs.track_id, obs.source_geometry_sha256, obs.source_payload_sha256)).encode())
        digest.update(obs.points_world.tobytes())
        if obs.visual_embedding is not None:
            digest.update(b"visual_embedding")
            digest.update(obs.visual_embedding.tobytes())
        return digest.hexdigest()
