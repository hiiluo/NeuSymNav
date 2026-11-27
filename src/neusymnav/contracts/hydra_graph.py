"""CPU-only Hydra input contracts; native Hydra is imported only by workers."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np

from ._base import Contract, array, choice, coordinates, digest, finite, integer, text
from ..geometry.frames import CANONICAL_Z_UP, validate_intrinsics, validate_pose
from .observations import FrameKey, age_ns

OPTICAL_CAMERA = 'optical_x_right_y_down_z_forward_v1'
METRIC_AXIAL_DEPTH = 'metric_axial_v1'


def _rotation_to_quaternion_wxyz(rotation: np.ndarray) -> np.ndarray:
    """Convert a proper rotation matrix to normalized Eigen-compatible wxyz."""
    r = np.asarray(rotation, dtype=np.float64)
    trace = float(np.trace(r))
    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0
        q = np.array([0.25 * s, (r[2, 1] - r[1, 2]) / s,
                      (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s])
    else:
        index = int(np.argmax(np.diag(r)))
        if index == 0:
            s = np.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
            q = np.array([(r[2, 1] - r[1, 2]) / s, 0.25 * s,
                          (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s])
        elif index == 1:
            s = np.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
            q = np.array([(r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s,
                          0.25 * s, (r[1, 2] + r[2, 1]) / s])
        else:
            s = np.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
            q = np.array([(r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s,
                          (r[1, 2] + r[2, 1]) / s, 0.25 * s])
    q /= np.linalg.norm(q)
    if q[0] < 0.0:
        q *= -1.0
    return q


@dataclass(frozen=True)
class HydraCalibration(Contract):
    """Static camera calibration with ``body_T_camera`` in metres.

    ``pose_version`` records the simulator pose at calibration acquisition.
    Per-frame pose versions advance with body motion and belong to HydraFrame;
    a physical mount change requires a new calibration ID/hash.
    """

    calibration_id: str
    version: str
    sensor_id: str
    camera_name: str
    K: np.ndarray
    body_T_camera: np.ndarray
    pose_version: int
    coordinate_convention: str
    camera_convention: str
    depth_convention: str
    provenance: str

    def __post_init__(self):
        text(self.calibration_id, 'calibration_id')
        text(self.version, 'version')
        text(self.sensor_id, 'sensor_id')
        text(self.camera_name, 'camera_name')
        integer(self.pose_version, 'pose_version')
        choice(self.coordinate_convention, {CANONICAL_Z_UP}, 'coordinate_convention')
        choice(self.camera_convention, {OPTICAL_CAMERA}, 'camera_convention')
        choice(self.depth_convention, {METRIC_AXIAL_DEPTH}, 'depth_convention')
        text(self.provenance, 'provenance')
        k = array(self.K, 'K', dtype=np.float64, shape=(3, 3))
        extrinsics = array(self.body_T_camera, 'body_T_camera', dtype=np.float64, shape=(4, 4))
        validate_intrinsics(k)
        validate_pose(extrinsics)
        object.__setattr__(self, 'K', k)
        object.__setattr__(self, 'body_T_camera', extrinsics)

    @property
    def calibration_hash(self) -> str:
        sha = hashlib.sha256(b'NeuSymNav:hydra-calibration:v1\0')
        metadata = {'calibration_id': self.calibration_id, 'version': self.version,
                    'sensor_id': self.sensor_id, 'camera_name': self.camera_name,
                    'pose_version': self.pose_version,
                    'coordinate_convention': self.coordinate_convention,
                    'camera_convention': self.camera_convention,
                    'depth_convention': self.depth_convention, 'provenance': self.provenance}
        sha.update(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode())
        for name in ('K', 'body_T_camera'):
            value = getattr(self, name).astype('<f8', copy=False)
            sha.update(name.encode() + b'\0')
            sha.update(json.dumps(list(value.shape), separators=(',', ':')).encode() + b'\0')
            sha.update(value.tobytes(order='C'))
        return sha.hexdigest()


@dataclass(frozen=True)
class HydraFrame(Contract):
    """Immutable, provenance-bound RGB-D and pose packet for the Hydra child."""

    source_key: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    sim_time_s: float
    source_geometry_hash: str
    calibration_id: str
    calibration_version: str
    calibration_hash: str
    detector_profile_id: str
    vocabulary_id: str
    pose_version: int
    coordinate_convention: str
    camera_convention: str
    depth_convention: str
    rgb: np.ndarray
    depth_m: np.ndarray
    valid_depth: np.ndarray
    labels: np.ndarray
    K: np.ndarray
    body_T_camera: np.ndarray
    world_T_body: np.ndarray
    world_t_body: np.ndarray
    world_R_body_wxyz: np.ndarray
    labelspace_id: str
    labelspace_hash: str
    no_return: np.ndarray | None = None
    far_plane: np.ndarray | None = None
    no_return_range_m: float | None = None
    far_plane_range_m: float | None = None

    def __post_init__(self):
        if not isinstance(self.source_key, FrameKey):
            raise ValueError('source_key must be FrameKey')
        integer(self.capture_monotonic_ns, 'capture_monotonic_ns')
        text(self.clock_domain, 'clock_domain')
        finite(self.sim_time_s, 'sim_time_s', 0)
        digest(self.source_geometry_hash, 'source_geometry_hash')
        text(self.calibration_id, 'calibration_id')
        text(self.calibration_version, 'calibration_version')
        digest(self.calibration_hash, 'calibration_hash')
        text(self.detector_profile_id, 'detector_profile_id')
        text(self.vocabulary_id, 'vocabulary_id')
        text(self.labelspace_id, 'labelspace_id')
        digest(self.labelspace_hash, 'labelspace_hash')
        integer(self.pose_version, 'pose_version')
        choice(self.coordinate_convention, {CANONICAL_Z_UP}, 'coordinate_convention')
        choice(self.camera_convention, {OPTICAL_CAMERA}, 'camera_convention')
        choice(self.depth_convention, {METRIC_AXIAL_DEPTH}, 'depth_convention')

        rgb = array(self.rgb, 'rgb', dtype=np.uint8, shape=(None, None, 3))
        if not rgb.shape[0] or not rgb.shape[1]:
            raise ValueError('RGB dimensions must be nonempty')
        shape = rgb.shape[:2]
        depth = array(self.depth_m, 'depth_m', dtype=np.float32, shape=shape, finite_only=False)
        valid = array(self.valid_depth, 'valid_depth', dtype=np.bool_, shape=shape)
        labels = array(self.labels, 'labels', dtype=np.int32, shape=shape)
        if np.any(valid & (~np.isfinite(depth) | (depth <= 0))):
            raise ValueError('valid_depth must refer to finite positive metric depth')
        if np.any(~valid & ~np.isnan(depth)):
            raise ValueError('invalid Hydra depth samples must use NaN sentinel')
        if np.any(labels < 0):
            raise ValueError('labels must be nonnegative semantic indices')
        k = array(self.K, 'K', dtype=np.float64, shape=(3, 3))
        body_T_camera = array(self.body_T_camera, 'body_T_camera', dtype=np.float64, shape=(4, 4))
        world_T_body = array(self.world_T_body, 'world_T_body', dtype=np.float64, shape=(4, 4))
        world_t_body = array(self.world_t_body, 'world_t_body', dtype=np.float64, shape=(3,))
        world_q = array(self.world_R_body_wxyz, 'world_R_body_wxyz', dtype=np.float64, shape=(4,))
        validate_intrinsics(k)
        validate_pose(body_T_camera)
        validate_pose(world_T_body)
        if not np.allclose(world_t_body, world_T_body[:3, 3], rtol=0, atol=1e-10):
            raise ValueError('world_t_body disagrees with world_T_body')
        expected_q = _rotation_to_quaternion_wxyz(world_T_body[:3, :3])
        if not np.allclose(world_q, expected_q, rtol=0, atol=1e-10):
            raise ValueError('world_R_body_wxyz must match world_T_body in wxyz order')
        for name, value in [('rgb', rgb), ('depth_m', depth), ('valid_depth', valid),
                            ('labels', labels), ('K', k), ('body_T_camera', body_T_camera),
                            ('world_T_body', world_T_body), ('world_t_body', world_t_body),
                            ('world_R_body_wxyz', world_q)]:
            object.__setattr__(self, name, value)

        certificates = []
        for name, range_name in [('no_return', 'no_return_range_m'), ('far_plane', 'far_plane_range_m')]:
            mask, certified_range = getattr(self, name), getattr(self, range_name)
            if mask is not None:
                mask = array(mask, name, dtype=np.bool_, shape=shape)
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

    def validate_now(self, now_ns: int, now_domain: str) -> int:
        """Return age only in the original capture clock; reject skew/future."""
        return age_ns(self.capture_monotonic_ns, self.clock_domain, now_ns, now_domain)


def validate_hydra_frame_order(previous: HydraFrame, current: HydraFrame) -> None:
    """Enforce one primary source stream while permitting intentional frame gaps.

    The H4 worker/session calls this before accepting a frame. Keeping the rule
    here makes ordering testable without importing or starting native Hydra.
    """
    if not isinstance(previous, HydraFrame) or not isinstance(current, HydraFrame):
        raise ValueError('sequence members must be HydraFrame')
    if (previous.source_key.episode_id != current.source_key.episode_id or
            previous.source_key.sensor_id != current.source_key.sensor_id):
        raise ValueError('Hydra frame source episode/sensor changed')
    if previous.clock_domain != current.clock_domain:
        raise ValueError('Hydra frame clock domain changed')
    if current.source_key.frame_index <= previous.source_key.frame_index:
        raise ValueError('Hydra frame sequence must be strictly increasing')
    if current.capture_monotonic_ns <= previous.capture_monotonic_ns:
        raise ValueError('Hydra capture timestamps must be strictly increasing')


@dataclass(frozen=True)
class HydraReadToken:
    """Address one native graph publication within a worker generation."""

    episode_id: str
    run_id: str
    graph_revision: int
    input_prefix_sha256: str
    world_epoch: str | None = None
    source_sha256: str | None = None
    build_sha256: str | None = None
    config_sha256: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        text(self.episode_id, 'episode_id')
        text(self.run_id, 'run_id')
        object.__setattr__(self, 'graph_revision', integer(self.graph_revision, 'graph_revision'))
        digest(self.input_prefix_sha256, 'input_prefix_sha256')
        if self.world_epoch is not None:
            text(self.world_epoch, 'world_epoch')
        revision = self.source_sha256
        if revision is not None and (not isinstance(revision, str) or len(revision) not in (40, 64)
                                     or any(c not in '0123456789abcdef' for c in revision)):
            raise ValueError('source_sha256 must be a lowercase Git object ID or SHA-256')
        for name in ('build_sha256', 'config_sha256'):
            value = getattr(self, name)
            if value is not None:
                digest(value, name)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('unsupported Hydra read token version')


@dataclass(frozen=True)
class NativeNodeRef:
    token: HydraReadToken
    native_id: str
    layer_id: int

    def __post_init__(self):
        if not isinstance(self.token, HydraReadToken):
            raise TypeError('expected a Hydra read token')
        text(self.native_id, 'native_id')
        layer = integer(self.layer_id, 'layer_id')
        if len(self.native_id) > 256 or layer > 7:
            raise ValueError('invalid native node identity')
        object.__setattr__(self, 'layer_id', layer)


@dataclass(frozen=True)
class HydraReadResult:
    status: str
    value: object = None
    reason: str | None = None

    def __post_init__(self):
        choice(self.status, {'available', 'missing', 'not_recorded', 'ambiguous',
                             'stale', 'evicted', 'corrupt', 'unavailable', 'pending'}, 'status')
        if (self.status == 'available') != (self.value is not None):
            raise ValueError('only available reads carry a value')


@dataclass(frozen=True)
class HydraPage:
    items: tuple
    next_cursor: str | None = None


@dataclass(frozen=True)
class NativeDetailRequest:
    node: NativeNodeRef
    kind: str
    offset: int = 0
    limit: int = 64
    target: NativeNodeRef | None = None

    def __post_init__(self):
        choice(self.kind, {'attributes', 'bbox', 'mesh', 'feature', 'edge'}, 'kind')
        if not isinstance(self.node, NativeNodeRef):
            raise TypeError('expected a native node reference')
        offset, limit = integer(self.offset, 'offset'), integer(self.limit, 'limit')
        if offset > 10_000_000 or not 1 <= limit <= 64:
            raise ValueError('detail range exceeds the page cap')
        object.__setattr__(self, 'offset', offset)
        object.__setattr__(self, 'limit', limit)
        if self.kind == 'edge':
            if not isinstance(self.target, NativeNodeRef) or self.target.token != self.node.token:
                raise ValueError('edge endpoints must bind the same graph token')
        elif self.target is not None:
            raise ValueError('only edge reads take a target')

    def to_wire(self) -> dict:
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_wire(cls, value):
        def ref(raw):
            return NativeNodeRef(HydraReadToken(**raw['token']), raw['native_id'], raw['layer_id'])

        return cls(ref(value['node']), value['kind'], value['offset'], value['limit'],
                   None if value['target'] is None else ref(value['target']))
