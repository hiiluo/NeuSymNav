"""Offline geometry quality against explicitly observed GT support.

No runtime or dataset loader is imported here. Callers own annotation provenance,
coordinate/unit validation and selection of the observed-support GT subset. These
metrics do not measure whole-scene coverage. Point scores describe supplied sampled
surfaces on geometrically matched objects, not unseen annotated surfaces or FPs/FNs.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

import numpy as np
from scipy.spatial import cKDTree

from .instance_metrics import match_instances
from .metrics import aabb_iou, aabb_xy_iou, ratio


def _entries(entries, name):
    result = {}
    for item in entries:
        if not isinstance(item, Mapping):
            raise ValueError(f"{name} entries must be mappings")
        identity = item.get("id")
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"{name} IDs must be nonempty strings")
        if identity in result:
            raise ValueError(f"{name} contains duplicate IDs")
        label = item.get("label")
        if label is not None and not isinstance(label, str):
            raise ValueError(f"{name} labels must be strings or null")
        try:
            bounds = np.asarray(item.get("bounds"), dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} bounds must be numeric 2x3 arrays") from exc
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1] < bounds[0]):
            raise ValueError(f"{name} bounds must be finite ordered 2x3 arrays")
        points = item.get("points")
        if points is not None:
            try:
                points = np.asarray(points, dtype=float)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} points must be numeric Nx3 arrays") from exc
            if points.shape == (0,):
                points = points.reshape(0, 3)
            if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
                raise ValueError(f"{name} points must be finite Nx3 arrays")
        result[identity] = {"label": label, "bounds": bounds, "points": points}
    return result


def _summary(values, *, mean=False):
    return dict(
        **({"mean": float(np.mean(values)) if values else None} if mean else {}),
        median=float(np.median(values)) if values else None,
        **({} if mean else {"p95": float(np.percentile(values, 95)) if values else None}),
        support=len(values),
    )


def _unavailable(reason, *, support=0):
    return dict(value=None, support=support, reason=reason)


def _pointcloud(matches, predictions, ground_truth, tolerance):
    pairs = []
    predicted_count = truth_count = predicted_hits = truth_hits = complete_pairs = 0
    for match in matches:
        predicted = predictions[match.predicted_id]["points"]
        truth = ground_truth[match.ground_truth_id]["points"]
        p_count = 0 if predicted is None else len(predicted)
        g_count = 0 if truth is None else len(truth)
        predicted_count += p_count
        truth_count += g_count
        pair = dict(predicted_id=match.predicted_id, ground_truth_id=match.ground_truth_id,
                    prediction_points=p_count, ground_truth_points=g_count)
        if not p_count or not g_count:
            pair.update(available=False, reason="missing_or_empty_matched_cloud")
        else:
            p_hits = int(np.count_nonzero(cKDTree(truth).query(predicted)[0] <= tolerance))
            g_hits = int(np.count_nonzero(cKDTree(predicted).query(truth)[0] <= tolerance))
            predicted_hits += p_hits
            truth_hits += g_hits
            complete_pairs += 1
            precision = p_hits / p_count
            recall = g_hits / g_count
            pair.update(available=True, reason=None,
                        precision=precision, recall=recall,
                        f1=2 * precision * recall / (precision + recall) if precision + recall else 0,
                        prediction_points_within_tolerance=p_hits,
                        ground_truth_points_within_tolerance=g_hits)
        pairs.append(pair)
    reason = "no_geometric_matches" if not matches else (
        "missing_or_empty_matched_cloud" if complete_pairs != len(matches) else None)
    result = dict(available=reason is None, reason=reason, matched_pairs=len(matches),
                  pairs_with_clouds=complete_pairs, prediction_points=predicted_count,
                  ground_truth_points=truth_count, pairs=pairs,
                  aggregation="micro pooled directional nearest-neighbor counts across all matched pairs",
                  scope="supplied sampled surfaces of matched observed-support objects only; excludes unmatched objects and unseen surfaces")
    if reason:
        result.update(precision=_unavailable(reason, support=predicted_count),
                      recall=_unavailable(reason, support=truth_count),
                      f1=_unavailable(reason, support=predicted_count + truth_count))
    else:
        precision = ratio(predicted_hits, predicted_count, denominator_name="all matched predicted points")
        recall = ratio(truth_hits, truth_count, denominator_name="all matched ground-truth points")
        p, r = precision["value"], recall["value"]
        result.update(precision=precision, recall=recall,
                      f1=dict(value=2 * p * r / (p + r) if p + r else 0,
                              support=predicted_count + truth_count, reason=None,
                              definition="harmonic mean of micro point precision and recall"))
    return result


def _evaluate_view(predictions, ground_truth, threshold, tolerance, *, footprint):
    prediction_ids = tuple(predictions)
    ground_truth_ids = tuple(ground_truth)
    dimensions = 2 if footprint else 3
    scores = []
    for predicted in predictions.values():
        row = []
        for truth in ground_truth.values():
            bounds = (predicted["bounds"], truth["bounds"])
            if any(np.any(item[1, :dimensions] == item[0, :dimensions]) for item in bounds):
                row.append(0.0)
            else:
                score = (aabb_xy_iou if footprint else aabb_iou)(*bounds)
                if not math.isfinite(score):
                    raise ValueError("bounds exceed numerical range for IoU")
                row.append(score)
        scores.append(row)
    matching = match_instances(prediction_ids, ground_truth_ids, scores, minimum_score=threshold)
    matches = []
    correct_labels = labeled_gt_pairs = 0
    for match in matching.matches:
        predicted = predictions[match.predicted_id]
        truth = ground_truth[match.ground_truth_id]
        # Half-before-sum avoids overflowing the midpoint of large finite bounds.
        p_center = predicted["bounds"][0] / 2 + predicted["bounds"][1] / 2
        g_center = truth["bounds"][0] / 2 + truth["bounds"][1] / 2
        center_error = math.dist(p_center, g_center)
        if not math.isfinite(center_error):
            raise ValueError("bounds exceed numerical range for center distance")
        matches.append(dict(predicted_id=match.predicted_id, ground_truth_id=match.ground_truth_id,
                            iou=match.score, center_error_m=center_error))
        if truth["label"] is not None:
            labeled_gt_pairs += 1
            correct_labels += predicted["label"] is not None and predicted["label"] == truth["label"]
    tp, fp, fn = len(matches), len(matching.false_positive_ids), len(matching.false_negative_ids)
    duplicates = len(matching.duplicate_prediction_ids)
    duplicate_metric = dict(value=duplicates / tp if tp else None, numerator=duplicates,
                            denominator=tp, denominator_name="geometrically matched ground-truth instances",
                            support=tp, reason=None if tp else "no_geometric_matches")
    return dict(tp=tp, fp=fp, fn=fn, prediction_count=len(predictions), observed_gt_count=len(ground_truth),
                metric="aabb_xy_footprint_iou" if footprint else "aabb_volume_iou",
                precision=ratio(tp, tp + fp, denominator_name="predicted instances"),
                observed_recall=ratio(tp, tp + fn, denominator_name="observed-support ground-truth instances"),
                f1=ratio(2 * tp, 2 * tp + fp + fn, denominator_name="2*TP + FP + FN"),
                matches=matches, false_positive_ids=list(matching.false_positive_ids),
                false_negative_ids=list(matching.false_negative_ids),
                duplicate_prediction_ids=list(matching.duplicate_prediction_ids), duplicate_count=duplicates,
                duplicates_per_matched_gt=duplicate_metric,
                label_accuracy=ratio(correct_labels, labeled_gt_pairs,
                                     denominator_name="geometric matches with non-null GT raw labels; null predictions incorrect"),
                label_policy="exact raw string equality; literal unknown is a string, null GT labels omitted",
                center_error_m=_summary([match["center_error_m"] for match in matches]),
                center_error_dimensions="3D AABB centers, including for footprint matching",
                matched_iou=_summary([match["iou"] for match in matches], mean=True),
                pointcloud=_pointcloud(matching.matches, predictions, ground_truth, tolerance))


def evaluate_geometry(predictions, ground_truth, *, iou_threshold=0.25, point_tolerance_m=0.05):
    """Evaluate class-independent 3D volume and XY footprint matching separately.

    Entries have ``id``, optional nullable ``label``, ``bounds`` (2x3 metre-space
    canonical AABB), and optional ``points`` (Nx3). IDs must be unique on each
    side. Degenerate boxes remain in FP/FN denominators with zero score for the
    affected dimensions. GT must already be the observed-support subset.

    Matches use the existing maximum-total-IoU assignment, with positive scores
    >= the threshold. Label accuracy uses non-null GT labels on those matches;
    null predicted labels are incorrect. Median/p95 center errors use 3D centers.
    Point tolerance uses inclusive Euclidean distance in 3D; no surface completion
    or voxel weighting is implied. Pointcloud F1 is the harmonic mean of pooled
    directional point precision/recall, unavailable if any matched cloud is absent
    or empty. Zero-denominator metrics are null rather than a perfect score.
    """
    if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, (int, float)) or not math.isfinite(iou_threshold) or not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold must be finite in [0, 1]")
    if isinstance(point_tolerance_m, bool) or not isinstance(point_tolerance_m, (int, float)) or not math.isfinite(point_tolerance_m) or point_tolerance_m <= 0:
        raise ValueError("point_tolerance_m must be finite and positive")
    predictions = _entries(predictions, "predictions")
    ground_truth = _entries(ground_truth, "ground_truth")
    return dict(volume=_evaluate_view(predictions, ground_truth, iou_threshold, point_tolerance_m, footprint=False),
                footprint=_evaluate_view(predictions, ground_truth, iou_threshold, point_tolerance_m, footprint=True),
                iou_threshold=iou_threshold, point_tolerance_m=point_tolerance_m,
                scope="caller-supplied observed-support GT subset; whole-scene coverage is computed separately")
