"""Tour goal gates (no shortcut through out-and-back spurs) and in-place scans.

Live 00806 v8: the route enters the bathroom (goal at (-3.74,-4.29)) and comes
back through the same door; progress matched the return leg at the door and
the robot turned back without entering. Scans give Hydra views of small rooms.
"""
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from test_navigation import nav
from test_navmap import geometry
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.tour import TourFollower, TourPlan, densify, goal_polyline_indices


def _grid(size=60):
    from neusymnav.navigation._grid import adapt
    return adapt(nav(np.zeros((size, size), np.int8)), geometry().height_m, geometry().geometry_id)


def _spur_plan():
    # East along y=0.5 to a dead-end goal at x=2.5, then back west on y=0.7.
    vertices = [(0.5, 0.5), (2.5, 0.5), (0.5, 0.7)]
    dense = densify(vertices)
    goals = goal_polyline_indices(dense, [(2.5, 0.5), (0.5, 0.7)])
    return TourPlan(tuple(dense), dense[0], 'a' * 64, 'b' * 64, 0., goals)


def _index_near(plan, xy, start=0):
    return min(range(start, len(plan.polyline)), key=lambda i: math.dist(plan.polyline[i], xy))


def test_goal_indices_are_monotone_route_vertices():
    plan = _spur_plan()
    assert len(plan.goal_indices) == 2
    assert plan.polyline[plan.goal_indices[0]] == pytest.approx((2.5, 0.5))
    assert plan.goal_indices[0] < plan.goal_indices[1] == len(plan.polyline) - 1


def test_progress_cannot_pass_an_unvisited_goal_via_the_return_leg():
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    plan = _spur_plan()
    follower = TourFollower(plan)
    follower.index = _index_near(plan, (1.7, 0.5))
    # 0.8 m before the dead end; the return leg passes 0.2 m away.
    selection = follower.select(_grid(), (1.7, 0.5), 0., navigator.planner.core, yaw_rad=0.)
    assert follower.index <= plan.goal_indices[0]
    assert selection.reason == 'tour_target'
    assert selection.goal_world_xy[0] > 1.8  # still heading into the spur
    follower.report_reached((1.7, 0.7), 1.)  # a return-leg point
    assert follower.index <= plan.goal_indices[0]


def test_scan_at_goal_rotates_in_steps_then_continues():
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    plan = _spur_plan()
    follower = TourFollower(plan, scan_degrees=360., scan_step_degrees=90.)
    follower.index = _index_near(plan, (2.4, 0.5))
    core = navigator.planner.core
    first = follower.select(_grid(), (2.5, 0.5), 0., core, yaw_rad=0.)
    assert first.reason == 'tour_scan' and first.goal_id.endswith('-0')
    assert first.heading_rad == pytest.approx(math.pi / 2)
    assert first.path is None and math.dist(first.goal_world_xy, (2.5, 1.0)) < 1e-9
    # The same step is repeated until the local follower reports alignment.
    again = follower.select(_grid(), (2.5, 0.5), 5., core, yaw_rad=.5)
    assert again.goal_id == first.goal_id and follower.counts['skipped'] == 0
    for step in range(4):
        follower.report_scan_done(f'scan-{plan.goal_indices[0]}-{step}', 6. + step)
    assert follower.counts['scans'] == 1 and plan.goal_indices[0] in follower._passed_goals
    after = follower.select(_grid(), (2.5, 0.5), 12., core, yaw_rad=0.)
    assert after.reason == 'tour_target' and after.goal_world_xy[0] < 2.4
    assert follower.status()['scanned_xy'] == [list(plan.polyline[plan.goal_indices[0]])]


def test_scan_step_timeout_and_min_separation():
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    plan = _spur_plan()
    follower = TourFollower(plan, scan_degrees=180., scan_step_degrees=90.,
                            scan_step_timeout_s=2., scan_min_separation_m=5.)
    follower.index = _index_near(plan, (2.4, 0.5))
    core = navigator.planner.core
    assert follower.select(_grid(), (2.5, 0.5), 0., core, yaw_rad=0.).reason == 'tour_scan'
    follower.select(_grid(), (2.5, 0.5), 2.5, core, yaw_rad=0.)  # step 0 timed out
    follower.select(_grid(), (2.5, 0.5), 5.0, core, yaw_rad=0.)  # step 1 timed out
    assert follower.counts['scan_step_timeouts'] == 2 and follower.counts['scans'] == 1
    # The final goal is within 5 m of the scanned one: passed without a scan.
    follower.index = len(plan.polyline) - 2
    follower.select(_grid(), (0.5, 0.7), 6., core, yaw_rad=0.)
    assert follower.counts['scans'] == 1


