"""Plan A for world/control GIL contention (00806 v4/v5, 2026-11-09)."""
import sys

import numpy as np
import pytest

from neusymnav.mapping.overview import OverviewTiles, build_overview


def _reference_overview(tiles):
    """The original scatter-add implementation (factor 1 branch)."""
    size = tiles.tile_size
    bounds = []
    for (tr, tc), tile in tiles.tiles.items():
        r, c = np.nonzero(tile != -1)
        if len(r):
            bounds.append((r.min() + tr * size, c.min() + tc * size, r.max() + tr * size, c.max() + tc * size))
    minr = min(b[0] for b in bounds); minc = min(b[1] for b in bounds)
    maxr = max(b[2] for b in bounds); maxc = max(b[3] for b in bounds)
    shape = (maxr - minr + 1, maxc - minc + 1)
    counts = np.zeros(shape, np.int64); occupied = np.zeros(shape, bool)
    for (tr, tc), tile in tiles.tiles.items():
        r, c = np.nonzero(tile != -1)
        rr = r + tr * size - minr; cc = c + tc * size - minc
        vals = tile[r, c]
        np.add.at(counts, (rr, cc), vals == 0)
        np.logical_or.at(occupied, (rr, cc), vals == 100)
    states = np.full(shape, -1, np.int8); states[counts == 1] = 0; states[occupied] = 100
    return states, (tiles.origin_xy[0] + minc * tiles.resolution_m, tiles.origin_xy[1] + minr * tiles.resolution_m)


def test_full_resolution_overview_fast_path_matches_scatter_reference():
    rng = np.random.default_rng(7)
    size = 16
    tiles = {}
    for key in [(0, 0), (0, 1), (1, 1), (3, -2), (-1, 0)]:
        tile = np.full((size, size), -1, np.int8)
        mask = rng.random((size, size)) < .4
        tile[mask] = rng.choice(np.array([0, 100], np.int8), mask.sum())
        tiles[key] = tile
    from test_navigation import nav
    value = OverviewTiles(nav(), (1.0, -2.0), .1, size, tiles, True)
    built = build_overview(value)
    expected, origin = _reference_overview(value)
    assert np.array_equal(built.states, expected)
    assert built.origin_xy == pytest.approx(origin) and built.resolution_m == .1


def test_overview_refresh_due_respects_period():
    from neusymnav.runtime import Pipeline
    p = Pipeline.__new__(Pipeline)
    assert p._overview_refresh_due(0)  # no period configured: always refresh
    p.overview_refresh_ns = 2_000_000_000
    p._last_overview_refresh_ns = None
    assert p._overview_refresh_due(5)
    p._last_overview_refresh_ns = 1_000_000_000
    assert not p._overview_refresh_due(2_999_999_999)
    assert p._overview_refresh_due(3_000_000_000)


def test_gil_switch_interval_helper_sets_and_validates():
    from neusymnav.runtime.coordinator import set_gil_switch_interval
    original = sys.getswitchinterval()
    try:
        previous = set_gil_switch_interval(.001)
        assert previous == original and sys.getswitchinterval() == pytest.approx(.001)
        for bad in (.0001, .01, 1, float('nan')):
            with pytest.raises(ValueError):
                set_gil_switch_interval(bad)
    finally:
        sys.setswitchinterval(original)


def test_config_keys_are_validated_and_reach_pipeline_kwargs(tmp_path):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.launcher import _mapper
    runtime = dict(primary_hz=5., navigation_hz=10., control_sample_cap=100)
    loaded = load_config(config(tmp_path, runtime=dict(runtime, gil_switch_interval_ms=1),
                                navigation=dict(mapper=dict(overview_refresh_s=2.0))))
    assert loaded.data['runtime']['gil_switch_interval_ms'] == 1
    assert loaded.data['navigation']['mapper']['overview_refresh_s'] == 2.0
    for bad in (0.1, 6, float('inf')):
        with pytest.raises(ValueError, match='gil_switch_interval_ms'):
            load_config(config(tmp_path, runtime=dict(runtime, gil_switch_interval_ms=bad)))
    for bad in (0.1, 11, True):
        with pytest.raises(ValueError, match='overview_refresh_s'):
            load_config(config(tmp_path, navigation=dict(mapper=dict(overview_refresh_s=bad))))
