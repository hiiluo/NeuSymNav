"""Grid shortest paths and the waypoint -> discrete action adapter (paper mode)."""
from __future__ import annotations

import heapq
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

try:
    from numba import njit
except ImportError:          # pragma: no cover - numba is in the project venv
    njit = None

SQRT2 = math.sqrt(2.0)


def _dijkstra(mask, penalty, start_r, start_c, max_cost):
    h, w = mask.shape
    dist = np.full((h, w), np.inf)
    parent = np.full((h, w), -1, np.int64)
    dist[start_r, start_c] = 0.0
    heap = [(0.0, start_r * w + start_c)]
    drs = (-1, 1, 0, 0, -1, -1, 1, 1)
    dcs = (0, 0, -1, 1, -1, 1, -1, 1)
    while heap:
        d, idx = heapq.heappop(heap)
        r, c = idx // w, idx % w
        if d > dist[r, c] or d > max_cost:
            continue
        for k in range(8):
            nr, nc = r + drs[k], c + dcs[k]
            if nr < 0 or nr >= h or nc < 0 or nc >= w or not mask[nr, nc]:
                continue
            if k >= 4 and (not mask[r + drs[k], c] or not mask[r, c + dcs[k]]):
                continue                         # no corner cutting
            nd = d + (1.0 if k < 4 else SQRT2) * (1.0 + penalty[nr, nc])
            if nd < dist[nr, nc]:
                dist[nr, nc] = nd
                parent[nr, nc] = idx
                heapq.heappush(heap, (nd, nr * w + nc))
    return dist, parent


_dijkstra_fast = njit(cache=False)(_dijkstra) if njit is not None else _dijkstra


class DistanceField:
    """Single-source grid costs (in cells) from ``start`` over a traversable mask, on the bounding
    box of the mask (plus a margin) to keep the search small. ``penalty`` (>= 0 per cell) multiplies
    the step cost by ``1 + penalty``: with a near-wall penalty, paths keep to the middle of doors."""

    def __init__(self, traversable: np.ndarray, start: Tuple[int, int], margin: int = 2,
                 penalty: Optional[np.ndarray] = None):
        self.start = start
        if not (0 <= start[0] < traversable.shape[0] and 0 <= start[1] < traversable.shape[1]):
            self.offset = (0, 0)
            self.dist = np.empty((0, 0))
            self.parent = np.empty((0, 0), dtype=np.int64)
            return
        rows, cols = np.nonzero(traversable)
        rows, cols = np.append(rows, start[0]), np.append(cols, start[1])
        r0, r1 = max(0, min(rows.min(), start[0]) - margin), min(traversable.shape[0], max(rows.max(), start[0]) + margin + 1)
        c0, c1 = max(0, min(cols.min(), start[1]) - margin), min(traversable.shape[1], max(cols.max(), start[1]) + margin + 1)
        self.offset = (r0, c0)
        sub = traversable[r0:r1, c0:c1].copy()
        sub[start[0] - r0, start[1] - c0] = True
        pen = (np.zeros(sub.shape) if penalty is None
               else np.ascontiguousarray(penalty[r0:r1, c0:c1], dtype=np.float64))
        self.dist, self.parent = _dijkstra_fast(sub, pen, start[0] - r0, start[1] - c0, np.inf)

    def distance(self, cell) -> float:
        r, c = cell[0] - self.offset[0], cell[1] - self.offset[1]
        if not (0 <= r < self.dist.shape[0] and 0 <= c < self.dist.shape[1]):
            return math.inf
        return float(self.dist[r, c])

    def path(self, cell) -> List[Tuple[int, int]]:
        """Cells from the start to ``cell`` (empty if unreachable)."""
        if not math.isfinite(self.distance(cell)):
            return []
        w = self.dist.shape[1]
        r, c = cell[0] - self.offset[0], cell[1] - self.offset[1]
        out = [(r + self.offset[0], c + self.offset[1])]
        while (r, c) != (self.start[0] - self.offset[0], self.start[1] - self.offset[1]):
            p = int(self.parent[r, c])
            if p < 0:
                return []
            r, c = p // w, p % w
            out.append((r + self.offset[0], c + self.offset[1]))
        return out[::-1]

    def nearest_reachable(self, cells: Sequence[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        best, best_d = None, math.inf
        for cell in cells:
            d = self.distance(cell)
            if d < best_d:
                best, best_d = cell, d
        return best


def waypoint(path_xy: Sequence[Tuple[float, float]], robot_xy, lookahead_m: float = 0.5) -> Optional[Tuple[float, float]]:
    """First path point at least ``lookahead_m`` from the robot (else the last point)."""
    if not path_xy:
        return None
    for p in path_xy:
        if math.dist(p, robot_xy) >= lookahead_m:
            return tuple(p)
    return tuple(path_xy[-1])


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def heading_action(robot_xy, yaw_rad: float, target_xy, turn_deg: float = 30.0) -> str:
    """Turn toward ``target_xy`` until within half a turn step, then move forward."""
    err = wrap(math.atan2(target_xy[1] - robot_xy[1], target_xy[0] - robot_xy[0]) - yaw_rad)
    if abs(err) <= math.radians(turn_deg) / 2 + 1e-6:
        return 'move_forward'
    return 'turn_left' if err > 0 else 'turn_right'


def wall_penalty(obstacle: np.ndarray, resolution_m: float, safe_m: float, weight: float) -> np.ndarray:
    """Per-cell step-cost penalty: ``weight`` at an obstacle, falling linearly to 0 at ``safe_m``
    (a Euclidean distance transform of the free space, i.e. an ESDF outside obstacles)."""
    if weight <= 0 or not obstacle.any():
        return np.zeros(obstacle.shape)
    esdf = ndimage.distance_transform_edt(~obstacle) * resolution_m
    return weight * np.clip((safe_m - esdf) / safe_m, 0.0, 1.0)
