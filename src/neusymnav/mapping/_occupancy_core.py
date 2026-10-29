"""Sparse, conservative RGB-D occupancy mapping for a single flat floor."""

from __future__ import annotations

from _thread import LockType
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import math
from contextlib import nullcontext
from pathlib import Path
from threading import Lock
import time

import numpy as np

from typing import Any
Observation = Any  # private index-layout adapter only
from ._grid import GridSpec
from ._raycast_kernel import RaycastVotes, collect_ray_votes
from .tiles import TileArchive, TileArchiveError


class CellState(str, Enum):
    UNKNOWN = "unknown"
    FREE = "free"
    OCCUPIED = "occupied"


class DuplicateFrameError(ValueError):
    """Raised when a source observation would be fused more than once."""


@dataclass(frozen=True)
class MapDelta:
    """Tiles whose occupancy evidence changed in one integration call."""

    version: int
    changed_tiles: tuple[tuple[int, int], ...]
    frame_votes: RaycastVotes | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class MapCellSnapshot:
    """Immutable current evidence for one cell touched by an integration."""

    row: int
    col: int
    planar_log_odds: float | None
    height_log_odds: tuple[tuple[int, float], ...]
    floor_supported: bool


@dataclass(frozen=True)
class _SnapshotCellArrays:
    """Read-only, copied cell evidence for one dirty snapshot."""

    rows: np.ndarray
    cols: np.ndarray
    planar_log_odds: np.ndarray
    height_log_odds: np.ndarray
    floor_supported: np.ndarray


@dataclass(frozen=True)
class MapSnapshot:
    """Bounded immutable snapshot of only the cells touched by one frame."""

    version: int
    episode_id: str
    source_frame_id: int
    sim_time_s: float
    capture_wall_ns: int
    integration_wall_ns: int
    integration_duration_ns: int
    grid: GridSpec
    changed_tiles: tuple[tuple[int, int], ...]
    source_x_m: float
    source_z_m: float
    _cell_arrays: _SnapshotCellArrays | None = field(repr=False, compare=False)
    _cells_cache: tuple[MapCellSnapshot, ...] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _cells_lock: LockType = field(default_factory=Lock, init=False, repr=False, compare=False)

    @property
    def cells(self) -> tuple[MapCellSnapshot, ...]:
        """Materialize the legacy cell objects only when a caller requests them."""
        cached = self._cells_cache
        if cached is not None:
            return cached

        with self._cells_lock:
            cached = self._cells_cache
            if cached is not None:
                return cached

            arrays = self._cell_arrays
            if arrays is None:
                raise RuntimeError("snapshot cell data was released before materialization")
            result = []
            height_tuple_cache: dict[bytes, tuple[tuple[int, float], ...]] = {}
            for index, (row, col) in enumerate(zip(arrays.rows, arrays.cols)):
                planar_value = arrays.planar_log_odds[index]
                height_values_at_cell = arrays.height_log_odds[index]
                height_key = height_values_at_cell.tobytes()
                height_values = height_tuple_cache.get(height_key)
                if height_values is None:
                    observed_height_bins = np.flatnonzero(~np.isnan(height_values_at_cell))
                    height_values = tuple(
                        (int(height_bin), float(height_values_at_cell[height_bin]))
                        for height_bin in observed_height_bins
                    )
                    height_tuple_cache[height_key] = height_values
                result.append(
                    MapCellSnapshot(
                        row=int(row),
                        col=int(col),
                        planar_log_odds=None if np.isnan(planar_value) else float(planar_value),
                        height_log_odds=height_values,
                        floor_supported=bool(arrays.floor_supported[index]),
                    )
                )

            cached = tuple(result)
            object.__setattr__(self, "_cells_cache", cached)
            object.__setattr__(self, "_cell_arrays", None)
            return cached

    @property
    def capture_to_map_ns(self) -> int:
        """Elapsed monotonic time from capture to completed map integration."""
        return self.integration_wall_ns - self.capture_wall_ns


@dataclass
class _Tile:
    planar_log_odds: np.ndarray
    height_log_odds: np.ndarray
    floor_support: np.ndarray

    @classmethod
    def empty(cls, tile_size_cells: int, height_bin_count: int) -> _Tile:
        shape = (tile_size_cells, tile_size_cells)
        return cls(
            planar_log_odds=np.full(shape, np.nan, dtype=np.float32),
            height_log_odds=np.full((*shape, height_bin_count), np.nan, dtype=np.float32),
            floor_support=np.zeros(shape, dtype=np.bool_),
        )


