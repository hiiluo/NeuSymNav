import math

import numpy as np
import pytest

from neusymnav.navigation._controller_core import Controller, ControllerConfig
from neusymnav.navigation._grid import GridView, PathResult


def _straight_fixture(axis="x", *, capture_s=10.0):
    if axis == "x":
        shape = (5, 2002)
        origin = (-0.025, -0.125)
        cells = tuple((2, col) for col in range(2002))
        start = (0.0, 0.0)
    else:
        shape = (2002, 5)
        origin = (-0.125, -0.025)
        cells = tuple((row, 2) for row in range(2002))
        start = (0.0, 0.0)
    states = np.zeros(shape, dtype=np.int8)
    snapshot = GridView(
        "episode", "cylinder-v1", 1, "navigation", 0, capture_s,
        0.05, *origin, states, np.ones(shape, dtype=bool),
        np.ones(shape, dtype=np.float32), np.zeros(shape, dtype=bool),
        np.zeros(shape, dtype=np.float32),
    )
    path = PathResult(True, cells, 100.0, 1, grid_origin_x_m=origin[0],
                      grid_origin_y_m=origin[1], grid_resolution_m=0.05)
    return snapshot, path, start


def _tick(controller, snapshot, path, start, *, yaw=0.0, age_s=0.1, dt_s=0.1):
    now = snapshot.host_monotonic_s + age_s
    return controller.tick(
        robot_xy=start,
        yaw_rad=yaw,
        now_monotonic_s=now,
        dt_s=dt_s,
        depth_host_monotonic_s=snapshot.host_monotonic_s,
        depth_front_min_m=None,
        depth_coverage_ok=True,
        snapshot=snapshot,
        path=path,
        frame_id="nav-frame",
    )


def test_discrete_turn_uses_bounded_pulse_instead_of_continuous_asymptotic_gain():
    controller=Controller(ControllerConfig(discrete_heading_control=True,
        yaw_acceleration_radps2=math.radians(360.)))
    snapshot,path,start=_straight_fixture()
    _tick(controller,snapshot,path,start,yaw=math.radians(20.))
    command=_tick(controller,snapshot,path,start,yaw=math.radians(8.))
    assert command.linear_mps == 0.
    assert command.yaw_rate_radps == pytest.approx(-math.radians(30.))
    assert abs(command.yaw_rate_radps)*.1 <= math.radians(8.)


def test_discrete_turn_cannot_overshoot_even_with_small_custom_heading_band():
    controller=Controller(ControllerConfig(discrete_heading_control=True,
        heading_align_enter_rad=math.radians(2.),heading_align_exit_rad=math.radians(1.),
        yaw_acceleration_radps2=math.radians(360.)))
    snapshot,path,start=_straight_fixture()
    _tick(controller,snapshot,path,start,yaw=math.radians(10.))
    command=_tick(controller,snapshot,path,start,yaw=math.radians(1.5))
    assert command.yaw_rate_radps == pytest.approx(-math.radians(15.))
    assert abs(command.yaw_rate_radps)*.1 <= math.radians(1.5)+1e-12


@pytest.mark.parametrize('side',[-1.,1.])
@pytest.mark.parametrize('dt',[.02,.1])
def test_replanned_turn_never_emits_residual_yaw_away_from_target(side,dt):
    controller=Controller(ControllerConfig(discrete_heading_control=True,
        yaw_acceleration_radps2=math.radians(180.)))
    snapshot,path,start=_straight_fixture()
    for _ in range(2):_tick(controller,snapshot,path,start,yaw=side*math.radians(20.))
    # The newly replanned lookahead is now on the other side of current yaw.
    opposite_yaw=-side*math.radians(20.)
    command=_tick(controller,snapshot,path,start,yaw=opposite_yaw,dt_s=dt)
    assert command.linear_mps == 0.
    assert command.yaw_rate_radps*side >= 0.
    next_command=_tick(controller,snapshot,path,start,yaw=opposite_yaw,dt_s=dt)
    assert next_command.yaw_rate_radps*side > 0.


