"""Offline metrics with hand-derived geometric and point-support oracles."""

import math

import pytest

from neusymnav.evaluation.geometry_quality import evaluate_geometry


def box(identity, *, bounds=None, label="chair", points=None):
    result = {"id": identity, "label": label,
              "bounds": bounds if bounds is not None else [[0, 0, 0], [1, 1, 1]]}
    if points is not None:
        result["points"] = points
    return result


def test_perfect_geometry_and_cloud_have_explicit_support():
    result = evaluate_geometry([box("p", points=[[0, 0, 0], [1, 1, 1]])],
                               [box("g", points=[[0, 0, 0], [1, 1, 1]])])
    for view in (result["volume"], result["footprint"]):
        assert (view["tp"], view["fp"], view["fn"]) == (1, 0, 0)
        assert view["precision"]["value"] == view["observed_recall"]["value"] == 1
        assert view["f1"]["value"] == view["label_accuracy"]["value"] == 1
        assert view["center_error_m"] == {"median": 0, "p95": 0, "support": 1}
        assert view["matched_iou"] == {"mean": 1, "median": 1, "support": 1}
        assert view["pointcloud"]["precision"]["denominator"] == 2
        assert view["pointcloud"]["recall"]["denominator"] == 2
        assert view["pointcloud"]["f1"]["value"] == 1


def test_shifted_geometry_remains_fp_fn_without_label_gating():
    result = evaluate_geometry([box("p", bounds=[[2, 0, 0], [3, 1, 1]])], [box("g")])
    assert (result["volume"]["tp"], result["volume"]["fp"], result["volume"]["fn"]) == (0, 1, 1)
    assert result["volume"]["f1"]["value"] == 0
    assert result["volume"]["matched_iou"]["mean"] is None
    wrong_class = evaluate_geometry([box("p", label="table")], [box("g")])["volume"]
    assert wrong_class["tp"] == 1
    assert wrong_class["label_accuracy"]["value"] == 0


def test_iou_and_center_error_have_known_numerical_values():
    result = evaluate_geometry([box("p", bounds=[[0.5, 0, 0], [1.5, 1, 1]])], [box("g")])
    assert result["volume"]["matched_iou"]["mean"] == pytest.approx(1 / 3)
    assert result["volume"]["center_error_m"]["median"] == pytest.approx(0.5)
    assert evaluate_geometry([box("p", bounds=[[0.5, 0, 0], [1.5, 1, 1]])],
                             [box("g")], iou_threshold=0.5)["volume"]["tp"] == 0


def test_degenerate_volume_can_have_valid_xy_footprint():
    flat = [[0, 0, 0], [1, 1, 0]]
    result = evaluate_geometry([box("p", bounds=flat)], [box("g", bounds=flat)])
    assert (result["volume"]["tp"], result["volume"]["fp"], result["volume"]["fn"]) == (0, 1, 1)
    assert result["footprint"]["tp"] == 1
    assert result["footprint"]["matched_iou"]["mean"] == 1


def test_duplicates_are_excess_predictions_per_matched_gt_not_a_fraction():
    result = evaluate_geometry([box("p0"), box("p1"), box("p2")], [box("g")])["volume"]
    assert (result["tp"], result["fp"], result["fn"]) == (1, 2, 0)
    assert result["precision"]["value"] == pytest.approx(1 / 3)
    assert result["f1"]["value"] == 0.5
    assert result["duplicates_per_matched_gt"]["value"] == 2
    assert result["duplicates_per_matched_gt"]["denominator"] == 1
    assert len(result["duplicate_prediction_ids"]) == 2


def test_point_outlier_degrades_precision_but_not_recall():
    result = evaluate_geometry([box("p", points=[[0, 0, 0], [10, 0, 0]])],
                               [box("g", points=[[0, 0, 0]])])["volume"]["pointcloud"]
    assert result["precision"]["value"] == 0.5
    assert result["recall"]["value"] == 1
    assert result["f1"]["value"] == pytest.approx(2 / 3)
    assert result["pairs"][0]["prediction_points"] == 2


def test_point_tolerance_is_inclusive_and_uses_3d_distance():
    result = evaluate_geometry([box("p", points=[[0, 0, 0.05]])],
                               [box("g", points=[[0, 0, 0]])])["volume"]["pointcloud"]
    assert result["f1"]["value"] == 1
    result = evaluate_geometry([box("p", points=[[0, 0, 0.051]])],
                               [box("g", points=[[0, 0, 0]])])["volume"]["pointcloud"]
    assert result["f1"]["value"] == 0


def test_missing_one_matched_cloud_does_not_select_favorable_subset():
    far = [[2, 0, 0], [3, 1, 1]]
    result = evaluate_geometry([box("p", points=[[0, 0, 0]]), box("p2", bounds=far)],
                               [box("g", points=[[0, 0, 0]]), box("g2", bounds=far, points=[[2, 0, 0]])])
    cloud = result["volume"]["pointcloud"]
    assert not cloud["available"]
    assert cloud["matched_pairs"] == 2
    assert cloud["pairs_with_clouds"] == 1
    assert cloud["precision"]["value"] is None
    assert cloud["recall"]["value"] is None
    assert cloud["f1"]["value"] is None


