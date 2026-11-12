"""Lossless, bounded conversion of retained raw occupancy tiles for rooms.

Room mapping consumes the mapper's canonical tile history directly.  This
module never reads the coarsened display overview and never changes the local
navigation snapshot used by control.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from collections.abc import Mapping
from types import MappingProxyType

import numpy as np

from ..contracts import GridState, NavSnapshot
from .occupancy import RobotGeometry
from .overview import OverviewTiles


_MAX_RETAINED_TILES = 4096
_MAX_RETAINED_TILE_BYTES = 16 * 1024 * 1024
_MAX_DENSE_CELLS = 1_000_000


class RoomMapUnavailable(ValueError):
    """Raised when a fresh, complete raw room-map input is unavailable."""


def _frozen_tile(tile: np.ndarray) -> np.ndarray:
    """Return an independently owned, immutable int8 tile."""
    return np.frombuffer(np.ascontiguousarray(tile).tobytes(), dtype=np.int8).reshape(tile.shape)


def _validate_raw_tiles(tiles: OverviewTiles) -> OverviewTiles:
    if not isinstance(tiles, OverviewTiles):
        raise RoomMapUnavailable("raw overview tiles are missing")
    if not isinstance(tiles.source_nav, NavSnapshot):
        raise RoomMapUnavailable("raw tile source snapshot is missing")
    if type(tiles.complete) is not bool:
        raise ValueError("raw tile completeness flag must be bool")
    if not isinstance(tiles.origin_xy, (tuple, list)) or len(tiles.origin_xy) != 2:
        raise ValueError("raw tile origin must contain two coordinates")
    origin = tuple(float(v) for v in tiles.origin_xy)
    if not all(math.isfinite(v) for v in origin):
        raise ValueError("raw tile origin must be finite")
    if isinstance(tiles.tile_size, bool) or not isinstance(tiles.tile_size, (int, np.integer)):
        raise ValueError("raw tile size must be an integer")
    size = int(tiles.tile_size)
    if size < 1:
        raise ValueError("raw tile size must be positive")
    if isinstance(tiles.resolution_m, bool) or not isinstance(tiles.resolution_m, (int, float, np.integer, np.floating)):
        raise ValueError("raw tile resolution must be numeric")
    resolution = float(tiles.resolution_m)
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("raw tile resolution must be finite and positive")
    if not isinstance(tiles.tiles, Mapping):
        raise RoomMapUnavailable("raw tile provider is missing")

    tile_count = len(tiles.tiles)
    retained_limit = min(_MAX_RETAINED_TILES, _MAX_RETAINED_TILE_BYTES // (size * size))
    if tile_count > retained_limit:
        raise ValueError("raw tile retention exceeds the 4096-tile/16-MiB provider bound")

    frozen: dict[tuple[int, int], np.ndarray] = {}
    for key, tile in tiles.tiles.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)) for v in key)
        ):
            raise ValueError("raw tile keys must be integer row/column pairs")
        key = (int(key[0]), int(key[1]))
        if not isinstance(tile, np.ndarray) or tile.dtype != np.dtype(np.int8) or tile.shape != (size, size):
            raise ValueError("raw tile must be a square int8 array matching tile_size")
        if not np.isin(tile, (GridState.UNKNOWN, GridState.FREE, GridState.OCCUPIED)).all():
            raise ValueError("raw tile contains an invalid occupancy state")
        frozen[key] = _frozen_tile(tile)

    # Store a private immutable copy so later provider mutation cannot change
    # an already-issued room input.
    return OverviewTiles(
        source_nav=tiles.source_nav,
        origin_xy=origin,
        resolution_m=resolution,
        tile_size=size,
        tiles=MappingProxyType(frozen),
        complete=tiles.complete,
    )


@dataclass(frozen=True)
class RoomMapEvidence:
    """Immutable raw mapper tiles and the geometry used to bound clearance."""

    tiles: OverviewTiles
    robot: RobotGeometry

    def __post_init__(self) -> None:
        if self.tiles is not None:
            object.__setattr__(self, "tiles", _validate_raw_tiles(self.tiles))
        if self.robot is not None and not isinstance(self.robot, RobotGeometry):
            raise ValueError("RobotGeometry required for room-map evidence")


def _same_source_header(source: NavSnapshot, expected: NavSnapshot) -> bool:
    fields = (
        "episode_id",
        "revision",
        "source",
        "capture_monotonic_ns",
        "clock_domain",
        "robot_geometry_id",
        "floor_z_m",
        "floor_datum_source",
        "calibration_hash",
    )
    return all(getattr(source, field) == getattr(expected, field) for field in fields)


def _is_grid_aligned(value: float, reference: float, resolution: float) -> bool:
    cells = (value - reference) / resolution
    return math.isfinite(cells) and math.isclose(cells, round(cells), rel_tol=0.0, abs_tol=1e-6)


def build_room_map(
    evidence: RoomMapEvidence,
    expected_nav: NavSnapshot,
    max_cells: int = _MAX_DENSE_CELLS,
) -> NavSnapshot:
    """Build a native-resolution full-history ``NavSnapshot`` for room work.

    The tile state is copied without resampling.  Unknown tile cells and gaps
    between distant tiles remain unknown.  The cell bound is checked before
    allocating the dense output raster.
    """
    if not isinstance(evidence, RoomMapEvidence):
        raise RoomMapUnavailable("room-map evidence is missing")
    if not isinstance(expected_nav, NavSnapshot):
        raise RoomMapUnavailable("expected navigation snapshot is missing")
    if evidence.tiles is None or not isinstance(evidence.tiles, OverviewTiles):
        raise RoomMapUnavailable("raw tile provider is missing")
    if evidence.robot is None or not isinstance(evidence.robot, RobotGeometry):
        raise RoomMapUnavailable("robot geometry is missing")
    tiles = evidence.tiles
    source = tiles.source_nav
    if not tiles.complete:
        raise RoomMapUnavailable("raw tile history is incomplete")
    if not _same_source_header(source, expected_nav):
        raise RoomMapUnavailable("raw tile source is stale")
    if evidence.robot.geometry_id != expected_nav.robot_geometry_id:
        raise RoomMapUnavailable("robot geometry does not match navigation source")
    if tiles.resolution_m != source.resolution_m or source.resolution_m != expected_nav.resolution_m:
        raise ValueError("raw tiles must retain the source navigation resolution")
    if any(
        not _is_grid_aligned(value, reference, source.resolution_m)
        for value, reference in zip(tiles.origin_xy, expected_nav.origin_xy)
    ):
        raise ValueError("raw tile grid is not aligned to the source navigation grid")
    if isinstance(max_cells, bool) or not isinstance(max_cells, int) or not 1 <= max_cells <= _MAX_DENSE_CELLS:
        raise ValueError("max_cells must be an integer from 1 through 1,000,000")

    size = tiles.tile_size
    min_row: int | None = None
    min_col: int | None = None
    max_row: int | None = None
    max_col: int | None = None
    for (tile_row, tile_col), tile in tiles.tiles.items():
        rows = np.flatnonzero(np.any(tile != GridState.UNKNOWN, axis=1))
        if not rows.size:
            continue
        cols = np.flatnonzero(np.any(tile != GridState.UNKNOWN, axis=0))
        row_lo, row_hi = tile_row * size + int(rows[0]), tile_row * size + int(rows[-1])
        col_lo, col_hi = tile_col * size + int(cols[0]), tile_col * size + int(cols[-1])
        min_row = row_lo if min_row is None else min(min_row, row_lo)
        max_row = row_hi if max_row is None else max(max_row, row_hi)
        min_col = col_lo if min_col is None else min(min_col, col_lo)
        max_col = col_hi if max_col is None else max(max_col, col_hi)

    if min_row is None:
        states = np.full((1, 1), GridState.UNKNOWN, dtype=np.int8)
        return replace(
            source,
            origin_xy=source.origin_xy,
            resolution_m=source.resolution_m,
            states=states,
            floor_support=np.zeros((1, 1), dtype=np.bool_),
            clearance=np.zeros((1, 1), dtype=np.float64),
        )

    height = max_row - min_row + 1
    width = max_col - min_col + 1
    dense_cells = height * width
    if dense_cells > max_cells:
        raise RoomMapUnavailable(f"raw room-map extent exceeds max_cells ({dense_cells}>{max_cells})")

    states = np.full((height, width), GridState.UNKNOWN, dtype=np.int8)
    for (tile_row, tile_col), tile in tiles.tiles.items():
        tile_row_start = tile_row * size
        tile_col_start = tile_col * size
        row_start = max(min_row, tile_row_start)
        row_stop = min(max_row + 1, tile_row_start + size)
        col_start = max(min_col, tile_col_start)
        col_stop = min(max_col + 1, tile_col_start + size)
        if row_start >= row_stop or col_start >= col_stop:
            continue
        states[
            row_start - min_row : row_stop - min_row,
            col_start - min_col : col_stop - min_col,
        ] = tile[
            row_start - tile_row_start : row_stop - tile_row_start,
            col_start - tile_col_start : col_stop - tile_col_start,
        ]

    resolution = source.resolution_m
    origin = (
        tiles.origin_xy[0] + min_col * resolution,
        tiles.origin_xy[1] + min_row * resolution,
    )
    free = states == GridState.FREE
    clearance = np.where(free, np.float64(evidence.robot.height_m), np.float64(0.0))
    return replace(
        source,
        origin_xy=origin,
        resolution_m=resolution,
        states=states,
        floor_support=free,
        clearance=clearance,
    )
