"""ObjectNav metrics with Habitat-lab semantics (pure Python, offline only).

Definitions follow habitat-lab's ObjectNav measures:

* DistanceToGoal (DTG): geodesic distance from the agent to the NEAREST goal
  view point (``distance_to: VIEW_POINTS``).
* Success: the agent called STOP and DTG at the end is strictly below
  ``success_distance`` (0.1 m for ObjectNav).
* SPL = success * l / max(p, l), with l = DTG at episode start computed on the
  same navmesh (habitat-lab's ``_start_end_episode_distance``) and p = the
  length the agent actually travelled (sum of position deltas).
* SoftSPL = max(0, 1 - d_end / l) * l / max(p, l).

The geodesic oracle is passed in by the caller (Habitat interpreter); this
module never imports Habitat and never touches the robot runtime.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

SUCCESS_DISTANCE_M = 0.1

# Failure modes for unsuccessful episodes (assigned by the evaluator from
# offline evidence; see classify_failure).
FAILURE_MODES = (
    'never_seen',          # target never inside any frame
    'seen_not_detected',   # target visible, detector never reported it
    'wrong_object_stop',   # STOP far from any target, near a false detection
    'stopped_too_far',     # STOP with DTG between success distance and near_m
    'stopped_elsewhere',   # STOP far from target without false-detection evidence
    'budget_exhausted',    # no STOP before the step/time budget
    'stuck',               # no progress for the stuck window
    'invalid_episode',     # start unreachable / no path (excluded from means by flag)
    'start_not_navigable', # episode start not on the robot body's navmesh (robot never ran)
)


@dataclass(frozen=True)
class EpisodeOutcome:
    uid: str
    scene: str
    category: str
    called_stop: bool
    success: bool
    spl: float
    soft_spl: float
    dtg_end_m: float
    dtg_start_m: float
    stored_geodesic_m: Optional[float]
    path_length_m: float
    steps: int
    sim_time_s: Optional[float]
    failure_mode: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)


def path_length(positions: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for a, b in zip(positions, positions[1:]):
        total += math.dist(a, b)
    return total


def score_episode(*, uid: str, scene: str, category: str, positions: Sequence[Sequence[float]],
                  called_stop: bool, distance_to_goal: Callable[[Sequence[float]], float],
                  steps: int, sim_time_s: Optional[float] = None,
                  stored_geodesic_m: Optional[float] = None,
                  success_distance: float = SUCCESS_DISTANCE_M) -> EpisodeOutcome:
    """Score one trajectory. ``positions[0]`` must be the episode start."""
    if len(positions) < 1:
        raise ValueError('trajectory needs at least the start position')
    d_start = float(distance_to_goal(positions[0]))
    d_end = float(distance_to_goal(positions[-1]))
    p = path_length(positions)
    if not math.isfinite(d_start) or d_start <= 0:
        # Habitat-lab would divide by an infinite/zero start distance; flag it.
        return EpisodeOutcome(uid, scene, category, called_stop, False, 0.0, 0.0, d_end, d_start,
                              stored_geodesic_m, p, steps, sim_time_s, 'invalid_episode')
    success = bool(called_stop) and math.isfinite(d_end) and d_end < success_distance
    efficiency = d_start / max(p, d_start)
    spl = efficiency if success else 0.0
    soft = max(0.0, 1.0 - d_end / d_start) if math.isfinite(d_end) else 0.0
    return EpisodeOutcome(uid, scene, category, bool(called_stop), success, spl, soft * efficiency,
                          d_end, d_start, stored_geodesic_m, p, int(steps), sim_time_s)


def classify_failure(outcome: EpisodeOutcome, *, target_seen: Optional[bool] = None,
                     target_detected: Optional[bool] = None,
                     stop_near_false_detection: Optional[bool] = None,
                     stuck: bool = False, start_not_navigable: bool = False,
                     near_m: float = 1.0) -> Optional[str]:
    """Assign one failure mode (None for successes). Order = most specific first."""
    if outcome.success:
        return None
    if start_not_navigable:
        return 'start_not_navigable'
    if outcome.failure_mode == 'invalid_episode':
        return 'invalid_episode'
    if outcome.called_stop:
        if outcome.dtg_end_m < near_m:
            return 'stopped_too_far'
        if stop_near_false_detection:
            return 'wrong_object_stop'
        if target_seen is False:
            return 'never_seen'
        return 'stopped_elsewhere'
    if stuck:
        return 'stuck'
    if target_seen is False:
        return 'never_seen'
    if target_seen and target_detected is False:
        return 'seen_not_detected'
    return 'budget_exhausted'


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float('nan')


def bootstrap_ci(values: Sequence[float], *, iterations: int = 2000, seed: int = 0,
                 level: float = 0.95) -> Tuple[float, float]:
    """Percentile bootstrap CI of the mean; deterministic for a seed."""
    if not values:
        return (float('nan'), float('nan'))
    rng = random.Random(seed)
    n = len(values)
    means = sorted(_mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations))
    lo = means[int((1 - level) / 2 * iterations)]
    hi = means[min(iterations - 1, int((1 + level) / 2 * iterations))]
    return (lo, hi)


def summarize(outcomes: Iterable[EpisodeOutcome], *, seed: int = 0) -> dict:
    """Overall / per-category / per-scene means with bootstrap CIs for SR and SPL.

    Invalid episodes are counted but excluded from the means (reported apart).
    """
    rows = list(outcomes)
    valid = [o for o in rows if o.failure_mode != 'invalid_episode']

    def block(items: List[EpisodeOutcome]) -> dict:
        sr = [1.0 if o.success else 0.0 for o in items]
        spl = [o.spl for o in items]
        dtg = [o.dtg_end_m for o in items if math.isfinite(o.dtg_end_m)]
        return {
            'episodes': len(items),
            'success_rate': _mean(sr), 'success_rate_ci95': bootstrap_ci(sr, seed=seed),
            'spl': _mean(spl), 'spl_ci95': bootstrap_ci(spl, seed=seed),
            'soft_spl': _mean([o.soft_spl for o in items]),
            'dtg_m': _mean(dtg),
            'path_length_m': _mean([o.path_length_m for o in items]),
            'stop_rate': _mean([1.0 if o.called_stop else 0.0 for o in items]),
        }

    def grouped(key) -> Dict[str, dict]:
        groups: Dict[str, List[EpisodeOutcome]] = {}
        for o in valid:
            groups.setdefault(key(o), []).append(o)
        return {k: block(v) for k, v in sorted(groups.items())}

    failures: Dict[str, int] = {}
    for o in rows:
        if not o.success:
            mode = o.failure_mode or 'unclassified'
            failures[mode] = failures.get(mode, 0) + 1
    return {
        'schema_version': 1,
        'success_distance_m': SUCCESS_DISTANCE_M,
        'overall': block(valid),
        'invalid_episodes': len(rows) - len(valid),
        'by_category': grouped(lambda o: o.category),
        'by_scene': grouped(lambda o: o.scene),
        'failure_modes': dict(sorted(failures.items())),
    }