def test_cloud_aggregate_pools_point_counts_instead_of_averaging_pairs():
    far = [[2, 0, 0], [3, 1, 1]]
    result = evaluate_geometry(
        [box("p1", points=[[0, 0, 0]]),
         box("p2", bounds=far, points=[[2, 0, 0], [10, 0, 0], [20, 0, 0]])],
        [box("g1", points=[[0, 0, 0]]), box("g2", bounds=far, points=[[2, 0, 0]])])
    cloud = result["volume"]["pointcloud"]
    assert cloud["precision"]["numerator"] == 2
    assert cloud["precision"]["denominator"] == 4
    assert cloud["precision"]["value"] == 0.5
    assert cloud["recall"]["value"] == 1
    assert cloud["f1"]["value"] == pytest.approx(2 / 3)


def test_vertical_separation_keeps_xy_diagnostic_independent_of_volume():
    result = evaluate_geometry([box("p", bounds=[[0, 0, 2], [1, 1, 3]])], [box("g")])
    assert result["volume"]["tp"] == 0
    assert result["footprint"]["tp"] == 1
    assert result["footprint"]["center_error_m"]["median"] == 2


def test_center_p95_is_computed_over_matched_objects():
    result = evaluate_geometry(
        [box("p1"), box("p2", bounds=[[2.5, 0, 0], [3.5, 1, 1]])],
        [box("g1"), box("g2", bounds=[[2, 0, 0], [3, 1, 1]])])
    center = result["volume"]["center_error_m"]
    assert center["median"] == 0.25
    assert center["p95"] == pytest.approx(0.475)
    assert center["support"] == 2


@pytest.mark.parametrize("points", [None, []])
def test_empty_cloud_is_unavailable(points):
    result = evaluate_geometry([box("p", points=points)], [box("g", points=[[0, 0, 0]])])
    assert not result["volume"]["pointcloud"]["available"]


def test_no_gt_support_preserves_false_positive_penalty():
    result = evaluate_geometry([box("p")], [])["volume"]
    assert (result["tp"], result["fp"], result["fn"]) == (0, 1, 0)
    assert result["precision"]["value"] == 0
    assert result["observed_recall"]["value"] is None
    assert result["f1"]["value"] == 0
    assert result["duplicates_per_matched_gt"]["value"] is None
    missing = evaluate_geometry([], [box("g")])["volume"]
    assert missing["precision"]["value"] is None
    assert missing["observed_recall"]["value"] == 0
    assert missing["f1"]["value"] == 0
    empty = evaluate_geometry([], [])["volume"]
    assert empty["f1"]["value"] is None
    assert empty["precision"]["value"] is None
    assert empty["observed_recall"]["value"] is None
    assert not empty["pointcloud"]["available"]


def test_null_prediction_is_incorrect_and_null_gt_is_unlabeled():
    assert evaluate_geometry([box("p", label=None)], [box("g")])["volume"]["label_accuracy"]["value"] == 0
    assert evaluate_geometry([box("p", label=None)], [box("g", label=None)])["volume"]["label_accuracy"]["value"] is None
    assert evaluate_geometry([box("p", label="unknown")], [box("g")])["volume"]["label_accuracy"]["value"] == 0


@pytest.mark.parametrize("bounds", [
    [[1, 0, 0], [0, 1, 1]], [[0, 0, 0], [math.inf, 1, 1]],
    [[0, 0, 0], [math.nan, 1, 1]], [[0, 0], [1, 1]],
])
def test_invalid_bounds_rejected(bounds):
    with pytest.raises(ValueError):
        evaluate_geometry([box("p", bounds=bounds)], [box("g")])


@pytest.mark.parametrize("side", ["prediction", "ground_truth"])
def test_duplicate_ids_rejected_per_side(side):
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_geometry([box("p"), box("p")] if side == "prediction" else [box("p")],
                          [box("g"), box("g")] if side == "ground_truth" else [box("g")])


@pytest.mark.parametrize("kwargs", [
    {"iou_threshold": -0.1}, {"iou_threshold": 1.1}, {"iou_threshold": math.nan},
    {"point_tolerance_m": 0}, {"point_tolerance_m": -1}, {"point_tolerance_m": math.inf},
])
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValueError):
        evaluate_geometry([], [], **kwargs)


@pytest.mark.parametrize("points", [[[math.nan, 0, 0]], [[0, 1]], [1, 2, 3]])
def test_invalid_point_cloud_rejected(points):
    with pytest.raises(ValueError):
        evaluate_geometry([box("p", points=points)], [box("g")])
