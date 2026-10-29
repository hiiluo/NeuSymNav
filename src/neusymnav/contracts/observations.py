"""Schema v1 source observations and asynchronous perception boundaries.

Runtime observations are canonical Z-up / optical-camera / metric axial depth.
Invalid depth remains unknown. GT semantics never enter these constructors.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping, Protocol
import numpy as np
from ._base import (Contract, array, boolean, choice, coordinates, digest, finite,
                    freeze, integer, text, typed_mapping, typed_tuple)
from ..geometry.frames import CANONICAL_Z_UP, validate_intrinsics, validate_pose


def age_ns(capture_ns: int, domain: str, now_ns: int, now_domain: str) -> int:
    capture, now = integer(capture_ns, 'capture_ns'), integer(now_ns, 'now_ns')
    text(domain, 'clock domain')
    text(now_domain, 'clock domain')
    if domain != now_domain:
        raise ValueError('clock domain mismatch')
    if now < capture:
        raise ValueError('capture timestamp is in the future')
    return now - capture


@dataclass(frozen=True)
class FrameKey(Contract):
    episode_id: str
    sensor_id: str
    frame_index: int

    def __post_init__(self):
        text(self.episode_id, 'episode_id')
        text(self.sensor_id, 'sensor_id')
        integer(self.frame_index, 'frame_index')


def _key(value):
    if not isinstance(value, FrameKey):
        raise ValueError('source must be FrameKey')


@dataclass(frozen=True)
class Observation(Contract):
    key: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    sim_time_s: float
    rgb: np.ndarray
    depth_m: np.ndarray
    valid_depth: np.ndarray
    K: np.ndarray
    T_world_camera: np.ndarray
    calibration_id: str
    pose_version: int
    modality: str
    no_return: np.ndarray | None = None
    far_plane: np.ndarray | None = None
    no_return_range_m: float | None = None
    far_plane_range_m: float | None = None
    coordinate_convention: str = CANONICAL_Z_UP
    depth_convention: str = 'metric_axial_v1'

    def __post_init__(self):
        _key(self.key)
        integer(self.capture_monotonic_ns, 'capture_monotonic_ns')
        text(self.clock_domain, 'clock_domain')
        finite(self.sim_time_s, 'sim_time_s', 0)
        text(self.calibration_id, 'calibration_id')
        integer(self.pose_version, 'pose_version')
        choice(self.modality, {'rgbd', 'depth_only'}, 'modality')
        choice(self.coordinate_convention, {CANONICAL_Z_UP}, 'coordinate_convention')
        choice(self.depth_convention, {'metric_axial_v1'}, 'depth_convention')
        rgb = array(self.rgb, 'rgb', dtype=np.uint8, shape=(None, None, 3))
        if 0 in rgb.shape:
            raise ValueError('RGB dimensions must be nonempty')
        depth = array(self.depth_m, 'depth_m', dtype=np.float32, shape=rgb.shape[:2], finite_only=False)
        valid = array(self.valid_depth, 'valid_depth', dtype=np.bool_, shape=depth.shape)
        if np.any(valid & (~np.isfinite(depth) | (depth <= 0))):
            raise ValueError('valid_depth must mark finite positive measured depth')
        k = array(self.K, 'K', dtype=np.float64, shape=(3, 3))
        pose = array(self.T_world_camera, 'T_world_camera', dtype=np.float64, shape=(4, 4))
        validate_intrinsics(k)
        validate_pose(pose)
        for name, value in [('rgb', rgb), ('depth_m', depth), ('valid_depth', valid), ('K', k), ('T_world_camera', pose)]:
            object.__setattr__(self, name, value)
        certificates = []
        for name, range_name in [('no_return', 'no_return_range_m'), ('far_plane', 'far_plane_range_m')]:
            mask, certified_range = getattr(self, name), getattr(self, range_name)
            if mask is not None:
                mask = array(mask, name, dtype=np.bool_, shape=depth.shape)
                if np.any(mask & valid):
                    raise ValueError(f'{name} overlaps valid measured depth')
                if mask.any() and certified_range is None:
                    raise ValueError(f'{name} needs certified range')
                object.__setattr__(self, name, mask)
                certificates.append(mask)
            elif certified_range is not None:
                raise ValueError(f'{range_name} requires explicit {name} mask')
            if certified_range is not None and finite(certified_range, range_name) <= 0:
                raise ValueError('certified range must be positive')
        if len(certificates) == 2 and np.any(certificates[0] & certificates[1]):
            raise ValueError('no_return and far_plane must not overlap')

    @property
    def geometry_hash(self) -> str:
        return geometry_hash(self)


def geometry_hash(observation: Observation) -> str:
    """Bind source identity, timing, geometry AND original sensor samples.

    Canonical JSON metadata and explicit little-endian byte arrays make the
    digest stable across host byte order. Prefix and metadata carry v1.
    """
    if not isinstance(observation, Observation):
        raise ValueError('geometry_hash requires Observation')
    meta = dict(episode_id=observation.key.episode_id, sensor_id=observation.key.sensor_id,
                frame_index=int(observation.key.frame_index), pose_version=int(observation.pose_version),
                capture_ns=int(observation.capture_monotonic_ns), clock_domain=observation.clock_domain,
                sim_time_s=float(observation.sim_time_s), calibration_id=observation.calibration_id,
                modality=observation.modality, coordinate_convention=observation.coordinate_convention,
                depth_convention=observation.depth_convention,
                no_return_range_m=None if observation.no_return_range_m is None else float(observation.no_return_range_m),
                far_plane_range_m=None if observation.far_plane_range_m is None else float(observation.far_plane_range_m))
    sha = hashlib.sha256(b'NeuSymNav:source-geometry:v1\0')
    sha.update(json.dumps(meta, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    for name in ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera', 'no_return', 'far_plane'):
        values = getattr(observation, name)
        sha.update(name.encode() + b'\0')
        if values is None:
            sha.update(b'none\0')
            continue
        canonical = values.astype(values.dtype.newbyteorder('<'), copy=False)
        sha.update(json.dumps([canonical.dtype.str, canonical.shape], separators=(',', ':')).encode() + b'\0')
        sha.update(canonical.tobytes(order='C'))
    return sha.hexdigest()


@dataclass(frozen=True)
class Detection(Contract):
    detection_id: str
    raw_label: str
    category: str | None
    score: float
    mask: np.ndarray

    def __post_init__(self):
        text(self.detection_id, 'detection_id')
        text(self.raw_label, 'raw_label')
        if self.category is not None:
            text(self.category, 'category')
        if not 0 <= finite(self.score, 'score') <= 1:
            raise ValueError('score must be in [0,1]')
        mask = array(self.mask, 'mask', dtype=np.bool_, ndim=2)
        if not mask.any():
            raise ValueError('detection mask must contain pixels')
        object.__setattr__(self, 'mask', mask)


@dataclass(frozen=True)
class DetectionBatch(Contract):
    source: FrameKey
    geometry_hash: str
    vocabulary_id: str
    detections: tuple[Detection, ...]
    completion: str
    cap_reached: bool

    def __post_init__(self):
        _key(self.source)
        digest(self.geometry_hash)
        text(self.vocabulary_id, 'vocabulary_id')
        detections = typed_tuple(self.detections, Detection, 'detections')
        ids = [d.detection_id for d in detections]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate detection_id')
        if len({d.mask.shape for d in detections}) > 1:
            raise ValueError('all masks in a batch must have the same source shape')
        object.__setattr__(self, 'detections', detections)
        choice(self.completion, {'complete', 'partial', 'failed', 'unknown'}, 'completion')
        boolean(self.cap_reached, 'cap_reached')

    @property
    def allows_negative_evidence(self) -> bool:
        """Necessary batch condition only; source visibility/depth still required."""
        return self.completion == 'complete' and not self.cap_reached

    @classmethod
    def from_observation(cls, observation: Observation, detections: tuple[Detection, ...], *,
                         vocabulary_id: str, completion: str = 'complete', cap_reached: bool = False):
        batch = cls(observation.key, observation.geometry_hash, vocabulary_id, detections, completion, cap_reached)
        validate_detection_batch(observation, batch)
        return batch


def require_rgbd(observation: Observation) -> None:
    if not isinstance(observation, Observation) or observation.modality != 'rgbd':
        raise ValueError('object perception requires a primary rgbd observation')


def validate_detection_batch(observation: Observation, batch: DetectionBatch) -> None:
    require_rgbd(observation)
    if not isinstance(batch, DetectionBatch) or batch.source != observation.key or batch.geometry_hash != observation.geometry_hash:
        raise ValueError('batch source/geometry_hash mismatch')
    if any(d.mask.shape != observation.depth_m.shape for d in batch.detections):
        raise ValueError('mask must match original source image shape')


@dataclass(frozen=True)
class AppearanceFeature(Contract):
    space_id: str
    vector: np.ndarray

    def __post_init__(self):
        text(self.space_id, 'space_id')
        vector = array(self.vector, 'vector', ndim=1)
        if vector.dtype.kind != 'f' or vector.size == 0 or np.linalg.norm(vector) == 0:
            raise ValueError('appearance vector must be nonzero finite floating point vector')
        object.__setattr__(self, 'vector', vector)

    def require_compatible(self, other: AppearanceFeature) -> None:
        if not isinstance(other, AppearanceFeature) or self.space_id != other.space_id or self.vector.shape != other.vector.shape:
            raise ValueError('appearance feature space/dimension mismatch')


@dataclass(frozen=True)
class ObjectObservation(Contract):
    source: FrameKey
    detection_id: str
    geometry_hash: str
    points_world: np.ndarray
    camera_position: tuple[float, float, float]
    raw_label: str
    category: str | None
    score: float
    evidence_kind: str
    appearance: AppearanceFeature | None

    def __post_init__(self):
        _key(self.source)
        text(self.detection_id, 'detection_id')
        digest(self.geometry_hash)
        points = array(self.points_world, 'points_world', shape=(None, 3))
        if points.dtype.kind != 'f' or not len(points):
            raise ValueError('points_world must contain measured floating point points')
        object.__setattr__(self, 'points_world', points)
        object.__setattr__(self, 'camera_position', coordinates(self.camera_position, 3, 'camera_position'))
        text(self.raw_label, 'raw_label')
        if self.category is not None:
            text(self.category, 'category')
        if not 0 <= finite(self.score, 'score') <= 1:
            raise ValueError('score must be in [0,1]')
        text(self.evidence_kind, 'evidence_kind')
        if self.appearance is not None and not isinstance(self.appearance, AppearanceFeature):
            raise ValueError('appearance must be AppearanceFeature or None')


@dataclass(frozen=True)
class AppearanceBatch(Contract):
    source: FrameKey
    geometry_hash: str
    features: Mapping[str, AppearanceFeature]

    def __post_init__(self):
        _key(self.source)
        digest(self.geometry_hash)
        object.__setattr__(self, 'features', typed_mapping(self.features, AppearanceFeature, 'features'))
        values = tuple(self.features.values())
        for value in values[1:]:
            values[0].require_compatible(value)


def validate_appearance_batch(observation: Observation, batch: DetectionBatch, appearance: AppearanceBatch) -> None:
    validate_detection_batch(observation, batch)
    if not isinstance(appearance, AppearanceBatch) or appearance.source != batch.source or appearance.geometry_hash != batch.geometry_hash:
        raise ValueError('appearance source/geometry_hash mismatch')
    if not set(appearance.features).issubset({d.detection_id for d in batch.detections}):
        raise ValueError('appearance cannot create a detection ID')


def validate_object_observations(observation: Observation, batch: DetectionBatch,
                                 observations: tuple[ObjectObservation, ...]) -> None:
    validate_detection_batch(observation, batch)
    detections = {d.detection_id: d for d in batch.detections}
    events = set()
    for item in typed_tuple(observations, ObjectObservation, 'observations'):
        if item.source != observation.key or item.geometry_hash != batch.geometry_hash or item.detection_id not in detections:
            raise ValueError('projected observation source/geometry/detection mismatch')
        detection = detections[item.detection_id]
        if (item.raw_label, item.category, item.score) != (detection.raw_label, detection.category, detection.score):
            raise ValueError('projected semantics differ from detection')
        if not np.allclose(item.camera_position, observation.T_world_camera[:3, 3], atol=1e-8, rtol=0):
            raise ValueError('projected camera_position differs from source pose')
        event = (item.detection_id, item.evidence_kind)
        if event in events:
            raise ValueError('duplicate projected evidence event')
        events.add(event)


@dataclass(frozen=True)
class Taxonomy(Contract):
    vocabulary_id: str
    categories: tuple[str, ...]
    aliases: Mapping[str, str]
    provenance: str
    unknown_category: None = None

    def __post_init__(self):
        from ._base import string_tuple
        text(self.vocabulary_id, 'vocabulary_id')
        text(self.provenance, 'provenance')
        categories = string_tuple(self.categories, 'categories')
        if not categories:
            raise ValueError('taxonomy must have categories')
        if self.unknown_category is not None:
            raise ValueError('unknown category must be None')
        aliases = typed_mapping(self.aliases, str, 'aliases')
        if any(v not in categories for v in aliases.values()) or any(k in categories and k != v for k, v in aliases.items()):
            raise ValueError('taxonomy aliases must target canonical categories without overriding them')
        object.__setattr__(self, 'categories', categories)
        object.__setattr__(self, 'aliases', aliases)

    def canonicalize(self, raw_label: str) -> str | None:
        text(raw_label, 'raw_label')
        label = raw_label.strip().lower()
        return label if label in self.categories else self.aliases.get(label)

    @staticmethod
    def exact_match(raw_label: str, evaluator_label: str) -> bool:
        return raw_label == evaluator_label

    @classmethod
    def load(cls, path: str | Path) -> Taxonomy:
        payload = json.loads(Path(path).read_text())
        version = payload.pop('schema_version', None)
        if type(version) is not int or version != 1:
            raise ValueError('unsupported taxonomy schema')
        return cls(**payload)


class PoseSource(Protocol):
    def capture(self) -> Observation: ...
    def capture_navigation(self) -> Observation: ...


class Detector(Protocol):
    def infer(self, observation: Observation) -> DetectionBatch: ...


class Projector(Protocol):
    def project(self, observation: Observation, batch: DetectionBatch) -> tuple[ObjectObservation, ...]: ...


class AppearanceEncoder(Protocol):
    def encode(self, observation: Observation, batch: DetectionBatch) -> AppearanceBatch: ...
