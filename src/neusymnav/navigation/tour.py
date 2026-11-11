"""Privileged navmesh coverage tour used as a goal source for 3DSG evaluation.

The tour polyline is computed OFFLINE from the simulator navmesh
(``tools/make_navmesh_tour.py``); it is privileged map knowledge and is never
an ObjectNav result. At run time it only replaces frontier *goal selection*:
every route is still planned on the robot's own observed NavMap, and every
command is re-planned and guarded on the current local depth frame.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np

TOUR_SCHEMA_VERSION = 1
TOUR_KIND = 'navmesh_coverage_tour'
GOAL_SOURCE = 'navmesh_tour_privileged_v1'
MAX_POLYLINE_POINTS = 50_000
MAX_SEGMENT_M = 0.30


# ---------------------------------------------------------------------------
# Offline planning (pathfinder adapter, no habitat import here)
# ---------------------------------------------------------------------------

def canonical_xy(source_xyz) -> tuple[float, float]:
    """Habitat source (+Y up) -> canonical planar XY used by the robot pose."""
    x, _y, z = (float(v) for v in source_xyz)
    return (x, -z)


def densify(points, max_segment_m=MAX_SEGMENT_M):
    out = []
    for point in points:
        point = (float(point[0]), float(point[1]))
        if out:
            previous = out[-1]
            distance = math.dist(previous, point)
            if distance < 1e-6:
                continue
            steps = max(1, math.ceil(distance / max_segment_m))
            for step in range(1, steps):
                t = step / steps
                out.append((previous[0] + t * (point[0] - previous[0]),
                            previous[1] + t * (point[1] - previous[1])))
        out.append(point)
    return out


def plan_coverage_tour(pathfinder, start_xyz, *, spacing_m=1.0, coverage_radius_m=1.5,
                       floor_tolerance_m=0.5, nearest_candidates=12, max_goals=500):
    """Greedy geodesic coverage of one navmesh floor island.

    ``pathfinder`` provides ``bounds()``, ``snap(xyz)`` (None if unusable),
    ``island(xyz)`` and ``path(a, b) -> (distance_m, points)`` with
    ``math.inf`` when unreachable. Returns source-frame goals and polyline.
    """
    if not (0.25 <= spacing_m <= 5.0) or not (0.25 <= coverage_radius_m <= 10.0):
        raise ValueError('tour spacing/coverage radius out of range')
    start = pathfinder.snap(start_xyz)
    if start is None:
        raise ValueError('tour start is not on the navmesh')
    start_island = pathfinder.island(start)
    (min_x, _min_y, min_z), (max_x, _max_y, max_z) = pathfinder.bounds()
    candidates = []
    x = min_x
    while x <= max_x + 1e-9:
        z = min_z
        while z <= max_z + 1e-9:
            snapped = pathfinder.snap((x, start[1], z))
            if (snapped is not None and abs(snapped[1] - start[1]) <= floor_tolerance_m
                    and pathfinder.island(snapped) == start_island
                    and math.dist((snapped[0], snapped[2]), (x, z)) <= spacing_m * 0.75
                    and all(math.dist(snapped, other) > spacing_m * 0.5 for other in candidates)):
                candidates.append(tuple(float(v) for v in snapped))
            z += spacing_m
        x += spacing_m

    def cover(point, pending):
        return [c for c in pending if math.dist((c[0], c[2]), (point[0], point[2])) > coverage_radius_m]

    pending = cover(start, candidates)
    current = start
    goals = []
    polyline = [start]
    unreachable = 0
    total_m = 0.0
    while pending and len(goals) < max_goals:
        nearest = sorted(pending, key=lambda c: math.dist(c, current))[:nearest_candidates]
        best = None
        for candidate in nearest:
            distance, points = pathfinder.path(current, candidate)
            if math.isfinite(distance) and (best is None or distance < best[0]):
                best = (distance, points, candidate)
        if best is None:
            # None of the nearest are reachable from here: drop them.
            unreachable += len(nearest)
            pending = [c for c in pending if c not in nearest]
            continue
        distance, points, candidate = best
        total_m += distance
        polyline.extend(tuple(float(v) for v in p) for p in points[1:])
        goals.append(candidate)
        current = candidate
        pending = cover(candidate, [c for c in pending if c != candidate])
    return dict(start=start, goals=goals, polyline=polyline, length_m=total_m,
                candidates=len(candidates), unreachable_candidates=unreachable)


def tour_document(result, *, scene_path, scene_sha256, spacing_m, coverage_radius_m,
                  agent_radius_m, agent_height_m):
    polyline = densify([canonical_xy(p) for p in result['polyline']])
    return dict(schema_version=TOUR_SCHEMA_VERSION, kind=TOUR_KIND, privileged=True,
        goal_source=GOAL_SOURCE,
        note='Privileged simulator navmesh tour for 3DSG evaluation; not an ObjectNav result.',
        scene=dict(path=str(scene_path), sha256=scene_sha256),
        parameters=dict(spacing_m=spacing_m, coverage_radius_m=coverage_radius_m,
                        agent_radius_m=agent_radius_m, agent_height_m=agent_height_m),
        start_xy=list(canonical_xy(result['start'])),
        goals_xy=[list(canonical_xy(g)) for g in result['goals']],
        polyline_xy=[list(p) for p in polyline],
        length_m=float(result['length_m']), candidates=int(result['candidates']),
        unreachable_candidates=int(result['unreachable_candidates']))


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TourPlan:
    polyline: tuple[tuple[float, float], ...]
    start_xy: tuple[float, float]
    scene_sha256: str
    sha256: str
    length_m: float
    # Polyline indices of the coverage goals, in tour order (monotone).
    goal_indices: tuple[int, ...] = ()

    @classmethod
    def load(cls, path, sha256=None) -> 'TourPlan':
        data = Path(path).read_bytes()
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('tour file exceeds 16 MiB')
        digest = hashlib.sha256(data).hexdigest()
        if sha256 is not None and digest != sha256:
            raise ValueError('tour sha256 mismatch')
        value = json.loads(data)
        if (not isinstance(value, dict) or value.get('schema_version') != TOUR_SCHEMA_VERSION
                or value.get('kind') != TOUR_KIND or value.get('privileged') is not True):
            raise ValueError('not a privileged navmesh coverage tour v1')
        points = value.get('polyline_xy')
        if not isinstance(points, list) or not 2 <= len(points) <= MAX_POLYLINE_POINTS:
            raise ValueError('tour polyline must have 2..50000 points')
        polyline = []
        for point in points:
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
                raise ValueError('tour polyline points must be finite XY pairs')
            polyline.append((float(point[0]), float(point[1])))
        for a, b in zip(polyline, polyline[1:]):
            if math.dist(a, b) > MAX_SEGMENT_M + 1e-6:
                raise ValueError('tour polyline is not densified')
        start = value.get('start_xy')
        if not isinstance(start, list) or len(start) != 2:
            raise ValueError('tour start_xy missing')
        scene = value.get('scene', {})
        goals = value.get('goals_xy', [])
        if not isinstance(goals, list) or any(
                not isinstance(g, list) or len(g) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in g) for g in goals):
            raise ValueError('tour goals_xy must be finite XY pairs')
        return cls(tuple(polyline), (float(start[0]), float(start[1])),
                   str(scene.get('sha256', '')), digest, float(value.get('length_m', 0.0)),
                   goal_polyline_indices(polyline, goals))


def goal_polyline_indices(polyline, goals_xy, tolerance_m=0.05):
    """Monotone polyline index of each coverage goal (goals are route vertices)."""
    out, start = [], 0
    for goal in goals_xy:
        goal = (float(goal[0]), float(goal[1]))
        best = None
        for index in range(start, len(polyline)):
            if math.dist(polyline[index], goal) <= tolerance_m:
                best = index
                break
        if best is None:
            continue  # tolerate a goal that is not a route vertex
        out.append(best)
        start = best + 1
    return tuple(out)


@dataclass(frozen=True)
class TourSelection:
    goal_id: str | None
    path: object | None
    goal_world_xy: tuple[float, float] | None
    reason: str
    heading_rad: float | None = None


class TourFollower:
    """Monotone progress along the polyline with a bounded look-ahead target.

    Progress is searched only in a window of route LENGTH ahead of the current
    index (look-ahead + reach). A tour that passes the same corridor twice
    therefore cannot "reach" the later pass and drop the loop in between.
    """

    def __init__(self, plan: TourPlan, *, reach_m=0.5, lookahead_m=1.6,
                 stuck_timeout_s=10.0, skip_m=1.0, search_window=None, relax_m=0.5,
                 approach_m=3.0, stall_timeout_s=60.0, scan_degrees=0.0, scan_step_degrees=90.0,
                 scan_min_separation_m=2.0, scan_step_timeout_s=8.0):
        if not isinstance(plan, TourPlan):
            raise TypeError('plan must be TourPlan')
        if not (0.1 <= reach_m <= 2.0 and 0.3 <= lookahead_m <= 5.0
                and 1.0 <= stuck_timeout_s <= 120.0 and 0.2 <= skip_m <= 5.0
                and 0.0 <= relax_m <= 1.5 and 0.0 <= approach_m <= 10.0
                and stuck_timeout_s <= stall_timeout_s <= 600.0
                and 0.0 <= scan_degrees <= 360.0 and 30.0 <= scan_step_degrees <= 180.0
                and 0.0 <= scan_min_separation_m <= 20.0 and 1.0 <= scan_step_timeout_s <= 60.0):
            raise ValueError('invalid tour follower parameters')
        del search_window  # superseded by the route-length progress window
        self.plan = plan
        self.reach_m, self.lookahead_m = float(reach_m), float(lookahead_m)
        self.stuck_timeout_s, self.skip_m = float(stuck_timeout_s), float(skip_m)
        self.stall_timeout_s = float(stall_timeout_s)
        self.relax_m, self.approach_m = float(relax_m), float(approach_m)
        self.progress_window_m = self.lookahead_m + max(self.reach_m, self.relax_m)
        points = np.asarray(plan.polyline, dtype=np.float64)
        self._points = points
        self._route_s = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(points, axis=0).T))))
        self._visited = np.zeros(len(points), dtype=bool)
        self.index = 0
        self._progress_at_s = None      # last index advance or robot motion while following
        self._index_at_s = None         # last index advance (hard stall bound)
        self._motion_mark = None        # (xy, yaw) at the last progress mark
        self.end_reason = None          # 'reached' | 'skipped' once complete
        # Coverage goals are gates: progress never passes an unvisited goal by
        # matching a later pass of the route (out-and-back spurs into small
        # rooms). At a goal the robot may scan in place for the 3DSG.
        self.scan_degrees = float(scan_degrees)
        self.scan_step_rad = math.radians(scan_step_degrees)
        self.scan_min_separation_m = float(scan_min_separation_m)
        self.scan_step_timeout_s = float(scan_step_timeout_s)
        self._goal_indices = tuple(i for i in plan.goal_indices if 0 < i < len(plan.polyline))
        self._passed_goals = set()
        self._scan = None               # dict(gate, headings, step, step_started_s)
        self.scanned_xy: list[tuple[float, float]] = []
        self.counts = dict(selected=0, relaxed=0, approach=0, unobserved=0, skipped=0,
                           skipped_points=0, reached=0, motion_resets=0, goals_reached=0,
                           scans=0, scan_steps=0, scan_step_timeouts=0)
        self.skipped_xy: list[tuple[float, float]] = []

    @property
    def complete(self) -> bool:
        return self.index >= len(self.plan.polyline) - 1

    def status(self) -> dict:
        n = len(self.plan.polyline)
        return dict(goal_source=GOAL_SOURCE, tour_sha256=self.plan.sha256, index=self.index,
                    points=n, progress=round(self.index / max(1, n - 1), 4),
                    complete=self.complete, complete_reason=self.end_reason,
                    visited_points=int(self._visited.sum()),
                    coverage=round(float(self._visited.mean()), 4),
                    route_length_m=round(float(self._route_s[-1]), 2),
                    goals=len(self._goal_indices), goals_passed=len(self._passed_goals),
                    scanning=self._scan is not None,
                    scanned_xy=[list(p) for p in self.scanned_xy[-32:]],
                    counts=dict(self.counts),
                    skipped_xy=[list(p) for p in self.skipped_xy[-32:]])

    def _gate(self):
        """Next coverage goal index at or after the current index not yet passed."""
        for index in self._goal_indices:
            if index >= self.index and index not in self._passed_goals:
                return index
        return None

    def _window_end(self):
        """Exclusive end index of the progress window (route length ahead)."""
        limit = self._route_s[self.index] + self.progress_window_m
        end = int(min(len(self._route_s), np.searchsorted(self._route_s, limit, side='right') + 1))
        gate = self._gate()
        return end if gate is None else min(end, gate + 1)

    def _advance_to(self, index, now_s, *, skipped=False):
        if index > self.index:
            self.index = min(index, len(self.plan.polyline) - 1)
            self._progress_at_s = self._index_at_s = now_s
            # Skipping (timeout) passes gates; reaching stops at the gate.
            for goal in self._goal_indices:
                if goal < self.index or (skipped and goal <= self.index):
                    self._passed_goals.add(goal)
            if self.complete and self.end_reason is None:
                self.end_reason = 'skipped' if skipped else 'reached'

    def _skip(self, now_s):
        polyline = self.plan.polyline
        travelled = 0.0
        index = self.index
        while index < len(polyline) - 1 and travelled < self.skip_m:
            travelled += math.dist(polyline[index], polyline[index + 1])
            index += 1
        self.skipped_xy.append(polyline[self.index])
        self.counts['skipped'] += 1
        self.counts['skipped_points'] += int((~self._visited[self.index + 1:index + 1]).sum())
        self._advance_to(index, now_s, skipped=True)

    def _nearest_in_window(self, xy):
        end = self._window_end()
        window = self._points[self.index:end]
        if len(window) == 0:
            return None, math.inf
        d = np.hypot(*(window - np.asarray(xy, dtype=np.float64)).T)
        j = int(np.argmin(d))
        return self.index + j, float(d[j])

    def report_reached(self, xy, now_s=None, index=None):
        polyline = self.plan.polyline
        when = now_s if now_s is not None else self._progress_at_s or 0.0
        tolerance = max(self.reach_m, self.relax_m) + 1e-6
        if index is not None and self.index <= index < min(len(polyline), self._window_end()) and (
                math.dist(polyline[index], xy) <= tolerance):
            self.counts['reached'] += 1
            self._advance_to(index, when)
            return
        best, distance = self._nearest_in_window(xy)
        if best is not None and distance <= tolerance:
            self.counts['reached'] += 1
            self._advance_to(best, when)

    def report_scan_done(self, goal_id, now_s=None):
        scan = self._scan
        if scan is None or goal_id != f"scan-{scan['gate']}-{scan['step']}":
            return
        self.counts['scan_steps'] += 1
        self._next_scan_step(now_s if now_s is not None else scan['step_started_s'])

    def _next_scan_step(self, now_s):
        scan = self._scan
        scan['step'] += 1
        scan['step_started_s'] = now_s
        self._progress_at_s = now_s
        if scan['step'] >= len(scan['headings']):
            self._passed_goals.add(scan['gate'])
            self.scanned_xy.append(self.plan.polyline[scan['gate']])
            self.counts['scans'] += 1
            self._index_at_s = now_s
            self._scan = None

    def _gate_action(self, robot_xy, yaw_rad, now_s):
        """At a coverage goal: return a scan selection, or pass the gate."""
        gate = self._gate()
        if gate is None or self.index < gate:
            return None
        if self._scan is None:
            self.counts['goals_reached'] += 1
            goal_xy = self.plan.polyline[gate]
            wants = (self.scan_degrees > 0 and yaw_rad is not None and all(
                math.dist(goal_xy, other) >= self.scan_min_separation_m for other in self.scanned_xy))
            if not wants:
                self._passed_goals.add(gate)
                return None
            steps = max(1, math.ceil(math.radians(self.scan_degrees) / self.scan_step_rad - 1e-9))
            step = math.radians(self.scan_degrees) / steps
            self._scan = dict(gate=gate, step=0, step_started_s=now_s,
                              headings=tuple(yaw_rad + step * (k + 1) for k in range(steps)))
        scan = self._scan
        if now_s - scan['step_started_s'] > self.scan_step_timeout_s:
            self.counts['scan_step_timeouts'] += 1
            self._next_scan_step(now_s)
            if self._scan is None:
                return None
        heading = scan['headings'][scan['step']]
        target = (robot_xy[0] + 0.5 * math.cos(heading), robot_xy[1] + 0.5 * math.sin(heading))
        return TourSelection(f"scan-{scan['gate']}-{scan['step']}", None, target, 'tour_scan',
                             heading_rad=heading)

    def _note_motion(self, robot_xy, yaw_rad, now_s):
        """Moving or turning while following a target is progress (not stuck)."""
        mark = self._motion_mark
        if mark is None:
            self._motion_mark = (tuple(robot_xy), yaw_rad)
            return
        moved = math.dist(mark[0], robot_xy) >= 0.2
        turned = (yaw_rad is not None and mark[1] is not None
                  and abs(math.remainder(yaw_rad - mark[1], math.tau)) >= 0.35)
        if moved or turned:
            self._motion_mark = (tuple(robot_xy), yaw_rad)
            self._progress_at_s = now_s
            self.counts['motion_resets'] += 1

    def select(self, grid, robot_xy, now_s, planner_core, yaw_rad=None) -> TourSelection:
        selection = self._select(grid, robot_xy, now_s, planner_core, yaw_rad)
        if selection.reason == 'tour_scan':
            self._progress_at_s = now_s  # scanning in place is progress
            self._motion_mark = (tuple(robot_xy), yaw_rad)
        elif selection.path is not None:
            self._note_motion(robot_xy, yaw_rad, now_s)
        else:
            self._motion_mark = (tuple(robot_xy), yaw_rad)
        return selection

    def _select(self, grid, robot_xy, now_s, planner_core, yaw_rad=None) -> TourSelection:
        polyline = self.plan.polyline
        if self._progress_at_s is None:
            self._progress_at_s = self._index_at_s = now_s
        d_all = np.hypot(*(self._points - np.asarray(robot_xy, dtype=np.float64)).T)
        self._visited |= d_all <= self.reach_m
        nearest, distance = self._nearest_in_window(robot_xy)
        if nearest is not None and distance <= self.reach_m:
            self._advance_to(nearest, now_s)
        if self.complete:
            return TourSelection(None, None, None, 'tour_complete')
        action = self._gate_action(robot_xy, yaw_rad, now_s)
        if action is not None:
            return action
        if (now_s - self._progress_at_s > self.stuck_timeout_s
                or now_s - self._index_at_s > self.stall_timeout_s):
            self._skip(now_s)
            if self.complete:
                return TourSelection(None, None, None, 'tour_complete')
        # Candidate targets: forward along the polyline within the look-ahead.
        # The navmesh route hugs walls at the navmesh agent radius, while the
        # observed-map footprint (radius + margin, unknown blocks) is wider, so
        # a polyline point itself is often not traversable near corners and
        # doors. Each point is therefore relaxed to the nearest traversable
        # observed cells within ``relax_m``; the farthest point with a plan wins.
        traversable = planner_core.traversable(grid)
        free_rc = np.argwhere(traversable)
        if free_rc.size == 0:
            self.counts['unobserved'] += 1
            return TourSelection(None, None, None, 'tour_target_unobserved')
        free_xy = np.column_stack((grid.origin_x_m + (free_rc[:, 1] + 0.5) * grid.resolution_m,
                                   grid.origin_y_m + (free_rc[:, 0] + 0.5) * grid.resolution_m))
        robot = np.asarray(robot_xy, dtype=np.float64)
        moving = np.hypot(*(free_xy - robot).T) > 0.15

        def nearest_cells(point, radius, k):
            d = np.hypot(*(free_xy - np.asarray(point)).T)
            mask = moving & (d <= radius)
            if not mask.any():
                return []
            order = np.flatnonzero(mask)[np.argsort(d[mask], kind='stable')[:k]]
            return [(tuple(int(v) for v in free_rc[j]), float(d[j])) for j in order]

        # Relaxed progress: a route point whose nearest traversable cell is
        # where the robot already stands counts as reached (the closest the
        # observed footprint allows), so the look-ahead moves on.
        gate = self._gate()
        limit = len(polyline) - 1 if gate is None else gate
        travelled, index = 0.0, self.index
        while index < limit and travelled <= self.lookahead_m:
            index += 1
            travelled += math.dist(polyline[index - 1], polyline[index])
            d = np.hypot(*(free_xy - np.asarray(polyline[index])).T)
            j = int(np.argmin(d))
            if d[j] <= self.relax_m and math.dist(free_xy[j], robot_xy) <= 0.2:
                self._advance_to(index, now_s)
        if self.complete:
            return TourSelection(None, None, None, 'tour_complete')
        action = self._gate_action(robot_xy, yaw_rad, now_s)
        if action is not None:
            return action
        gate = self._gate()
        limit = len(polyline) - 1 if gate is None else gate
        candidates = []
        travelled = 0.0
        index = self.index
        while index < limit and travelled <= self.lookahead_m:
            index += 1
            travelled += math.dist(polyline[index - 1], polyline[index])
            if math.dist(polyline[index], robot_xy) > 0.15:
                cells = nearest_cells(polyline[index], self.relax_m, 4)
                if cells:
                    candidates.append((index, cells))
        if candidates:
            goals = tuple(dict.fromkeys(cell for _i, cells in candidates for cell, _d in cells))
            results = planner_core.plan_many(grid, robot_xy, goals)
            for index, cells in reversed(candidates):
                for cell, offset in cells:  # nearest to the polyline point first
                    result = results.get(cell)
                    if result is not None and result.success and len(result.cells) > 1:
                        self.counts['selected'] += 1
                        if offset > grid.resolution_m:
                            self.counts['relaxed'] += 1
                        return TourSelection(f'tour-{index}', result, grid.cell_to_world(*cell),
                                             'tour_target')
        # Nothing near the route is plannable yet (typically the route turns
        # around a wall into space the robot has not observed). Approach: go
        # to the reachable observed cell closest to the next route point, if
        # that is real progress towards it. Moving there reveals the space.
        if self.approach_m > 0:
            target = polyline[min(index, len(polyline) - 1)]
            here = math.dist(target, robot_xy)
            cells = nearest_cells(target, self.approach_m, 96)
            if cells:
                results = planner_core.plan_many(grid, robot_xy, tuple(c for c, _d in cells))
                for cell, distance in cells:
                    result = results.get(cell)
                    if (result is not None and result.success and len(result.cells) > 1
                            and distance <= here - 0.3):
                        self.counts['approach'] += 1
                        return TourSelection(f'tour-{index}', result, grid.cell_to_world(*cell),
                                             'tour_target_approach')
        self.counts['unobserved'] += 1
        return TourSelection(None, None, None, 'tour_target_unobserved')
