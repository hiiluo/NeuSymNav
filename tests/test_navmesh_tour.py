"""Privileged navmesh tour: offline coverage planning and runtime follower."""
from dataclasses import replace
import hashlib
import json
import math

import numpy as np
import pytest

from test_navigation import nav
from test_navmap import geometry
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.tour import (GOAL_SOURCE, TourFollower, TourPlan, canonical_xy,
                                       densify, plan_coverage_tour, tour_document)


class TwoRoomPathfinder:
    """Two 4x4 m rooms (x in [0,4] and [5,9]) joined by a door at z in [1.6,2.4]."""

    def bounds(self):
        return (0., 0., 0.), (9., 0., 4.)

    def _inside(self, x, z):
        return (0 <= x <= 4 and 0 <= z <= 4) or (5 <= x <= 9 and 0 <= z <= 4) or (
            4 <= x <= 5 and 1.6 <= z <= 2.4)

    def snap(self, xyz):
        x, y, z = xyz
        x, z = min(max(x, 0.), 9.), min(max(z, 0.), 4.)
        if not self._inside(x, z):
            z = min(max(z, 1.6), 2.4)
        return (x, 0.0, z) if self._inside(x, z) else None

    def island(self, xyz):
        return 0

    def path(self, a, b):
        ax, _, az = a
        bx, _, bz = b
        if (ax <= 4.5) == (bx <= 4.5):
            return math.dist((ax, az), (bx, bz)), [a, b]
        door = ((4.5, 0.0, 2.0))
        return math.dist((ax, az), (4.5, 2.)) + math.dist((4.5, 2.), (bx, bz)), [a, door, b]


def test_offline_tour_covers_both_rooms_through_the_door():
    result = plan_coverage_tour(TwoRoomPathfinder(), (1., 0., 1.), spacing_m=1.0,
                                coverage_radius_m=1.5)
    goals = result['goals']
    assert any(g[0] < 4 for g in goals) and any(g[0] > 5 for g in goals)
    assert any(abs(p[0] - 4.5) < 1e-9 for p in result['polyline'])  # passes the door
    # Every candidate cell ends within coverage radius of some goal or the start.
    covered = [result['start'], *goals]
    for x in np.arange(0, 9.01, 1.0):
        for z in np.arange(0, 4.01, 1.0):
            point = TwoRoomPathfinder().snap((x, 0, z))
            if point is not None:
                assert min(math.dist((point[0], point[2]), (c[0], c[2])) for c in covered) <= 1.5 + 1e-9


def test_tour_document_is_canonical_dense_and_loadable(tmp_path):
    result = plan_coverage_tour(TwoRoomPathfinder(), (1., 0., 1.))
    document = tour_document(result, scene_path='s.glb', scene_sha256='a' * 64, spacing_m=1.0,
                             coverage_radius_m=1.5, agent_radius_m=.2, agent_height_m=1.5)
    assert document['privileged'] is True and document['goal_source'] == GOAL_SOURCE
    assert document['start_xy'] == list(canonical_xy(result['start'])) == [1.0, -1.0]
    path = tmp_path / 'tour.json'
    data = json.dumps(document).encode()
    path.write_bytes(data)
    plan = TourPlan.load(path, hashlib.sha256(data).hexdigest())
    assert len(plan.polyline) == len(document['polyline_xy'])
    assert all(math.dist(a, b) <= .3 + 1e-6 for a, b in zip(plan.polyline, plan.polyline[1:]))
    with pytest.raises(ValueError, match='sha256'):
        TourPlan.load(path, 'b' * 64)
    bad = dict(document, privileged=False)
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        TourPlan.load(path)
    sparse = dict(document, polyline_xy=[[0, 0], [2, 0]])
    path.write_text(json.dumps(sparse))
    with pytest.raises(ValueError, match='densified'):
        TourPlan.load(path)


def _plan(points):
    dense = densify(points)
    return TourPlan(tuple(dense), dense[0], 'a' * 64, 'b' * 64, 0.)


