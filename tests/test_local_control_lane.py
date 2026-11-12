from dataclasses import replace

import pytest

from test_navigation import nav
from neusymnav.navigation.local_control import WorldIntent


def test_world_intent_preserves_source_and_rejects_expiry_and_scope_mismatch():
    world = nav()
    intent = WorldIntent.from_decision(world, 'goal', ((.35, .35), (.75, .35)), 1_100_000_000)
    assert intent.compatible(world, 3_000_000_000)
    assert not intent.compatible(world, 3_000_000_001)
    assert not intent.compatible(replace(world, episode_id='other', source=replace(world.source, episode_id='other')), 1_100_000_000)
    assert not intent.compatible(replace(world, calibration_hash='b'*64), 1_100_000_000)
    assert not intent.compatible(replace(world, clock_domain='replay:other'), 1_100_000_000)
    assert intent.capture_monotonic_ns == world.capture_monotonic_ns


def test_local_snapshot_is_current_measured_only_with_monotonic_revision(tmp_path):
    from test_navmap import down, mapper
    from neusymnav.navigation.local_control import LocalMeasuredMap
    from neusymnav.contracts import GridState
    base = mapper(tmp_path)
    local = LocalMeasuredMap(base)
    first = local.snapshot(down(), robot_xy=(0., 0.))
    second = local.snapshot(down(1, valid=False), robot_xy=(0., 0.))
    assert first.revision == 1 and second.revision == 2
    assert first.source == down().key and second.source == down(1).key
    assert (first.states == GridState.FREE).any()
    assert not (second.states == GridState.FREE).any()


def test_local_follower_replans_and_stops_on_unknown_or_stale_intent():
    import numpy as np
    from neusymnav.navigation.controller import Navigator
    from neusymnav.navigation.local_control import LocalFollower
    from test_navmap import geometry
    world = nav()
    intent = WorldIntent.from_decision(world, 'goal', ((.75, .75), (1.15, .75)), 1_000_000_000)
    follower = LocalFollower(Navigator(geometry(), clock_domain=world.clock_domain))
    decision = follower.step(world, intent, (.75, .75), 0., 1_000_000_000)
    assert decision.map_revision == world.revision and decision.path
    assert decision.desired_linear_mps > 0
    blocked = replace(world, states=np.full(world.states.shape, -1, np.int8), revision=2)
    assert follower.step(blocked, intent, (.75, .75), 0., 1_000_000_000).desired_linear_mps == 0
    assert follower.step(world, intent, (.75, .75), 0., 3_000_000_001).reason == 'world_intent_stale'


def test_local_mode_does_not_wait_for_world_map():
    from types import SimpleNamespace
    from neusymnav.runtime.launcher import _wait_exact_navigation
    pipeline = SimpleNamespace(local_depth_control=True)
    assert _wait_exact_navigation(pipeline, None, 0.) is None


def test_local_pipeline_control_uses_current_local_map_without_world_map(tmp_path):
    from test_guard_goal_feedback import pipeline, Actuator, DOMAIN, STAMP
    from test_navmap import mapper, down
    from neusymnav.navigation.controller import Navigator
    from neusymnav.navigation.local_control import LocalMeasuredMap, LocalFollower
    from neusymnav.navigation.safety import MotionGuard
    obs = down(0, stamp=STAMP, domain=DOMAIN)
    world_mapper = mapper(tmp_path)
    navigator = Navigator(world_mapper.robot, clock_domain=DOMAIN)
    p = pipeline(obs, None, navigator, None, now=STAMP)
    p.local_depth_control = True
    p._local_map = LocalMeasuredMap(world_mapper)
    p._local_follower = LocalFollower(navigator)
    p._local_guard = MotionGuard(p._local_map.mapper, clock_domain=DOMAIN)
    p._local_intent = None
    class Body(Actuator):
        def robot_pose(self, obs):
            return dict(super().robot_pose(obs), robot_xy=(0., 0.), yaw_rad=0.)
    body = Body()
    result = p.control_step(body)
    assert result['reason'] == 'world_intent_unavailable'
    assert body.commands[-1].map_revision == 1
    assert body.commands[-1].source == obs.key


