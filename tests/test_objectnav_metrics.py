import math

import pytest

from neusymnav.evaluation.objectnav_metrics import (bootstrap_ci, classify_failure, path_length,
                                                    score_episode, snap_view_points, summarize)

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


def test_oracle_success_counts_passing_a_view_point_without_changing_success():
    # Drives through the goal (9.95 m) and comes back without STOP: oracle yes, success no.
    passed = score([(0, 0, 0), (9.95, 0, 0), (5, 0, 0)], stop=False)
    assert passed.oracle_success and not passed.success and passed.spl == 0.0
    assert passed.dtg_min_m == pytest.approx(0.05) and passed.dtg_min_step == 1
    # Stops beyond the goal after passing it: still a failure, oracle yes.
    overshoot = score([(0, 0, 0), (9.95, 0, 0), (9.5, 0, 0)])
    assert overshoot.oracle_success and not overshoot.success
    # Never within 0.1 m (boundary is strict, like success).
    near = score_episode(uid='u', scene='s', category='c', positions=[(0, 0, 0), (1, 0, 0)],
                         called_stop=True, distance_to_goal=lambda p: 10.0 if p[0] == 0 else 0.1, steps=1)
    assert not near.oracle_success and near.dtg_min_m == pytest.approx(0.1)
    # A success is always an oracle success.
    assert score([(0, 0, 0), (9.95, 0, 0)]).oracle_success


def test_oracle_distance_queried_once_per_distinct_position():
    calls = []

    def counted(p):
        calls.append(tuple(p))
        return straight_line_distance(p)

    score_episode(uid='u', scene='s', category='c', positions=[(0, 0, 0)] * 50 + [(1, 0, 0)] * 50,
                  called_stop=False, distance_to_goal=counted, steps=99)
    assert sorted(calls) == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]


def test_summary_reports_oracle_rate_and_reached_without_success():
    rows = [score([(0, 0, 0), (9.95, 0, 0)], uid='a'),                      # success
            score([(0, 0, 0), (9.95, 0, 0), (5, 0, 0)], stop=False, uid='b'),  # passed, no STOP
            score([(0, 0, 0), (5, 0, 0)], uid='c')]                          # never close
    o = summarize(rows)['overall']
    assert o['success_rate'] == pytest.approx(1 / 3)
    assert o['oracle_success_rate'] == pytest.approx(2 / 3)
    assert o['oracle_not_success'] == 1
    assert o['dtg_min_m'] == pytest.approx((0.05 + 0.05 + 5.0) / 3)
    assert summarize(rows)['schema_version'] == 3
    assert summarize(rows)['view_point_rule']['name'] == 'snap-to-scorer-navmesh-v1'
    assert o['oracle_within_m'] == {'0.1': pytest.approx(2 / 3), '0.25': pytest.approx(2 / 3),
                                    '0.5': pytest.approx(2 / 3), '1': pytest.approx(2 / 3)}


def test_view_points_snap_onto_scorer_navmesh_only_within_the_rule():
    floor_y = 0.15                       # scorer navmesh 0.15 m above the stored view points

    def snap(p):
        if p[0] > 50:                    # no navmesh there
            return (float('nan'),) * 3
        if p[0] > 20:                    # navmesh only 0.2 m to the side
            return (p[0] + 0.2, floor_y, p[2])
        if p[0] > 10:                    # another floor
            return (p[0], p[1] + 2.5, p[2])
        return (p[0] + 0.03, floor_y, p[2])

    raw = [(1.0, 0.0, 0.0), (15.0, 0.0, 0.0), (25.0, 0.0, 0.0), (60.0, 0.0, 0.0)]
    targets, n = snap_view_points(raw, snap)
    assert n == 1
    assert targets[0] == pytest.approx([1.03, 0.15, 0.0])
    assert targets[1:] == [list(v) for v in raw[1:]]      # kept raw


def test_snapped_view_point_removes_height_gap_from_dtg():
    # Robot stands on the navmesh exactly above a view point stored 0.15 m lower.
    vp = (5.0, 0.0, 0.0)
    targets, _ = snap_view_points([vp], lambda p: (p[0], 0.15, p[2]))
    dist = lambda goal: (lambda p: math.dist(p, goal))
    before = score_episode(uid='u', scene='s', category='c', positions=[(0, 0.15, 0), (5.0, 0.15, 0)],
                           called_stop=True, distance_to_goal=dist(vp), steps=1)
    after = score_episode(uid='u', scene='s', category='c', positions=[(0, 0.15, 0), (5.0, 0.15, 0)],
                          called_stop=True, distance_to_goal=dist(tuple(targets[0])), steps=1)
    assert not before.success and before.dtg_end_m == pytest.approx(0.15)
    assert after.success and after.dtg_end_m == pytest.approx(0.0)
