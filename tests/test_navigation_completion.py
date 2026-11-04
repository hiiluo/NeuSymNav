"""Policy candidate diagnostics preserve distinct causes and bounded history."""
import numpy as np
import pytest
from neusymnav.navigation._grid import adapt
from neusymnav.navigation._policy_core import FrontierPolicy, PolicyConfig
from neusymnav.navigation.frontiers import Frontier, FrontierSet
from neusymnav.navigation.planner import Planner
from neusymnav.navigation.controller import Navigator
from test_navigation import nav
from test_navmap import geometry


def test_candidate_diagnostics_distinguish_cooldown_visited_and_path_failure():
    states = np.zeros((15, 15), np.int8)
    states[10, 10] = 100
    grid = adapt(nav(states, revision=5), 1., 'cylinder-v1')
    policy = FrontierPolicy(Planner(geometry()).core, PolicyConfig(failed_viewpoint_radius_m=.1))
    policy.report_goal_reached('visited', (.45, .45))
    policy.report_goal_failure('failed', 5, goal_world_xy=(.65, .65))
    candidates = tuple(Frontier(name, 5, (), cell, 1) for name, cell in [
        ('visited', (4, 4)), ('failed', (6, 6)), ('alias', (6, 6)),
        ('blocked', (10, 10)), ('available', (4, 9))])
    decision = policy.select(snapshot=grid, frontiers=FrontierSet(5, 'frame', candidates),
                             robot_xy=(.35, .35), now_monotonic_s=1.)
    rows = {row['frontier_id']: row for row in decision.goal_diagnostics['candidate_diagnostics']}
    assert rows['visited']['eligibility'] == 'visited_id'
    assert rows['failed']['eligibility'] == 'failed_id_cooldown'
    assert rows['failed']['cooldown_until_revision'] == 105
    assert rows['alias']['eligibility'] == 'failed_viewpoint_cooldown'
    assert rows['alias']['cooldown_until_revision'] == 105
    assert rows['blocked']['eligibility'] == 'path_rejected'
    assert rows['blocked']['path_reason']
    assert rows['available']['eligibility'] == 'reachable'
    assert rows['available']['viewpoint_xy'] == pytest.approx([.95, .45])
    assert decision.frontier.frontier_id == 'available'


def test_navigator_exposes_current_policy_status_and_clears_on_stale_input():
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    navigator.step(nav(), (.75, .75), 0., 1_000_000_000)
    import json
    assert json.loads(json.dumps(navigator.last_policy_status))['source']['frame_index'] == 0
    assert navigator.last_policy_status['map_revision'] == 1
    assert navigator.last_policy_status['capture_monotonic_ns'] == 1_000_000_000
    navigator.step(nav(), (.75, .75), 0., 1_400_000_000)
    assert navigator.last_policy_status is None


def test_failed_frontier_can_choose_a_different_viewpoint_before_cooldown_expires():
    states = np.full((25, 25), -1, np.int8)
    states[3:22, 3:22] = 0
    current = nav(states, revision=5)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    first = navigator.step(current, (1.25, 1.25), 0., 1_000_000_000)
    assert first.goal_id is not None
    failed_id, failed_xy = navigator.last_committed_goal
    navigator.report_goal_failure(failed_id, 5, goal_world_xy=failed_xy)
    navigator.policy._clear_goal()  # watchdog clears only after reporting failure
    second = navigator.step(current, (1.25, 1.25), 0., 1_000_000_000)
    assert second.goal_id is not None
    assert second.goal_id != failed_id
    assert np.linalg.norm(np.asarray(navigator.last_committed_goal[1]) - failed_xy) >= .3
    assert not navigator.policy.visited_viewpoints()


def test_cooldown_expires_but_reached_viewpoint_stays_visited():
    policy = FrontierPolicy(Planner(geometry()).core,
                            PolicyConfig(visited_viewpoint_radius_m=.1, failed_viewpoint_radius_m=.1))
    policy.report_goal_reached('visited', (.45, .45))
    policy.report_goal_failure('failed', 5, goal_world_xy=(.95, .45))
    candidates = (Frontier('visited', 106, (), (4, 4), 1),
                  Frontier('failed', 106, (), (4, 9), 1))
    grid = adapt(nav(revision=106), 1., 'cylinder-v1')
    decision = policy.select(snapshot=grid, frontiers=FrontierSet(106, 'frame', candidates),
                             robot_xy=(.35, .35), now_monotonic_s=1.)
    assert decision.frontier.frontier_id == 'failed'
    assert policy.visited_viewpoints() == ((.45, .45),)


def test_candidate_diagnostics_are_bounded_without_truncating_selection():
    grid = adapt(nav(), 1., 'cylinder-v1')
    policy = FrontierPolicy(Planner(geometry()).core)
    candidates = tuple(Frontier(f'visited-{i}', 1, (), (4, 4), 1) for i in range(40))
    for frontier in candidates:
        policy.report_goal_reached(frontier.frontier_id, (.45, .45))
    candidates += (Frontier('available', 1, (), (4, 9), 1),)
    decision = policy.select(snapshot=grid, frontiers=FrontierSet(1, 'frame', candidates),
                             robot_xy=(.35, .35), now_monotonic_s=1.)
    assert decision.frontier.frontier_id == 'available'
    assert len(decision.goal_diagnostics['candidate_diagnostics']) == 32
    assert decision.goal_diagnostics['candidate_diagnostics_total'] == 41
    assert decision.goal_diagnostics['candidate_diagnostics_truncated'] is True


def test_repeated_failure_id_outlives_spatial_cooldown_without_hiding_alternative():
    from dataclasses import replace
    states = np.full((25, 25), -1, np.int8)
    states[3:22, 3:22] = 0
    current = nav(states, revision=5)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    navigator.step(current, (1.25, 1.25), 0., 1_000_000_000)
    failed_id, failed_xy = navigator.last_committed_goal
    navigator.report_goal_failure(failed_id, 5, goal_world_xy=failed_xy)
    failure = None
    for i in range(21):
        stamp = 1_000_000_000 + i * 400_000_000
        observed = replace(current, revision=5+i, capture_monotonic_ns=stamp)
        failure = navigator.observe_navigation_result(observed, (1.25, 1.25), stamp,
                                                     'committed_goal_waiting_after_collision', True)
    assert failure is not None
    assert failure['goal_id'] == failed_id
    assert not navigator.policy.visited_viewpoints()
    after_spatial_expiry = replace(current, revision=126, capture_monotonic_ns=9_000_000_000)
    next_goal = navigator.step(after_spatial_expiry, (1.25, 1.25), 0., 9_000_000_000)
    assert next_goal.goal_id is not None and next_goal.goal_id != failed_id
    assert not navigator.policy.failed_viewpoints(126)
    navigator.policy._clear_goal()
    after_id_expiry = replace(current, revision=526, capture_monotonic_ns=9_000_000_000)
    original = navigator.step(after_id_expiry, (1.25, 1.25), 0., 9_000_000_000)
    assert original.goal_id == failed_id
    assert not navigator.policy.visited_viewpoints()
