"""Measured, bounded robot samples for display only; never control input."""
from collections import deque
from dataclasses import dataclass
import math
import threading

import numpy as np

from ..contracts import FrameKey

MAX_TRAIL = 1024


@dataclass(frozen=True, slots=True)
class RobotSample:
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    pose_version: int
    xy: tuple[float, float]
    yaw_rad: float

    def __post_init__(self):
        if (not isinstance(self.source, FrameKey) or type(self.capture_monotonic_ns) is not int
                or self.capture_monotonic_ns < 0 or type(self.pose_version) is not int or self.pose_version < 0
                or not isinstance(self.clock_domain, str) or not self.clock_domain
                or type(self.xy) is not tuple or len(self.xy) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*self.xy, self.yaw_rad))):
            raise ValueError('invalid measured robot sample')


@dataclass(frozen=True, slots=True)
class CameraCone:
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    pose_version: int
    calibration_id: str
    xy: tuple[float, float]
    edge_yaws: tuple[float, float]

    def __post_init__(self):
        RobotSample(self.source, self.capture_monotonic_ns, self.clock_domain, self.pose_version, self.xy, 0.)
        if (not isinstance(self.calibration_id, str) or not 0 < len(self.calibration_id) <= 512
                or type(self.edge_yaws) is not tuple or len(self.edge_yaws) != 2
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in self.edge_yaws)):
            raise ValueError('invalid calibrated camera cone')


@dataclass(frozen=True, slots=True)
class CameraProjection:
    """Rigid planar camera schematic at a measured body pose, not RGB pixels."""
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    pose_version: int
    calibration_id: str
    xy: tuple[float, float]
    edge_yaws: tuple[float, float]
    calibration_source: FrameKey
    calibration_capture_monotonic_ns: int
    calibration_clock_domain: str
    calibration_pose_version: int
    policy: str = 'rigid_planar_from_paired_rgb_v1'

    def __post_init__(self):
        CameraCone(self.source,self.capture_monotonic_ns,self.clock_domain,self.pose_version,
                   self.calibration_id,self.xy,self.edge_yaws)
        if (not isinstance(self.calibration_source,FrameKey)
                or self.calibration_source.episode_id!=self.source.episode_id
                or self.calibration_clock_domain!=self.clock_domain
                or type(self.calibration_capture_monotonic_ns) is not int
                or not 0<=self.calibration_capture_monotonic_ns<=self.capture_monotonic_ns
                or type(self.calibration_pose_version) is not int
                or not 0<=self.calibration_pose_version<=self.pose_version
                or self.policy!='rigid_planar_from_paired_rgb_v1'):
            raise ValueError('invalid rigid camera projection provenance')


@dataclass(frozen=True, slots=True)
class RobotTrack:
    samples: tuple[RobotSample, ...]
    camera: CameraCone | CameraProjection | None = None
    truncated: bool = False

    def __post_init__(self):
        if (type(self.samples) is not tuple or not 0 < len(self.samples) <= MAX_TRAIL
                or any(not isinstance(s, RobotSample) for s in self.samples) or type(self.truncated) is not bool):
            raise ValueError('invalid bounded robot trail')
        last = self.samples[-1]
        for a, b in zip(self.samples, self.samples[1:]):
            if (a.source.episode_id != b.source.episode_id or a.source.sensor_id != b.source.sensor_id
                    or a.clock_domain != b.clock_domain or a.source.frame_index >= b.source.frame_index
                    or a.capture_monotonic_ns >= b.capture_monotonic_ns or a.pose_version > b.pose_version):
                raise ValueError('robot trail source/order mismatch')
        if self.camera is not None:
            c = self.camera
            if (not isinstance(c, (CameraCone,CameraProjection)) or c.source.episode_id != last.source.episode_id
                    or c.clock_domain != last.clock_domain or c.pose_version != last.pose_version
                    or c.capture_monotonic_ns > last.capture_monotonic_ns):
                raise ValueError('camera/body source mismatch')
            if isinstance(c,CameraProjection) and (c.source,c.capture_monotonic_ns)!=(last.source,last.capture_monotonic_ns):
                raise ValueError('projected camera must match current measured body source')


