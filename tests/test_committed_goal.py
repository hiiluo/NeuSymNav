"""Runtime goals are world-space commitments, independent of frontier churn."""
from dataclasses import replace

import numpy as np
import pytest

from neusymnav.navigation._grid import GridView
from neusymnav.navigation._planner_core import AStarPlanner, PlannerConfig
from neusymnav.navigation._policy_core import FrontierPolicy, PolicyConfig
from neusymnav.navigation.frontiers import Frontier, FrontierSet


def grid(revision=1, **kwargs):
    values = np.zeros((40, 40), np.int8)
    return replace(GridView('e', 'robot', revision, 'f', 0, 1., .1, 0., 0.,
        values, np.ones_like(values, bool), np.ones_like(values, np.float32),
        np.zeros_like(values, bool), np.zeros_like(values, float)), **kwargs)


def policy():
    return FrontierPolicy(AStarPlanner(PlannerConfig(.04, 0.), accelerate_many=False),
        PolicyConfig(commit_goal_until_reached=True, failed_viewpoint_radius_m=.3))


def select(p, s, targets=(('original', (25, 25)),), robot=(.55, .55), now=1.):
    frontiers = tuple(Frontier(name, s.revision, (cell,), cell, 1) for name, cell in targets)
    return p.select(snapshot=s, frontiers=FrontierSet(s.revision, 'f', frontiers),
                    robot_xy=robot, now_monotonic_s=now)


def test_frontier_drift_id_churn_and_cheaper_alternative_never_move_goal():
    p = policy(); first = select(p, grid()); xy = p._goal_world_xy
    for i in range(1, 8):
        s = grid(i + 1)
        choice = select(p, s, (('original' if i % 2 else 'alias', (25, 25+i)),
                              ('closer', (10, 10))), now=10.+i)
        assert choice.state == 'MOVE'
        assert choice.frontier.frontier_id == first.frontier.frontier_id
        assert p._goal_world_xy == xy
        assert s.cell_to_world(*choice.path.cells[-1]) == xy
        assert choice.selected_at_monotonic_s == 1.
    assert select(p, grid(10), (), now=100.).path is not None


def test_reach_threshold_then_select_next_on_following_tick():
    p = policy(); select(p, grid()); xy = p._goal_world_xy
    targets = (('other', (10, 10)),)
    assert select(p, grid(2), targets, robot=(xy[0]-.201, xy[1])).state == 'MOVE'
    reached = select(p, grid(3), targets, robot=(xy[0]-.199, xy[1]))
    assert reached.reason == 'frontier_viewpoint_reached'
    assert reached.path is None and p._goal_world_xy is None
    next_goal = select(p, grid(4), targets, robot=xy)
    assert next_goal.frontier.frontier_id == 'other'


@pytest.mark.parametrize('obstacle', [-1, 100])
def test_unsafe_target_stops_without_selecting_alternative_and_recovers(obstacle):
    p = policy(); select(p, grid()); xy = p._goal_world_xy
    s = grid(2); states = s.states.copy(); states[25, 25] = obstacle
    blocked = select(p, replace(s, states=states), (('other', (10, 10)),))
    assert blocked.state == 'WAIT' and blocked.path is None
    assert p._goal_world_xy == xy
    recovered = select(p, grid(3), (('other', (10, 10)),))
    assert recovered.frontier.frontier_id == 'original'
    assert p._goal_world_xy == xy


def test_guard_failure_retains_goal_through_cooldown():
    p = policy(); select(p, grid()); xy = p._goal_world_xy
    p.report_goal_failure('original', 1, goal_world_xy=xy)
    blocked = select(p, grid(2), (('other', (10, 10)),))
    assert blocked.path is None and blocked.state == 'WAIT'
    assert p._goal_world_xy == xy
    retry = select(p, grid(102), ())
    assert retry.frontier.frontier_id == 'original' and retry.path is not None


def test_rolling_origin_retains_world_target_and_outside_map_waits():
    p = policy(); select(p, grid()); xy = p._goal_world_xy
    shifted = grid(2, origin_x_m=.5, origin_y_m=.5)
    choice = select(p, shifted, (), robot=(.85, .85))
    assert choice.path.cells[-1] == (20, 20)
    assert p._goal_world_xy == xy
    outside = select(p, grid(3, origin_x_m=5.), (), robot=(5.55, .55))
    assert outside.state == 'WAIT' and outside.path is None
    assert p._goal_world_xy == xy


def test_new_wall_blocks_route_but_never_retargets():
    p = policy(); select(p, grid()); xy = p._goal_world_xy
    s = grid(2); states = s.states.copy(); states[15, :] = 100
    blocked = select(p, replace(s, states=states), (('nearby', (10, 10)),))
    assert blocked.state == 'WAIT' and blocked.path is None
    assert p._goal_world_xy == xy
    assert select(p, grid(3), ()).frontier.frontier_id == 'original'


def test_stale_frontier_set_does_not_clear_commitment():
    p = policy(); select(p, grid()); xy = p._goal_world_xy
    blocked = p.select(snapshot=grid(2), frontiers=FrontierSet(1, 'f', ()),
                       robot_xy=(.55, .55), now_monotonic_s=5.)
    assert blocked.path is None and blocked.reason == 'frontier_snapshot_stale'
    assert p._goal_world_xy == xy


def test_controller_tracks_exact_target_after_coarse_subcell_origin_shift():
    from neusymnav.navigation._controller_core import Controller, ControllerConfig
    p = policy(); select(p, grid()); target = p._goal_world_xy
    s = grid(2, resolution_m=.5, origin_x_m=.29, origin_y_m=.29)
    # Center (2.54,2.54) only differs slightly; move origin to create larger offset.
    s = replace(s, origin_x_m=.49, origin_y_m=.49)
    cell = s.world_to_cell(*target); center = s.cell_to_world(*cell)
    assert np.linalg.norm(np.array(center)-target) > .2
    path = p.planner.plan(s, center, cell)
    controller = Controller(ControllerConfig(), traversable=p.planner.traversable)
    command = controller.tick(robot_xy=center, yaw_rad=-2.35619449,
        now_monotonic_s=1., dt_s=.1, depth_host_monotonic_s=1.,
        depth_front_min_m=None, depth_coverage_ok=True, snapshot=s, path=path,
        frame_id='f', goal_world_xy=target)
    assert command.reason != 'goal_reached'
    assert command.linear_mps > 0
