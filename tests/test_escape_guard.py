"""Escape commands near obstacles (approved 12/11/2026): body radius only, short, strictly away."""
from dataclasses import replace

import numpy as np
import pytest

from neusymnav.contracts import GridState, NavigationDecision
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry
from neusymnav.navigation.safety import MotionGuard, free_distance
from test_navmap import down as _down


def down(i=0):
    return _down(i, size=201, focal=60.)       # dense enough for 5 cm cells

DOMAIN = 'host_monotonic:test'


def setup(tmp_path, *, escape=True, obstacle_x=(0.25, 0.30)):
    robot = RobotGeometry('cylinder-v1', .2, 1., .1, .05)          # body 0.2 m, inflated 0.3 m
    m = NavMapper(robot=robot, floor_z_m=3., floor_datum_source='scene-calibration:v1', calibration_hash='a' * 64,
                  resolution_m=.05, tile_size_cells=16, sampling_stride=1, snapshot_radius_m=3., tile_archive_dir=tmp_path)
    m.update(down())
    n = m.update(down(1))
    states = np.array(n.states, copy=True)
    res, (ox, oy) = n.resolution_m, n.origin_xy
    cols = (ox + (np.arange(states.shape[1]) + .5) * res)
    rows = (oy + (np.arange(states.shape[0]) + .5) * res)
    xs, ys = np.meshgrid(cols, rows)
    states[(xs >= obstacle_x[0]) & (xs <= obstacle_x[1]) & (np.abs(ys) < .4)] = GridState.OCCUPIED
    n = replace(n, states=states)
    guard = MotionGuard(m, clock_domain=DOMAIN, escape=escape)
    return guard, n


def decide(n, reason, linear=0., yaw=0.):
    path = ((0., 0.), (-.15, 0.)) if linear else ()
    return NavigationDecision(None, path, linear, yaw, n.revision, reason)


def test_normal_commands_stay_blocked_inside_the_margin(tmp_path):
    guard, n = setup(tmp_path)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=np.pi)
    cmd = guard.filter(NavigationDecision('g', ((0., 0.), (-.3, 0.)), .15, 0., n.revision, 'tracking'), down(2), 1_000_000_000)
    assert cmd.linear_mps == 0 and cmd.reason == 'footprint_not_observed'
    cmd = guard.filter(decide(n, 'b0_spin', yaw=.5), down(3), 1_000_000_000)
    assert cmd.yaw_radps == 0                                      # plain rotation keeps the margin rule


def test_escape_step_away_is_issued_short_and_toward_is_refused(tmp_path):
    guard, n = setup(tmp_path)
    assert free_distance(n, (-.05, 0.), 1.) > free_distance(n, (0., 0.), 1.)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=np.pi)            # facing away from the obstacle
    cmd = guard.filter(decide(n, 'escape_step', linear=.1), down(2), 1_000_000_000)
    assert cmd.linear_mps == .1 and cmd.reason == 'escape_step'
    assert (cmd.deadline_monotonic_ns - cmd.issued_monotonic_ns) / 1e9 * .1 <= .05 + 1e-9
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)               # facing the obstacle
    cmd = guard.filter(decide(n, 'escape_step', linear=.1), down(3), 1_000_000_000)
    assert cmd.linear_mps == 0 and cmd.reason in ('escape_not_away', 'escape_body_not_clear')
    assert guard.escape_issued == 1


def test_escape_rotation_needs_the_body_disc_clear(tmp_path):
    guard, n = setup(tmp_path)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)
    assert guard.filter(decide(n, 'escape_rotate', yaw=.5), down(2), 1_000_000_000).yaw_radps == .5
    guard, n = setup(tmp_path / 'b', obstacle_x=(.10, .15))         # obstacle inside the body radius
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)
    cmd = guard.filter(decide(n, 'escape_rotate', yaw=.5), down(2), 1_000_000_000)
    assert cmd.yaw_radps == 0 and cmd.reason == 'escape_body_not_clear'


@pytest.mark.parametrize('dec', [
    lambda n: decide(n, 'escape_step', linear=.2),                 # faster than the escape limit
    lambda n: decide(n, 'escape_step', linear=.1, yaw=.2),         # no turning while stepping
    lambda n: decide(n, 'escape_rotate', linear=.1, yaw=.2),       # rotation must be in place
])
def test_malformed_escape_commands_are_refused(tmp_path, dec):
    guard, n = setup(tmp_path)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=np.pi)
    cmd = guard.filter(dec(n), down(2), 1_000_000_000)
    assert cmd.linear_mps == cmd.yaw_radps == 0


def test_escape_is_off_unless_enabled(tmp_path):
    guard, n = setup(tmp_path, escape=False)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=np.pi)
    cmd = guard.filter(decide(n, 'escape_step', linear=.1), down(2), 1_000_000_000)
    assert cmd.linear_mps == 0 and cmd.reason == 'escape_disabled'
    with pytest.raises(ValueError):
        MotionGuard(guard.mapper, clock_domain=DOMAIN, escape=1)


