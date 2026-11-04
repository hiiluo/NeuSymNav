"""Measured-raster corridor and world-goal checks for the 1 m campaign body."""
from dataclasses import replace
import numpy as np
import pytest

from neusymnav.contracts import FrameKey, NavSnapshot, NavigationDecision
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry
from neusymnav.navigation.planner import Planner
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.frontiers import Frontier, FrontierSet
from neusymnav.navigation.safety import MotionGuard
from test_navmap import down

DOMAIN = 'host_monotonic:test'
ROBOT = RobotGeometry('campaign-body', .125, 1., .05)


def corridor(rows, *, phase=0.):
    # Free width is rows * .05 m between occupied raster cells.
    states = np.full((40, 40), 100, np.int8)
    first = (40 - rows) // 2
    states[first:first + rows, :] = 0
    return NavSnapshot('ep', 1, FrameKey('ep', 'navigation', 2), 1_000_000_000,
        DOMAIN, .05, (-1., -1. + phase), states, states == 0,
        np.where(states == 0, 1.5, 0.).astype(np.float32), ROBOT.geometry_id,
        3., 'scene-calibration:v1', 'a' * 64)


@pytest.mark.parametrize('rows,allowed', [(4, False), (12, True)])
@pytest.mark.parametrize('phase', [0., .0125])
def test_measured_corridor_planner_and_depth_guard(tmp_path, rows, allowed, phase):
    nav = corridor(rows, phase=phase)
    robot = (0., phase)
    goal = (.4, phase)
    target_cell = (int((goal[1] - nav.origin_xy[1]) / .05), int((goal[0] - nav.origin_xy[0]) / .05))
    path = Planner(ROBOT).plan(nav, robot, target_cell)
    assert path.success is allowed
    mapper = NavMapper(robot=ROBOT, floor_z_m=3., floor_datum_source='scene-calibration:v1',
        calibration_hash='a' * 64, resolution_m=.05, tile_size_cells=16, sampling_stride=1,
        snapshot_radius_m=3., tile_archive_dir=tmp_path)
    guard = MotionGuard(mapper, clock_domain=DOMAIN)
    guard.bind_nav(nav, robot_xy=robot, yaw_rad=0.)
    decision = NavigationDecision('g', (goal,), .1, 0., nav.revision, 'tracking')
    result = guard.filter(decision, down(2, size=201, focal=100.), 1_000_000_000)
    assert (result.linear_mps > 0) is allowed
    # Invalid measured depth blocks even the otherwise wide corridor.
    guard = MotionGuard(mapper, clock_domain=DOMAIN)
    guard.bind_nav(nav, robot_xy=robot, yaw_rad=0.)
    assert guard.filter(decision, down(3, valid=False, size=201, focal=100.), 1_000_000_000).linear_mps == 0


def test_actual_navigator_keeps_exact_world_goal_across_shifted_map():
    from test_navigation import nav
    base = nav(np.zeros((40, 40), np.int8))
    navigator = Navigator(RobotGeometry('cylinder-v1', .05, 1., 0.), clock_domain=DOMAIN)
    class Frontiers:
        def extract(self, grid, robot_xy, **kwargs):
            f = Frontier('first', grid.revision, ((25, 25),), (25, 25), 1)
            return FrontierSet(grid.revision, grid.as_of_frame_id, (f,))
    navigator.extractor = Frontiers()
    first = navigator.step(base, (.55, .55), 0., 1_000_000_000)
    assert first.path
    target = first.path[-1]
    shifted = replace(base, revision=2, origin_xy=(.5, .5))
    second = navigator.step(shifted, (.85, .85), 0., 1_000_000_000)
    assert second.goal_id == first.goal_id
    assert second.path[-1] == target
    assert navigator.last_committed_goal == (first.goal_id, target)
