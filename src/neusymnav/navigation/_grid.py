"""Private value adapter for selected 3DSG navigation algorithms."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Mapping
import math
import numpy as np
from ..contracts import NavSnapshot, GridState

def _finite(value, name):
    result=float(value)
    if not math.isfinite(result): raise ValueError(name+' must be finite')
    return result

@dataclass(frozen=True)
class GridView:
    episode_id: str
    robot_geometry_id: str
    revision: int
    as_of_frame_id: str
    as_of_frame_index: int
    host_monotonic_s: float
    resolution_m: float
    origin_x_m: float
    origin_y_m: float
    states: np.ndarray = field(repr=False, compare=False)
    floor_support: np.ndarray = field(repr=False, compare=False)
    clearance_evidence: np.ndarray = field(repr=False, compare=False)
    spawn_validated: np.ndarray = field(repr=False, compare=False)
    occupancy_log_odds: np.ndarray = field(repr=False, compare=False)
    scope_id: str = "observed_single_level"
    world_frame: str = "canonical_world_z_up"
    spawn_center_xy: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.revision < 0 or self.as_of_frame_index < 0:
            raise ValueError("revision and frame index must be non-negative")
        if not self.as_of_frame_id:
            raise ValueError("as_of_frame_id is required")
        for name in ("resolution_m", "origin_x_m", "origin_y_m", "host_monotonic_s"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.resolution_m <= 0:
            raise ValueError("resolution_m must be positive")
        if self.spawn_center_xy is not None:
            if len(self.spawn_center_xy) != 2 or not all(math.isfinite(float(v)) for v in self.spawn_center_xy):
                raise ValueError("spawn_center_xy must contain two finite coordinates")
        shapes = [np.asarray(getattr(self, name)).shape for name in
                  ("states", "floor_support", "clearance_evidence", "spawn_validated", "occupancy_log_odds")]
        if len(shapes[0]) != 2 or any(shape != shapes[0] for shape in shapes):
            raise ValueError("all map arrays must share a non-empty 2D shape")
        for name in ("states", "floor_support", "clearance_evidence", "spawn_validated", "occupancy_log_odds"):
            arr = np.asarray(getattr(self, name)).copy()
            arr.setflags(write=False)
            object.__setattr__(self, name, arr)

    @property
    def shape(self) -> tuple[int, int]:
        return self.states.shape

    def world_to_cell(self, x_m: float, y_m: float) -> tuple[int, int] | None:
        col = math.floor((float(x_m) - self.origin_x_m) / self.resolution_m)
        row = math.floor((float(y_m) - self.origin_y_m) / self.resolution_m)
        if 0 <= row < self.states.shape[0] and 0 <= col < self.states.shape[1]:
            return row, col
        return None

    def cell_to_world(self, row: int, col: int) -> tuple[float, float]:
        if not (0 <= row < self.states.shape[0] and 0 <= col < self.states.shape[1]):
            raise IndexError("cell is outside map")
        return (self.origin_x_m + (col + 0.5) * self.resolution_m,
                self.origin_y_m + (row + 0.5) * self.resolution_m)


@dataclass(frozen=True)
class PathResult:
    success: bool
    cells: tuple[tuple[int, int], ...]
    cost_m: float
    map_revision: int
    reason: str = ""
    grid_origin_x_m: float | None = None
    grid_origin_y_m: float | None = None
    grid_resolution_m: float | None = None


@dataclass(frozen=True)
class ActionCommand:
    linear_mps: float
    yaw_rate_radps: float
    reason: str
    frame_id: str
    map_revision: int
    valid_until_monotonic_s: float
    metadata: Mapping[str, float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("linear_mps", "yaw_rate_radps", "valid_until_monotonic_s"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))

GridSnapshot = GridView

def adapt(nav: NavSnapshot, robot_height_m: float, geometry_id: str) -> GridView:
    if nav.robot_geometry_id != geometry_id:
        raise ValueError('robot geometry mismatch')
    states=nav.states.copy()
    states[(states == GridState.FREE) & (~nav.floor_support | (nav.clearance < robot_height_m))] = GridState.UNKNOWN
    return GridView(nav.episode_id,nav.robot_geometry_id,nav.revision,str(nav.source),nav.source.frame_index,
        nav.capture_monotonic_ns/1e9,nav.resolution_m,*nav.origin_xy,states,nav.floor_support,
        nav.clearance,np.zeros_like(states,bool),np.full(states.shape,np.nan))

def footprint_offsets(radius_m: float, resolution_m: float):
    """All closed grid squares intersecting the cylindrical body at cell center."""
    n=math.ceil(radius_m/resolution_m+.5)
    for dr in range(-n,n+1):
        for dc in range(-n,n+1):
            near_r=max(abs(dr)*resolution_m-resolution_m/2,0.)
            near_c=max(abs(dc)*resolution_m-resolution_m/2,0.)
            if math.hypot(near_r,near_c) <= radius_m+1e-12:
                yield dr,dc

def footprint_mask(snapshot: GridView, radius_m: float) -> np.ndarray:
    known=snapshot.states==GridState.FREE
    result=known.copy();h,w=known.shape
    for dr,dc in footprint_offsets(radius_m,snapshot.resolution_m):
        shifted=np.zeros_like(known)
        r0,r1=max(0,-dr),min(h,h-dr);c0,c1=max(0,-dc),min(w,w-dc)
        if r1>r0 and c1>c0:
            shifted[r0:r1,c0:c1]=known[r0+dr:r1+dr,c0+dc:c1+dc]
        result &= shifted
    result.setflags(write=False)
    return result


class FootprintMaskCache:
    """One exact-content entry, never a revision/identity freshness shortcut."""
    def __init__(self):
        self._entry = None

    def get(self, snapshot, radius_m):
        states = snapshot.states
        key = (float(radius_m), snapshot.resolution_m, states.shape, states.dtype.str, states.tobytes())
        entry = self._entry
        if entry is None or key != entry[0]:
            mask = footprint_mask(snapshot, radius_m)
            # Bytes-backed storage cannot be made writable by a consumer.
            frozen = np.frombuffer(mask.tobytes(), dtype=np.bool_).reshape(mask.shape)
            entry = (key, frozen)
            self._entry = entry
        return entry[1]
