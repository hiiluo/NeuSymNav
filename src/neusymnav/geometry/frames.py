"""Explicit right-handed world and camera frame conversions, in metres.

World conversion multiplies on the left. Camera basis conversion multiplies
on the right. Neither operation guesses an incoming convention.
"""
from __future__ import annotations
import math
from itertools import product
import numpy as np

NEW_Y_UP = 'new_y_up_v1'
CANONICAL_Z_UP = 'canonical_z_up_v1'
Y_UP_TO_Z_UP = np.frombuffer(np.array([[1., 0, 0], [0, 0, -1], [0, 1, 0]]).tobytes(), dtype=np.float64).reshape(3, 3)


def validate_rotation(R: np.ndarray) -> np.ndarray:
    r = np.asarray(R, dtype=np.float64)
    if r.shape != (3, 3) or not np.isfinite(r).all():
        raise ValueError('rotation must be finite 3x3')
    if not np.allclose(r.T @ r, np.eye(3), rtol=0, atol=1e-8) or not np.isclose(np.linalg.det(r), 1, rtol=0, atol=1e-8):
        raise ValueError('rotation must be orthonormal and right-handed')
    return r


def validate_pose(T: np.ndarray) -> np.ndarray:
    pose = np.asarray(T, dtype=np.float64)
    if pose.shape != (4, 4) or not np.isfinite(pose).all() or not np.allclose(pose[3], [0, 0, 0, 1], rtol=0, atol=1e-8):
        raise ValueError('pose must be finite homogeneous 4x4')
    validate_rotation(pose[:3, :3])
    return pose


def validate_intrinsics(K: np.ndarray) -> np.ndarray:
    k = np.asarray(K, dtype=np.float64)
    if k.shape != (3, 3) or not np.isfinite(k).all():
        raise ValueError('K must be finite 3x3')
    if k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1], rtol=0, atol=1e-10) or abs(k[1, 0]) > 1e-10:
        raise ValueError('K must be pinhole intrinsics with positive focal lengths')
    return k


def to_canonical_pose(T_old: np.ndarray, source_convention: str) -> np.ndarray:
    pose = validate_pose(T_old)
    if source_convention == CANONICAL_Z_UP:
        return pose.copy()
    if source_convention != NEW_Y_UP:
        raise ValueError('unknown source_convention')
    world = np.eye(4, dtype=np.float64)
    world[:3, :3] = Y_UP_TO_Z_UP
    return world @ pose


def habitat_to_optical_pose(T_world_habitat: np.ndarray) -> np.ndarray:
    """Change local Habitat (+X right,+Y up,-Z forward) to optical basis."""
    return validate_pose(T_world_habitat) @ np.diag([1., -1., -1., 1.])


def transform_vectors(vectors: np.ndarray, R: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float64)
    if values.ndim < 1 or values.shape[-1] != 3 or not np.isfinite(values).all():
        raise ValueError('vectors must be finite [...,3]')
    return values @ validate_rotation(R).T


def transform_bounds(bounds: np.ndarray, R: np.ndarray) -> np.ndarray:
    values = np.asarray(bounds, dtype=np.float64)
    if values.shape != (2, 3) or not np.isfinite(values).all() or np.any(values[0] > values[1]):
        raise ValueError('bounds must be ordered finite [min,max] 2x3')
    corners = np.array(list(product(*zip(values[0], values[1]))), dtype=np.float64)
    converted = transform_vectors(corners, R)
    return np.stack([converted.min(axis=0), converted.max(axis=0)])


def transform_covariance(covariance: np.ndarray, R: np.ndarray) -> np.ndarray:
    c = np.asarray(covariance, dtype=np.float64)
    if c.shape != (3, 3) or not np.isfinite(c).all() or not np.allclose(c, c.T, rtol=0, atol=1e-8):
        raise ValueError('covariance must be finite symmetric 3x3')
    if np.linalg.eigvalsh(c).min() < -1e-8:
        raise ValueError('covariance must be positive semidefinite')
    r = validate_rotation(R)
    return r @ c @ r.T


def transform_heading(heading_rad: float, R: np.ndarray, *, source_convention: str = CANONICAL_Z_UP) -> float:
    """Heading is a directed horizontal vector, then atan2 in canonical XY.

    New's horizontal reference is +X toward -Z (positive rotation about +Y).
    Canonical's reference is +X toward +Y (positive rotation about +Z).
    """
    if not math.isfinite(heading_rad):
        raise ValueError('heading must be finite')
    if source_convention == NEW_Y_UP:
        direction = [math.cos(heading_rad), 0., -math.sin(heading_rad)]
    elif source_convention == CANONICAL_Z_UP:
        direction = [math.cos(heading_rad), math.sin(heading_rad), 0.]
    else:
        raise ValueError('unknown source_convention')
    transformed = transform_vectors(direction, R)
    if np.linalg.norm(transformed[:2]) < 1e-10:
        raise ValueError('transformed heading has no horizontal direction')
    return math.atan2(transformed[1], transformed[0])
