"""Hybrid forward and steering pulses keep the simulator's motion bounds."""

import math

import numpy as np
import pytest

from neusymnav.navigation._controller_core import Controller, ControllerConfig
from neusymnav.navigation._grid import GridView, PathResult


def _fixture(axis="x", *, capture_s=10.0):
    if axis == "x":
        shape = (5, 100)
        origin = (-0.025, -0.125)
        cells = tuple((2, col) for col in range(100))
    else:
        shape = (100, 5)
        origin = (-0.125, -0.025)
        cells = tuple((row, 2) for row in range(100))
    states = np.zeros(shape, dtype=np.int8)
    snapshot = GridView(
        "episode", "cylinder-v1", 1, "navigation", 0, capture_s,
        0.05, *origin, states, np.ones(shape, dtype=bool),
        np.ones(shape, dtype=np.float32), np.zeros(shape, dtype=bool),
        np.zeros(shape, dtype=np.float32),
    )
    path = PathResult(True, cells, 100.0, 1, grid_origin_x_m=origin[0],
                      grid_origin_y_m=origin[1], grid_resolution_m=0.05)
    return snapshot, path


def _controller(**overrides):
    values = dict(
        max_speed_mps=0.4,
        nominal_speed_mps=0.25,
        acceleration_mps2=0.6,
        yaw_acceleration_radps2=math.radians(180.0),
        max_depth_age_s=0.3,
        max_nav_age_s=0.5,
        hybrid_pulse_control=True,
    )
    values.update(overrides)
    return Controller(ControllerConfig(**values))


def _tick(controller, snapshot, path, *, start=(0.0, 0.0), yaw=0.0,
          age_s=0.18, dt_s=0.1, traversable=None, blocked_edges=frozenset(),
          depth_front_min_m=None):
    if traversable is not None:
        controller.set_traversable(traversable)
    return controller.tick(
        robot_xy=start,
        yaw_rad=yaw,
        now_monotonic_s=snapshot.host_monotonic_s + age_s,
        dt_s=dt_s,
        depth_host_monotonic_s=snapshot.host_monotonic_s,
        depth_front_min_m=depth_front_min_m,
        depth_coverage_ok=True,
        snapshot=snapshot,
        path=path,
        frame_id="nav-frame",
        blocked_edges=blocked_edges,
    )


def _assert_command_bounds(command, snapshot):
    assert 0.0 <= command.linear_mps <= 0.2
    assert abs(command.yaw_rate_radps) <= math.radians(30.0) + 1e-12
    assert command.valid_until_monotonic_s == pytest.approx(
        snapshot.host_monotonic_s + 0.3
    )


def test_hybrid_20_degree_pursuit_moves_and_5_degree_deadband_is_forward_only():
    controller = _controller()
    snapshot, path = _fixture()

    turning = _tick(controller, snapshot, path, yaw=math.radians(20.0))
    curvature = 2.0 * math.sin(math.radians(-20.0)) / 0.4
    assert turning.reason == "tracking"
    assert turning.linear_mps > 0.0
    assert turning.yaw_rate_radps < 0.0
    assert turning.yaw_rate_radps / turning.linear_mps == pytest.approx(curvature)
    _assert_command_bounds(turning, snapshot)

    aligned = _tick(controller, snapshot, path, yaw=math.radians(5.0))
    assert aligned.linear_mps > turning.linear_mps
    assert aligned.yaw_rate_radps == 0.0  # clears the prior steering slew inside 6°
    _assert_command_bounds(aligned, snapshot)

    for _ in range(2):
        aligned = _tick(controller, snapshot, path, yaw=math.radians(5.0))
        _assert_command_bounds(aligned, snapshot)
    assert aligned.linear_mps == pytest.approx(0.2)


def test_hybrid_70_degree_turn_stays_in_place_until_25_degree_exit():
    controller = _controller()
    snapshot, path = _fixture()

    large_error = _tick(controller, snapshot, path, yaw=math.radians(70.0))
    still_aligning = _tick(controller, snapshot, path, yaw=math.radians(40.0))
    blend = _tick(controller, snapshot, path, yaw=math.radians(20.0))

    assert large_error.linear_mps == still_aligning.linear_mps == 0.0
    assert large_error.yaw_rate_radps < 0.0
    assert still_aligning.yaw_rate_radps < 0.0
    assert abs(large_error.yaw_rate_radps) * 0.1 <= math.radians(70.0)
    assert blend.linear_mps > 0.0 and blend.yaw_rate_radps < 0.0
    for command in (large_error, still_aligning, blend):
        _assert_command_bounds(command, snapshot)


def test_hybrid_turns_in_place_when_actual_forward_pulse_hits_a_blocked_edge():
    controller = _controller()
    snapshot, path = _fixture("y")
    # The planned route points north; the current body faces east near the
    # cell edge, so its <=2 cm pulse would cross this unrelated blocked edge.
    blocked = frozenset({((0, 2), (0, 3))})

    command = _tick(
        controller, snapshot, path, start=(0.02, 0.0), yaw=0.0,
        blocked_edges=blocked,
    )

    assert command.reason == "align_heading"
    assert command.linear_mps == 0.0
    assert command.yaw_rate_radps > 0.0
    _assert_command_bounds(command, snapshot)


def test_hybrid_stops_when_fresh_depth_blocks_a_forward_aligned_pulse():
    controller = _controller()
    snapshot, path = _fixture()

    command = _tick(
        controller, snapshot, path, yaw=0.0, depth_front_min_m=0.1,
    )

    assert command.reason == "front_obstacle_brake"
    assert command.linear_mps == command.yaw_rate_radps == 0.0
    _assert_command_bounds(command, snapshot)


def test_hybrid_stale_source_stops_both_components():
    controller = _controller()
    snapshot, path = _fixture()

    command = _tick(controller, snapshot, path, yaw=math.radians(20.0), age_s=0.31)

    assert command.reason == "depth_stale"
    assert command.linear_mps == command.yaw_rate_radps == 0.0
    _assert_command_bounds(command, snapshot)


def test_hybrid_yaw_reversal_brakes_old_sign_before_turning_new_direction():
    controller = _controller(yaw_acceleration_radps2=math.radians(20.0))
    snapshot, path = _fixture()

    first = _tick(controller, snapshot, path, yaw=math.radians(-20.0))
    reversal = _tick(controller, snapshot, path, yaw=math.radians(7.0))
    resumed = _tick(controller, snapshot, path, yaw=math.radians(7.0))

    assert first.yaw_rate_radps > 0.0
    assert reversal.yaw_rate_radps == 0.0
    assert resumed.yaw_rate_radps < 0.0
    assert reversal.linear_mps > 0.0
    for command in (first, reversal, resumed):
        _assert_command_bounds(command, snapshot)


def test_hybrid_configuration_is_opt_in_and_exclusive_with_discrete_mode():
    assert ControllerConfig().hybrid_pulse_control is False
    with pytest.raises(ValueError, match="mutually exclusive"):
        ControllerConfig(discrete_heading_control=True, hybrid_pulse_control=True)
