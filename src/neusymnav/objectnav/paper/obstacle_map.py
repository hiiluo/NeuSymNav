"""2D obstacle / explored map from the forward RGB-D camera (paper mode, VLFM-style).

Frame: canonical_z_up_v1 (x, y on the floor, z up), the frame of ``Observation.T_world_camera``.
The body base height is the simulator pose (GPS-equivalent), so no floor datum is measured.

Per frame, depth pixels (subsampled) are back-projected to world points; along each camera ray:

* a point whose height above the base is in ``[obstacle_min_h_m, agent_height_m]`` is an obstacle
  (lower is climbable / floor, higher is above the body);
* a point below the base is not an obstacle (as in VLFM): standing on a stair step, the floor would
  otherwise turn into a wall of obstacles. ``drop_h_m`` only bounds the free-space tracing below;
* the ray samples between the camera and the end point, while they are inside the body's height
  band, mark cells explored. Pixels at the clipped max range end at max range.

Explored and not obstacle is free; not explored is unknown. A forward move the simulator refused
marks the spot in front of the body as obstacle; repeated refusals at one spot become a wall segment
kept at full inflation even when the planner relaxes it. The cells under the body are always free.
Collision safety is the simulator's job in this mode: the map only has to be good enough to plan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage


@dataclass
class Frontier:
    cell: Tuple[int, int]           # frontier cell closest to the cluster centroid
    xy: Tuple[float, float]
    size: int                       # cells in the cluster


@dataclass
class _Level:
    z_m: float
    explored: np.ndarray
    obstacle: np.ndarray
    hits: np.ndarray
    bumps: Optional[np.ndarray] = None     # walls from repeated refused moves at one spot (never relaxed)
    bump_points: List[Tuple[float, float]] = field(default_factory=list)


class ObstacleMap:
    def __init__(self, *, origin_xy: Tuple[float, float], size_m: float = 60.0, resolution_m: float = 0.05,
                 agent_radius_m: float = 0.18, agent_height_m: float = 0.88, obstacle_min_h_m: float = 0.2,
                 drop_h_m: float = 0.25, max_range_m: float = 5.0, stride: int = 4, ray_stride: int = 8, min_hits: int = 1,
                 level_change_m: float = 0.5):
        self.res = float(resolution_m)
        self.n = int(round(size_m / self.res))
        self.origin = (float(origin_xy[0]) - self.n * self.res / 2, float(origin_xy[1]) - self.n * self.res / 2)
        self.radius, self.height = float(agent_radius_m), float(agent_height_m)
        self.obstacle_min_h, self.drop_h, self.max_range = float(obstacle_min_h_m), float(drop_h_m), float(max_range_m)
        self.stride, self.ray_stride = int(stride), int(ray_stride)
        self.min_hits, self.level_change = int(min_hits), float(level_change_m)
        self.levels: List[_Level] = []
        self.level: Optional[_Level] = None
        self.collision_marks = 0
        self.repeat_bumps = 0

    # -- geometry helpers
    def cell(self, xy) -> Tuple[int, int]:
        return (int(math.floor((xy[1] - self.origin[1]) / self.res)), int(math.floor((xy[0] - self.origin[0]) / self.res)))

    def xy(self, cell) -> Tuple[float, float]:
        return (self.origin[0] + (cell[1] + 0.5) * self.res, self.origin[1] + (cell[0] + 0.5) * self.res)

    def inside(self, cell) -> bool:
        return 0 <= cell[0] < self.n and 0 <= cell[1] < self.n

    def _cells(self, x, y):
        r = np.floor((y - self.origin[1]) / self.res).astype(np.int64)
        c = np.floor((x - self.origin[0]) / self.res).astype(np.int64)
        ok = (r >= 0) & (r < self.n) & (c >= 0) & (c < self.n)
        return r[ok], c[ok], ok

    def _select_level(self, base_z: float) -> _Level:
        for level in self.levels:
            if abs(level.z_m - base_z) <= self.level_change:
                self.level = level
                return level
        shape = (self.n, self.n)
        level = _Level(base_z, np.zeros(shape, bool), np.zeros(shape, bool), np.zeros(shape, np.int16),
                       np.zeros(shape, bool))
        self.levels.append(level)
        self.level = level
        return level

    @property
    def explored(self) -> np.ndarray:
        return self.level.explored

    @property
    def obstacle(self) -> np.ndarray:
        return self.level.obstacle

    # -- updates
    def _points(self, observation, stride: int, base_z_m: float):
        depth = np.asarray(observation.depth_m, np.float64)[::stride, ::stride]
        valid = np.asarray(observation.valid_depth, bool)[::stride, ::stride]
        h, w = depth.shape
        rows, cols = np.mgrid[0:h, 0:w]
        rows, cols = rows * stride, cols * stride
        K = np.asarray(observation.K, np.float64)
        T = np.asarray(observation.T_world_camera, np.float64)
        keep = np.isfinite(depth) & ((valid & (depth > 0)) | (depth == np.float32(self.max_range)))
        d = depth[keep]
        cam = np.stack(((cols[keep] - K[0, 2]) * d / K[0, 0],
                        (rows[keep] - K[1, 2]) * d / K[1, 1], d), axis=-1)
        world = cam @ T[:3, :3].T + T[:3, 3]
        valid = valid[keep]
        rel_h = world[:, 2] - base_z_m
        is_obstacle = valid & (rel_h >= self.obstacle_min_h) & (rel_h <= self.height)
        return T[:3, 3], world, is_obstacle

    def update(self, observation, *, robot_xy, base_z_m: float) -> None:
        level = self._select_level(float(base_z_m))
        # explored: samples along each (coarser) ray, inside the body band, before the end point
        origin, world, is_obstacle = self._points(observation, self.ray_stride, base_z_m)
        samples = max(2, int(math.ceil(self.max_range / self.res)))
        t = (np.arange(1, samples + 1) / samples)[None, :, None]
        pts = origin[None, None, :] + t * (world - origin)[:, None, :]          # rays x samples x 3
        length = np.linalg.norm(world - origin, axis=1)
        rel = pts[..., 2] - base_z_m
        keep = (rel <= self.height) & (rel >= -self.drop_h)
        before_end = (t[..., 0] * length[:, None]) <= (length[:, None] - self.res)
        keep &= np.where(is_obstacle[:, None], before_end, True)
        r, c, _ = self._cells(pts[..., 0][keep], pts[..., 1][keep])
        if len(r):
            # far rays are > 1 cell apart: close the gaps of THIS frame's fan (bounding box only)
            r0, r1, c0, c1 = r.min(), r.max() + 1, c.min(), c.max() + 1
            frame = np.zeros((r1 - r0, c1 - c0), bool)
            frame[r - r0, c - c0] = True
            frame = ndimage.binary_closing(np.pad(frame, 2), structure=np.ones((3, 3), bool), iterations=2)[2:-2, 2:-2]
            level.explored[r0:r1, c0:c1] |= frame
        # obstacles: denser points
        _, world, is_obstacle = self._points(observation, self.stride, base_z_m)
        r, c, _ = self._cells(world[is_obstacle, 0], world[is_obstacle, 1])
        np.add.at(level.hits, (r, c), 1)
        level.obstacle |= level.hits >= self.min_hits
        level.explored[r, c] = True
        self._clear_body(robot_xy)

    def _disc(self, xy, radius_m):
        cr, cc = self.cell(xy)
        k = int(math.ceil(radius_m / self.res)) + 1
        r0, r1, c0, c1 = max(0, cr - k), min(self.n, cr + k + 1), max(0, cc - k), min(self.n, cc + k + 1)
        rr, ccs = np.mgrid[r0:r1, c0:c1]
        cx = self.origin[0] + (ccs + 0.5) * self.res
        cy = self.origin[1] + (rr + 0.5) * self.res
        inside = np.hypot(cx - xy[0], cy - xy[1]) <= radius_m
        return rr[inside], ccs[inside]

    def _clear_body(self, robot_xy) -> None:
        r, c = self._disc(robot_xy, self.radius)
        self.level.explored[r, c] = True
        self.level.obstacle[r, c] = False
        self.level.hits[r, c] = 0
        if self.level.bumps is not None:
            self.level.bumps[r, c] = False

    def mark_collision(self, robot_xy, yaw_rad: float, step_m: float = 0.25, half_width_m: float = 0.25,
                       repeat_m: float = 0.35) -> None:
        """The simulator refused a forward move: block the spot just ahead of the body.

        A first refusal marks a small disc (a door jamb hit at an angle must not seal the door; a
        relaxed plan may still pass beside it). A refusal within ``repeat_m`` of an earlier one means
        an edge the camera does not see (navmesh edge at a drop, a low sill): it becomes a wall
        segment perpendicular to the heading, ``2 * half_width_m`` long, kept at full inflation."""
        cx, sy = math.cos(yaw_rad), math.sin(yaw_rad)
        d = self.radius + 0.1
        ahead = (robot_xy[0] + cx * d, robot_xy[1] + sy * d)
        repeat = any(math.dist(ahead, q) <= repeat_m for q in self.level.bump_points)
        self.level.bump_points.append(ahead)
        if repeat:
            rows, cols = [], []
            for t in np.arange(-half_width_m, half_width_m + 1e-9, self.res / 2):
                r, c = self._disc((ahead[0] - sy * t, ahead[1] + cx * t), 0.05)
                rows.append(r)
                cols.append(c)
            r, c = np.concatenate(rows), np.concatenate(cols)
            self.level.bumps[r, c] = True
            self.repeat_bumps += 1
        else:
            r, c = self._disc(ahead, 0.1)
        self.level.obstacle[r, c] = True
        self.level.hits[r, c] = np.maximum(self.level.hits[r, c], self.min_hits)
        self.level.explored[r, c] = True
        self.collision_marks += 1
        self._clear_body(robot_xy)

    # -- derived layers
    def traversable(self, robot_xy, inflate_m: Optional[float] = None) -> np.ndarray:
        inflate = self.radius if inflate_m is None else float(inflate_m)
        k = int(math.ceil(inflate / self.res))
        yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
        struct = (yy ** 2 + xx ** 2) * self.res ** 2 <= inflate ** 2 + 1e-9
        blocked = ndimage.binary_dilation(self.level.obstacle, structure=struct)
        if inflate < self.radius and self.level.bumps is not None and self.level.bumps.any():
            k = int(math.ceil(self.radius / self.res))      # a relaxed plan must not squeeze past a bump
            yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
            full = (yy ** 2 + xx ** 2) * self.res ** 2 <= self.radius ** 2 + 1e-9
            blocked |= ndimage.binary_dilation(self.level.bumps, structure=full)
        free = self.level.explored & ~blocked
        # the body stands here: its centre neighbourhood is a valid start even inside the inflation
        r, c = self._disc(robot_xy, 0.1)
        free[r, c] = ~self.level.obstacle[r, c]
        return free

    def frontiers(self, traversable: np.ndarray, min_cells: int = 5) -> List[Frontier]:
        unknown = ~self.level.explored
        near_unknown = ndimage.binary_dilation(unknown, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool))
        cells = traversable & near_unknown & self.level.explored
        labels, count = ndimage.label(cells, structure=np.ones((3, 3), bool))
        out = []
        for i in range(1, count + 1):
            rr, cc = np.nonzero(labels == i)
            if len(rr) < min_cells:
                continue
            j = int(np.argmin((rr - rr.mean()) ** 2 + (cc - cc.mean()) ** 2))
            cell = (int(rr[j]), int(cc[j]))
            out.append(Frontier(cell, self.xy(cell), len(rr)))
        return out

    def explored_area_m2(self) -> float:
        return float(sum(level.explored.sum() for level in self.levels)) * self.res ** 2