def local_pipeline(tmp_path, *, intent=True):
    from collections import deque
    from test_guard_goal_feedback import pipeline, Actuator, DOMAIN, STAMP
    from test_navmap import mapper, down
    from neusymnav.navigation.controller import Navigator
    from neusymnav.navigation.local_control import LocalMeasuredMap, LocalFollower
    from neusymnav.navigation.safety import MotionGuard
    obs = down(0, stamp=STAMP, domain=DOMAIN)
    world_mapper = mapper(tmp_path)
    navigator = Navigator(world_mapper.robot, clock_domain=DOMAIN)
    p = pipeline(obs, None, navigator, None, now=STAMP)
    p.local_depth_control = True
    p._local_map = LocalMeasuredMap(world_mapper)
    p._local_follower = LocalFollower(navigator)
    p._local_guard = MotionGuard(p._local_map.mapper, clock_domain=DOMAIN)
    world = replace(nav(episode=obs.key.episode_id), source=obs.key, clock_domain=DOMAIN,
                    floor_datum_source=world_mapper.floor_datum_source)
    p._local_intent = WorldIntent.from_decision(world, 'goal', ((0., 0.), (.4, 0.)), STAMP) if intent else None
    p._local_feedback = deque(maxlen=1)
    p._local_intent_generation = 0
    class Body(Actuator):
        def robot_pose(self, obs):
            return dict(super().robot_pose(obs), robot_xy=(0., 0.), yaw_rad=0.)
    return p, Body(), world


