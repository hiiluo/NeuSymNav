"""Small helpers for the opt-in bounded rolling NavMap policy."""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

import numpy as np

from ._raycast_kernel import RaycastVotes


MAX_LOCAL_RETENTION_S = 300.0


def validate_local_retention_s(value: object) -> float | None:
    """Return a finite supported TTL, preserving ``None`` as legacy mode."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("local_retention_s must be a finite number in (0, 300]")
    seconds = float(value)
    if not math.isfinite(seconds) or not 0.0 < seconds <= MAX_LOCAL_RETENTION_S:
        raise ValueError("local_retention_s must be a finite number in (0, 300]")
    return seconds


@dataclass(frozen=True)
class RollingWindow:
    """Square inclusive grid window aligned to the navigation camera cell."""

    min_row: int
    min_col: int
    size: int

    @property
    def end_row(self) -> int:
        return self.min_row + self.size

    @property
    def end_col(self) -> int:
        return self.min_col + self.size

    def contains(self, row: int, col: int) -> bool:
        return self.min_row <= row < self.end_row and self.min_col <= col < self.end_col

    @classmethod
    def centered(cls, grid, *, x_m: float, z_m: float, radius_m: float) -> "RollingWindow":
        half = math.ceil(radius_m / grid.resolution_m)
        center_row, center_col = grid.world_to_grid(x_m, z_m)
        return cls(center_row - half, center_col - half, 2 * half + 1)

    def crop_votes(self, votes: RaycastVotes) -> RaycastVotes:
        """Crop collected full-frame votes after raycasting; preserve ray evidence."""
        rows, cols = votes.planar_free.shape
        start_row = max(self.min_row, votes.min_row)
        start_col = max(self.min_col, votes.min_col)
        end_row = min(self.end_row, votes.min_row + rows)
        end_col = min(self.end_col, votes.min_col + cols)
        if start_row >= end_row or start_col >= end_col:
            bins = votes.height_free.shape[2]
            return RaycastVotes(
                self.min_row, self.min_col,
                np.zeros((0, 0), dtype=np.bool_), np.zeros((0, 0), dtype=np.bool_),
                np.zeros((0, 0), dtype=np.bool_), np.zeros((0, 0, bins), dtype=np.bool_),
                np.zeros((0, 0, bins), dtype=np.bool_),
            )
        source = np.s_[start_row - votes.min_row:end_row - votes.min_row,
                       start_col - votes.min_col:end_col - votes.min_col]
        return RaycastVotes(
            start_row, start_col,
            votes.planar_free[source], votes.planar_hit[source], votes.floor_hit[source],
            votes.height_free[source], votes.height_hit[source],
        )


def expire_tile_components(tile, *, now_ns: int, retention_ns: int) -> tuple[int, int, int]:
    """Expire planar, voxel and floor evidence by their own last observation."""
    planar_expired = (tile.planar_last_ns >= 0) & (now_ns - tile.planar_last_ns >= retention_ns)
    height_expired = (tile.height_last_ns >= 0) & (now_ns - tile.height_last_ns >= retention_ns)
    floor_expired = (tile.floor_last_ns >= 0) & (now_ns - tile.floor_last_ns >= retention_ns)
    planar_count = int(np.count_nonzero(planar_expired))
    height_count = int(np.count_nonzero(height_expired))
    floor_count = int(np.count_nonzero(floor_expired))
    tile.planar_log_odds[planar_expired] = np.nan
    tile.planar_last_ns[planar_expired] = -1
    tile.height_log_odds[height_expired] = np.nan
    tile.height_last_ns[height_expired] = -1
    tile.floor_support[floor_expired] = False
    tile.floor_last_ns[floor_expired] = -1
    return planar_count, height_count, floor_count


def clear_tile_outside_window(tile, key: tuple[int, int], tile_size: int,
                              window: RollingWindow) -> tuple[int, int, int]:
    """Clear cells beyond the rolling window, including partial edge tiles."""
    tile_row, tile_col = key
    rows = tile_row * tile_size + np.arange(tile_size)
    cols = tile_col * tile_size + np.arange(tile_size)
    outside = (((rows < window.min_row) | (rows >= window.end_row))[:, None]
               | ((cols < window.min_col) | (cols >= window.end_col))[None, :])
    planar = outside & ~np.isnan(tile.planar_log_odds)
    height = outside[:, :, None] & ~np.isnan(tile.height_log_odds)
    floor = outside & tile.floor_support
    counts = (int(np.count_nonzero(planar)), int(np.count_nonzero(height)),
              int(np.count_nonzero(floor)))
    tile.planar_log_odds[outside] = np.nan
    tile.height_log_odds[outside, :] = np.nan
    tile.floor_support[outside] = False
    tile.planar_last_ns[outside] = -1
    tile.height_last_ns[outside, :] = -1
    tile.floor_last_ns[outside] = -1
    return counts


def maintain_tile(tile,key,tile_size,window,*,now_ns,retention_ns):
    """Exact fused maintenance when warmed; original NumPy path otherwise."""
    from ._retention_kernel import apply_maintenance
    result=apply_maintenance(tile,key,tile_size,window,now_ns,retention_ns)
    if result is not None:return result
    expired=expire_tile_components(tile,now_ns=now_ns,retention_ns=retention_ns)
    spatial=clear_tile_outside_window(tile,key,tile_size,window)
    return (*expired,*spatial)
