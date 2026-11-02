"""Contracts for Rebuild's geometry map and its bound M5 publication.

These maps are deliberately separate from :class:`NavSnapshot`: an M3
structural projection has no robot-clearance certificate and must never be
used as a control map by implication.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

from ._base import Contract, array, boolean, coordinates, digest, finite, integer, text
from .graphs import RegionSnapshot, _raster
from .observations import FrameKey, _key


@dataclass(frozen=True)
class RoomMapSnapshot(Contract):
    """Immutable M3 output, bound to its episode and original source frame."""

    episode_id: str
    map_domain_id: str
    revision: int
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    calibration_id: str
    prefix_sha256: str
    resolution_m: float
    origin_xy: tuple[float, float]
    states: np.ndarray
    z_floor_m: np.ndarray
    z_ceiling_m: np.ndarray
    floor_valid: np.ndarray
    ceiling_valid: np.ndarray
    m2_revision: int
    m3_revision: int
    source_hash: str
    worker_sha256: str
    region_worker_sha256: str
    config_sha256: str

    def __post_init__(self):
        text(self.episode_id, "episode_id")
        text(self.map_domain_id, "map_domain_id")
        _key(self.source)
        if self.source.episode_id != self.episode_id:
            raise ValueError("room map source belongs to a different episode")
        integer(self.revision, "revision")
        integer(self.capture_monotonic_ns, "capture_monotonic_ns")
        text(self.clock_domain, "clock_domain")
        text(self.calibration_id, "calibration_id")
        for name in ("prefix_sha256", "source_hash", "worker_sha256", "region_worker_sha256", "config_sha256"):
            digest(getattr(self, name), name)
        resolution = finite(self.resolution_m, "resolution_m")
        if resolution <= 0:
            raise ValueError("resolution_m must be positive")
        object.__setattr__(self, "origin_xy", coordinates(self.origin_xy, 2, "origin_xy"))
        states = _raster(self.states, "states")
        object.__setattr__(self, "states", states)
        shape = states.shape
        floor = array(self.z_floor_m, "z_floor_m", dtype=np.float64, shape=shape, finite_only=False)
        ceiling = array(self.z_ceiling_m, "z_ceiling_m", dtype=np.float64, shape=shape, finite_only=False)
        floor_valid = array(self.floor_valid, "floor_valid", dtype=np.bool_, shape=shape)
        ceiling_valid = array(self.ceiling_valid, "ceiling_valid", dtype=np.bool_, shape=shape)
        if np.any(floor_valid & ~np.isfinite(floor)) or np.any(~floor_valid & ~np.isnan(floor)):
            raise ValueError("z_floor_m must be finite exactly where floor_valid is true")
        if np.any(ceiling_valid & ~np.isfinite(ceiling)) or np.any(~ceiling_valid & ~np.isnan(ceiling)):
            raise ValueError("z_ceiling_m must be finite exactly where ceiling_valid is true")
        if np.any((floor_valid | ceiling_valid) & (states == -1)):
            raise ValueError("unknown M3 cells cannot carry height evidence")
        if np.any(ceiling_valid & floor_valid & (ceiling <= floor)):
            raise ValueError("valid ceiling must be above valid floor")
        object.__setattr__(self, "z_floor_m", floor)
        object.__setattr__(self, "z_ceiling_m", ceiling)
        object.__setattr__(self, "floor_valid", floor_valid)
        object.__setattr__(self, "ceiling_valid", ceiling_valid)
        integer(self.m2_revision, "m2_revision")
        integer(self.m3_revision, "m3_revision")
        if self.m2_revision != self.m3_revision or self.revision != self.m3_revision:
            raise ValueError("room map and M2/M3 revisions must identify the same accepted update")


@dataclass(frozen=True)
class RoomPipelinePublication(Contract):
    """Latest M3 plus the retained exact M3/M5 pair accepted by the source."""

    episode_id: str
    map_domain_id: str
    request_revision: int
    latest_map: RoomMapSnapshot
    accepted_map_revision: int | None
    regions: RegionSnapshot | None
    m5_revision: int | None
    regions_stale: bool
    replay_required: bool
    failure_reason: str | None = None
    admission_id: str | None = None
    timings_ms: Mapping[str, float] | None = None
    accepted_map: RoomMapSnapshot | None = None

    def __post_init__(self):
        text(self.episode_id, "episode_id")
        text(self.map_domain_id, "map_domain_id")
        integer(self.request_revision, "request_revision")
        if not isinstance(self.latest_map, RoomMapSnapshot):
            raise ValueError("latest_map must be RoomMapSnapshot")
        if self.latest_map.revision > self.request_revision:
            raise ValueError("latest M3 revision cannot exceed request revision")
        if (self.latest_map.episode_id, self.latest_map.map_domain_id) != (self.episode_id, self.map_domain_id):
            raise ValueError("latest map episode/domain mismatch")
        if self.accepted_map_revision is not None:
            integer(self.accepted_map_revision, "accepted_map_revision")
            if self.accepted_map_revision > self.latest_map.revision:
                raise ValueError("accepted M3 revision cannot exceed latest M3 revision")
            if not isinstance(self.accepted_map, RoomMapSnapshot):
                raise ValueError("accepted M3 revision requires its retained map snapshot")
            if (self.accepted_map.episode_id, self.accepted_map.map_domain_id) != (self.episode_id, self.map_domain_id):
                raise ValueError("accepted map episode/domain mismatch")
            if self.accepted_map.revision != self.accepted_map_revision:
                raise ValueError("accepted map snapshot revision mismatch")
            if (self.accepted_map.clock_domain != self.latest_map.clock_domain
                    or self.accepted_map.calibration_id != self.latest_map.calibration_id
                    or self.accepted_map.source.sensor_id != self.latest_map.source.sensor_id
                    or self.accepted_map.source.frame_index > self.latest_map.source.frame_index
                    or self.accepted_map.capture_monotonic_ns > self.latest_map.capture_monotonic_ns
                    or self.accepted_map.resolution_m != self.latest_map.resolution_m
                    or self.accepted_map.source_hash != self.latest_map.source_hash
                    or self.accepted_map.worker_sha256 != self.latest_map.worker_sha256
                    or self.accepted_map.region_worker_sha256 != self.latest_map.region_worker_sha256
                    or self.accepted_map.config_sha256 != self.latest_map.config_sha256):
                raise ValueError("accepted map provenance must match latest M3 domain/configuration")
        elif self.accepted_map is not None:
            raise ValueError("accepted map snapshot requires an accepted revision")
        if self.regions is not None and not isinstance(self.regions, RegionSnapshot):
            raise ValueError("regions must be RegionSnapshot or None")
        if self.regions is None:
            if self.m5_revision is not None or not self.regions_stale or self.accepted_map_revision is not None:
                raise ValueError("missing regions require stale=true and no M5 revision")
        else:
            if self.m5_revision is None:
                raise ValueError("published regions require an M5 revision")
            integer(self.m5_revision, "m5_revision")
            if self.regions.episode_id != self.episode_id or self.regions.revision != self.m5_revision:
                raise ValueError("region episode/revision mismatch")
            if self.accepted_map_revision != self.regions.source_map_revision:
                raise ValueError("regions must bind to their accepted M3 map revision")
            if self.regions_stale != self.regions.stale:
                raise ValueError("regions_stale must match RegionSnapshot.stale")
        boolean(self.regions_stale, "regions_stale")
        boolean(self.replay_required, "replay_required")
        if self.failure_reason is not None:
            text(self.failure_reason, "failure_reason")
        if (self.replay_required or self.failure_reason is not None) and not self.regions_stale:
            raise ValueError("failure or replay-required publication must be stale")
        if self.admission_id is not None:
            text(self.admission_id, "admission_id")
        if self.timings_ms is not None:
            values = {}
            for key, value in self.timings_ms.items():
                text(key, "timing name")
                duration = finite(value, f"timings_ms.{key}")
                if duration < 0:
                    raise ValueError("timings must be nonnegative")
                values[key] = duration
            from types import MappingProxyType
            object.__setattr__(self, "timings_ms", MappingProxyType(values))