def test_local_control_never_mutates_world_navigator(tmp_path):
    p, body, _ = local_pipeline(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('world Navigator has a single navigation-worker owner')
    p.navigator.step = forbidden
    p.navigator.reset_goal_failure_watch = forbidden
    p.navigator.observe_navigation_result = forbidden
    p.control_step(body)


def test_stale_world_step_preserves_previous_unexpired_intent_only(tmp_path):
    from neusymnav.contracts import NavigationDecision
    p, _, world = local_pipeline(tmp_path)
    previous = p._local_intent
    p.navigator.step = lambda *args: NavigationDecision(None, (), 0., 0., world.revision, 'nav_stale')
    p._update_world_intent(world, dict(robot_xy=(0., 0.), yaw_rad=0.))
    assert p._local_intent is previous
    p._update_world_intent(replace(world, clock_domain='host_monotonic:changed'), dict(robot_xy=(0., 0.), yaw_rad=0.))
    assert p._local_intent is None


def test_local_fault_clears_intent_and_does_not_reuse_source(tmp_path):
    p, body, _ = local_pipeline(tmp_path)
    p.control_step(body)
    before = len(body.commands)
    assert p.control_step(body)['reason'] == 'control_rejected'
    assert p._local_intent is None
    assert len(body.commands) == before
    assert p._step_navigation_diagnostics['control_map_scope'] == 'local_measured_depth_v1'
    assert p._step_navigation_diagnostics['world_intent'] is None


def test_paused_local_control_exposes_null_intent_telemetry_and_clears_intent(tmp_path):
    p, body, _ = local_pipeline(tmp_path)
    p._paused = True
    assert p.control_step(body)['reason'] == 'runtime_paused'
    detail = p._step_navigation_diagnostics
    assert detail['control_map_scope'] == 'local_measured_depth_v1' and detail['world_intent'] is None
    assert detail['goal_id'] is None and detail['path_point_count'] == 0
    assert p._local_intent is None and not body.commands


def test_local_map_is_bounded_without_changing_measured_center_evidence(tmp_path):
    import numpy as np
    from test_navmap import down, mapper
    from neusymnav.navigation.local_control import LocalMeasuredMap
    base = mapper(tmp_path)
    local = LocalMeasuredMap(base)
    obs = down()
    expected = base.measured_coverage(obs)
    actual = local.snapshot(obs, robot_xy=(0., 0.))
    assert actual.states.size < expected.states.size
    for xy in ((0., 0.), (.3, .1), (-.3, -.2)):
        er, ec = base.world_to_snapshot(expected, xy)
        ar, ac = base.world_to_snapshot(actual, xy)
        assert actual.states[ar, ac] == expected.states[er, ec]
        assert actual.floor_support[ar, ac] == expected.floor_support[er, ec]
        assert actual.clearance[ar, ac] == expected.clearance[er, ec]
    assert not actual.states.flags.writeable
    assert np.array_equal(actual.source, obs.key)


def test_world_feedback_uses_fresh_world_revision_without_single_local_penalty(tmp_path):
    from neusymnav.contracts import NavigationDecision
    p, _, world = local_pipeline(tmp_path)
    intent = replace(p._local_intent, map_revision=71)
    p._local_intent = intent
    p._local_feedback.append((intent, (0., 0.), 'local_path_blocked', True))
    calls = []
    p.navigator.report_goal_failure = lambda goal, revision, **kwargs: calls.append((goal, revision, kwargs))
    observed = []
    p.navigator.observe_navigation_result = lambda nav, xy, now, reason, stopped: observed.append((nav.revision, reason))
    p.navigator.step = lambda *args: NavigationDecision(None, (), 0., 0., world.revision, 'nav_stale')
    p._update_world_intent(replace(world, revision=72), dict(robot_xy=(0., 0.), yaw_rad=0.))
    assert observed == [(72, 'path_segment_blocked'), (72, 'nav_stale')]
    assert calls == []


def latch_world_goal(p):
    from types import SimpleNamespace
    from neusymnav.contracts import NavigationDecision
    p.navigator.policy._goal = SimpleNamespace(frontier_id='goal')
    p.navigator.policy._goal_world_xy = (.4, 0.)
    p.navigator._episode_id = p._latest_depth.key.episode_id
    def world_step(nav, *args):
        if p.navigator.policy._goal is None:
            return NavigationDecision(None, (), 0., 0., nav.revision, 'no_goal')
        return NavigationDecision('goal', ((0., 0.), (.4, 0.)), .1, 0., nav.revision, 'tracking')
    p.navigator.step = world_step


def test_one_unknown_local_frame_then_clear_does_not_blacklist_world_goal(tmp_path):
    import numpy as np
    p, body, world = local_pipeline(tmp_path)
    latch_world_goal(p)
    valid = p._latest_depth.valid_depth
    p._latest_depth = replace(p._latest_depth, valid_depth=np.zeros_like(valid))
    assert p.control_step(body)['reason'] == 'local_path_blocked'
    p._update_world_intent(replace(world, revision=101), dict(robot_xy=(0., 0.), yaw_rad=0.))
    assert not p.navigator.policy._failed_until_revision
    assert not p.navigator.policy._failed_viewpoints
    p._latest_depth = replace(p._latest_depth, key=replace(p._latest_depth.key, frame_index=1), valid_depth=valid)
    assert p.control_step(body)['executed']
    next_world = replace(world, source=p._latest_depth.key, revision=102)
    p._update_world_intent(next_world, dict(robot_xy=(0., 0.), yaw_rad=0.))
    assert not p.navigator.policy._failed_until_revision
    assert p.navigator._goal_failure_watch is None
    assert p._local_intent is not None


def test_sustained_local_missing_proof_recovers_using_fresh_world_revisions(tmp_path):
    import numpy as np
    from test_navmap import down
    p, body, world = local_pipeline(tmp_path)
    latch_world_goal(p)
    clock = [1_000_000_000]
    p.now_ns = lambda: clock[0]
    for index in range(21):
        clock[0] = 1_000_000_000 + index * 400_000_000
        current = down(index, valid=False, stamp=clock[0], domain=world.clock_domain)
        p._latest_depth = current
        assert p.control_step(body)['reason'] == 'local_path_blocked'
        current_world = replace(world, source=current.key, revision=100+index,
                                capture_monotonic_ns=clock[0])
        p._update_world_intent(current_world, dict(robot_xy=(0., 0.), yaw_rad=0.))
        if index < 20:
            assert not p.navigator.policy._failed_until_revision
            assert p._local_intent is not None
    assert p.navigator.policy._goal is None
    assert p._local_intent is None
    assert p.navigator.policy._failed_until_revision['goal'] == 220
    assert p._last_goal_failure['distinct_map_revisions'] == 21


def test_expiring_captured_intent_does_not_clear_newer_worker_publication(tmp_path):
    import threading
    from neusymnav.contracts import NavigationDecision
    p, body, world = local_pipeline(tmp_path)
    p.now_ns = lambda: 3_000_000_001
    p._latest_depth = replace(p._latest_depth, key=replace(p._latest_depth.key, frame_index=2),
                             capture_monotonic_ns=3_000_000_000)
    entered, resume = threading.Event(), threading.Event()
    follow = p._local_follower.step
    def blocked_follow(*args):
        entered.set()
        assert resume.wait(3.)
        return follow(*args)
    p._local_follower.step = blocked_follow
    results = []
    control = threading.Thread(target=lambda: results.append(p.control_step(body)))
    control.start()
    try:
        assert entered.wait(2.)
        next_world = replace(world, source=replace(world.source, frame_index=1),
                             capture_monotonic_ns=2_900_000_000, revision=72)
        p.navigator.step = lambda *args: NavigationDecision('goal', ((0., 0.), (.4, 0.)), .1, 0., 72, 'tracking')
        p._update_world_intent(next_world, dict(robot_xy=(0., 0.), yaw_rad=0.))
        newer = p._local_intent
        assert newer is not None and newer.map_revision == 72
    finally:
        resume.set()
        control.join(3.)
    assert not control.is_alive()
    assert results == [dict(executed=False, reason='world_intent_stale')]
    assert p._local_intent is newer
    assert p._local_intent_generation == 0


def test_local_control_moves_with_fresh_depth_independent_world_revision(tmp_path):
    p, body, _ = local_pipeline(tmp_path)
    p._local_intent = replace(p._local_intent, map_revision=71)
    assert p.control_step(body)['executed']
    command = body.commands[-1]
    assert command.map_revision == 1
    assert command.source == p._latest_depth.key
    assert command.source_capture_monotonic_ns == p._latest_depth.capture_monotonic_ns
    assert command.deadline_monotonic_ns <= command.issued_monotonic_ns + 100_000_000
    assert command.deadline_monotonic_ns <= p._latest_depth.capture_monotonic_ns + 300_000_000
    assert 0 < command.linear_mps <= .2
    assert p._step_navigation_diagnostics['world_intent']['map_revision'] == 71


def test_local_control_stale_intent_is_explicit_stop(tmp_path):
    p, body, _ = local_pipeline(tmp_path)
    p.now_ns = lambda: 3_000_000_001
    p._latest_depth = replace(p._latest_depth, key=replace(p._latest_depth.key, frame_index=1),
                             capture_monotonic_ns=3_000_000_000)
    assert p.control_step(body)['reason'] == 'world_intent_stale'
    assert not body.commands[-1].linear_mps and not body.commands[-1].yaw_radps
    assert p.navigation_status()['reason'] == 'world_intent_stale'
    assert p._local_intent is None


def test_local_current_depth_cannot_replace_unknown_with_world_history(tmp_path):
    import numpy as np
    p, body, _ = local_pipeline(tmp_path)
    assert p.control_step(body)['executed']
    p._latest_depth = replace(p._latest_depth,
        key=replace(p._latest_depth.key, frame_index=1),
        valid_depth=np.zeros_like(p._latest_depth.valid_depth))
    assert not p.control_step(body)['executed']
    assert body.commands[-1].reason == 'local_path_blocked'
    assert body.commands[-1].map_revision == 2


@pytest.mark.parametrize('offset', [-.27, 0., .35])
def test_bounded_local_votes_equal_independent_full_vote_crop(tmp_path, offset):
    import numpy as np
    from neusymnav.mapping.local_coverage import collect_local_measured_votes
    from test_navmap import mapper, down
    core = mapper(tmp_path)._core
    obs = down(x=offset)
    bounds = ((-.6, -.7), (.7, .6))
    grid_bounds = (-7, -6, 6, 7)
    full, _, _ = collect_local_measured_votes(obs, core, bounds)
    bounded, _, _ = collect_local_measured_votes(obs, core, bounds, grid_bounds=grid_bounds)
    r0, c0, r1, c1 = grid_bounds
    src = np.s_[r0-full.min_row:r1-full.min_row, c0-full.min_col:c1-full.min_col]
    assert (bounded.min_row, bounded.min_col) == (r0, c0)
    for name in ('planar_free','planar_hit','floor_hit','height_free','height_hit'):
        assert np.array_equal(getattr(bounded, name), getattr(full, name)[src]), name


def test_world_intent_publication_cannot_resurrect_after_control_fault(tmp_path):
    from neusymnav.contracts import NavigationDecision
    p, _, world = local_pipeline(tmp_path)
    def racing_step(*args):
        p._invalidate_local_intent()
        return NavigationDecision('goal', ((0., 0.), (.4, 0.)), .1, 0., world.revision, 'tracking')
    p.navigator.step = racing_step
    p._update_world_intent(world, dict(robot_xy=(0., 0.), yaw_rad=0.))
    assert p._local_intent is None


def test_local_profile_is_opt_in_allows_gc_and_rejects_non_boolean(tmp_path):
    import hashlib
    import json
    import sys
    from pathlib import Path
    from test_launcher import config
    from test_hydra_runtime import _hydra_profile
    from neusymnav.runtime.configuration import load_config
    assert load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True}}))
    with pytest.raises(ValueError, match='boolean'):
        load_config(config(tmp_path, navigation={'controller': {'local_depth_control': 1}}))
    setup = tmp_path / 'setup.bash'
    setup.write_text('true\n')
    entry = Path('src/neusymnav/backends/hydra/entry.py').resolve()
    worker = {name: dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
              for name, path in [('python', Path(sys.executable).resolve()),
                                 ('script', entry), ('setup_script', setup)]}
    path = _hydra_profile(tmp_path, workers=worker)
    data = json.loads(path.read_text())
    data['navigation'] = {'controller': {'local_depth_control': True}}
    data['runtime'] = dict(primary_hz=5., navigation_hz=10., control_sample_cap=100,
                           defer_capture_gc=True)
    path.write_text(json.dumps(data))
    assert load_config(path).data['runtime']['defer_capture_gc'] is True


