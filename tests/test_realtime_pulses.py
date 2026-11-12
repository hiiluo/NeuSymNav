"""Real-time guarded pulses: longer translation pulses bounded by depth TTL and
wall time, and pure in-place rotation pulses (2026-11-09, 00806 benchmark)."""
import math

import pytest

from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.safety import MotionGuard
from test_navmap import down, geometry, mapper

MS = 1_000_000


def _guard(tmp_path, **kwargs):
    m = mapper(tmp_path)
    m.update(down(0, stamp=1_000 * MS))
    n = m.update(down(1, stamp=1_000 * MS))
    guard = MotionGuard(m, clock_domain='host_monotonic:test', **kwargs)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)
    return guard, m, n


def _fresh(guard, m, index, stamp_ms):
    n = m.update(down(index, stamp=stamp_ms * MS))
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)
    return n


def _move(n):
    return NavigationDecision('g', ((0., 0.), (.3, 0.)), .15, 0., n.revision, 'tracking')


def _turn(n):
    return NavigationDecision('g', ((0., 0.), (0., .3)), 0., .5, n.revision, 'align_heading')


def test_unpaced_guard_keeps_previous_rotation_and_horizon_semantics(tmp_path):
    guard, m, n = _guard(tmp_path, command_horizon_ns=1_000 * MS)
    n = _fresh(guard, m, 3, 1_150)
    # Without the opt-in, rotation stays bounded by the depth TTL as before.
    turn = guard.filter(_turn(n), down(4, stamp=1_150 * MS), 1_200 * MS)
    assert turn.deadline_monotonic_ns == 1_450 * MS


def test_default_guard_keeps_the_100ms_pulse(tmp_path):
    guard, m, n = _guard(tmp_path)
    first = guard.filter(_move(n), down(2, stamp=1_000 * MS), 1_000 * MS)
    assert first.deadline_monotonic_ns - first.issued_monotonic_ns == 100 * MS
    n = _fresh(guard, m, 3, 1_250)
    second = guard.filter(_move(n), down(4, stamp=1_250 * MS), 1_250 * MS)
    assert second.deadline_monotonic_ns - second.issued_monotonic_ns == 100 * MS
    turn = guard.filter(_turn(n), down(5, stamp=1_250 * MS), 1_260 * MS)
    assert turn.deadline_monotonic_ns - turn.issued_monotonic_ns == 100 * MS


def test_translation_pulse_follows_wall_time_and_never_outlives_depth(tmp_path):
    guard, m, n = _guard(tmp_path, command_horizon_ns=300 * MS, pace_to_wall_time=True)
    first = guard.filter(_move(n), down(2, stamp=1_000 * MS), 1_000 * MS)
    assert first.deadline_monotonic_ns - first.issued_monotonic_ns == 100 * MS  # no history yet
    # Next motion command 250 ms later on fresh depth: the pulse spans the gap.
    n = _fresh(guard, m, 3, 1_250)
    second = guard.filter(_move(n), down(4, stamp=1_250 * MS), 1_250 * MS)
    assert second.deadline_monotonic_ns - second.issued_monotonic_ns == 250 * MS
    # Depth 200 ms old at issue: the pulse ends at capture + 300 ms.
    n = _fresh(guard, m, 5, 1_400)
    third = guard.filter(_move(n), down(6, stamp=1_400 * MS), 1_600 * MS)
    assert third.deadline_monotonic_ns == 1_700 * MS


def test_pure_rotation_pulse_may_outlive_depth_but_must_start_fresh(tmp_path):
    guard, m, n = _guard(tmp_path, command_horizon_ns=300 * MS, rotation_horizon_ns=500 * MS,
                         pace_to_wall_time=True)
    guard.filter(_turn(n), down(2, stamp=1_000 * MS), 1_000 * MS)
    n = _fresh(guard, m, 3, 1_150)
    turn = guard.filter(_turn(n), down(4, stamp=1_150 * MS), 1_440 * MS)  # depth 290 ms old
    assert turn.yaw_radps == .5 and turn.deadline_monotonic_ns == 1_440 * MS + 440 * MS
    assert turn.deadline_monotonic_ns > 1_150 * MS + 300 * MS
    stale = guard.filter(_turn(n), down(5, stamp=1_150 * MS), 1_460 * MS)
    assert stale.yaw_radps == 0 and stale.reason in {'depth_stale', 'nav_stale'}


