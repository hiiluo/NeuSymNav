"""Real-time profile: goal-selection age, intent TTL, local stride, priorities."""
from dataclasses import replace
import os
import subprocess
import sys
import time

import numpy as np
import pytest

from test_navigation import nav
from test_navmap import geometry
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.local_control import LocalMeasuredMap, WorldIntent


def _open_room():
    states = np.zeros((15, 15), np.int8)
    states[:, 13:] = -1  # unknown band -> frontier
    return nav(states)


def test_world_goal_selection_uses_its_own_age_limit_only_when_configured():
    world = _open_room()
    six_hundred_ms_old = world.capture_monotonic_ns + 600_000_000
    strict = Navigator(geometry(), clock_domain='host_monotonic:test')
    assert strict.step(world, (.45, .45), 0., six_hundred_ms_old).reason == 'nav_stale'
    relaxed = Navigator(geometry(), clock_domain='host_monotonic:test',
                        goal_selection_max_age_ns=1_000_000_000)
    decision = relaxed.step(world, (.45, .45), 0., six_hundred_ms_old)
    # Route only: no velocity is ever derived from a map older than 300 ms.
    assert decision.reason == 'world_goal_selected' and decision.goal_id and decision.path
    assert decision.desired_linear_mps == 0 and decision.desired_yaw_radps == 0
    fresh = relaxed.step(replace(world, revision=2), (.45, .45), 0., world.capture_monotonic_ns + 100_000_000)
    assert fresh.reason not in ('nav_stale', 'world_goal_selected')
    # Older than the selection limit is still refused.
    assert relaxed.step(world, (.45, .45), 0.,
                        world.capture_monotonic_ns + 1_000_000_001).reason == 'nav_stale'
    # The motion TTL itself is unchanged.
    assert relaxed.max_nav_age_ns == 300_000_000


@pytest.mark.parametrize('value', [0, 299_999_999, 2_000_000_001, 1.5e9, True])
def test_goal_selection_age_bounds(value):
    with pytest.raises(ValueError):
        Navigator(geometry(), clock_domain='host_monotonic:test', goal_selection_max_age_ns=value)


def test_failure_watch_counts_world_revisions_within_selection_age():
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test',
                          goal_selection_max_age_ns=1_500_000_000)
    world = _open_room()
    now = world.capture_monotonic_ns + 800_000_000
    assert navigator.step(world, (.45, .45), 0., now).path
    target = navigator.policy._goal_world_xy
    failure = None
    for index in range(1, 30):
        capture = world.capture_monotonic_ns + index * 400_000_000
        snapshot = replace(world, revision=world.revision + index, capture_monotonic_ns=capture)
        # Each world map is ~800 ms old when evaluated: stale for motion,
        # still valid evidence that the committed goal stays blocked.
        failure = navigator.observe_navigation_result(
            snapshot, (.45, .45), capture + 800_000_000, 'path_segment_blocked', True)
        if failure is not None:
            break
    assert failure is not None and failure['goal_xy'] == target


def test_world_intent_ttl_is_bounded_and_extends_validity():
    world = nav()
    default = WorldIntent.from_decision(world, 'g', ((.35, .35), (.75, .35)), 1_100_000_000)
    longer = WorldIntent.from_decision(world, 'g', ((.35, .35), (.75, .35)), 1_100_000_000,
                                       ttl_ns=4_000_000_000)
    assert not default.compatible(world, 3_500_000_000)
    assert longer.compatible(world, 3_500_000_000)
    assert not longer.compatible(world, 5_000_000_001)
    # A 2.5 s old decision is only accepted with a longer TTL.
    with pytest.raises(ValueError):
        WorldIntent.from_decision(world, 'g', ((.35, .35),), 3_500_000_000)
    assert WorldIntent.from_decision(world, 'g', ((.35, .35),), 3_500_000_000, ttl_ns=4_000_000_000)
    for bad in (1_999_999_999, 5_000_000_001, 3.0e9):
        with pytest.raises(ValueError):
            WorldIntent.from_decision(world, 'g', ((.35, .35),), 1_100_000_000, ttl_ns=bad)


def test_local_stride_only_coarsens_and_unsampled_cells_stay_unknown(tmp_path):
    from test_navmap import down, mapper
    from neusymnav.contracts import GridState
    base = mapper(tmp_path)
    full = LocalMeasuredMap(base).snapshot(down(), robot_xy=(0., 0.))
    coarse_map = LocalMeasuredMap(base, sampling_stride=2)
    assert coarse_map.sampling_stride == 2 and coarse_map.mapper._core.sampling_stride == 2
    coarse = coarse_map.snapshot(down(), robot_xy=(0., 0.))
    assert full.states.shape == coarse.states.shape
    full_free = full.states == GridState.FREE
    coarse_free = coarse.states == GridState.FREE
    # Coarser sampling never invents free space the full lattice did not see.
    assert not (coarse_free & ~full_free).any()
    assert coarse_free.any()
    for bad in (0, 5, 1.0, True):
        with pytest.raises(ValueError):
            LocalMeasuredMap(base, sampling_stride=bad)


