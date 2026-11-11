import math

import pytest

from neusymnav.evaluation.objectnav_metrics import (bootstrap_ci, classify_failure, path_length,
                                                    score_episode, summarize)

GOAL = (10.0, 0.0, 0.0)


def straight_line_distance(p):
    # A flat empty world: geodesic == euclidean distance to the single view point.
    return math.dist(p, GOAL)


def score(positions, stop=True, **kw):
    return score_episode(uid=kw.pop('uid', 'u'), scene=kw.pop('scene', 's'), category=kw.pop('category', 'chair'),
                         positions=positions, called_stop=stop, distance_to_goal=straight_line_distance,
                         steps=len(positions) - 1, **kw)


def test_optimal_path_scores_one_and_detour_reduces_spl():
    best = score([(0, 0, 0), (5, 0, 0), (9.95, 0, 0)])
    assert best.success and best.spl == pytest.approx(1.0)
    detour = score([(0, 0, 0), (0, 0, 5), (10, 0, 5), (10, 0, 0.05)])
    assert detour.success
    assert detour.spl == pytest.approx(10 / path_length([(0, 0, 0), (0, 0, 5), (10, 0, 5), (10, 0, 0.05)]))


def test_success_needs_stop_and_strictly_below_point_one_metre():
    assert not score([(0, 0, 0), (9.95, 0, 0)], stop=False).success
    boundary = score_episode(uid='u', scene='s', category='c', positions=[(0, 0, 0), (1, 0, 0)],
                             called_stop=True, distance_to_goal=lambda p: 10.0 if p[0] == 0 else 0.1, steps=1)
    assert not boundary.success                                  # exactly 0.1 m: not a success
    near = score([(0, 0, 0), (9.0, 0, 0)])
    assert not near.success and near.spl == 0.0
    assert near.soft_spl == pytest.approx((1 - 1.0 / 10.0) * 1.0)


def test_invalid_start_is_flagged_not_scored():
    out = score_episode(uid='u', scene='s', category='c', positions=[(0, 0, 0)], called_stop=True,
                        distance_to_goal=lambda p: float('inf'), steps=0)
    assert out.failure_mode == 'invalid_episode' and not out.success


def test_failure_classification_order():
    stop_far = score([(0, 0, 0), (2, 0, 0)])
    assert classify_failure(stop_far, stop_near_false_detection=True) == 'wrong_object_stop'
    assert classify_failure(stop_far) == 'stopped_elsewhere'
    assert classify_failure(score([(0, 0, 0), (9.5, 0, 0)])) == 'stopped_too_far'
    no_stop = score([(0, 0, 0), (2, 0, 0)], stop=False)
    assert classify_failure(no_stop, stuck=True) == 'stuck'
    assert classify_failure(no_stop, target_seen=False) == 'never_seen'
    assert classify_failure(no_stop, target_seen=True, target_detected=False) == 'seen_not_detected'
    assert classify_failure(no_stop) == 'budget_exhausted'
    assert classify_failure(score([(0, 0, 0), (9.95, 0, 0)])) is None
    assert classify_failure(score([(0, 0, 0)], stop=False), start_not_navigable=True) == 'start_not_navigable'


def test_summary_groups_excludes_invalid_and_ci_is_deterministic():
    rows = [score([(0, 0, 0), (9.95, 0, 0)], uid='a', category='chair', scene='s1'),
            score([(0, 0, 0), (5, 0, 0)], uid='b', category='bed', scene='s1'),
            score_episode(uid='c', scene='s2', category='bed', positions=[(0, 0, 0)], called_stop=True,
                          distance_to_goal=lambda p: float('inf'), steps=0)]
    s = summarize(rows)
    assert s['overall']['episodes'] == 2 and s['invalid_episodes'] == 1
    assert s['overall']['success_rate'] == pytest.approx(0.5)
    assert s['by_category']['chair']['success_rate'] == 1.0 and s['by_category']['bed']['success_rate'] == 0.0
    assert set(s['by_scene']) == {'s1'}
    assert bootstrap_ci([0, 1, 1, 0, 1], seed=1) == bootstrap_ci([0, 1, 1, 0, 1], seed=1)
    lo, hi = bootstrap_ci([1.0] * 10)
    assert lo == hi == 1.0