class RobotTrailBuffer:
    """Capture-side append never waits for publication/rendering or does I/O."""
    def __init__(self):
        self._lock = threading.Lock()
        self._records = deque(maxlen=MAX_TRAIL)
        self._truncated = False
        self._mount = None

    def observe(self, rgb, nav, pose):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if (pose['source'], pose['capture_monotonic_ns'], pose['clock_domain'], pose['pose_version']) != (
                    nav.key, nav.capture_monotonic_ns, nav.clock_domain, nav.pose_version):
                raise ValueError('display body proof source mismatch')
            sample = RobotSample(nav.key, nav.capture_monotonic_ns, nav.clock_domain,
                                 nav.pose_version, tuple(pose['robot_xy']), pose['yaw_rad'])
            if self._records:
                old = self._records[-1][0]
                if (old.source.episode_id, old.clock_domain) != (sample.source.episode_id, sample.clock_domain):
                    self._records.clear(); self._truncated = False; self._mount = None
                elif (old.source.sensor_id != sample.source.sensor_id
                      or old.source.frame_index >= sample.source.frame_index
                      or old.capture_monotonic_ns >= sample.capture_monotonic_ns or old.pose_version > sample.pose_version):
                    raise ValueError('display body proof replay/order mismatch')
            camera = None
            if rgb is not None:self._mount=None
            if (rgb is not None and rgb.key.episode_id == nav.key.episode_id and rgb.clock_domain == nav.clock_domain
                    and rgb.pose_version == nav.pose_version and rgb.capture_monotonic_ns <= nav.capture_monotonic_ns):
                rays = [rgb.T_world_camera[:2, :3] @ np.array([(x-float(rgb.K[0, 2]))/float(rgb.K[0, 0]), 0., 1.])
                        for x in (-.5, rgb.rgb.shape[1]-.5)]
                # A vertical camera has no well-defined horizontal viewing sector.
                if np.linalg.norm(rgb.T_world_camera[:2, 2]) > 1e-6 and all(np.linalg.norm(r) > 1e-6 for r in rays):
                    camera = CameraCone(rgb.key, rgb.capture_monotonic_ns, rgb.clock_domain, rgb.pose_version,
                        rgb.calibration_id, tuple(float(v) for v in rgb.T_world_camera[:2, 3]),
                        tuple(math.atan2(float(r[1]), float(r[0])) for r in rays))
                    dx,dy=camera.xy[0]-sample.xy[0],camera.xy[1]-sample.xy[1]
                    c,s=math.cos(sample.yaw_rad),math.sin(sample.yaw_rad)
                    self._mount=(camera,(c*dx+s*dy,-s*dx+c*dy),
                                 tuple(a-sample.yaw_rad for a in camera.edge_yaws))
            if camera is None and self._mount is not None:
                calibrated,offset,angles=self._mount
                c,s=math.cos(sample.yaw_rad),math.sin(sample.yaw_rad)
                camera=CameraProjection(sample.source,sample.capture_monotonic_ns,sample.clock_domain,
                    sample.pose_version,calibrated.calibration_id,
                    (sample.xy[0]+c*offset[0]-s*offset[1],sample.xy[1]+s*offset[0]+c*offset[1]),
                    tuple(sample.yaw_rad+a for a in angles),calibrated.source,
                    calibrated.capture_monotonic_ns,calibrated.clock_domain,calibrated.pose_version)
            self._truncated = self._truncated or len(self._records) == MAX_TRAIL
            self._records.append((sample, camera))
        finally:
            self._lock.release()

    def for_nav(self, nav):
        if nav is None:
            return None
        with self._lock:
            rows = tuple(self._records); truncated = self._truncated
        for i in range(len(rows)-1, -1, -1):
            s, camera = rows[i]
            if (s.source, s.capture_monotonic_ns, s.clock_domain) == (nav.source, nav.capture_monotonic_ns, nav.clock_domain):
                return RobotTrack(tuple(row[0] for row in rows[:i+1]), camera, truncated)
        return None
