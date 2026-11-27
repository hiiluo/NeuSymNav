"""ReasoningGraph v1 read addresses and evidence, owned by the graph producer."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ._base import choice, coordinates, digest, finite, integer, text
from .hydra_evidence import ObservationEvidence
from .hydra_graph import HydraReadToken, NativeNodeRef
from .observations import FrameKey


def _bounds(value):
    lo, hi = value
    lo, hi = coordinates(lo, 3, 'min_xyz'), coordinates(hi, 3, 'max_xyz')
    if any(a > b for a, b in zip(lo, hi)):
        raise ValueError('bounds are inverted')
    return lo, hi


@dataclass(frozen=True)
class GraphReadToken:
    native: HydraReadToken
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    calibration_id: str
    calibration_hash: str
    source_geometry_hash: str
    vocabulary_id: str
    labelspace_hash: str
    detector_profile_id: str
    pose_version: int
    sidecar_revision: int = 0
    coordinate_convention: str = 'canonical_z_up_v1'
    schema_version: int = 1

    def __post_init__(self):
        if (not isinstance(self.native, HydraReadToken) or not isinstance(self.source, FrameKey)
                or self.native.episode_id != self.source.episode_id or self.native.graph_revision == 0):
            raise ValueError('graph token requires an accepted source in the same episode')
        for name in ('clock_domain', 'calibration_id', 'vocabulary_id', 'detector_profile_id'):
            text(getattr(self, name), name)
        for name in ('calibration_hash', 'source_geometry_hash', 'labelspace_hash'):
            digest(getattr(self, name), name)
        recipe, separator, model_hash = self.detector_profile_id.rpartition('@sha256:')
        if not separator or not recipe:
            raise ValueError('detector profile is missing its checkpoint pin')
        digest(model_hash, 'detector profile checkpoint')
        for name in ('capture_monotonic_ns', 'pose_version', 'sidecar_revision'):
            object.__setattr__(self, name, integer(getattr(self, name), name))
        if self.coordinate_convention != 'canonical_z_up_v1' or type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('unsupported graph token convention or schema')

    @property
    def detector_hash(self):
        return self.detector_profile_id.rsplit('@sha256:', 1)[1]


@dataclass(frozen=True)
class DetectionGeometry:
    evidence: ObservationEvidence
    category: str
    geometry_sha256: str
    bounds: tuple[tuple[float, ...], tuple[float, ...]]
    labelspace_hash: str

    def __post_init__(self):
        if not isinstance(self.evidence, ObservationEvidence):
            raise TypeError('expected ObservationEvidence')
        text(self.category, 'category')
        digest(self.geometry_sha256, 'geometry_sha256')
        digest(self.labelspace_hash, 'labelspace_hash')
        object.__setattr__(self, 'bounds', _bounds(self.bounds))


@dataclass(frozen=True)
class NativeObjectGeometry:
    ref: NativeNodeRef
    category: str
    bounds: tuple[tuple[float, ...], tuple[float, ...]]

    def __post_init__(self):
        if not isinstance(self.ref, NativeNodeRef) or self.ref.layer_id != 2:
            raise ValueError('object geometry must bind a native object')
        text(self.category, 'category')
        object.__setattr__(self, 'bounds', _bounds(self.bounds))


@dataclass(frozen=True)
class NativeLink:
    token: GraphReadToken
    detector_hash: str
    detection_id: str
    status: str
    endpoint: NativeNodeRef | None = None
    overlap: float | None = None
    competing: tuple[NativeNodeRef, ...] = ()
    policy_version: str = 'rgbd_aabb_overlap_v1'
    competing_detections: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.token, GraphReadToken):
            raise TypeError('expected GraphReadToken')
        digest(self.detector_hash, 'detector_hash')
        if len(text(self.detection_id, 'detection_id')) > 256:
            raise ValueError('detection_id is too long')
        choice(self.status, {'geometric_candidate', 'ambiguous', 'no_support', 'unavailable'}, 'status')
        if self.status != 'unavailable' and self.detector_hash != self.token.detector_hash:
            raise ValueError('supported link requires the accepted detector checkpoint')
        competitors = tuple(self.competing)
        endpoints = competitors + (() if self.endpoint is None else (self.endpoint,))
        if len(competitors) > 32 or any(not isinstance(ref, NativeNodeRef) or ref.layer_id != 2
                                       or ref.token != self.token.native for ref in endpoints):
            raise ValueError('link endpoints must bind the exact object revision')
        if len(competitors) == 1 or len(set(competitors)) != len(competitors):
            raise ValueError('invalid competing endpoints')
        detection_conflicts = tuple(self.competing_detections)
        if (len(detection_conflicts) > 32
                or any(len(text(item, 'competing detection_id')) > 256 or item == self.detection_id
                       for item in detection_conflicts)
                or len(set(detection_conflicts)) != len(detection_conflicts)):
            raise ValueError('invalid competing detections')
        if ((self.status == 'geometric_candidate') != (self.endpoint is not None)
                or (self.status in ('geometric_candidate', 'ambiguous')) != (self.overlap is not None)
                or (self.status == 'ambiguous') != bool(len(competitors) >= 2 or detection_conflicts)):
            raise ValueError('status disagrees with link support')
        if self.overlap is not None:
            score = finite(self.overlap, 'overlap')
            if not 0 <= score <= 1:
                raise ValueError('overlap must be in [0, 1]')
            object.__setattr__(self, 'overlap', score)
        object.__setattr__(self, 'competing', competitors)
        object.__setattr__(self, 'competing_detections', detection_conflicts)
        choice(self.policy_version, {'rgbd_aabb_overlap_v1', 'rgbd_aabb_frame_unique_v1'}, 'link recipe')

    @property
    def canonical_id(self):
        """A geometric candidate carries no native identity continuity."""
        return None


@dataclass(frozen=True)
class GraphLifecycleDelta:
    previous: GraphReadToken | None
    current: GraphReadToken
    requires_rebase: bool
    status: str = 'revision_only'
    aliases: tuple = ()


@dataclass(frozen=True)
class FeatureSpec:
    feature_space_id: str
    model_sha256: str
    preprocessing_sha256: str
    dimension: int
    modality: str
    dtype: str = 'float32'
    normalized: bool = True

    def __post_init__(self):
        text(self.feature_space_id, 'feature_space_id')
        digest(self.model_sha256, 'model_sha256')
        digest(self.preprocessing_sha256, 'preprocessing_sha256')
        size = integer(self.dimension, 'dimension', minimum=1)
        if size > 65_536 or type(self.normalized) is not bool:
            raise ValueError('invalid feature dimensions or flags')
        object.__setattr__(self, 'dimension', size)
        choice(self.modality, {'image', 'text', 'object', 'room'}, 'modality')
        choice(self.dtype, {'float32', 'float16'}, 'dtype')


@dataclass(frozen=True)
class FeatureRef:
    spec: FeatureSpec
    relative_key: str
    sha256: str
    nbytes: int

    def __post_init__(self):
        if not isinstance(self.spec, FeatureSpec):
            raise TypeError('expected FeatureSpec')
        key = PurePosixPath(text(self.relative_key, 'relative_key'))
        if key.is_absolute() or not key.name or '..' in key.parts or '\\' in self.relative_key:
            raise ValueError('feature key must be a relative POSIX path')
        digest(self.sha256, 'sha256')
        size = integer(self.nbytes, 'nbytes', minimum=1)
        if size != self.spec.dimension * (4 if self.spec.dtype == 'float32' else 2):
            raise ValueError('feature length does not match the spec')
        object.__setattr__(self, 'nbytes', size)