def test_local_stages_are_bound_to_current_original_source(tmp_path):
    from threading import Event
    p, body, _ = local_pipeline(tmp_path, intent=False)
    stages = []
    class Measurements:
        stop_requested = Event()
        def stage(self, source, name, start, end):
            assert source is p._latest_depth and end >= start
            stages.append(name)
        def control(self, *args, **kwargs):
            assert kwargs['navigation']['world_intent'] is None
    p.measurements = Measurements()
    p.control_step(body)
    assert stages == ['local_depth_map','local_path_follow','local_motion_guard','control_loop']


def test_real_pipeline_local_control_runs_while_world_worker_is_blocked(tmp_path):
    import threading
    from test_runtime_scheduling import pipeline, wait_for, DOMAIN
    from test_guard_goal_feedback import Actuator
    from test_navmap import mapper, down
    from neusymnav.contracts import NavigationDecision
    from neusymnav.navigation.controller import Navigator
    from neusymnav.navigation.safety import MotionGuard
    world_mapper = mapper(tmp_path / 'archive')
    navigator = Navigator(world_mapper.robot, clock_domain=DOMAIN)
    calls = []
    def world_step(nav, *args):
        calls.append(threading.get_ident())
        return NavigationDecision('goal', ((0., 0.), (.4, 0.)), .1, 0., nav.revision, 'tracking')
    navigator.step = world_step
    update = world_mapper.update_for_control
    blocked = threading.Event()
    release = threading.Event()
    def delayed_update(obs):
        if obs.key.frame_index:
            blocked.set()
            assert release.wait(5.)
        return update(obs)
    world_mapper.update_for_control = delayed_update
    p, _, _ = pipeline(tmp_path, mapper=world_mapper, navigator=navigator,
        guard=MotionGuard(world_mapper, clock_domain=DOMAIN), local_depth_control=True)
    class Body(Actuator):
        def robot_pose(self, obs):
            return dict(super().robot_pose(obs), robot_xy=(0., 0.), yaw_rad=0.)
    body = Body()
    try:
        def obs(index):
            value = down(index, domain=DOMAIN)
            return replace(value, key=replace(value.key, episode_id='episode'))
        first = obs(0)
        p.submit_navigation(first, body.robot_pose(first))
        wait_for(lambda: p._local_intent is not None)
        current = obs(1)
        p.submit_navigation(current, body.robot_pose(current))
        assert blocked.wait(2.)
        assert p.control_step(body)['executed']
        assert not release.is_set()
        assert p._latest_nav.source == first.key
        assert body.commands[-1].source == current.key
        assert calls and set(calls) == {p._threads['navigation'].ident}
        assert threading.get_ident() not in calls
    finally:
        release.set()
        assert p.close(3.)['clean_shutdown']


