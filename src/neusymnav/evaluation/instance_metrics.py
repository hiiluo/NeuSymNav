"""Deterministic offline instance matching and metric denominator helpers.

This module accepts already prepared IDs, geometric compatibility scores, and
frame-level visibility/matches. It deliberately does not import dataset or
runtime code; semantic ground-truth loading belongs in an offline evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Hashable, Sequence


@dataclass(frozen=True)
class MetricValue:
    """A ratio and the support used to compute it.

    ``value`` is ``None`` when the denominator is zero; ``reason`` then names
    the empty support instead of silently reporting zero or perfect coverage.
    """

    value: float | None
    numerator: int | float
    denominator: int | float
    denominator_name: str
    reason: str | None = None


@dataclass(frozen=True)
class WilsonInterval:
    lower: float | None
    upper: float | None
    successes: int
    trials: int
    reason: str | None = None


def wilson_interval(successes: int, trials: int) -> WilsonInterval:
    """Two-sided 95% Wilson score interval for binary evaluation support."""

    if (
        isinstance(successes, bool) or not isinstance(successes, int)
        or isinstance(trials, bool) or not isinstance(trials, int)
        or successes < 0 or trials < 0 or successes > trials
    ):
        raise ValueError("successes and trials must be valid non-negative counts")
    if trials == 0:
        return WilsonInterval(None, None, successes, trials, "no_trials")
    z = 1.959963984540054
    estimate = successes / trials
    z2_over_n = z * z / trials
    divisor = 1.0 + z2_over_n
    center = (estimate + z2_over_n / 2.0) / divisor
    radius = z * math.sqrt(
        estimate * (1.0 - estimate) / trials + z * z / (4.0 * trials * trials)
    ) / divisor
    return WilsonInterval(max(0.0, center - radius), min(1.0, center + radius), successes, trials)


@dataclass(frozen=True)
class InstanceMatch:
    predicted_id: Hashable
    ground_truth_id: Hashable
    score: float


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[InstanceMatch, ...]
    false_positive_ids: tuple[Hashable, ...]
    false_negative_ids: tuple[Hashable, ...]
    duplicate_prediction_ids: tuple[Hashable, ...]


@dataclass(frozen=True)
class InstanceMetrics:
    matching: MatchResult
    precision: MetricValue
    observed_recall: MetricValue
    coverage: MetricValue
    duplicate_rate: MetricValue


@dataclass(frozen=True)
class FrameMatches:
    """One frame's visible GT instances and one-to-one geometric matches."""

    frame_id: Hashable
    predicted_ids: Sequence[Hashable]
    visible_ground_truth_ids: Sequence[Hashable]
    matches: Sequence[tuple[Hashable, Hashable]]


@dataclass(frozen=True)
class IDF1Result:
    metric: MetricValue
    idtp: int
    idfp: int
    idfn: int
    identity_matches: tuple[InstanceMatch, ...]


def _ids(values: Sequence[Hashable], name: str) -> tuple[Hashable, ...]:
    result = tuple(values)
    try:
        unique_count = len(set(result))
    except TypeError as exc:
        raise ValueError(f"{name} must contain hashable IDs") from exc
    if unique_count != len(result):
        raise ValueError(f"{name} must not contain duplicate IDs")
    return result


