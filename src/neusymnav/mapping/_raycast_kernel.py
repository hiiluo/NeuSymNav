"""Ray traversal kernels that produce sparse-frame occupancy vote masks.

The caller projects usable depth pixels into world-space endpoints and passes
those ``float64[N, 3]`` coordinates to :func:`collect_ray_votes`. This module
returns boolean masks over a compact grid window; it does not mutate an
occupancy map or apply log-odds updates.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import numpy as np

try:
    from numba import njit
except ImportError:  # Numba is an optional acceleration dependency.
    njit = None


Backend = Literal["auto", "python", "numba"]


@dataclass(frozen=True)
class RaycastVotes:
    """Per-frame vote masks and their global grid origin.

    Array axes are ``[row - min_row, col - min_col]``. Height arrays add a
    third axis for the mapper's height bin. Returned free masks already exclude
    cells with an occupied vote in this frame, so occupied evidence wins.
    """

    min_row: int
    min_col: int
    planar_free: np.ndarray
    planar_hit: np.ndarray
    floor_hit: np.ndarray
    height_free: np.ndarray
    height_hit: np.ndarray


def numba_available() -> bool:
    """Return whether this interpreter can use the optional Numba backend."""
    return njit is not None


def _collect_votes_impl(
    endpoints_world: np.ndarray,
    has_return: np.ndarray,
    camera_origin_world: np.ndarray,
    resolution_m: float,
    origin_x_m: float,
    origin_z_m: float,
    floor_y_m: float,
    robot_height_m: float,
    height_bin_m: float,
    ray_step_m: float,
    min_row: int,
    min_col: int,
    rows: int,
    cols: int,
    height_bin_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    planar_free = np.zeros((rows, cols), dtype=np.bool_)
    planar_hit = np.zeros((rows, cols), dtype=np.bool_)
    floor_hit = np.zeros((rows, cols), dtype=np.bool_)
    height_free = np.zeros((rows, cols, height_bin_count), dtype=np.bool_)
    height_hit = np.zeros((rows, cols, height_bin_count), dtype=np.bool_)

    for ray_index in range(endpoints_world.shape[0]):
        end_x = endpoints_world[ray_index, 0]
        end_y = endpoints_world[ray_index, 1]
        end_z = endpoints_world[ray_index, 2]
        endpoint_height = end_y - floor_y_m
        if has_return[ray_index] and endpoint_height < -height_bin_m:
            continue

        end_row = math.floor((end_z - origin_z_m) / resolution_m)
        end_col = math.floor((end_x - origin_x_m) / resolution_m)
        local_end_row = end_row - min_row
        local_end_col = end_col - min_col
        if has_return[ray_index] and abs(endpoint_height) <= height_bin_m:
            floor_hit[local_end_row, local_end_col] = True

        obstacle_hit = has_return[ray_index] and height_bin_m <= endpoint_height <= robot_height_m
        endpoint_bin = -1
        if obstacle_hit:
            endpoint_bin = math.floor(endpoint_height / height_bin_m)
            if 0.0 <= endpoint_height <= robot_height_m:
                endpoint_bin = min(endpoint_bin, height_bin_count - 1)

        delta_x = end_x - camera_origin_world[0]
        delta_y = end_y - camera_origin_world[1]
        delta_z = end_z - camera_origin_world[2]
        distance = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)
        sample_count = max(1, math.ceil(distance / ray_step_m))

        pending = False
        pending_row = 0
        pending_col = 0
        pending_height = 0
        previous_row = 0
        previous_col = 0
        previous_height = 0
        for step in range(sample_count + 1):
            fraction = step / sample_count
            point_x = camera_origin_world[0] + delta_x * fraction
            point_y = camera_origin_world[1] + delta_y * fraction
            point_z = camera_origin_world[2] + delta_z * fraction
            row = math.floor((point_z - origin_z_m) / resolution_m)
            col = math.floor((point_x - origin_x_m) / resolution_m)
            relative_height = point_y - floor_y_m
            height = math.floor(relative_height / height_bin_m)
            if 0.0 <= relative_height <= robot_height_m:
                height = min(height, height_bin_count - 1)

            # Each coordinate is linear along a ray, so row, column, and height
            # bin are monotone (with the top-height clamp also monotone). A
            # voxel therefore cannot reappear after it changes; this transition
            # check has the same effect as a per-ray tuple set without allocating
            # one Python object per sample.
            if (
                not pending
                or row != previous_row
                or col != previous_col
                or height != previous_height
            ):
                if pending and 1 <= pending_height < height_bin_count:
                    local_row = pending_row - min_row
                    local_col = pending_col - min_col
                    height_free[local_row, local_col, pending_height] = True
                    planar_free[local_row, local_col] = True
                pending = True
                pending_row = row
                pending_col = col
                pending_height = height
            previous_row = row
            previous_col = col
            previous_height = height

        if obstacle_hit and 0 <= endpoint_bin < height_bin_count:
            height_hit[local_end_row, local_end_col, endpoint_bin] = True
            planar_hit[local_end_row, local_end_col] = True

    return planar_free, planar_hit, floor_hit, height_free, height_hit


_numba_collect_votes = njit(cache=False, nogil=True)(_collect_votes_impl) if njit is not None else None


def collect_ray_votes(
    endpoints_world: np.ndarray,
    camera_origin_world: np.ndarray,
    *,
    has_return: np.ndarray | None = None,
    resolution_m: float,
    origin_x_m: float,
    origin_z_m: float,
    floor_y_m: float,
    robot_height_m: float,
    height_bin_m: float,
    ray_step_m: float,
    backend: Backend = "auto",
    workers: int = 1,
) -> RaycastVotes:
    """Rasterize world-space ray endpoints into per-frame occupancy votes.

    ``endpoints_world`` must contain one finite world-space endpoint per usable
    projected depth pixel, in ``float64[N, 3]`` or array-like ``(N, 3)`` form.
    The camera origin and grid geometry use meters. Invalid depth filtering and
    camera projection happen at the caller boundary. Inputs must remain
    unchanged for the duration of the call; the native kernel releases the GIL
    and writes only task-local output arrays.

    The ``python`` backend needs only NumPy. ``numba`` requires Numba and compiles
    lazily on its first call; ``auto`` uses Numba when it is available and falls
    back to Python otherwise.
    """
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("raycast workers must be an integer from 1 to 4")
    endpoints = np.ascontiguousarray(endpoints_world, dtype=np.float64)
    if endpoints.ndim != 2 or endpoints.shape[1:] != (3,):
        raise ValueError("endpoints_world must have shape (N, 3)")
    if not np.isfinite(endpoints).all():
        raise ValueError("endpoints_world must contain only finite coordinates")
    if has_return is None:
        returns = np.ones(endpoints.shape[0], dtype=np.bool_)
    else:
        returns = np.asarray(has_return)
        if returns.shape != (endpoints.shape[0],) or returns.dtype != np.bool_:
            raise ValueError("has_return must be bool[N]")
        returns = np.ascontiguousarray(returns)

    camera_origin = np.ascontiguousarray(camera_origin_world, dtype=np.float64)
    if camera_origin.shape != (3,) or not np.isfinite(camera_origin).all():
        raise ValueError("camera_origin_world must be a finite vector with shape (3,)")

    geometry = (
        resolution_m,
        origin_x_m,
        origin_z_m,
        floor_y_m,
        robot_height_m,
        height_bin_m,
        ray_step_m,
    )
    if not all(math.isfinite(value) for value in geometry):
        raise ValueError("grid and ray geometry must be finite")
    if resolution_m <= 0.0 or height_bin_m <= 0.0 or ray_step_m <= 0.0:
        raise ValueError("resolution, height bin, and ray step must be positive")
    if robot_height_m <= height_bin_m:
        raise ValueError("robot_height_m must exceed one height bin")
    if backend not in ("auto", "python", "numba"):
        raise ValueError("backend must be 'auto', 'python', or 'numba'")
    if backend == "numba" and _numba_collect_votes is None:
        raise RuntimeError("Numba is not installed; use backend='python' or 'auto'")

    height_bin_count = math.ceil(robot_height_m / height_bin_m)
    if endpoints.shape[0] == 0:
        empty_planar = np.zeros((0, 0), dtype=np.bool_)
        empty_height = np.zeros((0, 0, height_bin_count), dtype=np.bool_)
        return RaycastVotes(
            0,
            0,
            empty_planar,
            empty_planar.copy(),
            empty_planar.copy(),
            empty_height,
            empty_height.copy(),
        )

    # Include the camera origin and every endpoint. Linear interpolation cannot
    # leave these row/column bounds, including for negative world coordinates.
    min_z = min(float(endpoints[:, 2].min()), float(camera_origin[2]))
    max_z = max(float(endpoints[:, 2].max()), float(camera_origin[2]))
    min_x = min(float(endpoints[:, 0].min()), float(camera_origin[0]))
    max_x = max(float(endpoints[:, 0].max()), float(camera_origin[0]))
    # Retain one guard cell because endpoint + delta * 1.0 can round across a
    # grid boundary even when the stored endpoint lies exactly on that boundary.
    min_row = math.floor((min_z - origin_z_m) / resolution_m) - 1
    max_row = math.floor((max_z - origin_z_m) / resolution_m) + 1
    min_col = math.floor((min_x - origin_x_m) / resolution_m) - 1
    max_col = math.floor((max_x - origin_x_m) / resolution_m) + 1
    rows = max_row - min_row + 1
    cols = max_col - min_col + 1

    use_numba = backend in ("auto", "numba") and _numba_collect_votes is not None
    kernel = _numba_collect_votes if use_numba else _collect_votes_impl
    arguments = (camera_origin, resolution_m, origin_x_m, origin_z_m, floor_y_m,
                 robot_height_m, height_bin_m, ray_step_m, min_row, min_col,
                 rows, cols, height_bin_count)
    # Disjoint task-local masks: no concurrent writes to a shared NumPy array.
    # Leave half of the existing128MiB vote budget for reduction temporaries.
    parallel_bytes = workers * rows * cols * (3 + 2 * height_bin_count)
    if workers > 1 and use_numba and len(endpoints) >= 256 and parallel_bytes <= 64 * 1024**2:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='raycast-votes') as pool:
            jobs = [pool.submit(kernel, endpoints[len(endpoints)*i//workers:len(endpoints)*(i+1)//workers],
                                returns[len(endpoints)*i//workers:len(endpoints)*(i+1)//workers], *arguments)
                    for i in range(workers)]
            masks = jobs[0].result()
            for job in jobs[1:]:
                for dst, src in zip(masks, job.result()):
                    np.logical_or(dst, src, out=dst)
        # Apply occupied-wins AFTER union across chunks, exactly as serial.
        planar_free, planar_hit, floor_hit, height_free, height_hit = masks
    else:
        planar_free, planar_hit, floor_hit, height_free, height_hit = kernel(endpoints, returns, *arguments)
    np.logical_and(planar_free, np.logical_not(planar_hit), out=planar_free)
    np.logical_and(height_free, np.logical_not(height_hit), out=height_free)
    return RaycastVotes(
        min_row,
        min_col,
        planar_free,
        planar_hit,
        floor_hit,
        height_free,
        height_hit,
    )
