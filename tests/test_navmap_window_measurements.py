from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.contracts import GridState
from tools.measure_navmap_window import (
    compare_snapshots,
    footprint_diagnostic,
    nearest_rank_percentile,
)


def test_nearest_rank_percentile_uses_ceiling_rank_and_handles_empty_input():
    values = [1.0, 10.0, 2.0, 100.0]

    assert nearest_rank_percentile(values, 50) == 2.0
    assert nearest_rank_percentile(values, 95) == 100.0
    assert nearest_rank_percentile([], 95) is None


def test_snapshot_comparison_aligns_world_cells_when_window_origins_differ():
    overlap = np.arange(16, dtype=np.int8).reshape(4, 4) % 3
    reference_states = np.full((6, 6), GridState.UNKNOWN, dtype=np.int8)
    reference_states[2:6, 1:5] = overlap
    candidate_states = overlap.copy()
    candidate_states[1, 1] = GridState.UNKNOWN

    reference_floor = np.zeros((6, 6), dtype=bool)
    reference_floor[2:6, 1:5] = True
    candidate_floor = np.ones((4, 4), dtype=bool)
    candidate_floor[0, 0] = False

    reference_clearance = np.zeros((6, 6), dtype=np.float32)
    reference_clearance[2:6, 1:5] = 1.5
    candidate_clearance = np.full((4, 4), 1.5, dtype=np.float32)
    candidate_clearance[3, 3] = 0.0

    reference = SimpleNamespace(
        origin_xy=(0.0, 0.0), resolution_m=0.1, states=reference_states,
        floor_support=reference_floor, clearance=reference_clearance,
    )
    candidate = SimpleNamespace(
        origin_xy=(0.1, 0.2), resolution_m=0.1, states=candidate_states,
        floor_support=candidate_floor, clearance=candidate_clearance,
    )

    result = compare_snapshots(candidate, reference)

    # The candidate's [0:4, 0:4] maps to the baseline's [2:6, 1:5].
    assert result["common_cells"] == 16
    assert result["state_equal_cells"] == 15
    assert result["floor_equal_cells"] == 15
    assert result["clearance_equal_cells"] == 15


def test_snapshot_comparison_rejects_subcell_origin_misalignment():
    nav = SimpleNamespace(
        origin_xy=(0.0, 0.0), resolution_m=0.1,
        states=np.zeros((2, 2), dtype=np.int8),
        floor_support=np.ones((2, 2), dtype=bool),
        clearance=np.ones((2, 2), dtype=np.float32),
    )
    shifted = SimpleNamespace(
        origin_xy=(0.05, 0.0), resolution_m=0.1,
        states=np.zeros((2, 2), dtype=np.int8),
        floor_support=np.ones((2, 2), dtype=bool),
        clearance=np.ones((2, 2), dtype=np.float32),
    )

    with pytest.raises(ValueError, match="grid-aligned"):
        compare_snapshots(nav, shifted)


def test_footprint_diagnostic_uses_guard_geometry_and_requires_known_clearance():
    robot = SimpleNamespace(radius_m=0.2, margin_m=0.05, height_m=1.5)
    states = np.full((20, 20), GridState.FREE, dtype=np.int8)
    floor = np.ones((20, 20), dtype=bool)
    clearance = np.full((20, 20), 1.5, dtype=np.float32)
    nav = SimpleNamespace(
        origin_xy=(-1.0, -1.0), resolution_m=0.1,
        states=states, floor_support=floor, clearance=clearance,
    )

    fully_measured = footprint_diagnostic(nav, (0.0, 0.0), robot)
    assert fully_measured["robot_footprint_free"] is True
    assert fully_measured["footprint_cells_total"] > 0
    assert fully_measured["footprint_unknown_cells"] == 0

    clearance[10, 10] = 0.0
    blocked_by_clearance = footprint_diagnostic(nav, (0.0, 0.0), robot)
    assert blocked_by_clearance["robot_footprint_free"] is False
    assert blocked_by_clearance["footprint_clearance_insufficient_cells"] >= 1



def test_forensic_mapping_uses_private_clock_without_changing_original_capture():
    from tools import measure_navmap_window as tool
    from test_runtime_scheduling import source
    original=source(stamp=10**15,modality='depth_only')
    mapped=tool.mapping_observation(original,'replay:navmap-window-test')
    assert mapped.capture_monotonic_ns==original.capture_monotonic_ns
    assert mapped.key==original.key
    assert mapped.clock_domain=='replay:navmap-window-test'
    assert original.clock_domain!='replay:navmap-window-test'
    assert np.array_equal(mapped.depth_m,original.depth_m)
    with pytest.raises(ValueError,match='replay'):
        tool.mapping_observation(original,'host_monotonic:current')