def test_follower_targets_farthest_plannable_point_and_advances(tmp_path):
    from neusymnav.navigation._grid import adapt
    world = nav()  # 15x15 free cells of 0.1 m, origin (0,0)
    grid = adapt(world, geometry().height_m, geometry().geometry_id)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    follower = TourFollower(_plan([(0.45, 0.45), (1.05, 0.45), (1.05, 1.05)]), lookahead_m=0.8)
    selection = follower.select(grid, (0.45, 0.45), 1.0, navigator.planner.core)
    assert selection.reason == 'tour_target' and selection.goal_id.startswith('tour-')
    assert selection.path.success and math.dist(selection.goal_world_xy, (0.45, 0.45)) > 0.5
    # Moving along the route advances progress monotonically.
    follower.select(grid, (1.05, 0.45), 2.0, navigator.planner.core)
    assert follower.index > 0
    before = follower.index
    follower.select(grid, (0.45, 0.45), 3.0, navigator.planner.core)
    assert follower.index == before


def test_follower_skips_unreachable_segment_after_timeout():
    from neusymnav.navigation._grid import adapt
    states = np.zeros((15, 15), np.int8)
    states[:, 8:] = 100  # wall: every target beyond x=0.8 m is blocked
    grid = adapt(nav(states), geometry().height_m, geometry().geometry_id)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    follower = TourFollower(_plan([(0.45, 0.45), (1.25, 0.45), (1.25, 1.25)]),
                            lookahead_m=0.3, stuck_timeout_s=2.0, skip_m=0.5)
    first = follower.select(grid, (0.45, 0.45), 0.0, navigator.planner.core)
    index = follower.index
    later = follower.select(grid, (0.45, 0.45), 2.5, navigator.planner.core)
    assert follower.counts['skipped'] == 1 and follower.index > index
    assert follower.status()['skipped_xy']


def test_navigator_uses_tour_then_falls_back_to_frontiers():
    states = np.zeros((15, 15), np.int8)
    states[:, 13:] = -1
    world = nav(states)
    follower = TourFollower(_plan([(0.45, 0.45), (0.95, 0.45)]), reach_m=0.3)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', tour=follower,
                          goal_selection_max_age_ns=1_000_000_000)
    decision = navigator.step(world, (0.45, 0.45), 0., world.capture_monotonic_ns + 50_000_000)
    assert decision.goal_id.startswith('tour-') and decision.path
    navigator.report_goal_reached(decision.goal_id, decision.path[-1])
    assert follower.counts['reached'] == 1
    # At the end of the tour the robot keeps exploring with frontiers.
    done = navigator.step(replace(world, revision=2), (0.95, 0.45), 0.,
                          world.capture_monotonic_ns + 60_000_000)
    assert follower.complete
    assert done.goal_id and done.goal_id.startswith('frontier-')


def test_tour_config_requires_local_control_and_matching_start(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.launcher import _navigation_options
    result = plan_coverage_tour(TwoRoomPathfinder(), (1., 0., 1.))
    document = tour_document(result, scene_path='s.glb', scene_sha256='a' * 64, spacing_m=1.0,
                             coverage_radius_m=1.5, agent_radius_m=.2, agent_height_m=1.5)
    path = tmp_path / 'tour.json'
    data = json.dumps(document).encode()
    path.write_bytes(data)
    tour = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()}
    with pytest.raises(ValueError, match='local_depth_control'):
        load_config(config(tmp_path, navigation={'tour': tour}))
    loaded = load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True},
                                                      'tour': dict(tour, lookahead_m=1.2)}))
    loaded.data['sensor_config'] = dict(loaded.data.get('sensor_config', {}),
                                        initial_position=[1.0, 0.0, 1.0])
    options = _navigation_options(loaded)
    assert isinstance(options['tour'], TourFollower) and options['tour'].lookahead_m == 1.2
    loaded.data['sensor_config']['initial_position'] = [3.0, 0.0, 3.0]
    with pytest.raises(ValueError, match='start'):
        _navigation_options(loaded)
    with pytest.raises(ValueError):
        load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True},
                                                 'tour': dict(tour, lookahead_m=9.0)}))


