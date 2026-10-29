"""Optional GIL-free execution of the unchanged stable Dijkstra wavefront."""
import heapq
import math
import numpy as np

try:
    from numba import njit
except ImportError:
    njit = None


def _wavefront(mask, start, goals, diagonal, max_expansions, blocked):
    height, width = mask.shape
    size = height*width
    distance = np.full(size, np.inf)
    parents = np.full(size, -1, dtype=np.int64)
    closed = np.zeros(size, dtype=np.bool_)
    pending = np.zeros(size, dtype=np.bool_)
    for goal in goals:
        pending[goal] = True
    remaining = len(goals)
    settled = np.empty(len(goals), dtype=np.int64)
    found = 0
    distance[start] = 0.
    serial = 0
    queue = [(0., serial, start)]
    expansions = 0
    drs = (-1, 1, 0, 0, -1, -1, 1, 1)
    dcs = (0, 0, -1, 1, -1, 1, -1, 1)
    while queue and remaining and expansions < max_expansions:
        cost, _, current = heapq.heappop(queue)
        if closed[current]:
            continue
        if pending[current]:
            settled[found] = current
            found += 1
            pending[current] = False
            remaining -= 1
            if remaining == 0:
                break
        closed[current] = True
        expansions += 1
        row, col = current//width, current%width
        for direction in range(8 if diagonal else 4):
            dr, dc = drs[direction], dcs[direction]
            nr, nc = row+dr, col+dc
            if not 0 <= nr < height or not 0 <= nc < width:
                continue
            nxt = nr*width+nc
            if not mask[nr, nc] or closed[nxt]:
                continue
            if len(blocked):
                edge = min(current, nxt)*size+max(current, nxt)
                at = np.searchsorted(blocked, edge)
                if at < len(blocked) and blocked[at] == edge:
                    continue
            if dr and dc and (not mask[row+dr, col] or not mask[row, col+dc]):
                continue
            step = 1. if direction < 4 else math.sqrt(2.)
            candidate = cost+step
            if candidate < distance[nxt]:
                parents[nxt] = current
                distance[nxt] = candidate
                serial += 1
                heapq.heappush(queue, (candidate, serial, nxt))
    return distance, parents, settled[:found], expansions


_compiled = None if njit is None else njit(nogil=True, cache=False)(_wavefront)


def prepare():
    """Compile the actual read-only input signature before fresh capture/control."""
    if _compiled is None:
        return False
    mask = np.frombuffer(bytes([1, 1, 1, 1]), dtype=np.bool_).reshape(2, 2)
    _compiled(mask, 0, np.array([3], dtype=np.int64), True, 4, np.empty(0, dtype=np.int64))
    return True


def run(mask, start, goals, diagonal, max_expansions, blocked_edges):
    """Return raw search arrays, or None for the bounded Python fallback."""
    if (_compiled is None or mask.size > 16384 or len(goals) > 65
            or type(max_expansions) is not int or type(diagonal) is not bool
            or len(blocked_edges) > 1024):
        return None
    height, width = mask.shape
    keys = []
    try:
        for a, b in blocked_edges:
            if a > b:
                return None  # preserve the reference API for noncanonical edge sets
            if any(type(v) not in (int, np.int64, np.int32) for v in (*a, *b)):
                return None
            if not (0 <= a[0] < height and 0 <= a[1] < width and
                    0 <= b[0] < height and 0 <= b[1] < width):
                continue
            first, second = a[0]*width+a[1], b[0]*width+b[1]
            keys.append(min(first, second)*mask.size+max(first, second))
    except (TypeError, ValueError, OverflowError):
        return None
    encoded_goals = np.array([r*width+c for r, c in goals], dtype=np.int64)
    blocked = np.array(sorted(set(keys)), dtype=np.int64)
    return _compiled(mask, int(start[0]*width+start[1]), encoded_goals,
                     diagonal, max_expansions, blocked)
