"""Opt-in tolerance for UNKNOWN cells in the robot's own current footprint.

Live 00806 v9: one UNKNOWN cell (occluded floor) in the current footprint made
every plan fail (`start_not_traversable`) and every guard bootstrap block,
including in-place rotation, for > 125 s.
"""
import base64
from dataclasses import replace
import json
import math
from pathlib import Path
import zlib

import numpy as np
import pytest

from test_navigation import nav
from test_navmap import down, geometry, mapper
from neusymnav.contracts import GridState
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.navigation._grid import adapt
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.start_footprint import tolerate_start_unknown, validate_tolerance


def _live():
    data = json.loads((Path(__file__).parent / 'fixtures' / 'start_footprint_00806_v9.json').read_text())

    def array(key):
        item = data[key]
        raw = zlib.decompress(base64.b64decode(item['zlib_b64']))
        return np.frombuffer(raw, dtype=item['dtype']).reshape(item['shape']).copy()

    snapshot = replace(nav(array('states')), resolution_m=data['resolution_m'],
                       origin_xy=tuple(data['origin_xy']), floor_support=array('floor_support'),
                       clearance=array('clearance'))
    return snapshot, tuple(data['robot_xy']), data['yaw_rad']


ROBOT = RobotGeometry('cylinder-v1', 0.2, 1.5, 0.05, 0.05)  # live 00806 geometry


def test_live_v9_start_cell_is_blocked_without_and_plannable_with_tolerance():
    snapshot, robot_xy, yaw = _live()
    strict = Navigator(ROBOT, clock_domain='host_monotonic:test')
    grid = adapt(snapshot, ROBOT.height_m, ROBOT.geometry_id)
    cell = grid.world_to_cell(*robot_xy)
    assert not strict.planner.core.traversable(grid)[cell]
    tolerant = Navigator(ROBOT, clock_domain='host_monotonic:test', start_unknown_tolerance=.2)
    cleared, count = tolerate_start_unknown(snapshot, robot_xy, radius_m=.25, height_m=1.5,
                                            max_fraction=.2, pad_cell=True)
    assert 0 < count <= 3
    grid2 = adapt(cleared, ROBOT.height_m, ROBOT.geometry_id)
    assert tolerant.planner.core.traversable(grid2)[grid2.world_to_cell(*robot_xy)]
    # Only previously UNKNOWN cells changed; occupied/free cells are untouched.
    changed = cleared.states != snapshot.states
    assert np.all(snapshot.states[changed] == GridState.UNKNOWN)
    assert np.all(cleared.states[changed] == GridState.FREE)


def _disc_case(unknown_cells=1, occupied=False):
    states = np.zeros((15, 15), np.int8)
    states[7, 7:7 + unknown_cells] = GridState.UNKNOWN
    if occupied:
        states[6, 7] = GridState.OCCUPIED
    return nav(states)


def test_tolerance_refuses_occupied_or_too_many_unknown_cells():
    robot_xy = (.75, .75)  # centre of cell (7, 7) on the 0.1 m test grid
    ok, count = tolerate_start_unknown(_disc_case(1), robot_xy, radius_m=.1, height_m=1.5, max_fraction=.2)
    assert count == 1 and ok.states[7, 7] == GridState.FREE
    same, count = tolerate_start_unknown(_disc_case(1, occupied=True), robot_xy, radius_m=.1,
                                         height_m=1.5, max_fraction=.2)
    assert count == 0 and same.states[7, 7] == GridState.UNKNOWN
    same, count = tolerate_start_unknown(_disc_case(3), robot_xy, radius_m=.1, height_m=1.5, max_fraction=.2)
    assert count == 0
    same, count = tolerate_start_unknown(_disc_case(1), robot_xy, radius_m=.1, height_m=1.5, max_fraction=0.)
    assert count == 0
    for bad in (-.1, .31, True and 'x'):
        with pytest.raises(ValueError):
            validate_tolerance(bad)


def test_bootstrap_tolerates_start_disc_only_and_never_the_swept_corridor(tmp_path):
    m = mapper(tmp_path)
    obs = down(2)
    real = m.measured_coverage

    def with_hole(observation, required_bounds_xy):
        coverage = real(observation, required_bounds_xy=required_bounds_xy)
        states = np.array(coverage.states, copy=True)
        r, c = coverage.states.shape[0] // 2, coverage.states.shape[1] // 2
        states[r, c] = GridState.UNKNOWN  # under the robot
        return replace(coverage, states=states), (r, c)

    holder = {}

    def patched(observation, required_bounds_xy):
        coverage, cell = with_hole(observation, required_bounds_xy)
        holder['cell'] = cell
        holder['nav'] = coverage
        return coverage

    m.measured_coverage = patched
    # Robot exactly at the hole cell centre.
    def robot_at_hole():
        coverage = real(obs, required_bounds_xy=((-1., -1.), (1., 1.)))
        r, c = coverage.states.shape[0] // 2, coverage.states.shape[1] // 2
        return (coverage.origin_xy[0] + (c + .5) * coverage.resolution_m,
                coverage.origin_xy[1] + (r + .5) * coverage.resolution_m)
    xy = robot_at_hole()
    blocked = m.bootstrap(obs, robot_xy=xy, yaw_rad=0., corridor_m=0.)
    assert not blocked.ready
    allowed = m.bootstrap(obs, robot_xy=xy, yaw_rad=0., corridor_m=0., start_unknown_fraction=.2)
    assert allowed.ready and allowed.start_tolerated == 1
    forward = m.bootstrap(obs, robot_xy=xy, yaw_rad=0., corridor_m=.02, start_unknown_fraction=.2)
    assert forward.ready  # the corridor beyond the start disc is measured FREE


