"""Lossless, source-bound adapter from canonical Observation to Rebuild M1 input.

This module has no dependency on the external standalone_sg namespace. The
worker reconstructs its own RGBDFrame and FramePacket from the wire envelope.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import numpy as np

from ..contracts import Observation, require_rgbd


@dataclass(frozen=True)
class RebuildRGBDConfig:
    resolution_m: float = 0.05
    backprojection_stride: int = 1
    min_depth_m: float = 0.1
    max_depth_m: float = 10.0
    max_range_m: float = 5.0
    pose_source: str = "simulator_ground_truth"

    def __post_init__(self):
        for name in ("resolution_m", "min_depth_m", "max_depth_m", "max_range_m"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.resolution_m <= 0 or self.min_depth_m < 0 or self.max_depth_m <= self.min_depth_m or self.max_range_m <= 0:
            raise ValueError("invalid Rebuild mapping resolution or range")
        if type(self.backprojection_stride) is not int or self.backprojection_stride < 1:
            raise ValueError("backprojection_stride must be a positive integer")
        if self.pose_source != "simulator_ground_truth":
            raise ValueError("this profile requires explicitly declared simulator_ground_truth pose")


@dataclass(frozen=True)
class RebuildRGBDFrame:
    """Owned normalized arrays plus immutable provenance for one admitted frame."""

    scene_id: str
    sequence_id: str
    sensor_id: str
    frame_id: str
    frame_index: int
    timestamp_s: float
    capture_monotonic_ns: int
    clock_domain: str
    calibration_id: str
    pose_version: int
    geometry_sha256: str
    prefix_sha256: str
    rgb: np.ndarray
    depth_m: np.ndarray
    valid_depth: np.ndarray
    source_depth_m: np.ndarray
    source_valid_depth: np.ndarray
    no_return_mask: np.ndarray | None
    far_plane_mask: np.ndarray | None
    no_return_range_m: float | None
    far_plane_range_m: float | None
    K: np.ndarray
    T_world_camera: np.ndarray
    config: RebuildRGBDConfig

    def to_wire(self) -> dict[str, Any]:
        """Return JSON-compatible arrays with explicit dtype/shape and SHA-256."""
        arrays = {}
        for name in ("rgb", "depth_m", "valid_depth", "K", "T_world_camera"):
            value = getattr(self, name)
            canonical = value.astype(value.dtype.newbyteorder("<"), copy=False)
            raw = canonical.tobytes(order="C")
            arrays[name] = {
                "dtype": canonical.dtype.str,
                "shape": list(canonical.shape),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data": base64.b64encode(raw).decode("ascii"),
            }
        for name in ("source_depth_m", "source_valid_depth"):
            value = getattr(self, name)
            canonical = value.astype(value.dtype.newbyteorder("<"), copy=False)
            raw = canonical.tobytes(order="C")
            arrays[name] = {
                "dtype": canonical.dtype.str, "shape": list(canonical.shape),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data": base64.b64encode(raw).decode("ascii"),
            }
        for name in ("no_return_mask", "far_plane_mask"):
            value = getattr(self, name)
            if value is None:
                continue
            canonical = value.astype(value.dtype.newbyteorder("<"), copy=False)
            raw = canonical.tobytes(order="C")
            arrays[name] = {
                "dtype": canonical.dtype.str, "shape": list(canonical.shape),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data": base64.b64encode(raw).decode("ascii"),
            }
        return {
            "wire_version": 1,
            "frame": {
                "scene_id": self.scene_id, "sequence_id": self.sequence_id,
                "sensor_id": self.sensor_id,
                "frame_id": self.frame_id, "frame_index": self.frame_index,
                "timestamp_s": self.timestamp_s,
                "capture_monotonic_ns": self.capture_monotonic_ns,
                "clock_domain": self.clock_domain,
                "calibration_id": self.calibration_id,
                "pose_version": self.pose_version,
                "geometry_sha256": self.geometry_sha256,
                "prefix_sha256": self.prefix_sha256,
                "pose_source": self.config.pose_source,
                "coordinate_convention": "canonical_z_up_optical_v1",
                "depth_units": "m", "depth_representation": "axial",
                "source_masks_present": {
                    "no_return": self.no_return_mask is not None,
                    "far_plane": self.far_plane_mask is not None,
                },
                "no_return_range_m": self.no_return_range_m,
                "far_plane_range_m": self.far_plane_range_m,
            },
            "mapping": {
                "resolution_m": self.config.resolution_m,
                "backprojection_stride": self.config.backprojection_stride,
                "min_depth_m": self.config.min_depth_m,
                "max_depth_m": self.config.max_depth_m,
                "max_range_m": self.config.max_range_m,
                "depth_scale_to_m": 1.0,
            },
            "arrays": arrays,
        }

    def wire_bytes(self) -> bytes:
        """Canonical JSON bytes used for exact admission-size accounting."""
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")


class RebuildRGBDInputAdapter:
    """Validate episode ordering and convert one canonical primary RGB-D source."""

    def __init__(self, config: RebuildRGBDConfig = RebuildRGBDConfig()):
        if not isinstance(config, RebuildRGBDConfig):
            raise ValueError("config must be RebuildRGBDConfig")
        self.config = config
        self._episode: str | None = None
        self._sensor: str | None = None
        self._calibration: str | None = None
        self._clock_domain: str | None = None
        self._last_index = -1
        self._last_capture_ns = -1
        self._last_sim_time_s = -math.inf
        self._seen: set[int] = set()
        self._prefix = bytes(32)

    def adapt(self, observation: Observation) -> RebuildRGBDFrame:
        require_rgbd(observation)
        key = observation.key
        if self._episode is not None and key.episode_id != self._episode:
            raise ValueError("new episode requires a new Rebuild RGB-D adapter")
        if key.frame_index in self._seen or key.frame_index <= self._last_index:
            raise ValueError("duplicate or out-of-order Rebuild RGB-D frame")
        if observation.capture_monotonic_ns < self._last_capture_ns or observation.sim_time_s < self._last_sim_time_s:
            raise ValueError("Rebuild RGB-D source time moved backwards")
        if self._sensor is not None and key.sensor_id != self._sensor:
            raise ValueError("Rebuild room pipeline accepts one primary RGB-D sensor per episode")
        if self._calibration is not None and observation.calibration_id != self._calibration:
            raise ValueError("calibration changed within Rebuild RGB-D episode")
        if self._clock_domain is not None and observation.clock_domain != self._clock_domain:
            raise ValueError("clock domain changed within Rebuild RGB-D episode")
        for name in ("no_return", "far_plane"):
            mask = getattr(observation, name)
            if mask is not None and np.any(mask):
                raise ValueError(f"selected Rebuild M1 source path cannot preserve certified {name} rays")

        source_valid = np.asarray(observation.valid_depth, dtype=np.bool_).copy()
        source_depth = np.asarray(observation.depth_m, dtype=np.float32).copy()
        valid = source_valid.copy()
        depth = source_depth.copy()
        valid &= np.isfinite(depth) & (depth >= self.config.min_depth_m) & (depth <= self.config.max_depth_m)
        depth[~valid] = np.nan
        rgb = np.array(observation.rgb, dtype=np.uint8, copy=True)
        intrinsics = np.array(observation.K, dtype=np.float64, copy=True)
        pose = np.array(observation.T_world_camera, dtype=np.float64, copy=True)
        no_return = None if observation.no_return is None else np.array(observation.no_return, dtype=np.bool_, copy=True)
        far_plane = None if observation.far_plane is None else np.array(observation.far_plane, dtype=np.bool_, copy=True)
        for value in (valid, depth, source_valid, source_depth, rgb, intrinsics, pose, no_return, far_plane):
            if value is None:
                continue
            value.setflags(write=False)

        identity = f"{key.episode_id}\0{key.sensor_id}\0{key.frame_index}".encode("utf-8")
        frame_id = hashlib.sha256(identity).hexdigest()
        next_prefix = hashlib.sha256(self._prefix + bytes.fromhex(observation.geometry_hash)).digest()
        result = RebuildRGBDFrame(
            scene_id=key.episode_id, sequence_id=key.episode_id,
            sensor_id=key.sensor_id,
            frame_id=frame_id, frame_index=key.frame_index,
            timestamp_s=observation.sim_time_s,
            capture_monotonic_ns=observation.capture_monotonic_ns,
            clock_domain=observation.clock_domain,
            calibration_id=observation.calibration_id, pose_version=observation.pose_version,
            geometry_sha256=observation.geometry_hash, prefix_sha256=next_prefix.hex(),
            rgb=rgb, depth_m=depth, valid_depth=valid, K=intrinsics,
            source_depth_m=source_depth, source_valid_depth=source_valid,
            no_return_mask=no_return, far_plane_mask=far_plane,
            no_return_range_m=observation.no_return_range_m,
            far_plane_range_m=observation.far_plane_range_m,
            T_world_camera=pose, config=self.config,
        )
        self._episode, self._sensor = key.episode_id, key.sensor_id
        self._calibration, self._clock_domain = observation.calibration_id, observation.clock_domain
        self._last_index, self._last_capture_ns = key.frame_index, observation.capture_monotonic_ns
        self._last_sim_time_s = observation.sim_time_s
        self._seen.add(key.frame_index)
        self._prefix = next_prefix
        return result
