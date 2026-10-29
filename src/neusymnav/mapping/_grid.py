from dataclasses import dataclass
from math import floor, isfinite
from operator import index


@dataclass(frozen=True)
class GridSpec:
    """World/grid coordinate convention and global tile dimensions.

    Grid rows increase with world +z and columns increase with world +x.
    Cell and tile indices are global, so negative coordinates use the same
    floor-based partition as positive coordinates.
    """

    resolution_m: float = 0.05
    tile_size_cells: int = 256
    origin_x_m: float = 0.0
    origin_z_m: float = 0.0
    floor_y_m: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.resolution_m) or self.resolution_m <= 0:
            raise ValueError("resolution_m must be finite and positive")
        if isinstance(self.tile_size_cells, bool) or not isinstance(self.tile_size_cells, int) or self.tile_size_cells <= 0:
            raise ValueError("tile_size_cells must be a positive integer")
        if not all(isfinite(value) for value in (self.origin_x_m, self.origin_z_m, self.floor_y_m)):
            raise ValueError("grid origin and floor height must be finite")

    def world_to_grid(self, x: float, z: float) -> tuple[int, int]:
        """Return the global ``(row, col)`` cell containing world ``(x, z)``."""
        row = floor((z - self.origin_z_m) / self.resolution_m)
        col = floor((x - self.origin_x_m) / self.resolution_m)
        return row, col

    def grid_to_world(self, row: int, col: int) -> tuple[float, float, float]:
        """Return the center ``(x, y, z)`` of a global grid cell."""
        row = index(row)
        col = index(col)
        half_cell = 0.5 * self.resolution_m
        x = self.origin_x_m + (col * self.resolution_m) + half_cell
        z = self.origin_z_m + (row * self.resolution_m) + half_cell
        return x, self.floor_y_m, z

    def grid_to_tile(self, row: int, col: int) -> tuple[int, int, int, int]:
        """Return ``(tile_row, tile_col, local_row, local_col)`` for a cell."""
        row = index(row)
        col = index(col)
        tile_row, local_row = divmod(row, self.tile_size_cells)
        tile_col, local_col = divmod(col, self.tile_size_cells)
        return tile_row, tile_col, local_row, local_col