def test_planar_height_tolerant_filter_only_relaxes_height():
    from neusymnav.objectnav.sim_worker_entry import height_tolerant_filter, install
    class V(tuple):
        def __new__(cls, x, y, z):
            return tuple.__new__(cls, (x, y, z))
    raw = {'dy': .08}
    f = height_tolerant_filter(lambda s, e: V(e[0], s[1] + raw['dy'], e[2]), .10)
    assert f(V(0., 1., 0.), V(.05, 1., 0.)) == (.05, 1., 0.)            # 8 cm: height replaced
    raw['dy'] = .12
    assert f(V(0., 1., 0.), V(.05, 1., 0.))[1] == pytest.approx(1.12)  # 12 cm: unchanged, worker rejects
    raw['dy'] = .03
    assert f(V(0., 1., 0.), V(.05, 1., 0.))[1] == pytest.approx(1.03)  # within the worker's own 5 cm
    slide = height_tolerant_filter(lambda s, e: V(e[0], s[1] + .08, e[2] + .02), .10)
    assert slide(V(0., 1., 0.), V(.05, 1., 0.)) == (.05, 1., .02)       # sliding is left for the worker
    with pytest.raises(ValueError):
        install(object(), 'run', .2)


# ---------------------------------------------------------------- body-column fallback (approved 12/11/2026)

def _occluded(i, rows=slice(98, 103), cols=slice(108, 110), depth=.8):
    """Fresh frame with a thin object 1.2 m above the floor (above the 1.0 m body), 0.11 m to the side:
    it blocks the rays that would reach the upper body bins of a few nearby columns; their floor stays seen."""
    o = down(i)
    d = np.array(o.depth_m, copy=True)
    d[rows, cols] = depth
    return replace(o, depth_m=d)


def _mapper(tmp_path):
    robot = RobotGeometry('cylinder-v1', .2, 1., .1, .05)
    m = NavMapper(robot=robot, floor_z_m=3., floor_datum_source='scene-calibration:v1', calibration_hash='a' * 64,
                  resolution_m=.05, tile_size_cells=16, sampling_stride=1, snapshot_radius_m=3., tile_archive_dir=tmp_path)
    m.update(down())
    return m, m.update(down(1))


def test_column_fallback_accepts_only_unseen_body_columns_the_map_calls_free(tmp_path):
    m, n = _mapper(tmp_path)
    kw = dict(robot_xy=(0., 0.), yaw_rad=0., corridor_m=0., body_only=True)
    plain = m.bootstrap(_occluded(2), **kw)
    assert not plain.ready and plain.observed_cells < plain.required_cells
    missing = int(plain.required_cells - plain.observed_cells)
    ok = m.bootstrap(_occluded(2), column_fallback_nav=n, column_fallback_max_cells=12, **kw)
    assert ok.ready and ok.column_fallback == missing
    assert not m.bootstrap(_occluded(2), column_fallback_nav=n, column_fallback_max_cells=missing - 1, **kw).ready
    unknown = replace(n, states=np.full_like(np.asarray(n.states), GridState.UNKNOWN))   # map never saw those cells
    assert not m.bootstrap(_occluded(2), column_fallback_nav=unknown, column_fallback_max_cells=12, **kw).ready
    with pytest.raises(ValueError):
        m.bootstrap(_occluded(2), column_fallback_max_cells=4, **kw)            # needs the accumulated map
    with pytest.raises(ValueError):
        m.bootstrap(_occluded(2), column_fallback_nav=n, column_fallback_max_cells=13, **kw)


def test_column_fallback_never_covers_unseen_floor_or_a_return_in_the_body(tmp_path):
    m, n = _mapper(tmp_path)
    kw = dict(robot_xy=(0., 0.), yaw_rad=0., corridor_m=0., body_only=True, column_fallback_nav=n,
              column_fallback_max_cells=12)
    shadow = _occluded(2, rows=slice(95, 106), cols=slice(106, 116))          # its floor shadow falls in the disc
    assert not m.bootstrap(shadow, **kw).ready
    body = _occluded(3, rows=slice(95, 106), cols=slice(106, 113), depth=1.5)  # 0.5 m high: inside the body column
    assert not m.bootstrap(body, **kw).ready


def test_guard_escape_uses_the_column_fallback_only_when_enabled(tmp_path):
    for cells, expected in ((0, 'escape_bootstrap_blocked'), (6, 'escape_rotate')):
        guard, n = setup(tmp_path / str(cells), obstacle_x=(2.0, 2.05))
        guard.column_fallback_cells = cells
        guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)
        cmd = guard.filter(decide(n, 'escape_rotate', yaw=.5), _occluded(2), 1_000_000_000)
        assert cmd.reason == expected
        assert guard.column_fallback_used == (1 if cells else 0)
    with pytest.raises(ValueError):
        MotionGuard(guard.mapper, clock_domain=DOMAIN, column_fallback_cells=13)
