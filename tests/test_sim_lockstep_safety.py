"""The simulated lockstep clock domain gets exactly the live safety rules (approved 11/11/2026)."""
from dataclasses import replace

import numpy as np
import pytest

from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.clock_domains import is_live, is_simulated
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.safety import MotionGuard
from test_navigation import nav
from test_navmap import down, geometry, mapper

SIM = 'sim_lockstep:test'


def sim_guard(tmp_path):
    m = mapper(tmp_path)
    m.update(down(domain=SIM))
    n = m.update(down(1, domain=SIM))
    guard = MotionGuard(m, clock_domain=SIM)
    guard.bind_nav(n, robot_xy=(0., 0.), yaw_rad=0.)
    return guard, n


def decision(n):
    return NavigationDecision('g', ((0., 0.), (.3, 0.)), .15, 0., n.revision, 'tracking')


def test_fresh_simulated_depth_moves_with_the_same_horizon(tmp_path):
    guard, n = sim_guard(tmp_path)
    cmd = guard.filter(decision(n), down(2, domain=SIM), 1_000_000_000)
    assert cmd.linear_mps > 0 and cmd.deadline_monotonic_ns == 1_100_000_000
    assert cmd.clock_domain == SIM


@pytest.mark.parametrize('latest,now,reason', [
    (down(2, domain=SIM), 1_300_000_001, 'depth_stale'),
    (down(2, domain=SIM, stamp=1_000_000_001), 1_000_000_000, 'depth_future'),
    (down(2, domain='host_monotonic:test'), 1_000_000_000, 'clock_domain_mismatch'),
    (down(2, domain='replay:test'), 1_000_000_000, 'clock_domain_mismatch'),
    (down(2, domain='sim_lockstep:other-run'), 1_000_000_000, 'clock_domain_mismatch'),
])
def test_simulated_domain_keeps_every_live_rejection(tmp_path, latest, now, reason):
    guard, n = sim_guard(tmp_path)
    cmd = guard.filter(decision(n), latest, now)
    assert cmd.linear_mps == cmd.yaw_radps == 0 and cmd.reason == reason


def test_wall_time_pacing_and_unknown_domains_are_refused(tmp_path):
    m = mapper(tmp_path)
    with pytest.raises(ValueError, match='wall-time pacing'):
        MotionGuard(m, clock_domain=SIM, pace_to_wall_time=True)
    for bad in ('wall:x', 'sim:x', 'host:x'):
        with pytest.raises(ValueError):
            MotionGuard(m, clock_domain=bad)
        with pytest.raises(ValueError):
            Navigator(geometry(), clock_domain=bad)
    with pytest.raises(ValueError):
        MotionGuard(m, clock_domain=SIM, offline_replay=True)     # offline mode still needs replay:
    assert is_live(SIM) and is_simulated(SIM) and is_live('host_monotonic:b') and not is_live('replay:x')


def test_navigator_accepts_sim_domain_and_rejects_a_foreign_snapshot():
    navigator = Navigator(geometry(), clock_domain=SIM)
    host_nav = nav()                                           # host_monotonic:test snapshot
    assert navigator.step(host_nav, (.75, .75), 0., 1_000_000_000).reason == 'clock_domain_mismatch'
    sim_nav = replace(nav(np.full((15, 15), -1, np.int8)), clock_domain=SIM)
    stale = navigator.step(replace(nav(), clock_domain=SIM), (.75, .75), 0., 1_400_000_000)
    assert stale.desired_linear_mps == 0 and stale.reason == 'nav_stale'
    unknown = navigator.step(sim_nav, (.75, .75), 0., 1_000_000_000)   # unknown != free still holds
    assert unknown.desired_linear_mps == unknown.desired_yaw_radps == 0
    assert unknown.reason != 'clock_domain_mismatch'
