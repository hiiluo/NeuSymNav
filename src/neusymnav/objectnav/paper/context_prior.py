"""B1 context prior: rank frontiers by related objects already seen (paper mode, no GT).

Idea from commonsense-guided exploration (ESC, L3MVN): a toilet is near a sink or a bathtub, a bed near a
nightstand. Every detection whose raw label has a weight for the episode's target (and a score of at least
``min_score``) is kept as a context point (median xy of its 3D points, robot floor height). A frontier's
bonus is ``bonus_m * max_i(weight_i * exp(-d_i / sigma_m))`` over context points on the same floor within
``radius_m``; the frontier with the lowest ``path cost - bonus`` is chosen. With no context point every
bonus is 0 and the choice is the B0 nearest frontier.

The weight table is written by hand from common sense, once, before any run with it (see the config).
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np


class ContextPrior:
    KEYS = {'weights', 'min_score', 'bonus_m', 'sigma_m', 'radius_m', 'level_m'}

    @classmethod
    def validate(cls, cfg: dict) -> None:
        if set(cfg) != cls.KEYS:
            raise ValueError('context_prior needs exactly %s' % sorted(cls.KEYS))
        for target, table in cfg['weights'].items():
            if not table or not all(0 < float(w) <= 1 for w in table.values()):
                raise ValueError('context_prior.weights[%r] maps labels to weights in (0, 1]' % target)
        for key in ('min_score', 'bonus_m', 'sigma_m', 'radius_m', 'level_m'):
            if not float(cfg[key]) > 0:
                raise ValueError('context_prior.%s must be positive' % key)

    def __init__(self, cfg: dict, target: str):
        self.cfg = cfg
        self.weights: Dict[str, float] = {k: float(v) for k, v in cfg['weights'].get(target, {}).items()}
        self.points: List[Tuple[float, float, float, float]] = []     # x, y, floor z, weight
        self.labels: Dict[str, int] = {}
        self.choices = self.changed = 0

    def add(self, label: str, score: float, points_world: np.ndarray, floor_z_m: float) -> None:
        w = self.weights.get(label)
        if w is None or score < float(self.cfg['min_score']) or points_world is None or len(points_world) == 0:
            return
        xy = np.median(np.asarray(points_world)[:, :2], axis=0)
        self.points.append((float(xy[0]), float(xy[1]), float(floor_z_m), w))
        self.labels[label] = self.labels.get(label, 0) + 1

    def bonus(self, xy, floor_z_m: float) -> float:
        best = 0.0
        sigma, radius, level = float(self.cfg['sigma_m']), float(self.cfg['radius_m']), float(self.cfg['level_m'])
        for x, y, z, w in self.points:
            if abs(z - floor_z_m) > level:
                continue
            d = math.hypot(x - xy[0], y - xy[1])
            if d <= radius:
                best = max(best, w * math.exp(-d / sigma))
        return float(self.cfg['bonus_m']) * best

    def choose(self, frontiers, path_cost, floor_z_m: float):
        """Frontier with the lowest path cost minus context bonus (ties and no context: B0 nearest)."""
        costs = [path_cost(f.cell) for f in frontiers]
        nearest = int(np.argmin(costs))
        if not self.points:
            return frontiers[nearest]
        scored = [c - self.bonus(f.xy, floor_z_m) for f, c in zip(frontiers, costs)]
        pick = int(np.argmin(scored))
        self.choices += 1
        self.changed += int(pick != nearest)
        return frontiers[pick]

    def summary(self) -> dict:
        return dict(points=len(self.points), labels=dict(sorted(self.labels.items())),
                    choices=self.choices, changed=self.changed)
