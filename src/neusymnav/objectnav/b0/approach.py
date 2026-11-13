"""Goal cells for approaching a candidate object on the robot's observed map.

``approach_goals`` works on the adapted navigation grid (known traversable
cells only, robot footprint already inflated by the planner) and returns the
cells the planner should reach plus an extra cost per cell:

* ``ring``    traversable cells whose centre lies within ``aim_m`` of the
              object's observed floor-plan points: any of them ends the
              approach (extra cost 0, the planner picks the nearest);
* ``closer``  none yet: the traversable cells nearest the object within
              ``aim_m`` + 1.5 m (extra cost favours closeness), so the robot
              moves up and observes the free space next to the object;
* ``toward``  the object is beyond that window (e.g. outside the 8 m
              snapshot): traversable cells nearest the object centroid.
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

import numpy as np

CLOSER_WINDOW_M = 1.5
MAX_GOALS = 300
MAX_FOOTPRINT_POINTS = 400
CLOSER_WEIGHT = 2.0


def _subsample(points_xy: np.ndarray, n: int) -> np.ndarray:
    if len(points_xy) <= n:
        return points_xy
    return points_xy[np.linspace(0, len(points_xy) - 1, n).astype(np.int64)]


def _min_dist(cx: np.ndarray, cy: np.ndarray, points_xy: np.ndarray) -> np.ndarray:
    out = np.full(cx.shape, np.inf)
    for chunk in np.array_split(points_xy, max(1, len(points_xy) // 100)):
        d = np.hypot(cx[..., None] - chunk[:, 0], cy[..., None] - chunk[:, 1]).min(axis=-1)
        out = np.minimum(out, d)
    return out


def approach_goals(grid, traversable: np.ndarray, footprint_xy: np.ndarray, centroid_xy: Sequence[float],
                   *, aim_m: float) -> Tuple[List[Tuple[int, int]], Dict[Tuple[int, int], float], str]:
    res, ox, oy = float(grid.resolution_m), float(grid.origin_x_m), float(grid.origin_y_m)
    rows, cols = traversable.shape
    pts = _subsample(np.asarray(footprint_xy, dtype=np.float64).reshape(-1, 2), MAX_FOOTPRINT_POINTS)
    if len(pts):
        reach = aim_m + CLOSER_WINDOW_M
        c0 = max(0, int(math.floor((pts[:, 0].min() - reach - ox) / res)))
        c1 = min(cols, int(math.ceil((pts[:, 0].max() + reach - ox) / res)) + 1)
        r0 = max(0, int(math.floor((pts[:, 1].min() - reach - oy) / res)))
        r1 = min(rows, int(math.ceil((pts[:, 1].max() + reach - oy) / res)) + 1)
        if c0 < c1 and r0 < r1:
            rr, cc = np.mgrid[r0:r1, c0:c1]
            ok = traversable[r0:r1, c0:c1]
            if ok.any():
                rr, cc = rr[ok], cc[ok]
                d = _min_dist(ox + (cc + 0.5) * res, oy + (rr + 0.5) * res, pts)
                inside = d <= aim_m
                if inside.any():
                    sel = np.flatnonzero(inside)
                    if len(sel) > MAX_GOALS:
                        sel = sel[np.argsort(d[sel])[:MAX_GOALS]]
                    cells = [(int(rr[i]), int(cc[i])) for i in sel]
                    return cells, {c: 0.0 for c in cells}, 'ring'
                near = np.flatnonzero(d <= reach)
                if len(near):
                    sel = near[np.argsort(d[near])[:MAX_GOALS]]
                    cells = [(int(rr[i]), int(cc[i])) for i in sel]
                    return cells, {c: CLOSER_WEIGHT * float(d[i]) for c, i in zip(cells, sel)}, 'closer'
    rr, cc = np.nonzero(traversable)
    if not len(rr):
        return [], {}, 'none'
    d = np.hypot(ox + (cc + 0.5) * res - centroid_xy[0], oy + (rr + 0.5) * res - centroid_xy[1])
    sel = np.argsort(d)[:MAX_GOALS]
    cells = [(int(rr[i]), int(cc[i])) for i in sel]
    return cells, {c: CLOSER_WEIGHT * float(d[i]) for c, i in zip(cells, sel)}, 'toward'


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


def facing_rate(robot_xy, yaw_rad, target_xy, *, max_rate=math.radians(29.5), pulse_s=0.5, tol=math.radians(10.0)):
    """In-place yaw rate toward a target (0.0 when within tolerance); never overshoots one pulse."""
    err = wrap(math.atan2(target_xy[1] - robot_xy[1], target_xy[0] - robot_xy[0]) - yaw_rad)
    if abs(err) <= tol:
        return 0.0, err
    return max(-max_rate, min(max_rate, err / pulse_s)), err