# ---------------------------------------------------------------------------
# Live regression: tour-00807-300s stood still after 0.5 m (2026-11-09)
# ---------------------------------------------------------------------------

def _live_corner_case():
    import base64
    from pathlib import Path
    import zlib
    from neusymnav.mapping.occupancy import RobotGeometry
    from neusymnav.navigation._grid import adapt
    data = json.loads((Path(__file__).parent / 'fixtures' / 'tour_00807_corner_map.json').read_text())

    def array(key):
        item = data[key]
        raw = zlib.decompress(base64.b64decode(item['zlib_b64']))
        return np.frombuffer(raw, dtype=item['dtype']).reshape(item['shape']).copy()

    snapshot = replace(nav(array('states')), resolution_m=data['resolution_m'],
                       origin_xy=tuple(data['origin_xy']), floor_support=array('floor_support'),
                       clearance=array('clearance'))
    robot = RobotGeometry('cylinder-v1', 0.2, 1.5, 0.05, 0.05)  # live 00807 geometry
    navigator = Navigator(robot, clock_domain='host_monotonic:test')
    grid = adapt(snapshot, robot.height_m, robot.geometry_id)
    plan = TourPlan(tuple(map(tuple, data['polyline_xy'])), tuple(data['polyline_xy'][0]),
                    'a' * 64, 'b' * 64, 0.)
    return grid, navigator, plan, tuple(data['robot_xy'])


def test_live_00807_corner_route_is_relaxed_to_traversable_cells():
    grid, navigator, plan, robot_xy = _live_corner_case()
    traversable = navigator.planner.core.traversable(grid)
    # The navmesh route hugs the wall corner: none of the next route points is
    # footprint-free on the observed map (this is why the robot stood still).
    ahead = [grid.world_to_cell(*p) for p in plan.polyline[3:8]]
    assert not any(c is not None and traversable[c] for c in ahead)
    exact = TourFollower(plan, relax_m=0.0, approach_m=0.0)
    exact.index = 2
    assert exact.select(grid, robot_xy, 0., navigator.planner.core).reason == 'tour_target_unobserved'
    follower = TourFollower(plan)
    selection = follower.select(grid, robot_xy, 0., navigator.planner.core)
    assert selection.reason == 'tour_target' and selection.path.success
    goal_cell = grid.world_to_cell(*selection.goal_world_xy)
    assert traversable[goal_cell]
    index = int(selection.goal_id.split('-')[1])
    assert index > 3 and math.dist(selection.goal_world_xy, plan.polyline[index]) <= follower.relax_m
    assert follower.counts['relaxed'] == 1
    # Reaching the relaxed goal advances progress to that route index.
    follower.report_reached(selection.goal_world_xy, 1., index=index)
    assert follower.index == index


def test_navigator_explores_frontiers_instead_of_stopping_when_tour_is_unobserved():
    states = np.zeros((15, 15), np.int8)
    states[:, 13:] = -1
    world = nav(states)
    # Route leads into a region outside this observed map.
    follower = TourFollower(_plan([(0.45, 0.45), (0.45, 5.0), (0.45, 6.0)]), approach_m=0.0)
    follower.index = 8  # route point at y=2.85 m: the look-ahead is >1 m beyond the map
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', tour=follower,
                          goal_selection_max_age_ns=1_000_000_000)
    decision = navigator.step(world, (0.45, 0.45), 0., world.capture_monotonic_ns + 50_000_000)
    assert decision.goal_id and decision.goal_id.startswith('frontier-') and decision.path
    assert navigator.tour_fallback_active and navigator.tour_fallback_steps == 1
    assert follower.counts['unobserved'] == 1 and not follower.complete


