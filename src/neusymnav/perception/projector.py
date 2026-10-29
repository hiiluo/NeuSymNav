"""Exact source-frame projection; NumPy port of NewOH3DSG projection algorithms."""
from __future__ import annotations
import numpy as np
from ..contracts.observations import (ObjectObservation, validate_detection_batch,
                                      validate_object_observations)


class Projector:
    VOXEL_SIZE_M = 0.03
    MIN_DEPTH_M = 0.15
    MAX_DEPTH_M = 5.0
    DEPTH_CLUSTER_GAP_M = 0.05

    def __init__(self, *, min_points=30, max_points=4096):
        if type(min_points) is not int or min_points <= 0 or type(max_points) is not int or max_points <= 0:
            raise ValueError('point budgets must be positive integers')
        self.min_points, self.max_points = min_points, max_points

    def project(self, observation, batch):
        validate_detection_batch(observation, batch)
        valid = (observation.valid_depth & (observation.depth_m >= self.MIN_DEPTH_M)
                 & (observation.depth_m < self.MAX_DEPTH_M))
        inverse = np.linalg.inv(observation.K)
        pose = observation.T_world_camera
        results = []
        for detection in batch.detections:
            selected = np.flatnonzero((detection.mask & valid).ravel())
            depths = observation.depth_m.ravel()[selected]
            if len(depths) < self.min_points:
                continue
            keep = self._median_depth_component(depths)
            selected, depths = selected[keep], depths[keep].astype(np.float64)
            if len(depths) < self.min_points:
                continue
            rows, cols = np.divmod(selected, observation.depth_m.shape[1])
            pixels = np.column_stack((cols, rows, np.ones_like(cols)))
            camera = (pixels @ inverse.T) * depths[:, None]
            points = camera @ pose[:3, :3].T + pose[:3, 3]
            cloud, _ = self._voxelize(points)
            if len(cloud) > self.max_points:
                cloud = cloud[np.linspace(0, len(cloud)-1, self.max_points, dtype=np.int64)]
            results.append(ObjectObservation(observation.key, detection.detection_id,
                batch.geometry_hash, cloud, tuple(pose[:3, 3]), detection.raw_label,
                detection.category, detection.score, 'detected', None))
        result = tuple(results)
        validate_object_observations(observation, batch, result)
        return result

    @classmethod
    def _median_depth_component(cls, depths: np.ndarray) -> np.ndarray:
        """Keep the sorted depth cluster containing the median support pixel."""
        if depths.size <= 1:
            return np.ones(depths.shape, dtype=np.bool_)
        depth_range = float(np.ptp(depths))
        if depth_range <= cls.DEPTH_CLUSTER_GAP_M:
            return np.ones(depths.shape, dtype=np.bool_)
        sorted_depths = np.sort(depths)
        midpoint = sorted_depths.size // 2
        median_depth = float(
            sorted_depths[midpoint]
            if sorted_depths.size % 2
            else (sorted_depths[midpoint - 1] + sorted_depths[midpoint]) * 0.5
        )
        gap_limit = max(cls.DEPTH_CLUSTER_GAP_M, 0.03 * median_depth)
        if depth_range <= gap_limit:
            return np.ones(depths.shape, dtype=np.bool_)
        gaps = np.flatnonzero(np.diff(sorted_depths) > gap_limit)
        starts = np.concatenate(([0], gaps + 1))
        ends = np.concatenate((gaps + 1, [sorted_depths.size]))
        median_rank = sorted_depths.size // 2
        cluster_index = int(np.searchsorted(ends, median_rank, side="right"))
        component_depths = sorted_depths[starts[cluster_index] : ends[cluster_index]]
        component_midpoint = component_depths.size // 2
        center = float(
            component_depths[component_midpoint]
            if component_depths.size % 2
            else (component_depths[component_midpoint - 1] + component_depths[component_midpoint]) * 0.5
        )
        deviations = np.sort(np.abs(component_depths - center))
        deviation_midpoint = deviations.size // 2
        mad = float(
            deviations[deviation_midpoint]
            if deviations.size % 2
            else (deviations[deviation_midpoint - 1] + deviations[deviation_midpoint]) * 0.5
        )
        tolerance = max(0.03, 3.0 * 1.4826 * mad)
        return (
            (depths >= component_depths[0])
            & (depths <= component_depths[-1])
            & (np.abs(depths - center) <= tolerance)
        )

    @classmethod
    def _voxelize(cls, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        voxel_indices = np.floor(points / cls.VOXEL_SIZE_M).astype(np.int64)
        # The row-major Nx3 layout makes each per-axis reduction strided. A
        # contiguous 3xN view keeps the three min/max reductions cache-friendly.
        voxel_columns = np.ascontiguousarray(voxel_indices.T)
        voxel_min = voxel_columns.min(axis=1)
        voxel_max = voxel_columns.max(axis=1)
        shifted = voxel_columns - voxel_min[:, None]
        grid = voxel_max - voxel_min + 1
        # The source depth range bounds typical extents, while this guard keeps
        # the collision-free linear key safe for unusually large world frames.
        cell_count = int(grid[0]) * int(grid[1]) * int(grid[2])
        if cell_count <= 250_000:
            keys = (shifted[0] * grid[1] + shifted[1]) * grid[2] + shifted[2]
            counts_by_cell = np.bincount(keys, minlength=cell_count)
            occupied = np.flatnonzero(counts_by_cell)
            counts = counts_by_cell[occupied]
            sums = np.column_stack(
                [np.bincount(keys, weights=points[:, axis], minlength=cell_count)[occupied] for axis in range(3)]
            )
        else:
            if cell_count <= np.iinfo(np.int64).max:
                keys = (shifted[0] * grid[1] + shifted[1]) * grid[2] + shifted[2]
                _, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
            else:
                structured = np.empty(
                    voxel_indices.shape[0],
                    dtype=[("x", np.int64), ("y", np.int64), ("z", np.int64)],
                )
                structured["x"], structured["y"], structured["z"] = voxel_indices.T
                _, inverse, counts = np.unique(structured, return_inverse=True, return_counts=True)
            sums = np.column_stack(
                [np.bincount(inverse, weights=points[:, axis], minlength=counts.size) for axis in range(3)]
            )
        return sums / counts[:, None], counts

