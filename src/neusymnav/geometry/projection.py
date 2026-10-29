"""Projection from optical camera pixels; depth defaults to metric axial."""
from __future__ import annotations
import numpy as np
from .frames import validate_intrinsics, validate_pose


def project_pixel_to_world(u: float, v: float, depth_m: float, K: np.ndarray,
                           T_world_camera: np.ndarray, *, depth_mode: str = 'axial') -> np.ndarray:
    if not np.isfinite([u, v, depth_m]).all() or depth_m <= 0:
        raise ValueError('pixel coordinates and positive depth must be finite')
    k, pose = validate_intrinsics(K), validate_pose(T_world_camera)
    ray = np.linalg.solve(k, np.array([u, v, 1.], dtype=np.float64))
    if depth_mode == 'axial':
        point = ray * depth_m
    elif depth_mode == 'range':
        point = ray * (depth_m / np.linalg.norm(ray))
    else:
        raise ValueError('depth_mode must be axial or range')
    return pose[:3, :3] @ point + pose[:3, 3]


def unproject_depth(depth_m: np.ndarray, valid_depth: np.ndarray, K: np.ndarray,
                    T_world_camera: np.ndarray) -> np.ndarray:
    """Return measured valid pixels in row-major order as float64 world Nx3."""
    depth, valid = np.asarray(depth_m), np.asarray(valid_depth)
    if depth.ndim != 2 or valid.shape != depth.shape or valid.dtype != np.bool_:
        raise ValueError('depth and bool validity must have matching HxW shapes')
    if np.any(valid & (~np.isfinite(depth) | (depth <= 0))):
        raise ValueError('valid depth must be positive and finite')
    k, pose = validate_intrinsics(K), validate_pose(T_world_camera)
    rows, cols = np.nonzero(valid)
    pixels = np.stack([cols, rows, np.ones(len(rows))])
    camera = np.linalg.solve(k, pixels) * depth[valid][None, :]
    return camera.T @ pose[:3, :3].T + pose[:3, 3]