def test_world_no_path_watchdog_recovers_without_any_local_intent_feedback(tmp_path):
    import numpy as np
    from test_guard_goal_feedback import context
    p, _, world = local_pipeline(tmp_path)
    _, measured = context()
    world = replace(world, states=measured.states, floor_support=measured.floor_support,
                    clearance=measured.clearance)
    clock = [world.capture_monotonic_ns]
    p.now_ns = lambda: clock[0]
    proof = dict(robot_xy=(1.2, 1.2), yaw_rad=0.)
    p._update_world_intent(world, proof)
    original = p._local_intent
    assert original is not None
    blocked = world.states.copy()
    goal = original.path[-1]
    row = int(np.floor((goal[1]-world.origin_xy[1])/world.resolution_m))
    col = int(np.floor((goal[0]-world.origin_xy[0])/world.resolution_m))
    blocked[row, col] = 100
    for index in range(6):
        clock[0] = world.capture_monotonic_ns + index * 200_000_000
        current = replace(world, source=replace(world.source, frame_index=index+1),
                          states=blocked, revision=100+index, capture_monotonic_ns=clock[0])
        assert not p._local_feedback
        p._update_world_intent(current, proof)
        assert p._local_intent is None
    assert p.navigator.policy._goal is None
    assert p._last_goal_failure['reason'] == 'committed_goal_blocked:goal_not_traversable'
    assert p._last_goal_failure['distinct_map_revisions'] == 6
    status = p.navigation_status()['world_planner']
    assert status['reason_counts']['committed_goal_blocked:goal_not_traversable'] == 6
    assert status['latest']['source']['frame_index'] == 6
    assert status['latest']['map_revision'] == 105
    assert status['latest']['source_age_ns'] == 0
    assert status['latest']['intent_available'] is False
    clock[0] += 200_000_000
    p._update_world_intent(replace(current, source=replace(world.source, frame_index=7),
                          revision=106, capture_monotonic_ns=clock[0]), proof)
    assert p._local_intent is not None
    assert p._local_intent.path[-1] != original.path[-1]
