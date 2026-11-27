"""Paper-mode navigation core shared by policies: map upkeep, frontier choice, goal following.

The policy decides WHERE to go (a frontier, an object); ``PaperNav`` turns that into one discrete
action per step on the robot's own map. A goal the robot cannot reach or keeps bumping into is
reported back as failed so the policy can drop it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .obstacle_map import Frontier, ObstacleMap
from .planner import DistanceField, heading_action, wall_penalty, waypoint

Cell = Tuple[int, int]


@dataclass
class NavConfig:
    resolution_m: float = 0.05
    size_m: float = 60.0
    inflate_m: float = 0.18            # obstacle growth for planning (body radius)
    relaxed_inflate_m: float = 0.08    # one retry with this growth when no frontier is reachable (plan P4)
    lookahead_m: float = 0.5
    min_frontier_cells: int = 5
    reach_m: float = 0.3               # a frontier goal is reached within this distance
    frontier_blacklist_m: float = 0.5  # failed frontier goals block frontiers within this radius
    stuck_window: int = 20             # steps without 0.25 m of progress = stuck on the current goal
    stuck_progress_m: float = 0.25
    blocked_forwards: int = 2          # refused forward moves in a row at one pose = the way ahead is blocked
    blocked_give_up: int = 3           # escape turns on one frontier before it is dropped (plus stuck)
    obstacle_min_h_m: float = 0.2
    # action choice ("cách 1", ApexNav-style): 'scored' simulates each of the 12 headings' next forward
    # step on the map and scores it by the cost-to-goal field; 'heading' is the old waypoint rule
    controller: str = 'scored'
    wall_safe_m: float = 0.5           # near-wall penalty fades out at this distance from obstacles
    wall_weight: float = 4.0           # step cost x (1 + weight) right at an obstacle
    keep_heading_m: float = 0.05       # prefer the current heading unless another is this much better


@dataclass
class NavResult:
    action: Optional[str]          # None: goal reached or unreachable (see status)
    status: str                    # moving | reached | unreachable | stuck | blocked
    distance_m: float = math.inf   # path length to the goal


class PaperNav:
    def __init__(self, protocol, config: Optional[NavConfig] = None):
        self.p, self.cfg = protocol, config or NavConfig()
        self.map: Optional[ObstacleMap] = None
        self.blacklist: List[Tuple[float, float]] = []
        self.field: Optional[DistanceField] = None
        self.trav: Optional[np.ndarray] = None
        self._recent: List[Tuple[float, float]] = []
        self.robot_xy, self.yaw = (0.0, 0.0), 0.0
        self.blocked_streak = 0
        self.relaxed = False
        self.relaxed_steps = 0
        self.decision_audit = None

    # -- per step
    def observe(self, obs, last_action: Optional[str]) -> None:
        if self.map is None:
            self.map = ObstacleMap(origin_xy=obs.robot_xy, size_m=self.cfg.size_m, resolution_m=self.cfg.resolution_m,
                                   agent_radius_m=self.p.agent_radius_m, agent_height_m=self.p.agent_height_m,
                                   obstacle_min_h_m=self.cfg.obstacle_min_h_m, max_range_m=self.p.depth_max_m)
        self.robot_xy, self.yaw = tuple(obs.robot_xy), float(obs.yaw_rad)
        self.map._select_level(obs.z_m)
        if last_action == 'move_forward' and obs.collided:
            self.map.mark_collision(self.robot_xy, self.yaw, self.p.forward_step_m)
            self.blocked_streak += 1
        else:
            self.blocked_streak = 0
        self.map.update(obs.observation, robot_xy=self.robot_xy, base_z_m=obs.z_m)
        self._recent.append(self.robot_xy)
        self._plan(self.cfg.inflate_m)

    def _plan(self, inflate_m: float) -> None:
        self.relaxed = inflate_m < self.cfg.inflate_m
        self.trav = self.map.traversable(self.robot_xy, inflate_m)
        self.penalty = wall_penalty(self.map.obstacle, self.map.res, self.cfg.wall_safe_m, self.cfg.wall_weight)
        self.field = DistanceField(self.trav, self.map.cell(self.robot_xy), penalty=self.penalty)

    def reset_progress(self) -> None:
        self._recent = [self.robot_xy]

    def stuck(self) -> bool:
        w = self.cfg.stuck_window
        if len(self._recent) < w:
            return False
        tail = self._recent[-w:]
        return max(math.dist(tail[0], p) for p in tail) < self.cfg.stuck_progress_m

    # -- goals
    def frontiers(self) -> List[Frontier]:
        out = self._frontiers()
        if not out and not self.relaxed and self.cfg.relaxed_inflate_m < self.cfg.inflate_m:
            self._plan(self.cfg.relaxed_inflate_m)      # narrow passages: the simulator decides
            out = self._frontiers()
            self.relaxed_steps += 1
        return out

    def _frontiers(self) -> List[Frontier]:
        out = []
        for f in self.map.frontiers(self.trav, self.cfg.min_frontier_cells):
            if any(math.dist(f.xy, b) < self.cfg.frontier_blacklist_m for b in self.blacklist):
                continue
            if math.isfinite(self.field.distance(f.cell)):
                out.append(f)
        return out

    def path_length_m(self, cell: Cell) -> float:
        """Penalised path cost in metres (used to rank goals)."""
        return self.field.distance(cell) * self.map.res

    def reachable(self) -> np.ndarray:
        """Observed traversable cells in the robot's connected component."""
        out = np.zeros_like(self.trav)
        row, col = self.field.offset
        height, width = self.field.dist.shape
        out[row:row + height, col:col + width] = np.isfinite(self.field.dist)
        return out & self.trav

    def path_metres(self, cell: Cell) -> float:
        """Geometric length of the planned path to ``cell`` (the field itself holds penalised costs)."""
        path = self.field.path(cell)
        if not path:
            return math.inf
        steps = np.diff(np.asarray(path, float), axis=0)
        return float(np.hypot(steps[:, 0], steps[:, 1]).sum()) * self.map.res

    def go_to_cells(self, cells: Sequence[Cell], reach_m: Optional[float] = None) -> NavResult:
        """One step toward the nearest reachable of ``cells`` on the traversable map."""
        result = self._go_to_cells(cells, reach_m)
        if self.decision_audit is not None:
            self.decision_audit.append(dict(status=result.status, action=result.action, relaxed=self.relaxed))
        return result

    def _go_to_cells(self, cells: Sequence[Cell], reach_m: Optional[float]) -> NavResult:
        if not cells:
            return NavResult(None, 'unreachable')
        goal = self.field.nearest_reachable(cells)
        if goal is None:
            return NavResult(None, 'unreachable')
        dist = self.path_metres(goal)
        reach = self.cfg.reach_m if reach_m is None else reach_m
        if dist <= reach:
            return NavResult(None, 'reached', dist)
        if self.stuck():
            return NavResult(None, 'stuck', dist)
        action = self._scored_action(goal) if self.cfg.controller == 'scored' else None
        if action is None:
            path = [self.map.xy(c) for c in self.field.path(goal)]
            target = waypoint(path, self.robot_xy, self.cfg.lookahead_m)
            if target is None:
                return NavResult(None, 'unreachable', dist)
            action = heading_action(self.robot_xy, self.yaw, target, self.p.turn_deg)
        if action == 'move_forward' and self.blocked_streak >= self.cfg.blocked_forwards:
            return NavResult(None, 'blocked', dist)
        return NavResult(action, 'moving', dist)

    def _forward_ok(self, heading: float) -> Optional[Cell]:
        """End cell of one simulated forward step at ``heading`` if every sample on it is traversable."""
        step = self.p.forward_step_m
        n = max(2, int(math.ceil(step / (self.map.res / 2))))
        cell = None
        for t in np.linspace(step / n, step, n):
            cell = self.map.cell((self.robot_xy[0] + math.cos(heading) * t, self.robot_xy[1] + math.sin(heading) * t))
            if not (self.map.inside(cell) and self.trav[cell]):
                return None
        return cell

    def _scored_action(self, goal: Cell) -> Optional[str]:
        """Simulate the next forward step for each reachable heading (current yaw + k turns) and score
        its end point by the penalised cost-to-goal; turn toward the best heading, or step forward.
        None when no heading makes progress (the caller falls back to the waypoint rule)."""
        to_goal = DistanceField(self.trav, goal, penalty=self.penalty)
        here = to_goal.distance(self.map.cell(self.robot_xy))
        turn = math.radians(self.p.turn_deg)
        k_max = int(round(2 * math.pi / turn))
        best_k, best_v, v0 = None, math.inf, math.inf
        for k in range(k_max):
            cell = self._forward_ok(self.yaw + k * turn)
            if cell is None:
                continue
            v = to_goal.distance(cell) * self.map.res
            # turning costs steps: each turn adds roughly what a forward step could gain
            v_cost = v + min(k, k_max - k) * 0.5 * self.p.forward_step_m
            if k == 0:
                v0 = v_cost
            if v_cost < best_v:
                best_k, best_v = k, v_cost
        if best_k is None or not (best_v < here * self.map.res):
            return None
        if best_k == 0 or v0 <= best_v + self.cfg.keep_heading_m:
            return 'move_forward' if math.isfinite(v0) and v0 < here * self.map.res else None
        return 'turn_left' if best_k <= k_max - best_k else 'turn_right'

    def go_to_xy(self, xy, reach_m: Optional[float] = None) -> NavResult:
        return self.go_to_cells([self.map.cell(xy)], reach_m)

    def escape_turn(self, radius_m: float = 0.6) -> str:
        """After refused forward moves: turn toward the side with more traversable cells nearby."""
        r0, c0 = self.map.cell(self.robot_xy)
        k = int(math.ceil(radius_m / self.map.res))
        ra, ca = max(0, r0 - k), max(0, c0 - k)
        wr, wc = np.nonzero(self.trav[ra:r0 + k + 1, ca:c0 + k + 1])
        if len(wr) == 0:
            return 'turn_left'
        pts = np.array([self.map.xy((int(r) + ra, int(c) + ca)) for r, c in zip(wr, wc)])
        d = pts - np.asarray(self.robot_xy)
        near = np.hypot(d[:, 0], d[:, 1]) <= radius_m
        rel = (np.arctan2(d[near, 1], d[near, 0]) - self.yaw + math.pi) % (2 * math.pi) - math.pi
        left = int(np.count_nonzero((rel > 0.2) & (rel < 2.0)))
        right = int(np.count_nonzero((rel < -0.2) & (rel > -2.0)))
        return 'turn_left' if left >= right else 'turn_right'

    def face(self, xy) -> Optional[str]:
        """A turn toward ``xy``, or None when already facing it (within half a turn step)."""
        action = heading_action(self.robot_xy, self.yaw, xy, self.p.turn_deg)
        return None if action == 'move_forward' else action
