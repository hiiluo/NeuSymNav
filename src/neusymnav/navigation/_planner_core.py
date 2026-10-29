"""Exact grid paths over known-free cells, using A* or a shared Dijkstra search."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from itertools import count
from typing import Iterable

import numpy as np

from ._grid import GridSnapshot, GridState, PathResult, FootprintMaskCache


@dataclass(frozen=True)
class PlannerConfig:
    agent_radius_m: float
    inflation_margin_m: float = 0.05
    allow_diagonal: bool = True
    max_expansions: int = 500_000

    def __post_init__(self) -> None:
        if self.agent_radius_m <= 0 or self.inflation_margin_m < 0 or self.max_expansions < 1:
            raise ValueError("invalid planner configuration")


class AStarPlanner:
    def __init__(self, config: PlannerConfig, *, accelerate_many=True) -> None:
        self.config = config
        self._footprint_masks = FootprintMaskCache()
        self._wavefront_cache = None
        self._accelerated_many = False
        if accelerate_many:
            from ._planner_kernel import prepare
            self._accelerated_many = prepare()
        self._traversable_cache_key: tuple[object, ...] | None = None
        self._traversable_cache: np.ndarray | None = None

    def plan(self, snapshot: GridSnapshot, start_xy: tuple[float, float],
             goal_cell: tuple[int, int], *,
             allow_validated_start_anchor: bool = False,
             blocked_edges: frozenset[tuple[tuple[int, int], tuple[int, int]]] = frozenset()) -> PathResult:
        start = snapshot.world_to_cell(*start_xy)
        if start is None:
            return PathResult(False, (), math.inf, snapshot.revision, "start_outside_map")
        if not _inside(snapshot.states.shape, goal_cell):
            return PathResult(False, (), math.inf, snapshot.revision, "goal_outside_map")
        traversable = self._traversable(snapshot)
        if not traversable[start]:
            if False:  # NeuSymNav forbids GT/navmesh start anchors
                # This exception applies only to the externally validated
                # current pose. Successors and diagonal side cells remain
                # subject to the normal observed-footprint rule.
                traversable = traversable.copy()
                traversable[start] = True
            else:
                return PathResult(False, (), math.inf, snapshot.revision, "start_not_traversable")
        if not traversable[goal_cell]:
            return PathResult(False, (), math.inf, snapshot.revision, "goal_not_traversable")

        directions = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0))
        if self.config.allow_diagonal:
            root2 = math.sqrt(2.0)
            directions += ((-1, -1, root2), (-1, 1, root2), (1, -1, root2), (1, 1, root2))
        serial = count()
        open_heap: list[tuple[float, int, tuple[int, int]]] = []
        heapq.heappush(open_heap, (_heuristic(start, goal_cell), next(serial), start))
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g = {start: 0.0}
        closed: set[tuple[int, int]] = set()
        expansions = 0
        while open_heap and expansions < self.config.max_expansions:
            _, _, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            if current == goal_cell:
                cells = [current]
                while cells[-1] in came_from:
                    cells.append(came_from[cells[-1]])
                cells.reverse()
                return PathResult(
                    True, tuple(cells), g[current] * snapshot.resolution_m, snapshot.revision,
                    grid_origin_x_m=snapshot.origin_x_m,
                    grid_origin_y_m=snapshot.origin_y_m,
                    grid_resolution_m=snapshot.resolution_m,
                )
            closed.add(current)
            expansions += 1
            r, c = current
            for dr, dc, step in directions:
                nxt = r + dr, c + dc
                if not _inside(snapshot.states.shape, nxt) or not traversable[nxt] or nxt in closed:
                    continue
                if _edge_key(current, nxt) in blocked_edges:
                    continue
                if dr and dc and (not traversable[r + dr, c] or not traversable[r, c + dc]):
                    continue
                tentative = g[current] + step
                if tentative < g.get(nxt, math.inf):
                    came_from[nxt] = current
                    g[nxt] = tentative
                    heapq.heappush(open_heap, (tentative + _heuristic(nxt, goal_cell), next(serial), nxt))
        reason = "expansion_budget_exceeded" if expansions >= self.config.max_expansions else "no_known_free_path"
        return PathResult(False, (), math.inf, snapshot.revision, reason)

    def plan_many(self, snapshot: GridSnapshot, start_xy: tuple[float, float],
                  goal_cells: Iterable[tuple[int, int]], *,
                  allow_validated_start_anchor: bool = False,
                  blocked_edges: frozenset[
                      tuple[tuple[int, int], tuple[int, int]]
                  ] = frozenset()) -> dict[tuple[int, int], PathResult]:
        """Find exact shortest paths to all goals with one shared Dijkstra search.

        The footprint, start anchor, corner and edge rules match ``plan``.
        The expansion budget applies to the shared wavefront; goals already
        settled retain their optimal paths if that budget is exhausted.
        """
        goals = tuple(dict.fromkeys(goal_cells))
        results: dict[tuple[int, int], PathResult] = {}
        if not goals:
            return results

        def failure(reason: str) -> PathResult:
            return PathResult(False, (), math.inf, snapshot.revision, reason)

        start = snapshot.world_to_cell(*start_xy)
        if start is None:
            return {goal: failure("start_outside_map") for goal in goals}
        pending = set()
        # Match single-goal validation precedence, including out-of-map goals
        # when the start itself is not traversable.
        for goal in goals:
            if not _inside(snapshot.states.shape, goal):
                results[goal] = failure("goal_outside_map")
            else:
                pending.add(goal)
        if not pending:
            return results
        traversable = self._traversable(snapshot)
        if not traversable[start]:
            if False:  # NeuSymNav forbids GT/navmesh start anchors
                traversable = traversable.copy()
                traversable[start] = True
            else:
                results.update((goal, failure("start_not_traversable")) for goal in pending)
                return results
        for goal in tuple(pending):
            if not traversable[goal]:
                results[goal] = failure("goal_not_traversable")
                pending.remove(goal)
        if not pending:
            return results

        # A new revision may contain the exact same eroded free-cell graph.
        # Cache only this mathematical search, never a source/timestamp or a
        # controller decision. Reconstruct results with the CURRENT revision.
        search_key = None
        if traversable.size <= 1_000_000 and len(pending) <= 65:
            search_key = (snapshot.episode_id, snapshot.robot_geometry_id,
                          (self.config.agent_radius_m, self.config.inflation_margin_m,
                           self.config.allow_diagonal, self.config.max_expansions),
                          snapshot.origin_x_m, snapshot.origin_y_m, snapshot.resolution_m,
                          traversable.shape, traversable.tobytes(), start, goals, frozenset(blocked_edges))
            cached = self._wavefront_cache
            if cached is not None and cached[0] == search_key:
                for goal, fields in cached[1]:
                    success, cells, cost, reason, ox, oy, resolution = fields
                    results[goal] = PathResult(success, cells, cost, snapshot.revision, reason, ox, oy, resolution)
                return results
        search_goals = frozenset(pending)
        if self._accelerated_many:
            from ._planner_kernel import run
            compiled = run(traversable, start, tuple(pending), self.config.allow_diagonal,
                           self.config.max_expansions, blocked_edges)
            if compiled is not None:
                distances, parents, settled, expansions = compiled
                width = traversable.shape[1]
                for raw in settled:
                    node = int(raw)
                    goal = divmod(node, width)
                    cells = [goal]
                    previous = int(parents[node])
                    while previous >= 0:
                        cells.append(divmod(previous, width))
                        previous = int(parents[previous])
                    cells.reverse()
                    results[goal] = PathResult(True, tuple(cells), float(distances[node])*snapshot.resolution_m,
                        snapshot.revision, grid_origin_x_m=snapshot.origin_x_m,
                        grid_origin_y_m=snapshot.origin_y_m, grid_resolution_m=snapshot.resolution_m)
                    pending.remove(goal)
                reason = 'expansion_budget_exceeded' if expansions >= self.config.max_expansions else 'no_known_free_path'
                results.update((goal, failure(reason)) for goal in pending)
                self._remember_wavefront(search_key, search_goals, results)
                return results

        directions = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0))
        if self.config.allow_diagonal:
            root2 = math.sqrt(2.0)
            directions += ((-1, -1, root2), (-1, 1, root2),
                           (1, -1, root2), (1, 1, root2))
        serial = count()
        open_heap = [(0.0, next(serial), start)]
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        distances = {start: 0.0}
        closed: set[tuple[int, int]] = set()
        expansions = 0
        while open_heap and pending and expansions < self.config.max_expansions:
            distance, _, current = heapq.heappop(open_heap)
            if current in closed:
                continue
            if current in pending:
                cells = [current]
                while cells[-1] in came_from:
                    cells.append(came_from[cells[-1]])
                cells.reverse()
                results[current] = PathResult(
                    True, tuple(cells), distance * snapshot.resolution_m,
                    snapshot.revision, grid_origin_x_m=snapshot.origin_x_m,
                    grid_origin_y_m=snapshot.origin_y_m,
                    grid_resolution_m=snapshot.resolution_m,
                )
                pending.remove(current)
                if not pending:
                    break
            closed.add(current)
            expansions += 1
            r, c = current
            for dr, dc, step in directions:
                nxt = r + dr, c + dc
                if not _inside(snapshot.states.shape, nxt) or not traversable[nxt] or nxt in closed:
                    continue
                if blocked_edges and _edge_key(current, nxt) in blocked_edges:
                    continue
                if dr and dc and (not traversable[r + dr, c] or not traversable[r, c + dc]):
                    continue
                tentative = distance + step
                if tentative < distances.get(nxt, math.inf):
                    came_from[nxt] = current
                    distances[nxt] = tentative
                    heapq.heappush(open_heap, (tentative, next(serial), nxt))
        reason = ("expansion_budget_exceeded" if expansions >= self.config.max_expansions
                  else "no_known_free_path")
        results.update((goal, failure(reason)) for goal in pending)
        self._remember_wavefront(search_key, search_goals, results)
        return results

    def _remember_wavefront(self, search_key, search_goals, results):
        if search_key is not None and sum(len(results[g].cells) for g in search_goals) <= 65536:
            rows = []
            for goal, result in results.items():
                if goal in search_goals:
                    rows.append((goal, (result.success, result.cells, result.cost_m, result.reason,
                                       result.grid_origin_x_m, result.grid_origin_y_m, result.grid_resolution_m)))
            self._wavefront_cache = (search_key, tuple(rows))

    def revalidate(self, snapshot: GridSnapshot, path: PathResult,
                   current_xy: tuple[float, float] | None = None, *,
                   allow_validated_start_anchor: bool = False,
                   blocked_edges: frozenset[tuple[tuple[int, int], tuple[int, int]]] = frozenset()) -> PathResult:
        """Refresh a path on the current map without treating traveled cells as future route.

        When the current robot pose is provided, preserve the world-space goal
        but run A* from the current pose. Old path prefixes can become occupied
        after the robot has passed them; those cells must not invalidate the
        still-untraveled route. Without a pose, retain strict whole-path
        validation for callers that need that behavior.
        """
        if not path.success or not path.cells:
            return PathResult(False, (), math.inf, snapshot.revision, "no_path_to_revalidate")
        if (path.grid_origin_x_m is None or path.grid_origin_y_m is None
                or path.grid_resolution_m is None):
            return PathResult(False, (), math.inf, snapshot.revision, "path_grid_geometry_missing")
        if not math.isclose(path.grid_resolution_m, snapshot.resolution_m, rel_tol=0.0, abs_tol=1e-9):
            return PathResult(False, (), math.inf, snapshot.revision, "grid_resolution_changed")
        if current_xy is not None:
            goal_row, goal_col = path.cells[-1]
            goal_world_x = path.grid_origin_x_m + (goal_col + 0.5) * path.grid_resolution_m
            goal_world_y = path.grid_origin_y_m + (goal_row + 0.5) * path.grid_resolution_m
            goal_cell = snapshot.world_to_cell(goal_world_x, goal_world_y)
            if goal_cell is None:
                return PathResult(False, (), math.inf, snapshot.revision,
                                  "path_world_point_outside_map")
            return self.plan(
                snapshot, current_xy, goal_cell,
                allow_validated_start_anchor=allow_validated_start_anchor,
                blocked_edges=blocked_edges,
            )
        remapped: list[tuple[int, int]] = []
        for row, col in path.cells:
            world_x = path.grid_origin_x_m + (col + 0.5) * path.grid_resolution_m
            world_y = path.grid_origin_y_m + (row + 0.5) * path.grid_resolution_m
            cell = snapshot.world_to_cell(world_x, world_y)
            if cell is None:
                return PathResult(False, (), math.inf, snapshot.revision, "path_world_point_outside_map")
            remapped.append(cell)
        traversable = self._traversable(snapshot)
        previous = None
        cost_cells = 0.0
        for cell in remapped:
            if not _inside(snapshot.states.shape, cell) or not traversable[cell]:
                return PathResult(False, (), math.inf, snapshot.revision, "path_blocked_by_new_map")
            if previous is not None:
                dr, dc = abs(cell[0] - previous[0]), abs(cell[1] - previous[1])
                if max(dr, dc) > 1 or (dr == 0 and dc == 0):
                    return PathResult(False, (), math.inf, snapshot.revision, "path_discontinuous")
                if dr and dc and (not traversable[previous[0], cell[1]]
                                  or not traversable[cell[0], previous[1]]):
                    return PathResult(False, (), math.inf, snapshot.revision, "path_corner_cut_blocked")
                cost_cells += math.sqrt(2.0) if dr and dc else 1.0
            previous = cell
        return PathResult(True, tuple(remapped), cost_cells * snapshot.resolution_m,
                          snapshot.revision, "revalidated_on_new_map",
                          snapshot.origin_x_m, snapshot.origin_y_m, snapshot.resolution_m)

    def traversable(self, snapshot: GridSnapshot) -> np.ndarray:
        """Return the footprint-safe mask shared with the local controller.

        Callers must treat the cached mask as read-only.
        """
        return self._traversable(snapshot)

    def _traversable(self, snapshot: GridSnapshot) -> np.ndarray:
        return self._footprint_masks.get(snapshot, self.config.agent_radius_m + self.config.inflation_margin_m)


def _inside(shape: tuple[int, int], cell: tuple[int, int]) -> bool:
    return 0 <= cell[0] < shape[0] and 0 <= cell[1] < shape[1]


def _edge_key(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return an undirected, hashable transition key."""
    return (a, b) if a <= b else (b, a)


def _heuristic(a: tuple[int, int], b: tuple[int, int]) -> float:
    dr, dc = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(dr, dc) + (math.sqrt(2.0) - 1.0) * min(dr, dc)
