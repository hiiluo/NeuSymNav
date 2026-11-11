"""Fused, allocation-free log-odds updates for NavMap tile views."""

from __future__ import annotations

import numpy as np

try:
    from numba import njit, types
except ImportError:  # Numba is an optional acceleration dependency.
    njit = None
    types = None


def _apply_log_odds_impl(
    tile_values: np.ndarray,
    hit_votes: np.ndarray,
    free_votes: np.ndarray,
    hit_log_odds: float,
    free_log_odds: float,
    min_log_odds: float,
    max_log_odds: float,
) -> None:
    if tile_values.ndim == 2:
        for row in range(tile_values.shape[0]):
            for col in range(tile_values.shape[1]):
                hit = hit_votes[row, col]
                free = free_votes[row, col]
                if hit or free:
                    previous = np.float64(tile_values[row, col])
                    if np.isnan(previous):
                        previous = 0.0
                    increment = hit_log_odds if hit else free_log_odds
                    updated = previous + increment
                    if updated < min_log_odds:
                        updated = min_log_odds
                    elif updated > max_log_odds:
                        updated = max_log_odds
                    tile_values[row, col] = updated
    else:
        for row in range(tile_values.shape[0]):
            for col in range(tile_values.shape[1]):
                for height_bin in range(tile_values.shape[2]):
                    hit = hit_votes[row, col, height_bin]
                    free = free_votes[row, col, height_bin]
                    if hit or free:
                        previous = np.float64(tile_values[row, col, height_bin])
                        if np.isnan(previous):
                            previous = 0.0
                        increment = hit_log_odds if hit else free_log_odds
                        updated = previous + increment
                        if updated < min_log_odds:
                            updated = min_log_odds
                        elif updated > max_log_odds:
                            updated = max_log_odds
                        tile_values[row, col, height_bin] = updated


_numba_apply_log_odds = (
    njit(cache=False, nogil=True)(_apply_log_odds_impl) if njit is not None else None
)

_WARM_LAYOUTS = (("C", "C", "C"), ("A", "A", "A"), ("C", "A", "A"))


def _signature(ndim: int, layouts: tuple[str, str, str]):
    if types is None:
        return None
    value_layout, hit_layout, free_layout = layouts
    return (
        types.Array(types.float32, ndim, value_layout),
        types.Array(types.boolean, ndim, hit_layout),
        types.Array(types.boolean, ndim, free_layout),
        types.float64,
        types.float64,
        types.float64,
        types.float64,
    )


def warmup_log_odds_kernel() -> bool:
    """Compile only C/A layouts captured in the bounded NavMap replay."""
    dispatcher = _numba_apply_log_odds
    if dispatcher is None:
        return False
    for ndim in (2, 3):
        for layouts in _WARM_LAYOUTS:
            signature = _signature(ndim, layouts)
            if signature not in dispatcher.signatures:
                dispatcher.compile(signature)
            if signature not in dispatcher.signatures:
                raise RuntimeError("Numba log-odds warmup did not register its signature")
    return True


def compiled_log_odds_signatures() -> tuple[str, ...]:
    """Return the frozen compiled signature set for replay assertions."""
    dispatcher = _numba_apply_log_odds
    if dispatcher is None:
        return ()
    return tuple(str(signature) for signature in dispatcher.signatures)


def _array_layout(array: np.ndarray) -> str:
    if array.flags.c_contiguous:
        return "C"
    if array.flags.f_contiguous:
        return "F"
    return "A"


def apply_log_odds_kernel(
    tile_values: np.ndarray,
    hit_votes: np.ndarray,
    free_votes: np.ndarray,
    hit_log_odds: float,
    free_log_odds: float,
    min_log_odds: float,
    max_log_odds: float,
) -> bool:
    """Apply a warmed Numba specialization, or leave inputs untouched.

    This deliberately never invokes the dispatcher directly: an unknown
    layout falls back to the caller's NumPy implementation instead of JITing
    during a mapping frame.
    """
    dispatcher = _numba_apply_log_odds
    if dispatcher is None:
        return False
    if (
        not isinstance(tile_values, np.ndarray)
        or not isinstance(hit_votes, np.ndarray)
        or not isinstance(free_votes, np.ndarray)
        or tile_values.ndim not in (2, 3)
        or tile_values.shape != hit_votes.shape
        or tile_values.shape != free_votes.shape
        or tile_values.dtype != np.float32
        or hit_votes.dtype != np.bool_
        or free_votes.dtype != np.bool_
        or not tile_values.flags.writeable
        or not tile_values.flags.aligned
        or not hit_votes.flags.aligned
        or not free_votes.flags.aligned
    ):
        return False

    layouts = (_array_layout(tile_values), _array_layout(hit_votes), _array_layout(free_votes))
    signature = _signature(tile_values.ndim, layouts)
    overload = dispatcher.overloads.get(signature)
    if overload is None:
        return False
    overload.entry_point(
        tile_values,
        hit_votes,
        free_votes,
        float(hit_log_odds),
        float(free_log_odds),
        float(min_log_odds),
        float(max_log_odds),
    )
    return True
