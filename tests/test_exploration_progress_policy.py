"""Gain and heading aware frontier ranking stays bounded and preserves goals."""

import numpy as np

from neusymnav.navigation._grid import GridView
from neusymnav.navigation._planner_core import AStarPlanner, PlannerConfig
from neusymnav.navigation._policy_core import FrontierPolicy, PolicyConfig
from neusymnav.navigation.frontiers import Frontier, FrontierSet


def grid(revision=1, wall_column=None):
    states = np.zeros((40, 40), np.int8)
    if wall_column is not None:
        states[:, wall_column] = 100
    return GridView(
        "episode", "robot", revision, f"frame-{revision}", revision,
        float(revision), 0.1, 0.0, 0.0, states,
        np.ones_like(states, bool), np.ones_like(states, np.float32),
        np.zeros_like(states, bool), np.zeros(states.shape, float),
    )


def policy(**config):
    return FrontierPolicy(
        AStarPlanner(PlannerConfig(0.04, 0.0), accelerate_many=False),
        PolicyConfig(**config),
    )


def select(p, snapshot, candidates, *, robot=(0.55, 0.55), yaw=0.0, now=1.0):
    frontiers = tuple(
        Frontier(name, snapshot.revision, (cell,), cell, gain)
        for name, cell, gain in candidates
    )
    return p.select(
        snapshot=snapshot,
        frontiers=FrontierSet(snapshot.revision, f"frame-{snapshot.revision}", frontiers),
        robot_xy=robot,
        robot_yaw_rad=yaw,
        now_monotonic_s=now,
    )


def test_bounded_frontier_gain_can_justify_a_modestly_longer_route():
    p = policy(frontier_gain_weight=0.6, frontier_gain_saturation_cells=20)
    choice = select(p, grid(), (
        ("near_small", (5, 9), 1),   # 0.4 m route, little boundary evidence
        ("far_large", (5, 10), 100), # 0.5 m route, much more boundary evidence
    ))

    assert choice.frontier.frontier_id == "far_large"
    sample = {item["frontier_id"]: item
              for item in choice.goal_diagnostics["reachable_candidate_sample"]}
    assert sample["far_large"]["path_cost_m"] > sample["near_small"]["path_cost_m"]
    assert sample["far_large"]["gain_adjusted_score_m"] < sample["near_small"]["gain_adjusted_score_m"]
    assert 0.0 < sample["far_large"]["gain_factor"] <= 1.6


def test_gain_cannot_discount_a_much_longer_route_without_bound():
    p = policy(frontier_gain_weight=0.6, frontier_gain_saturation_cells=20)
    choice = select(p, grid(), (
        ("near_small", (5, 10), 1),  # 0.5 m
        ("far_huge", (5, 17), 1000), # 1.2 m; maximum gain discount is 1.6x
    ))

    assert choice.frontier.frontier_id == "near_small"


def test_first_path_heading_breaks_equal_cost_frontier_tie():
    p = policy(turn_cost_m_per_rad=0.5)
    choice = select(p, grid(), (
        ("a_turn_left", (10, 5), 10),
        ("z_straight", (5, 10), 10),
    ), yaw=0.0)

    assert choice.frontier.frontier_id == "z_straight"
    sample = {item["frontier_id"]: item
              for item in choice.goal_diagnostics["reachable_candidate_sample"]}
    assert sample["z_straight"]["turn_cost_m"] == 0.0
    assert sample["a_turn_left"]["turn_cost_m"] > 0.7


def test_minimum_goal_distance_prefers_a_farther_reachable_candidate():
    p = policy(min_goal_distance_m=0.6)
    choice = select(p, grid(), (
        ("near", (5, 9), 10),  # 0.4 m from the robot
        ("far", (5, 13), 10),  # 0.8 m from the robot
    ))

    assert choice.frontier.frontier_id == "far"
    diagnostics = choice.goal_diagnostics
    assert diagnostics["minimum_goal_distance_m"] == 0.6
    assert diagnostics["near_goal_candidate_count"] == 1
    assert diagnostics["eligible_goal_candidate_count"] == 1
    assert diagnostics["near_goal_preference_applied"] is True
    assert diagnostics["near_goal_fallback"] is False