@dataclass(frozen=True)
class _TileVoteSlice:
    key: tuple[int, int]
    vote_rows: slice
    vote_cols: slice
    tile_rows: slice
    tile_cols: slice


class OccupancyMapper:
    """Fuse axial-depth rays into sparse 2D tiles with local height evidence.

    Height evidence is relative to the ``GridSpec`` floor. Rays are projected
    using the observation's own camera intrinsics and world pose. Each frame
    contributes at most one vote per 2D cell and height voxel; occupied votes
    take precedence over free votes in that frame.
    """

    hit_log_odds = 0.85
    free_log_odds = -0.4
    min_log_odds = -4.0
    max_log_odds = 4.0
    occupied_threshold = math.log(0.65 / 0.35)
    free_threshold = math.log(0.35 / 0.65)
    MAX_PLANAR_MEMORY_BYTES = 256 * 1024 * 1024
    MAX_HEIGHT_MEMORY_BYTES = 256 * 1024 * 1024

    def __init__(
        self,
        grid: GridSpec,
        *,
        robot_height_m: float = 1.5,
        height_bin_m: float = 0.1,
        min_depth_m: float = 0.15,
        max_depth_m: float = 5.0,
        sampling_stride: int = 4,
        raycast_workers: int = 1,
        tile_archive_dir: str | Path | None = None,
    ) -> None:
        if not math.isfinite(robot_height_m) or robot_height_m <= height_bin_m:
            raise ValueError("robot_height_m must be finite and exceed one height bin")
        if not math.isfinite(height_bin_m) or height_bin_m <= 0:
            raise ValueError("height_bin_m must be finite and positive")
        if not math.isfinite(min_depth_m) or min_depth_m <= 0:
            raise ValueError("min_depth_m must be finite and positive")
        if not math.isfinite(max_depth_m) or max_depth_m <= min_depth_m:
            raise ValueError("max_depth_m must exceed min_depth_m")
        if isinstance(sampling_stride, bool) or not isinstance(sampling_stride, int) or sampling_stride <= 0:
            raise ValueError("sampling_stride must be a positive integer")
        if type(raycast_workers) is not int or not 1 <= raycast_workers <= 4:
            raise ValueError("raycast workers must be an integer from 1 to 4")
        self._archive_reservation = None
        self.raycast_workers = raycast_workers
        self.grid = grid
        self.robot_height_m = float(robot_height_m)
        self.height_bin_m = float(height_bin_m)
        self.min_depth_m = float(min_depth_m)
        self.max_depth_m = float(max_depth_m)
        self.sampling_stride = sampling_stride
        self.height_bin_count = math.ceil(self.robot_height_m / self.height_bin_m)
        self._tiles: OrderedDict[tuple[int, int], _Tile] = OrderedDict()
        self._tile_archive = TileArchive(tile_archive_dir)
        self._planar_memory_bytes = 0
        self._height_memory_bytes = 0
        self._seen_frames: set[tuple[str, int]] = set()
        self._episode_id: str | None = None
        self._version = 0
        self._ray_step_m = min(grid.resolution_m, self.height_bin_m) / 2.0
        self._last_snapshot: MapSnapshot | None = None

    @property
    def version(self) -> int:
        return self._version

    @property
    def tile_keys(self) -> tuple[tuple[int, int], ...]:
        """Sorted keys of tiles currently resident in the bounded active set."""
        return tuple(sorted(self._tiles))

    @property
    def active_tile_keys(self) -> tuple[tuple[int, int], ...]:
        """Sorted keys of tiles whose dense arrays are currently in memory."""
        return self.tile_keys

    @property
    def archived_tile_keys(self) -> tuple[tuple[int, int], ...]:
        """Sorted archived keys that are not currently resident in memory."""
        active = set(self._tiles)
        return tuple(key for key in self._tile_archive.tile_keys if key not in active)

    @property
    def archived_tile_count(self) -> int:
        return len(self.archived_tile_keys)

    @property
    def archive_disk_bytes(self) -> int:
        """Compressed archive bytes on disk, including stale copies of active tiles."""
        return self._tile_archive.disk_bytes

    @property
    def planar_memory_bytes(self) -> int:
        """Bytes held by planar log odds and floor support arrays."""
        return self._planar_memory_bytes

    @property
    def height_memory_bytes(self) -> int:
        """Bytes held by sparse-tile height log odds arrays."""
        return self._height_memory_bytes

    def reset(self, episode_id: str | None = None) -> None:
        """Clear all evidence before starting a new episode."""
        self._tile_archive.clear()
        self._tiles.clear()
        self._planar_memory_bytes = 0
        self._height_memory_bytes = 0
        self._seen_frames.clear()
        self._episode_id = episode_id
        self._version = 0
        self._last_snapshot = None

    def integrate(self, obs: Observation) -> MapDelta:
        """Integrate one immutable RGB-D observation from its source pose."""
        integration_started_ns = time.perf_counter_ns()
        key = (obs.episode_id, obs.frame_id)
        if key in self._seen_frames:
            raise DuplicateFrameError(f"duplicate observation frame {obs.episode_id}:{obs.frame_id}")
        if self._episode_id is not None and obs.episode_id != self._episode_id:
            raise ValueError("reset the mapper before integrating a different episode")

        intrinsics = np.asarray(obs.K, dtype=np.float64)
        if intrinsics[0, 0] <= 0 or intrinsics[1, 1] <= 0:
            raise ValueError("camera focal lengths must be positive")
        try:
            inverse_intrinsics = np.linalg.inv(intrinsics)
        except np.linalg.LinAlgError as exc:
            raise ValueError("camera intrinsics must be invertible") from exc

        camera_origin = obs.T_world_camera_cv[:3, 3]
        rotation = obs.T_world_camera_cv[:3, :3]
        stride = self.sampling_stride
        sampled_depth = obs.depth_m[::stride, ::stride]
        sampled_valid = obs.valid_depth[::stride, ::stride]
        usable = (
            sampled_valid
            & np.isfinite(sampled_depth)
            & (sampled_depth >= self.min_depth_m)
            & (sampled_depth < self.max_depth_m)
        )
        sample_v, sample_u = np.nonzero(usable)
        depths = sampled_depth[sample_v, sample_u].astype(np.float64)
        pixels = np.column_stack((sample_u * stride, sample_v * stride, np.ones(len(depths))))
        rays = pixels @ inverse_intrinsics.T
        finite_rays = np.isfinite(rays).all(axis=1) & (np.abs(rays[:, 2]) >= 1e-12)
        rays = rays[finite_rays]
        depths = depths[finite_rays]
        rays /= rays[:, 2:3]
        measured_endpoints = (rays * depths[:, None]) @ rotation.T + camera_origin
        endpoints = measured_endpoints
        has_return = np.ones(len(endpoints), dtype=np.bool_)
        if obs.no_return is not None and np.any(obs.no_return[::stride, ::stride]):
            certified_range = min(float(obs.no_return_range_m), self.max_depth_m)
            if certified_range > self.min_depth_m:
                no_hit_v, no_hit_u = np.nonzero(obs.no_return[::stride, ::stride])
                no_hit_pixels = np.column_stack((
                    no_hit_u * stride, no_hit_v * stride, np.ones(len(no_hit_u))
                ))
                no_hit_rays = no_hit_pixels @ inverse_intrinsics.T
                ray_norms = np.linalg.norm(no_hit_rays, axis=1)
                good = np.isfinite(no_hit_rays).all(axis=1) & np.isfinite(ray_norms) & (ray_norms > 1e-12)
                unit_world = (no_hit_rays[good] / ray_norms[good, None]) @ rotation.T
                no_hit_endpoints = camera_origin + unit_world * certified_range
                no_hit_endpoints = self._clip_no_return_rays(
                    camera_origin, no_hit_endpoints, measured_endpoints
                )
                if len(no_hit_endpoints):
                    endpoints = np.concatenate((endpoints, no_hit_endpoints))
                    has_return = np.concatenate((
                        has_return, np.zeros(len(no_hit_endpoints), dtype=np.bool_)
                    ))
        votes = collect_ray_votes(
            endpoints,
            camera_origin,
            has_return=has_return,
            resolution_m=self.grid.resolution_m,
            origin_x_m=self.grid.origin_x_m,
            origin_z_m=self.grid.origin_z_m,
            floor_y_m=self.grid.floor_y_m,
            robot_height_m=self.robot_height_m,
            height_bin_m=self.height_bin_m,
            ray_step_m=self._ray_step_m,
            workers=self.raycast_workers,
        )

        changed_tiles, cells = self._integrate_votes(votes)

        if changed_tiles:
            self._version += 1
        integration_wall_ns = time.monotonic_ns()
        integration_duration_ns = time.perf_counter_ns() - integration_started_ns
        self._last_snapshot = MapSnapshot(
            version=self._version,
            episode_id=obs.episode_id,
            source_frame_id=obs.frame_id,
            sim_time_s=float(obs.sim_time_s),
            capture_wall_ns=int(obs.capture_wall_ns),
            integration_wall_ns=integration_wall_ns,
            integration_duration_ns=integration_duration_ns,
            grid=self.grid,
            changed_tiles=changed_tiles,
            source_x_m=float(camera_origin[0]),
            source_z_m=float(camera_origin[2]),
            _cell_arrays=cells,
        )
        self._seen_frames.add(key)
        for tile_key in changed_tiles:
            self._tiles.move_to_end(tile_key)
        if self._episode_id is None:
            self._episode_id = obs.episode_id
        return MapDelta(self._version, changed_tiles, votes)

    def _clip_no_return_rays(
        self,
        origin: np.ndarray,
        endpoints: np.ndarray,
        measured_endpoints: np.ndarray,
    ) -> np.ndarray:
        """Stop certified clear rays before observed walls in this or prior frames."""
        same_frame_hits: set[tuple[int, int]] = set()
        for point in measured_endpoints:
            height = float(point[1] - self.grid.floor_y_m)
            if self.height_bin_m <= height <= self.robot_height_m:
                same_frame_hits.add(self.grid.world_to_grid(float(point[0]), float(point[2])))
        archived = set(self._tile_archive.tile_keys) - set(self._tiles)
        safe_endpoints = []
        for endpoint in endpoints:
            delta = endpoint - origin
            distance = float(np.linalg.norm(delta))
            steps = max(1, math.ceil(distance / self._ray_step_m))
            previous = origin
            clipped = endpoint
            last_cell: tuple[int, int] | None = None
            for step in range(1, steps + 1):
                point = origin + delta * (step / steps)
                row, col = self.grid.world_to_grid(float(point[0]), float(point[2]))
                if (row, col) == last_cell:
                    previous = point
                    continue
                last_cell = (row, col)
                tile_row, tile_col, local_row, local_col = self.grid.grid_to_tile(row, col)
                key = (tile_row, tile_col)
                tile = self._tiles.get(key)
                blocked = (row, col) in same_frame_hits or key in archived
                if tile is not None:
                    planar = tile.planar_log_odds[local_row, local_col]
                    blocked |= bool(np.isfinite(planar) and planar >= self.occupied_threshold)
                    # A height-specific wall can remain occupied after planar
                    # evidence has become ambiguous, so honor either record.
                    blocked |= bool(np.any(tile.height_log_odds[local_row, local_col, 1:] >= self.occupied_threshold))
                if blocked:
                    clipped = previous
                    break
                previous = point
            if np.linalg.norm(clipped - origin) > self._ray_step_m:
                safe_endpoints.append(clipped)
        if not safe_endpoints:
            return np.empty((0, 3), dtype=np.float64)
        return np.asarray(safe_endpoints, dtype=np.float64)

    def _integrate_votes(
        self,
        votes: RaycastVotes,
    ) -> tuple[tuple[tuple[int, int], ...], _SnapshotCellArrays]:
        shape = votes.planar_free.shape
        planar = (votes.planar_free, votes.planar_hit, votes.floor_hit)
        height = (votes.height_free, votes.height_hit)
        if (len(shape) != 2 or any(a.shape != shape or a.dtype != np.bool_ for a in planar)
                or any(a.shape != (*shape, self.height_bin_count) or a.dtype != np.bool_ for a in height)):
            raise ValueError("vote array shape/dtype does not match mapper height-bin profile")
        rows, cols = votes.planar_free.shape
        if rows == 0 or cols == 0:
            return (), self._empty_snapshot_cell_arrays()

        tile_size = self.grid.tile_size_cells
        end_row = votes.min_row + rows
        end_col = votes.min_col + cols
        first_tile_row, last_tile_row = votes.min_row // tile_size, (end_row - 1) // tile_size
        first_tile_col, last_tile_col = votes.min_col // tile_size, (end_col - 1) // tile_size
        tile_slices = []
        for tile_row in range(first_tile_row, last_tile_row + 1):
            tile_start_row = tile_row * tile_size
            overlap_start_row = max(votes.min_row, tile_start_row)
            overlap_end_row = min(end_row, tile_start_row + tile_size)
            for tile_col in range(first_tile_col, last_tile_col + 1):
                tile_start_col = tile_col * tile_size
                overlap_start_col = max(votes.min_col, tile_start_col)
                overlap_end_col = min(end_col, tile_start_col + tile_size)
                vote_rows = slice(overlap_start_row - votes.min_row, overlap_end_row - votes.min_row)
                vote_cols = slice(overlap_start_col - votes.min_col, overlap_end_col - votes.min_col)
                tile_rows = slice(overlap_start_row - tile_start_row, overlap_end_row - tile_start_row)
                tile_cols = slice(overlap_start_col - tile_start_col, overlap_end_col - tile_start_col)
                key = (tile_row, tile_col)
                if self._slice_has_votes(votes, vote_rows, vote_cols):
                    tile_slices.append(_TileVoteSlice(key, vote_rows, vote_cols, tile_rows, tile_cols))

        if not tile_slices:
            return (), self._empty_snapshot_cell_arrays()

        cell_count = tile_size * tile_size
        planar_tile_bytes = cell_count * (np.dtype(np.float32).itemsize + np.dtype(np.bool_).itemsize)
        height_tile_bytes = cell_count * self.height_bin_count * np.dtype(np.float32).itemsize
        required_keys = tuple(item.key for item in tile_slices)
        self._admit_tiles(
            required_keys,
            tile_size=tile_size,
            planar_tile_bytes=planar_tile_bytes,
            height_tile_bytes=height_tile_bytes,
        )

        dirty_slices = []
        changed_tiles = tuple(sorted(item.key for item in tile_slices))
        for item in tile_slices:
            tile = self._tiles[item.key]
            vote_slice = (item.vote_rows, item.vote_cols)
            tile_slice = (item.tile_rows, item.tile_cols)
            planar_hit = votes.planar_hit[vote_slice]
            planar_free = votes.planar_free[vote_slice]
            height_hit = votes.height_hit[vote_slice]
            height_free = votes.height_free[vote_slice]
            floor_hit = votes.floor_hit[vote_slice]

            self._apply_log_odds(tile.planar_log_odds[tile_slice], planar_hit, planar_free)
            self._apply_log_odds(tile.height_log_odds[tile_slice], height_hit, height_free)
            tile.floor_support[tile_slice] |= floor_hit

            dirty = planar_hit | planar_free | floor_hit
            np.logical_or(dirty, np.any(height_hit | height_free, axis=2), out=dirty)
            local_rows, local_cols = np.nonzero(dirty)
            if local_rows.size:
                dirty_slices.append(
                    (
                        item.key,
                        tile,
                        local_rows + item.tile_rows.start,
                        local_cols + item.tile_cols.start,
                    )
                )

        return changed_tiles, self._snapshot_cells(dirty_slices)

    def _write_archive(self, payload):
        # Reserve the unchanged conservative bound immediately before ALL
        # possible archive writes, including atomic staging/rollback files.
        # Memory-only frames need no filesystem quota scan.
        scope = nullcontext() if self._archive_reservation is None else self._archive_reservation()
        with scope:
            self._tile_archive.write_many(payload)

    def _admit_tiles(
        self,
        required_keys: tuple[tuple[int, int], ...],
        *,
        tile_size: int,
        planar_tile_bytes: int,
        height_tile_bytes: int,
    ) -> None:
        """Make all required tiles active, staging archive IO before map mutation."""
        required = set(required_keys)
        max_active_tiles = min(
            self.MAX_PLANAR_MEMORY_BYTES // planar_tile_bytes,
            self.MAX_HEIGHT_MEMORY_BYTES // height_tile_bytes,
        )
        if len(required) > max_active_tiles:
            planar_fits = len(required) * planar_tile_bytes <= self.MAX_PLANAR_MEMORY_BYTES
            if not planar_fits:
                raise MemoryError("planar occupancy tile memory cap exceeded")
            raise MemoryError("height occupancy tile memory cap exceeded")

        missing = [key for key in required_keys if key not in self._tiles]
        missing = list(dict.fromkeys(missing))
        active_after_load = len(self._tiles) + len(missing)
        evict_count = max(0, active_after_load - max_active_tiles)
        eviction_keys = [key for key in self._tiles if key not in required][:evict_count]
        if len(eviction_keys) != evict_count:
            # Required arrays alone fit, so this indicates inconsistent accounting.
            raise MemoryError("occupancy tile memory cap exceeded")

        # Archive reads, checksum validation, and all required array allocations
        # finish before writing eviction files or changing active map state.
        staged_tiles: dict[tuple[int, int], _Tile] = {}
        for key in missing:
            if self._tile_archive.contains(key):
                planar, height, floor = self._tile_archive.read(
                    key,
                    tile_size_cells=tile_size,
                    height_bin_count=self.height_bin_count,
                )
                staged_tiles[key] = _Tile(planar, height, floor)
            else:
                staged_tiles[key] = _Tile.empty(tile_size, self.height_bin_count)

        eviction_payload = {
            key: (
                self._tiles[key].planar_log_odds,
                self._tiles[key].height_log_odds,
                self._tiles[key].floor_support,
            )
            for key in eviction_keys
        }
        if eviction_payload:
            try:
                self._write_archive(eviction_payload)
            except Exception as exc:
                if isinstance(exc, TileArchiveError):
                    raise
                raise TileArchiveError(f"tile archive eviction failed: {exc}") from exc

        for key in eviction_keys:
            tile = self._tiles.pop(key)
            self._planar_memory_bytes -= tile.planar_log_odds.nbytes + tile.floor_support.nbytes
            self._height_memory_bytes -= tile.height_log_odds.nbytes
        for key, tile in staged_tiles.items():
            self._tiles[key] = tile
            self._planar_memory_bytes += tile.planar_log_odds.nbytes + tile.floor_support.nbytes
            self._height_memory_bytes += tile.height_log_odds.nbytes

    def reload_tile(self, key: tuple[int, int]) -> bool:
        """Synchronously reload an archived tile into the bounded active set.

        Returns false for a key that has never been archived. Until a successful
        reload, queries see an evicted tile as unknown and traversability remains
        conservative. A reload may evict the least recently used active tile.
        Archive or capacity errors leave the active arrays and snapshots intact.
        """
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, np.integer)) for value in key)
        ):
            raise ValueError("tile key must be an integer (row, col) pair")
        normalized_key = (int(key[0]), int(key[1]))
        current = self._tiles.get(normalized_key)
        if current is not None:
            self._tiles.move_to_end(normalized_key)
            return True
        if not self._tile_archive.contains(normalized_key):
            return False

        tile_size = self.grid.tile_size_cells
        planar_tile_bytes = tile_size**2 * (np.dtype(np.float32).itemsize + np.dtype(np.bool_).itemsize)
        height_tile_bytes = tile_size**2 * self.height_bin_count * np.dtype(np.float32).itemsize
        max_active_tiles = min(
            self.MAX_PLANAR_MEMORY_BYTES // planar_tile_bytes,
            self.MAX_HEIGHT_MEMORY_BYTES // height_tile_bytes,
        )
        if max_active_tiles < 1:
            raise MemoryError("occupancy tile memory cap cannot admit one tile")

        planar, height, floor = self._tile_archive.read(
            normalized_key,
            tile_size_cells=tile_size,
            height_bin_count=self.height_bin_count,
        )
        staged_tile = _Tile(planar, height, floor)
        evict_count = max(0, len(self._tiles) + 1 - max_active_tiles)
        eviction_keys = list(self._tiles)[:evict_count]
        eviction_payload = {
            active_key: (
                self._tiles[active_key].planar_log_odds,
                self._tiles[active_key].height_log_odds,
                self._tiles[active_key].floor_support,
            )
            for active_key in eviction_keys
        }
        if eviction_payload:
            try:
                self._write_archive(eviction_payload)
            except Exception as exc:
                if isinstance(exc, TileArchiveError):
                    raise
                raise TileArchiveError(f"tile archive eviction failed: {exc}") from exc

        for active_key in eviction_keys:
            tile = self._tiles.pop(active_key)
            self._planar_memory_bytes -= tile.planar_log_odds.nbytes + tile.floor_support.nbytes
            self._height_memory_bytes -= tile.height_log_odds.nbytes
        self._tiles[normalized_key] = staged_tile
        self._planar_memory_bytes += staged_tile.planar_log_odds.nbytes + staged_tile.floor_support.nbytes
        self._height_memory_bytes += staged_tile.height_log_odds.nbytes
        return True

    @staticmethod
    def _slice_has_votes(votes: RaycastVotes, rows: slice, cols: slice) -> bool:
        planar_free = votes.planar_free[rows, cols]
        planar_hit = votes.planar_hit[rows, cols]
        floor_hit = votes.floor_hit[rows, cols]
        height_free = votes.height_free[rows, cols]
        height_hit = votes.height_hit[rows, cols]
        return bool(
            np.any(planar_free)
            or np.any(planar_hit)
            or np.any(floor_hit)
            or np.any(height_free)
            or np.any(height_hit)
        )

    def _apply_log_odds(self, tile_values: np.ndarray, hit_votes: np.ndarray, free_votes: np.ndarray) -> None:
        observed = hit_votes | free_votes
        if not np.any(observed):
            return
        previous = tile_values[observed]
        previous = np.where(np.isnan(previous), 0.0, previous)
        increments = np.where(hit_votes[observed], self.hit_log_odds, self.free_log_odds)
        tile_values[observed] = np.clip(
            previous.astype(np.float64) + increments,
            self.min_log_odds,
            self.max_log_odds,
        ).astype(np.float32)

    def snapshot(self) -> MapSnapshot:
        """Return the most recent immutable dirty snapshot.

        Only evidence touched by the latest integration is retained here. A
        caller that needs history should retain returned snapshots itself.
        """
        if self._last_snapshot is None:
            raise RuntimeError("integrate an observation before requesting a snapshot")
        return self._last_snapshot

    def _snapshot_cells(
        self,
        dirty_slices: list[tuple[tuple[int, int], _Tile, np.ndarray, np.ndarray]],
    ) -> _SnapshotCellArrays:
        if not dirty_slices:
            return self._empty_snapshot_cell_arrays()
        size = self.grid.tile_size_cells
        rows = []
        cols = []
        planar_values = []
        height_values = []
        floor_values = []
        for key, tile, touched_rows, touched_cols in dirty_slices:
            count = touched_rows.size
            rows.append(touched_rows + key[0] * size)
            cols.append(touched_cols + key[1] * size)
            planar_values.append(tile.planar_log_odds[touched_rows, touched_cols])
            height_values.append(tile.height_log_odds[touched_rows, touched_cols])
            floor_values.append(tile.floor_support[touched_rows, touched_cols])

        all_rows = np.concatenate(rows)
        all_cols = np.concatenate(cols)
        all_planar_values = np.concatenate(planar_values)
        all_height_values = np.concatenate(height_values)
        all_floor_values = np.concatenate(floor_values)
        order = np.lexsort((all_cols, all_rows))
        return _SnapshotCellArrays(
            rows=self._readonly_snapshot_array(all_rows[order]),
            cols=self._readonly_snapshot_array(all_cols[order]),
            planar_log_odds=self._readonly_snapshot_array(all_planar_values[order]),
            height_log_odds=self._readonly_snapshot_array(all_height_values[order]),
            floor_supported=self._readonly_snapshot_array(all_floor_values[order]),
        )

    def _empty_snapshot_cell_arrays(self) -> _SnapshotCellArrays:
        return _SnapshotCellArrays(
            rows=self._readonly_snapshot_array(np.empty(0, dtype=np.int64)),
            cols=self._readonly_snapshot_array(np.empty(0, dtype=np.int64)),
            planar_log_odds=self._readonly_snapshot_array(np.empty(0, dtype=np.float32)),
            height_log_odds=self._readonly_snapshot_array(
                np.empty((0, self.height_bin_count), dtype=np.float32)
            ),
            floor_supported=self._readonly_snapshot_array(np.empty(0, dtype=np.bool_)),
        )

    @staticmethod
    def _readonly_snapshot_array(values: np.ndarray) -> np.ndarray:
        contiguous = np.ascontiguousarray(values)
        return np.frombuffer(contiguous.tobytes(), dtype=contiguous.dtype).reshape(contiguous.shape)

    def log_odds_at(self, row: int, col: int, *, height_bin: int | None = None) -> float | None:
        tile, local_row, local_col = self._find_tile(row, col)
        if tile is None:
            return None
        if height_bin is None:
            value = tile.planar_log_odds[local_row, local_col]
            return None if np.isnan(value) else float(value)
        self._validate_height_bin(height_bin)
        value = tile.height_log_odds[local_row, local_col, height_bin]
        return None if np.isnan(value) else float(value)

    def cell_state(self, row: int, col: int) -> CellState:
        return self._classify(self.log_odds_at(row, col))

    def height_state(self, row: int, col: int, height_bin: int) -> CellState:
        return self._classify(self.log_odds_at(row, col, height_bin=height_bin))

    def floor_supported(self, row: int, col: int) -> bool:
        tile, local_row, local_col = self._find_tile(row, col)
        return tile is not None and bool(tile.floor_support[local_row, local_col])

    def traversability_state(self, row: int, col: int) -> CellState:
        if self.cell_state(row, col) is CellState.OCCUPIED:
            return CellState.OCCUPIED
        for height_bin in range(1, self.height_bin_count):
            if self.height_state(row, col, height_bin) is CellState.OCCUPIED:
                return CellState.OCCUPIED
        if not self.floor_supported(row, col):
            return CellState.UNKNOWN
        if self.cell_state(row, col) is not CellState.FREE:
            return CellState.UNKNOWN
        if all(
            self.height_state(row, col, height_bin) is CellState.FREE
            for height_bin in range(1, self.height_bin_count)
        ):
            return CellState.FREE
        return CellState.UNKNOWN

    def is_traversable(self, row: int, col: int, *, footprint_radius_m: float = 0.25) -> bool:
        """Return whether an observed-free body clearance fits the robot footprint."""
        if not math.isfinite(footprint_radius_m) or footprint_radius_m < 0:
            raise ValueError("footprint_radius_m must be finite and nonnegative")
        radius_cells = math.ceil(footprint_radius_m / self.grid.resolution_m + 0.5)
        for offset_row in range(-radius_cells, radius_cells + 1):
            for offset_col in range(-radius_cells, radius_cells + 1):
                nearest_row_m = max(abs(offset_row) * self.grid.resolution_m - self.grid.resolution_m / 2.0, 0.0)
                nearest_col_m = max(abs(offset_col) * self.grid.resolution_m - self.grid.resolution_m / 2.0, 0.0)
                if math.hypot(nearest_row_m, nearest_col_m) > footprint_radius_m + 1e-12:
                    continue
                if self.traversability_state(row + offset_row, col + offset_col) is not CellState.FREE:
                    return False
        return True

    def can_step(
        self,
        row: int,
        col: int,
        next_row: int,
        next_col: int,
        *,
        footprint_radius_m: float = 0.25,
    ) -> bool:
        """Check one adjacent grid move, refusing diagonal corner cutting."""
        delta_row, delta_col = next_row - row, next_col - col
        if max(abs(delta_row), abs(delta_col)) != 1:
            return False
        if not self.is_traversable(row, col, footprint_radius_m=footprint_radius_m):
            return False
        if not self.is_traversable(next_row, next_col, footprint_radius_m=footprint_radius_m):
            return False
        if delta_row and delta_col:
            if not self.is_traversable(row + delta_row, col, footprint_radius_m=footprint_radius_m):
                return False
            if not self.is_traversable(row, col + delta_col, footprint_radius_m=footprint_radius_m):
                return False
        return True

    def _find_tile(self, row: int, col: int) -> tuple[_Tile | None, int, int]:
        tile_row, tile_col, local_row, local_col = self.grid.grid_to_tile(row, col)
        key = (tile_row, tile_col)
        tile = self._tiles.get(key)
        if tile is not None:
            self._tiles.move_to_end(key)
        return tile, local_row, local_col

    def _height_bin(self, relative_height_m: float) -> int:
        raw = math.floor(relative_height_m / self.height_bin_m)
        if 0 <= relative_height_m <= self.robot_height_m:
            return min(raw, self.height_bin_count - 1)
        return raw

    def _validate_height_bin(self, height_bin: int) -> None:
        if not isinstance(height_bin, int) or not 0 <= height_bin < self.height_bin_count:
            raise ValueError(f"height_bin must be in [0, {self.height_bin_count})")

    @classmethod
    def _classify(cls, log_odds: float | None) -> CellState:
        if log_odds is None:
            return CellState.UNKNOWN
        if log_odds >= cls.occupied_threshold:
            return CellState.OCCUPIED
        if log_odds <= cls.free_threshold:
            return CellState.FREE
        return CellState.UNKNOWN

    @classmethod
    def _clamp(cls, log_odds: float) -> np.float32:
        bounded = min(cls.max_log_odds, max(cls.min_log_odds, log_odds))
        return np.float32(bounded)
