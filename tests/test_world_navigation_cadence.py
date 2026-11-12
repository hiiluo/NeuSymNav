"""World cadence is independent of current measured-depth motion authority."""
from dataclasses import replace
from threading import Event, Lock

import pytest


def test_world_cadence_is_explicit_and_local_mode_only(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    runtime = dict(primary_hz=5., navigation_hz=10., control_sample_cap=100)
    base = load_config(config(tmp_path, runtime=runtime))
    assert 'world_navigation_hz' not in base.data['runtime']
    enabled = dict(controller=dict(local_depth_control=True))
    for rate in (2.5, 5., 10):
        value = load_config(config(tmp_path, runtime=dict(runtime, world_navigation_hz=rate),
                                   navigation=enabled))
        assert value.data['runtime']['navigation_hz'] == 10.
        assert value.data['runtime']['world_navigation_hz'] == rate
    with pytest.raises(ValueError, match='requires local_depth_control'):
        load_config(config(tmp_path, runtime=dict(runtime, world_navigation_hz=5.)))


@pytest.mark.parametrize('rate', [None, True, 0, -.1, 10.01, float('inf'), float('nan')])
def test_world_cadence_rejects_invalid_values(tmp_path, rate):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    with pytest.raises(ValueError):
        load_config(config(tmp_path,
            runtime=dict(primary_hz=5., navigation_hz=10., control_sample_cap=100, world_navigation_hz=rate),
            navigation=dict(controller=dict(local_depth_control=True))))


def test_world_slot_wait_leaves_latest_input_and_lock_available_and_skips_shutdown(monkeypatch):
    from neusymnav.runtime import Pipeline
    from neusymnav.runtime import coordinator
    from neusymnav.runtime.health import Health
    p = Pipeline.__new__(Pipeline)
    p._lock = Lock()
    p._closing = False
    p.health = Health('geometry-only')
    marker = object()
    p._nav_input = marker
    clock = [0.]
    waits = []
    class Wake:
        def wait(self, delay):
            assert 0 < delay <= .02
            assert p._nav_input is marker
            assert p._lock.acquire(blocking=False)
            p._lock.release()
            waits.append(delay)
            clock[0] += delay
        def clear(self):
            pass
    p._nav_wake = Wake()
    monkeypatch.setattr(coordinator.time, 'monotonic', lambda: clock[0])
    p._wait_world_navigation_slot(.05)
    assert clock[0] == pytest.approx(.05) and len(waits) == 3
    p._closing = True
    p._wait_world_navigation_slot(10.)
    assert len(waits) == 3
    p._closing = False
    p.health.fail('test', RuntimeError('stopped'))
    p._wait_world_navigation_slot(10.)
    assert len(waits) == 3


def test_world_cadence_dequeues_newest_capture_after_wait_while_local_control_runs(tmp_path, monkeypatch):
    from test_runtime_scheduling import pipeline, wait_for, DOMAIN
    from test_guard_goal_feedback import Actuator
    from test_navmap import mapper, down
    from neusymnav.runtime import Pipeline
    from neusymnav.contracts import NavigationDecision
    from neusymnav.navigation.controller import Navigator
    from neusymnav.navigation.safety import MotionGuard
    gated = Event()
    allow_dequeue = Event()
    wait_slot = Pipeline._wait_world_navigation_slot
    def observed_slot(self, deadline):
        if deadline > 0:
            gated.set()
            assert allow_dequeue.wait(3.)
        return wait_slot(self, deadline)
    monkeypatch.setattr(Pipeline, '_wait_world_navigation_slot', observed_slot)
    world_mapper = mapper(tmp_path / 'archive')
    updated = []
    update = world_mapper.update_for_control
    def measured_update(obs):
        updated.append(obs.key.frame_index)
        return update(obs)
    world_mapper.update_for_control = measured_update
    navigator = Navigator(world_mapper.robot, clock_domain=DOMAIN)
    navigator.step = lambda nav, *args: NavigationDecision('goal', ((0., 0.), (.4, 0.)), .1, 0., nav.revision, 'tracking')
    p, _, _ = pipeline(tmp_path, mapper=world_mapper, navigator=navigator,
        guard=MotionGuard(world_mapper, clock_domain=DOMAIN), local_depth_control=True,
        world_navigation_hz=2.5)
    class Body(Actuator):
        def robot_pose(self, obs):
            return dict(super().robot_pose(obs), robot_xy=(0., 0.), yaw_rad=0.)
    body = Body()
    def obs(index):
        value = down(index, domain=DOMAIN)
        return replace(value, key=replace(value.key, episode_id='episode'))
    try:
        first = obs(0)
        p.submit_navigation(first, body.robot_pose(first))
        wait_for(lambda: p._local_intent is not None)
        assert gated.wait(2.)
        for index in (1, 2):
            current = obs(index)
            p.submit_navigation(current, body.robot_pose(current))
        assert p.control_step(body)['executed']
        assert body.commands[-1].source == current.key
        allow_dequeue.set()
        wait_for(lambda: p._latest_nav.source == current.key)
        assert updated == [0, 2]
        assert p._latest_nav.capture_monotonic_ns == current.capture_monotonic_ns
        assert p._config['world_navigation_hz'] == 2.5
    finally:
        allow_dequeue.set()
        assert p.close(3.)['clean_shutdown']