def test_minimum_distance_keeps_approached_held_goal_until_hysteresis_allows_switch():
    p = policy(min_goal_distance_m=0.6, turn_cost_m_per_rad=0.35)
    first = select(p, grid(), (("held", (5, 13), 10),))  # 0.8 m away
    approached = select(p, grid(2), (
        ("held", (5, 13), 10),
        ("far", (5, 24), 10),
    ), robot=(1.65, 0.55), now=1.1)  # held goal is now 0.3 m away
    after_hold = select(p, grid(3), (
        ("held", (5, 13), 10),
        ("far", (5, 24), 10),
    ), robot=(1.65, 0.55), now=4.1)

    assert first.frontier.frontier_id == "held"
    assert approached.frontier.frontier_id == "held"
    assert approached.goal_diagnostics["near_goal_held_goal_retained"] is True
    assert approached.goal_diagnostics["near_goal_fallback"] is False
    assert after_hold.frontier.frontier_id == "far"


def test_minimum_distance_allows_near_held_cell_recovery_without_frontier_match():
    p = policy(min_goal_distance_m=0.6)
    select(p, grid(), (("held", (5, 13), 10),))
    choice = select(p, grid(2), (("far", (5, 24), 10),),
                    robot=(1.65, 0.55), now=1.1)

    assert choice.frontier.frontier_id == "held"
    assert choice.goal_diagnostics["held_goal_recovery"] == "held_cell_replanned"
    assert choice.goal_diagnostics["near_goal_held_goal_retained"] is True


def test_zero_minimum_goal_distance_keeps_nearest_frontier_ordering():
    p = policy()
    choice = select(p, grid(), (
        ("near", (5, 9), 10),
        ("far", (5, 13), 10),
    ))

    assert choice.frontier.frontier_id == "near"
    assert choice.goal_diagnostics["minimum_goal_distance_m"] == 0.0
    assert choice.goal_diagnostics["near_goal_fallback"] is False


def test_minimum_goal_distance_falls_back_when_all_reachable_goals_are_near():
    p = policy(min_goal_distance_m=0.6)
    choice = select(p, grid(), (
        ("nearest", (5, 8), 10),  # 0.3 m from the robot
        ("also_near", (5, 9), 10),  # 0.4 m from the robot
    ))

    assert choice.frontier.frontier_id == "nearest"
    diagnostics = choice.goal_diagnostics
    assert diagnostics["near_goal_candidate_count"] == 2
    assert diagnostics["eligible_goal_candidate_count"] == 0
    assert diagnostics["near_goal_preference_applied"] is False
    assert diagnostics["near_goal_fallback"] is True


def test_unreachable_far_goal_does_not_suppress_a_close_reachable_goal():
    p = policy(min_goal_distance_m=0.6)
    choice = select(p, grid(wall_column=11), (
        ("close_reachable", (5, 8), 10),  # 0.3 m from the robot
        ("far_blocked", (5, 20), 10),  # 1.5 m away, behind a full wall
    ))

    assert choice.frontier.frontier_id == "close_reachable"
    diagnostics = choice.goal_diagnostics
    assert diagnostics["path_failure_count"] == 1
    assert diagnostics["near_goal_candidate_count"] == 1
    assert diagnostics["eligible_goal_candidate_count"] == 0
    assert diagnostics["near_goal_fallback"] is True


def test_ranked_frontiers_do_not_retarget_an_active_committed_goal():
    p = policy(
        commit_goal_until_reached=True,
        reached_distance_m=0.05,
        min_goal_distance_m=0.6,
        frontier_gain_weight=0.6,
        frontier_gain_saturation_cells=20,
    )
    first = select(p, grid(), (("held", (5, 10), 4),))
    held_xy = p._goal_world_xy

    choice = select(p, grid(2), (
        ("new_far_high_gain", (5, 20), 1000),
        ("held", (5, 10), 4),
    ), now=2.0)

    assert first.frontier.frontier_id == "held"
    assert choice.reason == "committed_goal_retained"
    assert choice.frontier.frontier_id == "held"
    assert p._goal_world_xy == held_xy
    assert choice.path.cells[-1] == (5, 10)

