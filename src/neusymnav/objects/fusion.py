"""Bounded per-object voxel means with one capped vote per frame."""

from __future__ import annotations

import math

import numpy as np


class VoxelCloud:
    def __init__(self, *, voxel_m: float = 0.03, max_voxels: int = 4096, max_weight: int = 20) -> None:
        if not math.isfinite(voxel_m) or voxel_m <= 0:
            raise ValueError("voxel size must be positive and finite")
        if max_voxels <= 0 or max_weight <= 0:
            raise ValueError("voxel and weight caps must be positive")
        self.voxel_m = voxel_m
        self.max_voxels = max_voxels
        self.max_weight = max_weight
        self._voxels: dict[tuple[int, int, int], tuple[np.ndarray, int]] = {}
        self.truncated_voxel_count = 0

    @property
    def point_count(self) -> int:
        return len(self._voxels)

    def fork(self) -> "VoxelCloud":
        """Copy mutable vote state while sharing immutable voxel-center arrays."""
        result = VoxelCloud(
            voxel_m=self.voxel_m,
            max_voxels=self.max_voxels,
            max_weight=self.max_weight,
        )
        result._voxels = dict(self._voxels)
        result.truncated_voxel_count = self.truncated_voxel_count
        return result

    @property
    def max_observation_weight(self) -> int:
        return max((weight for _, weight in self._voxels.values()), default=0)

    def integrate(self, points_world: np.ndarray) -> None:
        points = np.asarray(points_world, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
            raise ValueError("voxel input must be finite (N, 3) points")
        if len(points) == 0:
            return
        keys, inverse = np.unique(np.floor(points / self.voxel_m).astype(np.int64), axis=0, return_inverse=True)
        sums = np.zeros((len(keys), 3), dtype=np.float64)
        np.add.at(sums, inverse, points)
        counts = np.bincount(inverse)
        for key_array, sample in zip(keys, sums / counts[:, None]):
            key = tuple(int(v) for v in key_array)
            prior = self._voxels.get(key)
            if prior is None:
                if len(self._voxels) >= self.max_voxels:
                    self.truncated_voxel_count += 1
                    continue
                self._voxels[key] = (sample, 1)
            else:
                center, weight = prior
                retained = min(weight, self.max_weight - 1)
                new_weight = min(weight + 1, self.max_weight)
                self._voxels[key] = ((center * retained + sample) / new_weight, new_weight)

    def points_world(self) -> np.ndarray:
        if not self._voxels:
            return np.empty((0, 3), dtype=np.float64)
        points = np.stack([self._voxels[key][0] for key in sorted(self._voxels)])
        return np.frombuffer(points.tobytes(), dtype=np.float64).reshape(points.shape)