def test_config_and_navigator_option(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.launcher import _navigation_options
    with pytest.raises(ValueError, match='local_depth_control'):
        load_config(config(tmp_path, navigation={'controller': {'start_unknown_tolerance': .2}}))
    with pytest.raises(ValueError, match='start_unknown_tolerance'):
        load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True,
                                                                'start_unknown_tolerance': .5}}))
    loaded = load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True,
                                                                     'start_unknown_tolerance': .2}}))
    assert _navigation_options(loaded)['start_unknown_tolerance'] == .2
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', start_unknown_tolerance=.2)
    from neusymnav.navigation.local_control import LocalFollower
    assert LocalFollower(navigator).start_unknown_tolerance == .2


# --- Live 00806, 09/11 evening: guard and follower tolerated DIFFERENT discs ---
# Four runs (v8.1, v9.1, demo-live, demo-live1) froze at (-5.94, 0.46). The
# local follower tolerated a padded footprint disc and planned through a cell
# the guard (unpadded disc) still saw as UNKNOWN, so every forward pulse was
# refused with path_segment_blocked and the robot never rotated to re-measure.

def _mismatch_cases():
    data = json.loads((Path(__file__).parent / 'fixtures'
                       / 'start_footprint_00806_guard_mismatch.json').read_text())
    for case in data['cases']:
        item = case['live_nav']

        def array(key):
            raw = zlib.decompress(base64.b64decode(item[key]['zlib_b64']))
            return np.frombuffer(raw, dtype=item[key]['dtype']).reshape(item[key]['shape']).copy()

        snapshot = replace(nav(array('states')), resolution_m=item['resolution_m'],
                           origin_xy=tuple(item['origin_xy']), floor_support=array('floor_support'),
                           clearance=array('clearance'))
        yield (case['run'], snapshot, tuple(case['robot_xy']), case['yaw_rad'],
               case['world_goal_id'], tuple(tuple(p) for p in case['world_path']))


def _guard(snapshot, tolerance=.2):
    from types import SimpleNamespace
    from neusymnav.navigation.safety import MotionGuard
    mapper = SimpleNamespace(robot=ROBOT, floor_z_m=snapshot.floor_z_m,
                             calibration_hash=snapshot.calibration_hash)
    return MotionGuard(mapper, clock_domain='host_monotonic:test', start_unknown_tolerance=tolerance)


def _follow(snapshot, robot_xy, yaw, goal_id, path):
    from neusymnav.navigation.local_control import LocalFollower, WorldIntent
    navigator = Navigator(ROBOT, clock_domain='host_monotonic:test', start_unknown_tolerance=.2,
                          discrete_heading_control=True, gain_aware=True, acceleration_mps2=.6,
                          max_pulse_s=.5)
    follower = LocalFollower(navigator)
    now = snapshot.capture_monotonic_ns + 60_000_000
    intent = WorldIntent.from_decision(snapshot, goal_id, path, now, ttl_ns=4_000_000_000)
    decision = follower.step(snapshot, intent, robot_xy, yaw, now + 40_000_000)
    return decision


def test_live_mismatch_follower_and_guard_now_agree_and_the_robot_may_move():
    from neusymnav.navigation.start_footprint import tolerate_robot_footprint
    cases = list(_mismatch_cases())
    assert len(cases) == 3
    for run, snapshot, robot_xy, yaw, goal_id, path in cases:
        decision = _follow(snapshot, robot_xy, yaw, goal_id, path)
        assert decision.desired_linear_mps > 0, (run, decision.reason)
        guard = _guard(snapshot)
        guard.bind_nav(snapshot, robot_xy=robot_xy, yaw_rad=yaw)
        bound = guard._bound[0]
        # The guard binds exactly the map the follower planned on.
        followed, _ = tolerate_robot_footprint(snapshot, robot_xy, ROBOT, .2)
        assert np.array_equal(bound.states, followed.states), run
        points = (robot_xy,) + tuple(decision.path)
        assert all(guard._clear(bound, a, b) for a, b in zip(points, points[1:])), run
        # Regression: the former unpadded guard disc refused the first segment.
        old, _ = tolerate_start_unknown(snapshot, robot_xy, radius_m=.25, height_m=1.5, max_fraction=.2)
        assert not guard._clear(old, points[0], points[1]), run


def test_shared_disc_still_refuses_occupied_and_never_extends_beyond_the_padded_footprint():
    from neusymnav.navigation.start_footprint import tolerance_radius_m, tolerate_robot_footprint
    run, snapshot, robot_xy, yaw, _, _ = next(_mismatch_cases())
    cleared, count = tolerate_robot_footprint(snapshot, robot_xy, ROBOT, .2)
    assert 0 < count <= 3
    changed = np.argwhere(cleared.states != snapshot.states)
    radius = tolerance_radius_m(ROBOT, snapshot.resolution_m)
    for r, c in changed:
        centre = (snapshot.origin_xy[0] + (c + .5) * snapshot.resolution_m,
                  snapshot.origin_xy[1] + (r + .5) * snapshot.resolution_m)
        assert math.dist(centre, robot_xy) <= radius + snapshot.resolution_m
    # An OCCUPIED cell inside the disc disables the exception entirely.
    states = np.array(snapshot.states, copy=True)
    r, c = map(int, changed[0])
    states[r, c] = GridState.OCCUPIED
    blocked, count = tolerate_robot_footprint(replace(snapshot, states=states), robot_xy, ROBOT, .2)
    assert count == 0
