"""Diagnosis only: why did the guard's fresh-frame proof fail here?

MotionGuard (navigation/safety.py) issues motion only if every cell of the
robot's swept footprint is FREE in the CURRENT downward depth frame alone
(``NavMapper.bootstrap``: floor return in the cell, every height bin of the
body column seen free, no return inside the body column). The accumulated map
the planner uses can call the same cells FREE. ``probe`` reads that
fresh-frame coverage again (read-only, ``measured_coverage`` with a local
bound), lists the footprint cells that are not FREE and explains each one
from the raw depth returns that land in it.

It never changes the mapper, the guard or the command, and is called by the
ObjectNav runner only for a few sampled blocked cycles per episode.

Cell classes:
    occupied_floor_bump   a return 5-10 cm above the floor datum (uneven floor, rug, threshold)
    occupied_body         a return 10 cm .. robot height above the floor (an obstacle in the body column)
    occupied_other        OCCUPIED, no return in the cell itself (a vote from a ray crossing it)
    no_floor_overhead     no floor return; returns above the robot height over the cell (occluded from above)
    no_floor_invalid      no floor return; invalid-depth rays aim at the cell (too near / no return)
    no_floor_other        no floor return and none of the above
    body_column_unseen    floor seen, but some height bin of the column has no free vote
    planar_not_free       floor seen, column seen, planar cell still not free
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np


def _world_points(obs):
    depth = np.asarray(obs.depth_m, dtype=np.float64)
    h, w = depth.shape
    k = np.asarray(obs.K, dtype=np.float64)
    vv, uu = np.mgrid[0:h, 0:w]
    rays = np.stack(((uu - k[0, 2]) / k[0, 0], (vv - k[1, 2]) / k[1, 1], np.ones_like(depth)), axis=-1)
    t = np.asarray(obs.T_world_camera, dtype=np.float64)
    dirs = rays @ t[:3, :3].T                      # world direction per pixel (not normalised: z_cam = 1)
    origin = t[:3, 3]
    valid = np.asarray(obs.valid_depth, dtype=bool) & np.isfinite(depth)
    pts = origin + dirs * np.where(valid, depth, 0.)[..., None]
    return origin, dirs, valid, pts


def probe(mapper, obs, nav, robot_xy, yaw_rad, *, body_only: bool, corridor_m: float = 0.05,
          max_cells: int = 40) -> dict:
    from ..contracts import GridState
    from ..mapping.occupancy import capsule_cells
    robot = mapper.robot
    radius = robot.radius_m + (0. if body_only else robot.margin_m)
    end = (robot_xy[0] + corridor_m * math.cos(yaw_rad), robot_xy[1] + corridor_m * math.sin(yaw_rad))
    lo = np.minimum(robot_xy, end) - radius - 0.1
    hi = np.maximum(robot_xy, end) + radius + 0.1
    cov = mapper.measured_coverage(obs, required_bounds_xy=(lo, hi))
    res = float(cov.resolution_m)
    ox, oy = (float(v) for v in cov.origin_xy)
    cells = list(capsule_cells(cov.origin_xy, res, robot_xy, end, radius))
    floor_z, height, tol = float(mapper.floor_z_m), float(robot.height_m), float(robot.near_ground_tolerance_m)

    origin, dirs, valid, pts = _world_points(obs)
    # every valid return, binned into coverage cells
    pc = np.floor((pts[..., 0] - ox) / res).astype(np.int64)
    pr = np.floor((pts[..., 1] - oy) / res).astype(np.int64)
    dz = pts[..., 2] - floor_z
    # where invalid rays would meet the floor plane
    with np.errstate(divide='ignore', invalid='ignore'):
        s = (floor_z - origin[2]) / dirs[..., 2]
    fl = origin[:2] + dirs[..., :2] * s[..., None]
    inv = (~valid) & np.isfinite(s) & (s > 0)
    ic = np.floor((fl[..., 0] - ox) / res).astype(np.int64)
    ir = np.floor((fl[..., 1] - oy) / res).astype(np.int64)

    acc_states = np.asarray(nav.states)
    aox, aoy = (float(v) for v in nav.origin_xy)
    ares = float(nav.resolution_m)

    def acc_state(cx, cy):
        r, c = math.floor((cy - aoy) / ares), math.floor((cx - aox) / ares)
        if 0 <= r < acc_states.shape[0] and 0 <= c < acc_states.shape[1]:
            return int(acc_states[r, c])
        return None

    states = np.asarray(cov.states)
    floor_ok = np.asarray(cov.floor_support, dtype=bool)
    clear = np.asarray(cov.clearance)
    counts, rows = Counter(), []
    for r, c in cells:
        inside = 0 <= r < states.shape[0] and 0 <= c < states.shape[1]
        st = int(states[r, c]) if inside else None
        if st == int(GridState.FREE):
            continue
        cx, cy = ox + (c + .5) * res, oy + (r + .5) * res
        here = valid & (pr == r) & (pc == c)
        z = dz[here]
        # returns above the robot height whose ray passes over this cell (occluders)
        over = valid & (dz > height) & (np.hypot(pts[..., 0] - cx, pts[..., 1] - cy) <= res)
        aimed = inv & (ir == r) & (ic == c)
        if not inside:
            kind = 'outside_coverage'
        elif st == int(GridState.OCCUPIED):
            zz = z[z > tol]
            kind = ('occupied_other' if not zz.size else
                    'occupied_floor_bump' if zz.max() <= 0.10 else 'occupied_body')
        elif not floor_ok[r, c]:
            kind = ('no_floor_overhead' if over.any() else 'no_floor_invalid' if aimed.any() else 'no_floor_other')
        elif clear[r, c] < height:
            kind = 'body_column_unseen'
        else:
            kind = 'planar_not_free'
        counts[kind] += 1
        if len(rows) < max_cells:
            rows.append(dict(d_m=round(math.dist((cx, cy), robot_xy), 3), kind=kind, state=st,
                             accumulated=acc_state(cx, cy), n_returns=int(here.sum()),
                             dz_max_m=round(float(z.max()), 3) if z.size else None,
                             dz_min_m=round(float(z.min()), 3) if z.size else None,
                             n_over=int(over.sum()), n_invalid_aimed=int(aimed.sum())))
    disc = np.hypot(pts[..., 0] - robot_xy[0], pts[..., 1] - robot_xy[1]) <= radius
    over_disc = valid & disc & (dz > height)
    result = mapper.bootstrap(obs, robot_xy=robot_xy, yaw_rad=yaw_rad, corridor_m=corridor_m, body_only=body_only)
    return dict(body_only=body_only, radius_m=round(radius, 3), corridor_m=corridor_m,
                cells=len(cells), not_free=sum(counts.values()), kinds=dict(counts),
                bootstrap=dict(ready=bool(result.ready), required=int(result.required_cells),
                               free=int(result.observed_cells)),
                returns_above_robot_over_disc=int(over_disc.sum()),
                min_return_height_over_disc_m=round(float(dz[valid & disc].min()), 3) if (valid & disc).any() else None,
                invalid_rays_over_disc=int((inv & (np.hypot(fl[..., 0] - robot_xy[0], fl[..., 1] - robot_xy[1]) <= radius)).sum()),
                cells_detail=sorted(rows, key=lambda d: d['d_m']))