def test_navigator_emits_rotation_only_scan_intent_and_routes_completion():
    plan = _spur_plan()
    follower = TourFollower(plan, scan_degrees=360.)
    follower.index = _index_near(plan, (2.4, 0.5))
    world = nav(np.zeros((60, 60), np.int8))
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', tour=follower,
                          goal_selection_max_age_ns=1_000_000_000)
    decision = navigator.step(world, (2.5, 0.5), 0., world.capture_monotonic_ns + 50_000_000)
    assert decision.goal_id.startswith('scan-') and decision.reason == 'tour_scan'
    assert decision.desired_linear_mps == decision.desired_yaw_radps == 0.
    assert decision.path[0] == (2.5, 0.5) and len(decision.path) == 2
    navigator.report_goal_reached(decision.goal_id, decision.path[-1])
    assert follower.counts['scan_steps'] == 1


def test_local_follower_scan_rotates_in_place_and_stops_when_aligned():
    from neusymnav.navigation.local_control import LocalFollower
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', max_pulse_s=.5)
    follower = LocalFollower(navigator)
    world = nav(np.zeros((30, 30), np.int8))
    now = world.capture_monotonic_ns + 10_000_000
    intent = SimpleNamespace(goal_id='scan-5-0', path=((1., 1.), (1., 1.5)),
                             clock_domain=world.clock_domain, compatible=lambda n, t: True)
    turning = follower.step(world, intent, (1., 1.), 0., now)
    assert turning.desired_linear_mps == 0. and turning.reason == 'tour_scan'
    assert turning.desired_yaw_radps == pytest.approx(math.radians(30.))
    small = follower.step(world, intent, (1., 1.), math.pi / 2 - math.radians(20), now)
    assert 0 < small.desired_yaw_radps <= math.radians(20) / .5 + 1e-9
    done = follower.step(world, intent, (1., 1.), math.pi / 2 - math.radians(3), now)
    assert done.reason == 'world_goal_reached' and done.desired_yaw_radps == 0.


def test_tour_plan_load_and_config_keys(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.launcher import _keyframe_policy, _navigation_options
    plan = _spur_plan()
    document = dict(schema_version=1, kind='navmesh_coverage_tour', privileged=True,
                    polyline_xy=[list(p) for p in plan.polyline], start_xy=list(plan.polyline[0]),
                    goals_xy=[[2.5, 0.5], [0.5, 0.7]], scene=dict(sha256='a' * 64), length_m=4.)
    path = tmp_path / 'tour.json'
    data = json.dumps(document).encode()
    path.write_bytes(data)
    loaded_plan = TourPlan.load(path, hashlib.sha256(data).hexdigest())
    assert loaded_plan.goal_indices == plan.goal_indices
    tour = dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), scan_degrees=360,
                scan_min_separation_m=2.5)
    loaded = load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True},
                                                      'tour': tour},
                                keyframe_novelty=dict(min_translation_m=.15, min_yaw_deg=15)))
    loaded.data['sensor_config'] = dict(loaded.data.get('sensor_config', {}), initial_position=[0.5, 0., -0.5])
    follower = _navigation_options(loaded)['tour']
    assert follower.scan_degrees == 360. and follower.scan_min_separation_m == 2.5
    policy = _keyframe_policy(loaded)
    assert policy.distance == .15 and policy.angle == pytest.approx(math.radians(15))
    with pytest.raises(ValueError, match='keyframe_novelty'):
        load_config(config(tmp_path, keyframe_novelty=dict(min_translation_m=.01, min_yaw_deg=15)))
    with pytest.raises(ValueError):
        load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True},
                                                 'tour': dict(tour, scan_degrees=400)}))