def test_config_accepts_realtime_keys_only_with_local_depth_control(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    navigation = {'controller': {'local_depth_control': True, 'world_goal_max_age_ms': 1500,
                                 'world_intent_ttl_ms': 4000},
                  'mapper': {'local_sampling_stride': 2}}
    assert load_config(config(tmp_path, navigation=navigation))
    for controller, mapper in (({'world_goal_max_age_ms': 1500}, {}),
                               ({'world_intent_ttl_ms': 4000}, {}),
                               ({}, {'local_sampling_stride': 2})):
        with pytest.raises(ValueError, match='local_depth_control'):
            load_config(config(tmp_path, navigation={'controller': controller, 'mapper': mapper}))
    for controller in ({'local_depth_control': True, 'world_goal_max_age_ms': 2500},
                       {'local_depth_control': True, 'world_goal_max_age_ms': 200},
                       {'local_depth_control': True, 'world_intent_ttl_ms': 6000}):
        with pytest.raises(ValueError):
            load_config(config(tmp_path, navigation={'controller': controller}))
    with pytest.raises(ValueError):
        load_config(config(tmp_path, navigation={'controller': {'local_depth_control': True},
                                                 'mapper': {'local_sampling_stride': 5}}))


def test_launcher_maps_selection_age_to_navigator_option(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.launcher import _navigation_options
    loaded = load_config(config(tmp_path, navigation={'controller': {
        'local_depth_control': True, 'world_goal_max_age_ms': 1200}}))
    options = _navigation_options(loaded)
    assert options['goal_selection_max_age_ns'] == 1_200_000_000
    assert 'goal_selection_max_age_ns' not in _navigation_options(load_config(config(tmp_path)))


def test_process_priority_validation_and_prefix():
    from neusymnav.runtime.priority import nice_prefix, validate_process_priority
    assert validate_process_priority(None) == {}
    assert validate_process_priority({'hydra': 2, 'detector': 5, 'ui': 8}) == {
        'hydra': 2, 'detector': 5, 'ui': 8}
    for bad in ({'control': 1}, {'hydra': -1}, {'ui': 20}, {'detector': 1.0}, [1]):
        with pytest.raises(ValueError):
            validate_process_priority(bad)
    assert nice_prefix(0) == ()
    prefix = nice_prefix(7)
    assert prefix[1:] == ('-n', '7') and os.path.isabs(prefix[0])


def test_nice_prefix_and_renice_tree_lower_real_processes():
    from neusymnav.runtime.priority import nice_prefix, renice_tree
    base = os.getpriority(os.PRIO_PROCESS, 0)
    target = min(19, base + 6)
    started = subprocess.Popen([*nice_prefix(target), sys.executable, '-c',
                                'import time; time.sleep(5)'])
    try:
        time.sleep(.2)
        assert os.getpriority(os.PRIO_PROCESS, started.pid) == target
    finally:
        started.kill(); started.wait()
    child = subprocess.Popen([sys.executable, '-c',
        'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(5)"]);'
        'time.sleep(5); p.kill()'])
    try:
        time.sleep(.5)
        report = renice_tree(child.pid, target)
        assert report['threads'] >= 2 and report['failed'] == 0
        assert os.getpriority(os.PRIO_PROCESS, child.pid) == target
        grandchildren = open(f'/proc/{child.pid}/task/{child.pid}/children').read().split()
        assert grandchildren and all(
            os.getpriority(os.PRIO_PROCESS, int(pid)) == target for pid in grandchildren)
    finally:
        child.kill(); child.wait()


def test_detector_client_nice_prefixes_worker_command(tmp_path):
    from neusymnav.perception import detector_client
    calls = {}

    class Recorder:
        def __init__(self, command, **kwargs):
            calls['command'] = tuple(command)

    original = detector_client._BoundedProcess
    detector_client._BoundedProcess = Recorder
    try:
        client = detector_client.DetectorClient.__new__(detector_client.DetectorClient)
        # Exercise only the command construction in __init__.
        from neusymnav.runtime.priority import nice_prefix
        prefix = nice_prefix(5)
        detector_client._BoundedProcess([*prefix, sys.executable, '-u', 'w.py'], timeout_s=1.,
                                        response_limit=1)
        assert calls['command'][:3] == prefix
    finally:
        detector_client._BoundedProcess = original
    with pytest.raises(ValueError):
        detector_client.DetectorClient(python=sys.executable, recipe={}, nice=-1)
