"""Collect bounded measured-only ray votes without changing mapper kernels."""

from __future__ import annotations

import math

import numpy as np

from ._raycast_kernel import RaycastVotes, collect_ray_votes


_MAX_FRAME_RAYS = 100_000
_MAX_VOTE_CELLS = 1_000_000
_MAX_VOTE_BYTES = 128 * 1024 * 1024
_ROUNDING_ULPS = 64.0


def collect_local_measured_votes(obs, core, bounds_xy, *, grid_bounds=None) -> tuple[RaycastVotes, int, int]:
    """Collect measured-depth votes that could affect a local XY rectangle.

    ``bounds_xy`` is ``((min_x, min_y), (max_x, max_y))`` in canonical world
    meters. Candidate rays are retained when their complete camera-to-return
    segment intersects that rectangle expanded by two grid cells and the
    mapper's conservative floor-to-body-height slab. This includes endpoint
    hits and every sampled free-space vote in the requested cells. The ray
    traversal and vote thresholds remain those of :func:`collect_ray_votes`.

    Only ``valid_depth`` measurements within the mapper's normal depth limits
    are projected. Certified no-return and far-plane samples never become
    local votes. The returned counts are the number of usable measured rays
    before spatial clipping and the number retained for ray traversal.

    The helper is read-only: it does not alter ``obs`` or ``core``.
    ``grid_bounds`` optionally restricts vote allocation and traversal to the
    exact half-open raster window. Its world rectangle must lie inside
    ``bounds_xy``; callers retain the original ray lattice and endpoint rules.
    """
    bounds = _validated_bounds(bounds_xy)
    stride = core.sampling_stride
    if isinstance(stride, bool) or not isinstance(stride, int) or stride <= 0:
        raise ValueError("core sampling stride must be a positive integer")

    resolution = float(core.grid.resolution_m)
    floor_y = float(core.grid.floor_y_m)
    height_bin = float(core.height_bin_m)
    robot_height = float(core.robot_height_m)
    min_depth = float(core.min_depth_m)
    max_depth = float(core.max_depth_m)
    ray_step = float(core._ray_step_m)
    geometry = (resolution, floor_y, height_bin, robot_height,
                min_depth, max_depth, ray_step)
    if (not all(math.isfinite(value) for value in geometry)
            or resolution <= 0.0 or height_bin <= 0.0
            or robot_height <= height_bin or min_depth <= 0.0
            or max_depth <= min_depth or ray_step <= 0.0):
        raise ValueError("core ray geometry is invalid")

    sampled_depth = np.asarray(obs.depth_m)[::stride, ::stride]
    sampled_valid = np.asarray(obs.valid_depth)[::stride, ::stride]
    usable = (sampled_valid & np.isfinite(sampled_depth)
              & (sampled_depth >= min_depth) & (sampled_depth < max_depth))
    candidate_ray_count = int(np.count_nonzero(usable))
    if candidate_ray_count > _MAX_FRAME_RAYS:
        raise MemoryError("per-frame ray count budget exceeded")

    sample_v, sample_u = np.nonzero(usable)
    depths = sampled_depth[sample_v, sample_u].astype(np.float64)
    pixels = np.column_stack((sample_u * stride, sample_v * stride,
                              np.ones(len(depths))))
    try:
        inverse_intrinsics = np.linalg.inv(np.asarray(obs.K, dtype=np.float64))
    except np.linalg.LinAlgError as exc:
        raise ValueError("camera intrinsics must be invertible") from exc
    rays = pixels @ inverse_intrinsics.T
    finite_rays = np.isfinite(rays).all(axis=1) & (np.abs(rays[:, 2]) >= 1e-12)
    rays = rays[finite_rays]
    depths = depths[finite_rays]
    rays /= rays[:, 2:3]
    camera_points = rays * depths[:, None]
    input_ray_count = len(camera_points)

    # Match NavMapper._adapt and OccupancyMapper._integrate's private
    # (planar-x, height, planar-y) world layout and arithmetic order exactly.
    private_pose = np.asarray(obs.T_world_camera, dtype=np.float64)[[0, 2, 1, 3], :]
    camera_origin = private_pose[:3, 3]
    rotation = private_pose[:3, :3]
    endpoints = camera_points @ rotation.T + camera_origin
    if not np.isfinite(camera_origin).all() or not np.isfinite(endpoints).all():
        raise ValueError("projected measured rays must remain finite")

    xmin, ymin = bounds[0]
    xmax, ymax = bounds[1]
    planar_margin = 2.0 * resolution
    lower = np.array((xmin - planar_margin,
                      floor_y - height_bin,
                      ymin - planar_margin), dtype=np.float64)
    upper = np.array((xmax + planar_margin,
                      floor_y + robot_height + height_bin,
                      ymax + planar_margin), dtype=np.float64)
    if not np.isfinite(lower).all() or not np.isfinite(upper).all():
        raise ValueError("expanded local bounds must remain finite")

    scale = max(1.0, float(np.max(np.abs(camera_origin))),
                float(np.max(np.abs(lower))), float(np.max(np.abs(upper))))
    if len(endpoints):
        scale = max(scale, float(np.max(np.abs(endpoints))))
    epsilon = max(1e-12, _ROUNDING_ULPS * np.finfo(np.float64).eps * scale)
    retained = _segments_intersect_box(camera_origin, endpoints,
                                       lower - epsilon, upper + epsilon)
    endpoints = np.ascontiguousarray(endpoints[retained], dtype=np.float64)
    selected_ray_count = len(endpoints)
    if selected_ray_count > _MAX_FRAME_RAYS:
        raise MemoryError("local ray count budget exceeded")
    _check_vote_raster_budget(endpoints, camera_origin, core)

    votes = collect_ray_votes(
        endpoints,
        camera_origin,
        resolution_m=resolution,
        origin_x_m=float(core.grid.origin_x_m),
        origin_z_m=float(core.grid.origin_z_m),
        floor_y_m=floor_y,
        robot_height_m=robot_height,
        height_bin_m=height_bin,
        ray_step_m=ray_step,
        workers=1,
        grid_bounds=grid_bounds,
    )
    return votes, input_ray_count, selected_ray_count


