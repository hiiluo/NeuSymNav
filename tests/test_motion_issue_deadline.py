"""Guard preparation must not consume a newly issued pulse's action window."""
from dataclasses import replace
import pytest
from test_navigation import ready_guard
from test_navmap import down
from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.safety import MotionGuard


def test_issue_after_geometry_checks_keeps_full_horizon_with_original_evidence(tmp_path):
    old, nav = ready_guard(tmp_path)
    guard = MotionGuard(old.mapper, clock_domain='host_monotonic:test',
                        now_ns=lambda: 1_040_000_000)
    guard.bind_nav(nav, robot_xy=(0., 0.), yaw_rad=0.)
    decision = NavigationDecision('goal', ((0., 0.), (.3, 0.)), .15, 0., nav.revision, 'tracking')
    command = guard.filter(decision, down(2), 1_000_000_000)
    assert command.issued_monotonic_ns == 1_040_000_000
    assert command.deadline_monotonic_ns == 1_140_000_000
    assert command.source_capture_monotonic_ns == 1_000_000_000
    assert command.source == down(2).key


@pytest.mark.parametrize('finished', [1_250_000_000, 1_300_000_000, 1_310_000_000])
def test_geometry_finishing_near_or_after_ttl_never_extends_evidence(tmp_path, finished):
    old, nav = ready_guard(tmp_path)
    guard = MotionGuard(old.mapper, clock_domain='host_monotonic:test', now_ns=lambda: finished)
    guard.bind_nav(nav, robot_xy=(0., 0.), yaw_rad=0.)
    decision = NavigationDecision('goal', ((0., 0.), (.3, 0.)), .15, 0., nav.revision, 'tracking')
    command = guard.filter(decision, down(2), 1_000_000_000)
    assert command.deadline_monotonic_ns <= max(finished, 1_300_000_000)
    if finished >= 1_300_000_000:
        assert command.linear_mps == command.yaw_radps == 0.
        assert command.reason == 'depth_stale'
    else:
        assert command.deadline_monotonic_ns == 1_300_000_000
