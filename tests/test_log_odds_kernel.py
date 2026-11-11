from __future__ import annotations

import numpy as np
import pytest

from neusymnav.mapping._log_odds_kernel import (
    apply_log_odds_kernel,
    compiled_log_odds_signatures,
    warmup_log_odds_kernel,
)
from neusymnav.mapping._occupancy_core import OccupancyMapper
from neusymnav.mapping._raycast_kernel import warmup_raycast_kernel


def _layout_array(shape, dtype, layout, fill_value):
    if layout == "C":
        result = np.full(shape, fill_value, dtype=dtype, order="C")
    elif layout == "F":
        result = np.full(shape, fill_value, dtype=dtype, order="F")
    elif layout == "A":
        backing = np.full(tuple(size * 2 for size in shape), fill_value, dtype=dtype)
        result = backing[tuple(slice(None, None, 2) for _ in shape)]
    else:
        raise AssertionError(layout)
    return result


def _votes(shape, hit_layout, free_layout):
    hits = _layout_array(shape, np.bool_, hit_layout, False)
    frees = _layout_array(shape, np.bool_, free_layout, False)
    flat_indices = (0, 2) if hits.size >= 3 else (0,)
    for flat_index in flat_indices:
        hits[np.unravel_index(flat_index, shape)] = True
    for flat_index in (0, 1, 3):
        if flat_index < frees.size:
            frees[np.unravel_index(flat_index, shape)] = True
    return hits, frees


def _numpy_oracle(values, hits, frees):
    expected = values.copy(order="K")
    observed = hits | frees
    previous = expected[observed]
    previous = np.where(np.isnan(previous), 0.0, previous)
    increments = np.where(hits[observed], 0.85, -0.4)
    expected[observed] = np.clip(
        previous.astype(np.float64) + increments,
        -4.0,
        4.0,
    ).astype(np.float32)
    return expected


def _assert_bitwise_equal(actual, expected):
    assert actual.dtype == np.float32
    assert expected.dtype == np.float32
    assert np.array_equal(actual.view(np.uint32), expected.view(np.uint32))


@pytest.mark.parametrize("ndim", (2, 3))
@pytest.mark.parametrize("value_layout,vote_layouts", (("C", "C"), ("A", "A"), ("C", "A")))
def test_warmed_kernel_matches_numpy_bitwise_for_recorded_layouts(ndim, value_layout, vote_layouts):
    if not warmup_log_odds_kernel():
        pytest.skip("Numba is unavailable")

    shape = (4, 5) if ndim == 2 else (3, 4, 5)
    values = _layout_array(shape, np.float32, value_layout, np.nan)
    values.flat[0] = np.float32(3.9)
    values.flat[1] = np.float32(-3.9)
    values.flat[2] = np.float32(0.125)
    hits, frees = _votes(shape, vote_layouts, vote_layouts)
    expected = _numpy_oracle(values, hits, frees)
    signatures_before = compiled_log_odds_signatures()

    used_kernel = apply_log_odds_kernel(values, hits, frees, 0.85, -0.4, -4.0, 4.0)

    assert used_kernel is True
    _assert_bitwise_equal(values, expected)
    assert compiled_log_odds_signatures() == signatures_before


@pytest.mark.parametrize("ndim", (2, 3))
def test_mapper_falls_back_for_unwarmed_fortran_views_without_changing_semantics(ndim):
    if not warmup_log_odds_kernel():
        pytest.skip("Numba is unavailable")

    shape = (4, 5) if ndim == 2 else (3, 4, 5)
    values = _layout_array(shape, np.float32, "F", np.nan)
    values.flat[0] = np.float32(3.9)
    values.flat[1] = np.float32(-3.9)
    hits, frees = _votes(shape, "F", "F")
    expected = _numpy_oracle(values, hits, frees)
    untouched = values.copy(order="K")
    signatures_before = compiled_log_odds_signatures()

    assert apply_log_odds_kernel(values, hits, frees, 0.85, -0.4, -4.0, 4.0) is False
    _assert_bitwise_equal(values, untouched)

    mapper = object.__new__(OccupancyMapper)
    mapper._apply_log_odds(values, hits, frees)

    _assert_bitwise_equal(values, expected)
    assert compiled_log_odds_signatures() == signatures_before


def test_mapper_routes_warmed_layouts_through_the_fused_kernel(monkeypatch):
    if not warmup_log_odds_kernel():
        pytest.skip("Numba is unavailable")

    import neusymnav.mapping._occupancy_core as occupancy_core

    values = np.array([[np.nan, 3.9], [-3.9, 0.125]], dtype=np.float32)
    hits = np.array([[True, False], [True, False]], dtype=np.bool_)
    frees = np.array([[True, True], [False, True]], dtype=np.bool_)
    expected = _numpy_oracle(values, hits, frees)
    original = occupancy_core.apply_log_odds_kernel
    used = []

    def observe_call(*args):
        result = original(*args)
        used.append(result)
        return result

    monkeypatch.setattr(occupancy_core, "apply_log_odds_kernel", observe_call)
    mapper = object.__new__(OccupancyMapper)
    mapper._apply_log_odds(values, hits, frees)

    assert used == [True]
    _assert_bitwise_equal(values, expected)


def test_raycast_startup_warms_log_odds_before_capture(monkeypatch):
    if not warmup_log_odds_kernel():
        pytest.skip("Numba is unavailable")

    from neusymnav.mapping import _log_odds_kernel
    calls=[]
    original=_log_odds_kernel.warmup_log_odds_kernel
    def warm():
        calls.append(True)
        return original()
    monkeypatch.setattr(_log_odds_kernel,'warmup_log_odds_kernel',warm)
    assert warmup_raycast_kernel() is True
    assert calls == [True]
    signatures = compiled_log_odds_signatures()
    assert len(signatures) == 6