def test_horizon_bounds_are_validated(tmp_path):
    m = mapper(tmp_path)
    for kwargs in (dict(command_horizon_ns=0), dict(rotation_horizon_ns=99 * MS),
                   dict(rotation_horizon_ns=501 * MS), dict(pace_to_wall_time=1)):
        with pytest.raises(ValueError):
            MotionGuard(m, clock_domain='host_monotonic:test', **kwargs)
    with pytest.raises(ValueError):
        Navigator(geometry(), clock_domain='host_monotonic:test', max_pulse_s=.6)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', max_pulse_s=.5)
    assert navigator.controller.config.max_dt_s == .5


def test_pulse_config_requires_local_control_and_reaches_pipeline_options(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.launcher import _navigation_options, _pulse_horizons_ns
    with pytest.raises(ValueError, match='local_depth_control'):
        load_config(config(tmp_path, navigation={'controller': {'pulse_ms': 300}}))
    with pytest.raises(ValueError, match='rotation_pulse_ms'):
        load_config(config(tmp_path, navigation={'controller': {
            'local_depth_control': True, 'pulse_ms': 300, 'rotation_pulse_ms': 200}}))
    with pytest.raises(ValueError):
        load_config(config(tmp_path, navigation={'controller': {
            'local_depth_control': True, 'pulse_ms': 400}}))
    loaded = load_config(config(tmp_path, navigation={'controller': {
        'local_depth_control': True, 'pulse_ms': 300, 'rotation_pulse_ms': 500}}))
    assert _pulse_horizons_ns(loaded) == (300 * MS, 500 * MS)
    assert _navigation_options(loaded)['max_pulse_s'] == .5



def _rotation_proof(amount_deg, *, pulse_ms, capture_age_ms):
    from neusymnav.contracts import FrameKey, MotionCommand
    from neusymnav.runtime.actuation_measurements import command_sha256
    key = dict(episode_id='ep', sensor_id='downward-depth', frame_index=5)
    capture = 10_000 * MS
    issued = capture + capture_age_ms * MS
    source = dict(schema_version='runtime_measurement_source_v1', key=key, capture_monotonic_ns=capture,
                  clock_domain='host_monotonic:test', pose_version=5, calibration_id='habitat:x')
    w = -math.radians(30.)
    command = MotionCommand(FrameKey(**key), 6, issued, issued + pulse_ms * MS, 'host_monotonic:test',
                            0., w, 'align_heading', capture)
    yaw0 = 0.5
    proof = dict(schema_version=1, command_sha256=command_sha256(command), source=source, map_revision=6,
                 source_pose_version=5, complete=True, reason='executed',
                 actions=[dict(index=0, action='turn_right', amount=amount_deg,
                               pre_step_monotonic_ns=issued + MS, post_step_monotonic_ns=issued + 2 * MS,
                               pose_version_before=5, pose_version_after=6,
                               body_before_xy=[0., 0.], body_after_xy=[0., 0.],
                               yaw_before_rad=yaw0, yaw_after_rad=yaw0 - math.radians(amount_deg) * .999)])
    return proof, command, source


def test_host_proof_accepts_long_rotation_pulse_and_rejects_beyond_bounds():
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof
    # 500 ms rotation pulse issued 250 ms after capture: 14.9 deg at 30 deg/s.
    proof, command, source = _rotation_proof(14.9, pulse_ms=500, capture_age_ms=250)
    checked = validate_actuation_source_proof(proof, command, source, modality='depth_only')
    assert checked['action_count'] == 1
    for amount, pulse in ((16., 500), (10., 300)):  # beyond 15 deg; beyond 30 deg/s x 0.3 s
        proof, command, source = _rotation_proof(amount, pulse_ms=pulse, capture_age_ms=250)
        with pytest.raises(ValueError):
            validate_actuation_source_proof(proof, command, source, modality='depth_only')
