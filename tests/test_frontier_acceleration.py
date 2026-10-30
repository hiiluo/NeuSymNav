"""Independent reference reductions protect frontier order and bounded dispatch."""
import numpy as np
import pytest

from neusymnav.navigation import frontiers


def original_reductions(cells, reachable, offsets):
    """Original vectorized reduction, retained here independently of production."""
    h, w = reachable.shape
    offset_rows, offset_cols, distances = offsets
    n_offsets = len(distances)
    min_distance = np.full(h * w, np.inf, dtype=np.float64)
    first_seen = np.full(h * w, np.iinfo(np.int64).max, dtype=np.int64)
    offset_order = np.arange(n_offsets, dtype=np.int64)
    batch_size = max(1, min(len(cells), 256))
    for start in range(0, len(cells), batch_size):
        batch = np.asarray(cells[start:start + batch_size], dtype=np.int32)
        rows = batch[:, 0, None] + offset_rows[None, :]
        cols = batch[:, 1, None] + offset_cols[None, :]
        valid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        valid &= reachable[np.clip(rows, 0, h - 1), np.clip(cols, 0, w - 1)]
        if not valid.any():
            continue
        source_order = np.arange(start, start + len(batch), dtype=np.int64)[:, None]
        flat_cells = (rows * w + cols)[valid]
        pair_distances = np.broadcast_to(distances, rows.shape)[valid]
        pair_order = (source_order * n_offsets + offset_order[None, :])[valid]
        np.minimum.at(min_distance, flat_cells, pair_distances)
        np.minimum.at(first_seen, flat_cells, pair_order)
    return min_distance, first_seen


def original_order(cells, reachable, offsets):
    if not cells or not len(offsets[2]):
        return []
    distance, first = original_reductions(cells, reachable, offsets)
    candidates = np.flatnonzero(np.isfinite(distance))
    rows, cols = np.divmod(candidates, reachable.shape[1])
    center = np.asarray(cells, dtype=np.float64).mean(axis=0)
    order = np.lexsort((first[candidates], (rows-center[0])**2 + (cols-center[1])**2,
                        np.abs(distance[candidates] - .45)))
    return [divmod(int(cell), reachable.shape[1]) for cell in candidates[order]]