def _finite_nonnegative(value: int | float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")


def _ratio(
    numerator: int | float,
    denominator: int | float,
    *,
    denominator_name: str,
    zero_reason: str,
) -> MetricValue:
    _finite_nonnegative(numerator, "numerator")
    _finite_nonnegative(denominator, "denominator")
    if numerator > denominator:
        raise ValueError("ratio numerator must not exceed its denominator")
    if denominator == 0:
        return MetricValue(None, numerator, denominator, denominator_name, zero_reason)
    return MetricValue(float(numerator) / float(denominator), numerator, denominator, denominator_name)


def coverage_ratio(
    covered_units: int | float,
    scope_units: int | float,
    *,
    scope_name: str = "units_in_scope",
) -> MetricValue:
    """Compute coverage against an explicitly declared evaluation scope."""

    if not scope_name:
        raise ValueError("scope_name must be non-empty")
    return _ratio(
        covered_units,
        scope_units,
        denominator_name=scope_name,
        zero_reason="no_units_in_scope",
    )


def _minimum_cost_assignment(costs: Sequence[Sequence[float]]) -> tuple[int, ...]:
    """Return one assigned column per row using the rectangular Hungarian method.

    The caller supplies at least as many columns as rows. Column order is the
    tie-break, making equal-score assignments repeatable for fixed input order.
    """

    row_count = len(costs)
    if row_count == 0:
        return ()
    column_count = len(costs[0])
    if column_count < row_count or any(len(row) != column_count for row in costs):
        raise ValueError("assignment costs must be rectangular with columns >= rows")

    # 1-based form of the shortest augmenting path Hungarian algorithm.
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)
    for row in range(1, row_count + 1):
        p[0] = row
        column0 = 0
        min_value = [math.inf] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[column0] = True
            row0 = p[column0]
            delta = math.inf
            column1 = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                reduced = costs[row0 - 1][column - 1] - u[row0] - v[column]
                if reduced < min_value[column]:
                    min_value[column] = reduced
                    way[column] = column0
                if min_value[column] < delta or (
                    min_value[column] == delta and (column1 == 0 or column < column1)
                ):
                    delta = min_value[column]
                    column1 = column
            for column in range(column_count + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    min_value[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break

    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if p[column] != 0:
            assignment[p[column] - 1] = column - 1
    if any(column < 0 for column in assignment):
        raise RuntimeError("assignment solver failed to assign every row")
    return tuple(assignment)


def match_instances(
    predicted_ids: Sequence[Hashable],
    ground_truth_ids: Sequence[Hashable],
    scores: Sequence[Sequence[float]],
    *,
    minimum_score: float = 0.25,
) -> MatchResult:
    """Match predicted nodes to GT instances one-to-one by maximum total score.

    ``scores[i][j]`` is a caller-computed, non-negative geometric
    compatibility score for prediction ``i`` and GT instance ``j``. Edges
    below ``minimum_score`` are forbidden. Semantic labels are intentionally
    not inputs, so semantic accuracy can be measured after geometric matching.
    """

    predictions = _ids(predicted_ids, "predicted_ids")
    ground_truth = _ids(ground_truth_ids, "ground_truth_ids")
    _finite_nonnegative(minimum_score, "minimum_score")
    matrix = tuple(tuple(float(score) for score in row) for row in scores)
    if len(matrix) != len(predictions):
        raise ValueError("scores must have one row per predicted ID")
    if any(len(row) != len(ground_truth) for row in matrix):
        raise ValueError("scores must have one column per ground-truth ID")
    for row in matrix:
        for score in row:
            _finite_nonnegative(score, "score")

    eligible = tuple(
        tuple(score > 0.0 and score >= minimum_score for score in row)
        for row in matrix
    )
    # One private zero-cost dummy column per prediction allows unmatched FPs.
    # Forbidden GT edges cost +1, so a dummy is always strictly preferable.
    costs = tuple(
        tuple(-score if allowed else 1.0 for score, allowed in zip(row, valid))
        + (0.0,) * len(predictions)
        for row, valid in zip(matrix, eligible)
    )
    assignment = _minimum_cost_assignment(costs)

    matches: list[InstanceMatch] = []
    matched_predictions: set[Hashable] = set()
    matched_ground_truth: set[Hashable] = set()
    for row_index, column_index in enumerate(assignment):
        if column_index >= len(ground_truth) or not eligible[row_index][column_index]:
            continue
        predicted_id = predictions[row_index]
        ground_truth_id = ground_truth[column_index]
        matches.append(InstanceMatch(predicted_id, ground_truth_id, matrix[row_index][column_index]))
        matched_predictions.add(predicted_id)
        matched_ground_truth.add(ground_truth_id)

    return MatchResult(
        matches=tuple(matches),
        false_positive_ids=tuple(item for item in predictions if item not in matched_predictions),
        false_negative_ids=tuple(item for item in ground_truth if item not in matched_ground_truth),
        duplicate_prediction_ids=tuple(
            predictions[row_index]
            for row_index, valid in enumerate(eligible)
            if predictions[row_index] not in matched_predictions
            and any(allowed and ground_truth[column] in matched_ground_truth for column, allowed in enumerate(valid))
        ),
    )


def evaluate_instances(
    predicted_ids: Sequence[Hashable],
    visible_ground_truth_ids: Sequence[Hashable],
    scope_ground_truth_ids: Sequence[Hashable],
    scores: Sequence[Sequence[float]],
    *,
    minimum_score: float = 0.25,
) -> InstanceMetrics:
    """Evaluate active nodes, visible-object recall, and annotated-scope coverage.

    Visible GT IDs define observed recall. ``scope_ground_truth_ids`` defines
    instance coverage and may include annotated objects never observed in the
    logged views. This is object-count coverage, not navigable-area coverage.
    """

    predictions = _ids(predicted_ids, "predicted_ids")
    visible = _ids(visible_ground_truth_ids, "visible_ground_truth_ids")
    scope = _ids(scope_ground_truth_ids, "scope_ground_truth_ids")
    if not set(visible).issubset(scope):
        raise ValueError("visible ground-truth IDs must be included in the declared scope")

    matching = match_instances(predictions, visible, scores, minimum_score=minimum_score)
    true_positives = len(matching.matches)
    return InstanceMetrics(
        matching=matching,
        precision=_ratio(
            true_positives,
            len(predictions),
            denominator_name="predicted_active_nodes",
            zero_reason="no_predicted_instances",
        ),
        observed_recall=_ratio(
            true_positives,
            len(visible),
            denominator_name="visible_ground_truth_instances",
            zero_reason="no_visible_ground_truth_instances",
        ),
        coverage=_ratio(
            true_positives,
            len(scope),
            denominator_name="ground_truth_instances_in_scope",
            zero_reason="no_ground_truth_instances_in_scope",
        ),
        duplicate_rate=MetricValue(
            len(matching.duplicate_prediction_ids) / max(1, true_positives),
            len(matching.duplicate_prediction_ids),
            max(1, true_positives),
            "max_1_matched_predictions",
        ),
    )


def compute_idf1(frames: Sequence[FrameMatches]) -> IDF1Result:
    """Compute IDF1 from one-to-one geometric matches in each observed frame.

    Each frame lists every predicted observation and every visible GT
    observation. Unobserved GT objects are omitted from this denominator.
    Global predicted-to-GT identity correspondence maximizes matched frame
    co-occurrences, as in standard IDF1 accounting.
    """

    frame_ids: set[Hashable] = set()
    total_predicted = 0
    total_ground_truth = 0
    predicted_identity_order: list[Hashable] = []
    ground_truth_identity_order: list[Hashable] = []
    pair_counts: dict[tuple[Hashable, Hashable], int] = {}

    for frame in frames:
        if frame.frame_id in frame_ids:
            raise ValueError("frame IDs must be unique")
        frame_ids.add(frame.frame_id)
        predictions = _ids(frame.predicted_ids, "frame predicted_ids")
        visible = _ids(frame.visible_ground_truth_ids, "frame visible_ground_truth_ids")
        total_predicted += len(predictions)
        total_ground_truth += len(visible)
        prediction_set = set(predictions)
        visible_set = set(visible)
        matched_predictions: set[Hashable] = set()
        matched_ground_truth: set[Hashable] = set()
        for pair in frame.matches:
            if len(pair) != 2:
                raise ValueError("each frame match must be a (predicted_id, ground_truth_id) pair")
            predicted_id, ground_truth_id = pair
            if predicted_id not in prediction_set or ground_truth_id not in visible_set:
                raise ValueError("frame matches must refer to listed predictions and visible GT IDs")
            if predicted_id in matched_predictions or ground_truth_id in matched_ground_truth:
                raise ValueError("frame matches must be one-to-one")
            matched_predictions.add(predicted_id)
            matched_ground_truth.add(ground_truth_id)
            pair_counts[(predicted_id, ground_truth_id)] = pair_counts.get((predicted_id, ground_truth_id), 0) + 1
            if predicted_id not in predicted_identity_order:
                predicted_identity_order.append(predicted_id)
            if ground_truth_id not in ground_truth_identity_order:
                ground_truth_identity_order.append(ground_truth_id)

    count_matrix = tuple(
        tuple(float(pair_counts.get((predicted_id, ground_truth_id), 0)) for ground_truth_id in ground_truth_identity_order)
        for predicted_id in predicted_identity_order
    )
    identity_matching = match_instances(
        predicted_identity_order,
        ground_truth_identity_order,
        count_matrix,
        minimum_score=1.0,
    )
    idtp = sum(int(match.score) for match in identity_matching.matches)
    idfp = total_predicted - idtp
    idfn = total_ground_truth - idtp
    numerator = 2 * idtp
    denominator = numerator + idfp + idfn
    metric = _ratio(
        numerator,
        denominator,
        denominator_name="2*IDTP + IDFP + IDFN",
        zero_reason="no_prediction_or_ground_truth_observations",
    )
    return IDF1Result(metric, idtp, idfp, idfn, identity_matching.matches)
