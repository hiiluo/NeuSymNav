"""Opt-in tolerance for UNKNOWN cells inside the robot's own current footprint.

Live 00806 v9: the robot stopped next to an overhang where one cell of its
current footprint was UNKNOWN in the one-frame downward-depth map (occluded
floor). Planning (start not traversable) and the guard bootstrap (capsule not
all FREE) then refused every command, including in-place rotation, forever.

The robot's body occupies its current footprint, so a few UNKNOWN cells there
are not an unobserved obstacle. With a tolerance > 0 such cells are treated as
FREE **only inside the current footprint disc**, only if no cell of the disc
is OCCUPIED, and only if at most ``max_fraction`` of the disc is UNKNOWN. Any
swept area beyond the current footprint must still be measured FREE.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from ..contracts import GridState
from ..mapping.occupancy import capsule_cells

MAX_TOLERANCE = 0.3
# Every consumer (world planner, local follower, guard map, guard bootstrap)
# must tolerate EXACTLY the same disc. Live 00806 (four runs, 09/11 evening)
# deadlocked when the follower used a padded disc and the guard did not: the
# follower planned through a cell the guard still saw as UNKNOWN, so every
# forward pulse was refused with path_segment_blocked.
FOOTPRINT_PAD_CELLS = 0.75


def validate_tolerance(value):
    if type(value) not in (int, float) or not 0.0 <= float(value) <= MAX_TOLERANCE:
        raise ValueError(f'start footprint unknown tolerance must be in [0, {MAX_TOLERANCE}]')
    return float(value)


def start_disc(nav, robot_xy, radius_m):
    """In-bounds (rows, cols) of the current footprint disc, or None."""
    cells = tuple(capsule_cells(nav.origin_xy, nav.resolution_m, tuple(robot_xy), tuple(robot_xy), radius_m))
    if not cells:
        return None
    rows, cols = np.asarray(cells, dtype=np.intp).T
    if not np.all((rows >= 0) & (rows < nav.states.shape[0]) & (cols >= 0) & (cols < nav.states.shape[1])):
        return None
    return rows, cols


def tolerated_unknown(nav, disc, max_fraction):
    """Mask of disc cells that may be treated as FREE (or None if not allowed)."""
    if not max_fraction or disc is None:
        return None
    states = nav.states[disc]
    if np.any(states == GridState.OCCUPIED):
        return None
    unknown = states == GridState.UNKNOWN
    if not unknown.any() or unknown.sum() > max_fraction * len(states):
        return None
    return unknown


def tolerate_start_unknown(nav, robot_xy, *, radius_m, height_m, max_fraction, pad_cell=False):
    """Return (nav, cleared_cell_count) with tolerated start cells set FREE.

    ``pad_cell`` widens the disc by one cell half-diagonal so a planner's
    footprint around the robot's *cell centre* is covered as well.
    """
    if pad_cell:
        radius_m = radius_m + 0.75 * nav.resolution_m
    disc = start_disc(nav, robot_xy, radius_m)
    unknown = tolerated_unknown(nav, disc, max_fraction)
    if unknown is None:
        return nav, 0
    rows, cols = disc[0][unknown], disc[1][unknown]
    states = np.array(nav.states, copy=True)
    support = np.array(nav.floor_support, copy=True)
    clearance = np.array(nav.clearance, copy=True)
    states[rows, cols] = GridState.FREE
    support[rows, cols] = True
    clearance[rows, cols] = np.maximum(clearance[rows, cols], np.asarray(height_m, clearance.dtype))
    return replace(nav, states=states, floor_support=support, clearance=clearance), int(len(rows))


def tolerance_radius_m(robot, resolution_m):
    """The single tolerated disc radius shared by every consumer."""
    return robot.radius_m + robot.margin_m + FOOTPRINT_PAD_CELLS * resolution_m


def tolerate_robot_footprint(nav, robot_xy, robot, max_fraction):
    """Shared entry point: (nav, cleared) with the one tolerated disc.

    Use this, never ``tolerate_start_unknown`` directly, in runtime code so the
    planner, follower, guard map and guard bootstrap cannot disagree.
    """
    return tolerate_start_unknown(nav, robot_xy, radius_m=robot.radius_m + robot.margin_m,
                                  height_m=robot.height_m, max_fraction=max_fraction, pad_cell=True)