def _validated_bounds(bounds_xy) -> np.ndarray:
    try:
        bounds = np.asarray(bounds_xy, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("bounds must be finite ((min_x, min_y), (max_x, max_y))") from exc
    if (bounds.shape != (2, 2) or not np.isfinite(bounds).all()
            or np.any(bounds[1] < bounds[0])):
        raise ValueError("bounds must be finite and ordered ((min_x, min_y), (max_x, max_y))")
    return bounds


def _segments_intersect_box(origin: np.ndarray, endpoints: np.ndarray,
                            lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """Inclusive vectorized slab test for camera-to-endpoint segments."""
    count = len(endpoints)
    if count == 0:
        return np.zeros(0, dtype=np.bool_)
    delta = endpoints - origin
    enter = np.zeros(count, dtype=np.float64)
    leave = np.ones(count, dtype=np.float64)
    keep = np.ones(count, dtype=np.bool_)
    for axis in range(3):
        parallel = np.abs(delta[:, axis]) < 1e-15
        outside = (origin[axis] < lower[axis]) | (origin[axis] > upper[axis])
        keep &= ~(parallel & outside)
        moving = ~parallel
        near = np.full(count, -np.inf, dtype=np.float64)
        far = np.full(count, np.inf, dtype=np.float64)
        if moving.any():
            first = (lower[axis] - origin[axis]) / delta[moving, axis]
            second = (upper[axis] - origin[axis]) / delta[moving, axis]
            near[moving] = np.minimum(first, second)
            far[moving] = np.maximum(first, second)
        enter = np.maximum(enter, near)
        leave = np.minimum(leave, far)
        keep &= enter <= leave
    return keep


def _check_vote_raster_budget(endpoints: np.ndarray, origin: np.ndarray, core) -> None:
    """Retain the mapper's existing dense vote-buffer limits after clipping."""
    if not len(endpoints):
        return
    planar_points = np.vstack((origin[[0, 2]], endpoints[:, (0, 2)]))
    grid_origin = np.array((core.grid.origin_x_m, core.grid.origin_z_m), dtype=np.float64)
    resolution = float(core.grid.resolution_m)
    extent = (np.floor((planar_points.max(axis=0) - grid_origin) / resolution)
              - np.floor((planar_points.min(axis=0) - grid_origin) / resolution) + 3)
    if (not np.isfinite(extent).all() or extent[0] <= 0.0 or extent[1] <= 0.0
            or extent[0] > _MAX_VOTE_CELLS / extent[1]):
        raise MemoryError("per-frame ray raster extent budget exceeded")
    vote_bytes = int(extent[0]) * int(extent[1]) * (3 + 2 * core.height_bin_count)
    if vote_bytes > _MAX_VOTE_BYTES:
        raise MemoryError("per-frame vote buffer budget exceeded")
