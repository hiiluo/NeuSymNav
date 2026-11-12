"""Navigator exposes a bounded acceleration option without changing safety caps."""

from dataclasses import replace
import math
import numpy as np

import pytest

from neusymnav.navigation.controller import Navigator
from test_navigation import geometry, nav


def safe_east_corridor(index):
    states = np.full((31, 31), 100, np.int8)
    states[13:18, 5:25] = 0
    states[15, 25] = -1
    stamp_ns = 1_000_000_000 + index * 100_000_000
    return replace(
        nav(states, revision=index + 1),
        capture_monotonic_ns=stamp_ns,
    )


def _navigator(acceleration_mps2):
    return Navigator(
        geometry(),
        clock_domain="host_monotonic:test",
        nominal_speed_mps=0.2,
        discrete_heading_control=True,
        acceleration_mps2=acceleration_mps2,
    )


def _decisions(acceleration_mps2, yaws_deg):
    navigator = _navigator(acceleration_mps2)
    decisions = []
    for index, yaw_deg in enumerate(yaws_deg):
        snapshot = safe_east_corridor(index)
        decision = navigator.step(
            snapshot,
            (1.55, 1.55),
            math.radians(yaw_deg),
            snapshot.capture_monotonic_ns,
        )
        assert decision.path
        decisions.append(decision)
    return decisions


def test_configured_acceleration_limits_real_navigator_steps_and_keeps_speed_cap():
    decisions = _decisions(0.6, [0.0] * 8)
    speeds = [decision.desired_linear_mps for decision in decisions]

    previous = 0.0
    for speed in speeds:
        assert speed <= 0.2
        assert abs(speed - previous) <= 0.6 * 0.1 + 1e-9
        previous = speed
    assert speeds[3] == pytest.approx(0.2)


def test_acceleration_option_reaches_nominal_in_four_ticks_after_alignment():
    yaws_after_startup_alignment = [20.0, 8.0, 5.0] + [5.0] * 14
    accelerated = _decisions(0.6, yaws_after_startup_alignment)
    legacy = _decisions(0.15, yaws_after_startup_alignment)
    accelerated_speeds = [decision.desired_linear_mps for decision in accelerated]
    legacy_speeds = [decision.desired_linear_mps for decision in legacy]

    assert accelerated_speeds[:2] == [0.0, 0.0]
    assert legacy_speeds[:2] == [0.0, 0.0]
    assert accelerated_speeds[2] == pytest.approx(0.6 * 0.1)
    accelerated_ticks = next(
        index + 1 for index, speed in enumerate(accelerated_speeds[2:])
        if speed >= 0.2 - 1e-9
    )
    legacy_ticks = next(
        index + 1 for index, speed in enumerate(legacy_speeds[2:])
        if speed >= 0.2 - 1e-9
    )

    assert accelerated_ticks == 4
    assert legacy_ticks == 14
    assert max(accelerated_speeds) <= 0.2
    assert max(legacy_speeds) <= 0.2


@pytest.mark.parametrize(
    "acceleration_mps2",
    [0.0, -0.1, 1.01, math.inf, math.nan, True],
)
def test_navigator_rejects_invalid_acceleration_values(acceleration_mps2):
    with pytest.raises(ValueError):
        _navigator(acceleration_mps2)
