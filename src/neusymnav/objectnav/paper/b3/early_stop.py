"""B3 ``early_stop`` (v5): arrive one forward step early.

Offline on B3 v1 DEV167 + v4 subset (scratchpad vp_diag, evaluator-side), 9 of 17 ``stopped_too_far``
stops had stood within 0.1 m of a goal view point just before the last forward step of the approach; that
step (taken because the object footprint was still > stop_distance_m) carried the robot off the view-point
set. Stopping at the pose before that step fixes 9 and breaks 0 of 155 stopping episodes.

Policy rule (no GT): during APPROACH, when the next action is ``move_forward`` and the predicted pose
after it would be within ``stop_distance_m`` of the object footprint, go to FACE now instead. VERIFY then
accepts up to ``stop_distance_m + step_m`` for that arrival.
"""
from __future__ import annotations

import math

import numpy as np

KEYS = {'step_m'}
NOTE = 'arrived_early'


def validate(spec) -> None:
    if set(spec) != KEYS:
        raise ValueError('early_stop needs exactly %s' % sorted(KEYS))
    if not 0 < float(spec['step_m']) <= 1.0:
        raise ValueError('early_stop step_m must be in (0, 1]')


def ahead(robot_xy, yaw_rad: float, step_m: float):
    return (robot_xy[0] + step_m * math.cos(yaw_rad), robot_xy[1] + step_m * math.sin(yaw_rad))


def arrives_next_step(footprint_xy: np.ndarray, robot_xy, yaw_rad: float, step_m: float, stop_m: float,
                      distance) -> bool:
    """True when the robot is still outside ``stop_m`` but one forward step would bring it inside."""
    return distance(footprint_xy, robot_xy) > stop_m and distance(footprint_xy, ahead(robot_xy, yaw_rad, step_m)) <= stop_m