def test_opt_in_drive_mode_reaches_nominal_speed_on_fresh_long_straight():
    config = ControllerConfig(
        max_speed_mps=0.4,
        nominal_speed_mps=0.25,
        discrete_heading_control=True,
        max_depth_age_s=0.3,
        max_nav_age_s=0.3,
    )
    controller = Controller(config)

    for index in range(14):
        snapshot, path, start = _straight_fixture(capture_s=10.0 + index * 0.1)
        command = _tick(controller, snapshot, path, start, age_s=0.18)
        assert command.yaw_rate_radps == 0.0

    assert command.reason == "tracking"
    assert command.linear_mps == pytest.approx(0.2)
    assert command.linear_mps <= config.nominal_speed_mps
    assert command.linear_mps <= 0.2
    assert command.valid_until_monotonic_s == pytest.approx(
        snapshot.host_monotonic_s + config.max_depth_age_s
    )


def test_opt_in_heading_mode_holds_turn_through_deadband_then_drives_straight():
    controller = Controller(ControllerConfig(discrete_heading_control=True))

    def command_at(yaw_deg, capture_s):
        snapshot, path, start = _straight_fixture(capture_s=capture_s)
        return _tick(controller, snapshot, path, start,
                     yaw=math.radians(yaw_deg), age_s=0.1)

    turning = command_at(15.0, 10.0)
    still_turning = command_at(8.0, 10.1)
    aligned = command_at(5.0, 10.2)
    inside_hysteresis = command_at(10.0, 10.3)
    realigned = command_at(13.0, 10.4)

    assert turning.linear_mps == still_turning.linear_mps == 0.0
    assert turning.yaw_rate_radps < 0.0
    assert still_turning.yaw_rate_radps < 0.0
    assert aligned.linear_mps > 0.0 and aligned.yaw_rate_radps == 0.0
    assert inside_hysteresis.linear_mps > 0.0 and inside_hysteresis.yaw_rate_radps == 0.0
    assert realigned.linear_mps == 0.0 and realigned.yaw_rate_radps < 0.0


def test_opt_in_heading_mode_never_translates_when_current_forward_ray_is_blocked():
    snapshot, path, start = _straight_fixture("y")

    def traversable(grid):
        mask = grid.states == 0
        mask = mask.copy()
        mask[0, 3] = False  # The robot faces east; the planned route goes north.
        return mask

    controller = Controller(
        ControllerConfig(discrete_heading_control=True),
        traversable=traversable,
    )
    command = _tick(controller, snapshot, path, start, yaw=0.0)

    assert command.reason == "align_heading"
    assert command.linear_mps == 0.0
    assert command.yaw_rate_radps > 0.0


def test_opt_in_stale_source_stops_and_resets_linear_acceleration():
    controller = Controller(ControllerConfig(
        discrete_heading_control=True,
        max_depth_age_s=0.3,
        max_nav_age_s=0.5,
    ))
    for index in range(12):
        snapshot, path, start = _straight_fixture(capture_s=10.0 + index * 0.1)
        command = _tick(controller, snapshot, path, start, age_s=0.1)
    assert command.linear_mps == pytest.approx(0.15)

    stale_snapshot, stale_path, stale_start = _straight_fixture(capture_s=20.0)
    stale = _tick(controller, stale_snapshot, stale_path, stale_start, age_s=0.31)
    fresh_snapshot, fresh_path, fresh_start = _straight_fixture(capture_s=21.0)
    fresh = _tick(controller, fresh_snapshot, fresh_path, fresh_start, age_s=0.1)

    assert stale.reason == "depth_stale"
    assert stale.linear_mps == stale.yaw_rate_radps == 0.0
    assert fresh.linear_mps == pytest.approx(0.015)
    assert fresh.yaw_rate_radps == 0.0


def test_default_controller_keeps_continuous_heading_and_speed_behavior():
    snapshot, path, start = _straight_fixture()
    yaw = math.radians(8.0)
    default = Controller(ControllerConfig())
    explicit_default = Controller(ControllerConfig(discrete_heading_control=False))

    first = _tick(default, snapshot, path, start, yaw=yaw, age_s=0.1)
    second = _tick(explicit_default, snapshot, path, start, yaw=yaw, age_s=0.1)

    assert first.linear_mps == pytest.approx(0.015)
    assert first.yaw_rate_radps == pytest.approx(-math.radians(4.5))
    assert first.reason == "tracking"
    assert (first.linear_mps, first.yaw_rate_radps, first.reason) == (
        second.linear_mps, second.yaw_rate_radps, second.reason
    )