def fixtures():
    rng = np.random.default_rng(6429)
    for case in range(25):
        h, w = 3 + case % 13, 4 + case % 11
        reachable = rng.random((h, w)) > .35
        if case % 3 == 0:
            reachable[:, w//2] = False  # disconnected sets stay exactly as supplied
        count = [0, 1, 8, 257, 400][case % 5]
        cells = list(zip(rng.integers(0, h, count).tolist(),
                         rng.integers(0, w, count).tolist()))
        offsets = frontiers._view_offsets(.1, .1, .6)
        if case % 4 == 0:
            reachable = reachable[::-1, ::-1]
            offsets = tuple(values[::-1] for values in offsets)
        if case % 2 == 0:
            reachable.flags.writeable = False
            for values in offsets:
                values.flags.writeable = False
        yield cells, reachable, offsets


def test_python_kernel_matches_independent_minimum_and_first_seen_reductions():
    # Wrong first-hit rank, swapped boundary/offset iteration, or lost duplicates fail.
    from neusymnav.navigation import _frontier_kernel as kernel
    for cells, reachable, offsets in fixtures():
        actual = kernel._reduce(np.asarray(cells, dtype=np.int32).reshape(-1, 2),
                                reachable, *offsets)
        expected = original_reductions(cells, reachable, offsets)
        for got, want in zip(actual, expected):
            np.testing.assert_array_equal(got, want)


def test_ranked_viewpoints_preserve_reference_order_and_readonly_inputs():
    for cells, reachable, offsets in fixtures():
        before = [values.copy() for values in (reachable, *offsets)]
        assert frontiers._ranked_reachable_viewpoints(cells, reachable, offsets) == original_order(
            cells, reachable, offsets)
        for values, copy in zip((reachable, *offsets), before):
            np.testing.assert_array_equal(values, copy)


def test_equal_score_ties_keep_first_seen_offset_order():
    cells = [(1, 1), (1, 1)]
    offsets = (np.array([0, 0], np.int32), np.array([1, -1], np.int32),
               np.array([.45, .45], np.float64))
    assert frontiers._ranked_reachable_viewpoints(cells, np.ones((3, 3), bool), offsets) == [
        (1, 2), (1, 0)]


def test_numba_dispatch_is_prepared_before_extraction_and_never_compiles_new_signatures(monkeypatch):
    from neusymnav.navigation import _frontier_kernel as kernel
    if kernel._compiled is None:
        pytest.skip('Numba is optional; run with the host interpreter for native dispatch')
    # Constructor must warm the real read-only signature before any control call.
    frontiers.FrontierExtractor(agent_radius_m=.1)
    signatures = tuple(kernel._compiled.signatures)
    assert len(signatures) == 1
    compiled = kernel._compiled
    calls = []

    def recording_reduce(*args):
        result = compiled(*args)
        calls.append(result)
        return result

    monkeypatch.setattr(kernel, '_compiled', recording_reduce)
    for cells, reachable, offsets in fixtures():
        if not cells:
            continue
        assert frontiers._ranked_reachable_viewpoints(cells, reachable, offsets) == original_order(
            cells, reachable, offsets)
    assert len(calls) == 20
    assert tuple(compiled.signatures) == signatures


@pytest.mark.parametrize('bad', ['large_map', 'large_work', 'large_pairs', 'bad_cells', 'float_cells',
                                'bad_offsets', 'nonfinite', 'wrong_mask', 'empty_map',
                                'overflow_offsets'])
def test_unsupported_inputs_decline_without_entering_compiled_kernel(monkeypatch, bad):
    from neusymnav.navigation import _frontier_kernel as kernel
    cells = [(1, 1)]
    reachable = np.ones((4, 4), bool)
    offsets = frontiers._view_offsets(.1, .1, .2)
    if bad == 'large_map':
        reachable = np.broadcast_to(np.array(True), (513, 513))
    elif bad == 'large_work':
        cells = [(1, 1)] * 1_000_001
    elif bad == 'large_pairs':
        cells = [(1, 1)] * 1000
        offsets = (np.zeros(9000, np.int32), np.zeros(9000, np.int32),
                   np.ones(9000, np.float64))
    elif bad == 'bad_cells':
        cells = [(1, 1, 1)]
    elif bad == 'float_cells':
        cells = [(1.5, 1)]
    elif bad == 'bad_offsets':
        offsets = (offsets[0][:-1], offsets[1], offsets[2])
    elif bad == 'nonfinite':
        offsets = (offsets[0], offsets[1], np.full(len(offsets[2]), np.nan))
    elif bad == 'wrong_mask':
        reachable = reachable.astype(np.int8)
    elif bad == 'empty_map':
        reachable = np.empty((0, 2), bool)
    elif bad == 'overflow_offsets':
        offsets = (np.array([2**31-1], np.int32), np.array([0], np.int32),
                   np.array([.45], np.float64))

    def forbidden(*args):
        raise AssertionError('unsupported input reached native indexing')

    monkeypatch.setattr(kernel, '_compiled', forbidden)
    monkeypatch.setattr(kernel, '_prepared', True)
    assert kernel.run(cells, reachable, offsets) is None


def test_absent_or_unprepared_kernel_keeps_original_vectorized_path(monkeypatch):
    from neusymnav.navigation import _frontier_kernel as kernel
    monkeypatch.setattr(kernel, '_compiled', None)
    monkeypatch.setattr(kernel, '_prepared', False)
    assert kernel.prepare() is False
    for cells, reachable, offsets in fixtures():
        assert kernel.run(cells, reachable, offsets) is None
        assert frontiers._ranked_reachable_viewpoints(cells, reachable, offsets) == original_order(
            cells, reachable, offsets)


def test_repeated_minimum_does_not_replace_first_seen_rank_or_signed_zero():
    from neusymnav.navigation import _frontier_kernel as kernel
    # Both offsets hit the same cell; minimum distance changes, insertion rank stays zero.
    cells = [(0, 0), (0, 0)]
    mask = np.ones((1, 1), bool)
    offsets = (np.zeros(4, np.int32), np.zeros(4, np.int32),
               np.array([.6, .45, 0., -0.], np.float64))
    got = kernel._reduce(np.asarray(cells, np.int32), mask, *offsets)
    assert got[0][0] == 0.
    assert np.signbit(got[0][0])
    assert got[1].tolist() == [0]
    kernel.prepare()
    native = kernel.run(cells, mask, offsets)
    if native is not None:
        assert native[0].tobytes() == got[0].tobytes()
        np.testing.assert_array_equal(native[1], got[1])


def test_empty_offsets_and_no_reachable_candidates_keep_empty_result():
    mask = np.zeros((1, 1), bool)
    empty = (np.empty(0, np.int32), np.empty(0, np.int32), np.empty(0, np.float64))
    assert frontiers._ranked_reachable_viewpoints([(0, 0)], mask, empty) == []
    assert frontiers._ranked_reachable_viewpoints(
        [(0, 0)], mask, frontiers._view_offsets(.1, .1, .2)) == []


def test_nonfinite_offsets_use_the_unchanged_vectorized_semantics():
    from neusymnav.navigation import _frontier_kernel as kernel
    kernel.prepare()
    cells = [(1, 1)]
    mask = np.ones((3, 3), bool)
    offsets = (np.array([0, 0, 0, -1], np.int32), np.array([0, 0, 1, 0], np.int32),
               np.array([.45, np.nan, np.inf, .4], np.float64))
    with np.errstate(invalid='ignore'):
        assert frontiers._ranked_reachable_viewpoints(cells, mask, offsets) == [(0, 1)]
        assert frontiers._ranked_reachable_viewpoints(cells, mask, offsets) == original_order(
            cells, mask, offsets)


def test_preparation_failure_keeps_fallback_available(monkeypatch):
    from neusymnav.navigation import _frontier_kernel as kernel

    def unavailable(*args):
        raise RuntimeError('compiler unavailable')

    monkeypatch.setattr(kernel, '_compiled', unavailable)
    monkeypatch.setattr(kernel, '_prepared', False)
    assert kernel.prepare() is False
    for cells, reachable, offsets in fixtures():
        assert frontiers._ranked_reachable_viewpoints(cells, reachable, offsets) == original_order(
            cells, reachable, offsets)