def test_follower_approaches_closest_reachable_cell_when_route_is_beyond_the_map():
    from neusymnav.navigation._grid import adapt
    grid = adapt(nav(), geometry().height_m, geometry().geometry_id)  # 1.5 m square, all free
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    follower = TourFollower(_plan([(0.45, 0.45), (0.45, 2.5), (0.45, 3.5)]), lookahead_m=0.6)
    selection = follower.select(grid, (0.45, 0.45), 0., navigator.planner.core)
    # Points inside the map within the look-ahead are used first...
    assert selection.reason == 'tour_target'
    follower.index = 6  # ...once the look-ahead lies beyond the map, approach it.
    far = follower.select(grid, (0.45, 0.45), 1., navigator.planner.core)
    assert far.reason == 'tour_target_approach' and far.path.success
    assert far.goal_world_xy[1] > 1.0


# ---------------------------------------------------------------------------
# Live regression: tour-00806-300s-v3 dropped a 28 m loop at 119.5 s (2026-11-09)
# ---------------------------------------------------------------------------

def _loop_case():
    from neusymnav.navigation._grid import adapt
    grid = adapt(nav(np.zeros((60, 60), np.int8)), geometry().height_m, geometry().geometry_id)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    # Out along y=0.5, around a loop, then back along y=0.8 (0.3 m from leg 1),
    # like the 00806 tour that passes the same corridor twice.
    route = [(0.5, 0.5), (5.5, 0.5), (5.5, 5.5), (0.5, 5.5), (0.5, 0.8), (5.5, 0.8)]
    return grid, navigator, _plan(route)


def test_progress_never_jumps_to_a_later_pass_of_the_same_corridor():
    grid, navigator, plan = _loop_case()
    follower = TourFollower(plan)
    follower.index = min(range(len(plan.polyline)), key=lambda i: math.dist(plan.polyline[i], (2.0, 0.5)))
    before = follower.index
    # Robot stands at x=1.0 on leg 1; the return leg passes 0.3 m away.
    selection = follower.select(grid, (1.0, 0.5), 0., navigator.planner.core, yaw_rad=0.)
    assert follower.index - before < 10  # stays on leg 1 (old code: jumped ~100 points)
    assert selection.reason == 'tour_target'
    assert plan.polyline[int(selection.goal_id.split('-')[1])][1] < 0.6
    follower.report_reached((1.0, 0.8), 1.)  # a point of the return leg
    assert follower.index - before < 10


def test_turning_toward_the_target_is_not_stuck_but_a_stall_still_skips():
    grid, navigator, plan = _loop_case()
    follower = TourFollower(plan, stuck_timeout_s=2.0, stall_timeout_s=6.0)
    core = navigator.planner.core
    follower.select(grid, (0.5, 0.5), 0., core, yaw_rad=math.pi)
    # Turning 0.5 rad per second in place for 5 s: no skip.
    for t in range(1, 6):
        follower.select(grid, (0.5, 0.5), float(t), core, yaw_rad=math.pi - 0.5 * t)
    assert follower.counts['skipped'] == 0 and follower.counts['motion_resets'] >= 4
    # Still no route progress after the stall bound: skip once.
    follower.select(grid, (0.5, 0.5), 6.5, core, yaw_rad=0.)
    assert follower.counts['skipped'] == 1


def test_status_reports_coverage_and_whether_the_end_was_reached_or_skipped():
    grid, navigator, plan = _loop_case()
    walked = TourFollower(plan)
    for i, point in enumerate(plan.polyline):
        walked.select(grid, point, float(i), navigator.planner.core, yaw_rad=0.)
    status = walked.status()
    assert status['complete'] and status['complete_reason'] == 'reached'
    assert status['coverage'] == 1.0
    skipped = TourFollower(plan, stuck_timeout_s=1.0, skip_m=5.0)
    for t in range(0, 200, 2):
        skipped.select(grid, (0.5, 0.5), float(t), navigator.planner.core, yaw_rad=0.)
        if skipped.complete:
            break
    status = skipped.status()
    assert status['complete_reason'] == 'skipped' and status['coverage'] < 0.2
    assert status['counts']['skipped_points'] > 0
