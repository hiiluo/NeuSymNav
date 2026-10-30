"""Optional bounded, GIL-free frontier reductions; ranking stays in NumPy."""
import numpy as np

try:
    from numba import njit
except ImportError:
    njit = None


# At most 4 MiB of result arrays and 8M pair visits per invocation. These
# implementation limits select the reference fallback, never truncate a search.
_MAX_GRID_CELLS = 262144
_MAX_BOUNDARY_CELLS = 65536
_MAX_OFFSETS = 16384
_MAX_PAIRS = 8_000_000


def _reduce(cells, reachable, offset_rows, offset_cols, distances):
    height, width = reachable.shape
    minimum = np.full(height * width, np.inf, dtype=np.float64)
    first_seen = np.full(height * width, np.iinfo(np.int64).max, dtype=np.int64)
    n_offsets = len(distances)
    for source in range(len(cells)):
        for offset in range(n_offsets):
            row = int(cells[source, 0]) + int(offset_rows[offset])
            col = int(cells[source, 1]) + int(offset_cols[offset])
            if 0 <= row < height and 0 <= col < width and reachable[row, col]:
                flat = row * width + col
                distance = distances[offset]
                # <= also preserves np.minimum.at's last signed-zero tie.
                if distance <= minimum[flat]:
                    minimum[flat] = distance
                order = source * n_offsets + offset
                if order < first_seen[flat]:
                    first_seen[flat] = order
    return minimum, first_seen


_compiled = None if njit is None else njit(nogil=True, cache=False)(_reduce)
_prepared = False


def _readonly_contiguous(values):
    result = np.ascontiguousarray(values).view()
    result.flags.writeable = False
    return result


def prepare():
    """Warm the sole read-only signature before sensor capture/control starts."""
    global _prepared
    if _compiled is None:
        return False
    if _prepared:
        return True
    try:
        _compiled(
            _readonly_contiguous(np.array([[0, 0]], dtype=np.int32)),
            _readonly_contiguous(np.ones((2, 2), dtype=np.bool_)),
            _readonly_contiguous(np.array([0], dtype=np.int32)),
            _readonly_contiguous(np.array([1], dtype=np.int32)),
            _readonly_contiguous(np.array([.45], dtype=np.float64)),
        )
    except Exception:
        # An optional compiler/toolchain failure must leave the reference usable.
        return False
    _prepared = True
    return True


def run(cells, reachable, offsets):
    """Return exact reduction arrays, or None to retain the reference path.

    Validate before native indexing and normalize every supported array to the
    warmed signature. No lazy compilation or pairwise temporary arrays occur in
    this entry point; nonfinite/unsupported inputs keep NumPy's original rules.
    """
    if not _prepared or _compiled is None:
        return None
    if (not isinstance(reachable, np.ndarray) or reachable.ndim != 2
            or reachable.dtype != np.bool_ or not 0 < reachable.size <= _MAX_GRID_CELLS
            or not isinstance(cells, (list, tuple))
            or not 0 < len(cells) <= _MAX_BOUNDARY_CELLS
            or not isinstance(offsets, tuple) or len(offsets) != 3):
        return None
    offset_rows, offset_cols, distances = offsets
    if (any(not isinstance(values, np.ndarray) or values.ndim != 1 for values in offsets)
            or offset_rows.dtype != np.int32 or offset_cols.dtype != np.int32
            or distances.dtype != np.float64
            or not 0 < len(distances) <= _MAX_OFFSETS
            or len(offset_rows) != len(distances) or len(offset_cols) != len(distances)
            or len(cells) * len(distances) > _MAX_PAIRS):
        return None
    if any(not isinstance(cell, (tuple, list)) or len(cell) != 2 for cell in cells):
        return None
    try:
        boundary = np.asarray(cells)
    except (ValueError, TypeError, OverflowError):
        return None
    # Bounds prove that the reference int32 additions and accepted flat indices
    # cannot overflow. Reject rather than silently changing NumPy arithmetic.
    if (boundary.dtype.kind not in 'iu' or boundary.shape != (len(cells), 2)
            or np.any(boundary < -_MAX_GRID_CELLS) or np.any(boundary > _MAX_GRID_CELLS)
            or np.any(offset_rows < -_MAX_GRID_CELLS) or np.any(offset_rows > _MAX_GRID_CELLS)
            or np.any(offset_cols < -_MAX_GRID_CELLS) or np.any(offset_cols > _MAX_GRID_CELLS)
            or not np.isfinite(distances).all()):
        return None
    return _compiled(_readonly_contiguous(boundary.astype(np.int32, copy=False)),
                     _readonly_contiguous(reachable), _readonly_contiguous(offset_rows),
                     _readonly_contiguous(offset_cols), _readonly_contiguous(distances))
