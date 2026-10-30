"""Hand-computed offline detection quality examples; no model/runtime needed."""

from copy import deepcopy
import json

import pytest


def evaluate(frames, **kwargs):
    from neusymnav.evaluation.detection_quality import evaluate_detection

    return evaluate_detection(frames, **kwargs)


def obj(id="g", label="chair", bbox=None, **kwargs):
    return {"id": id, "label": label, "bbox": bbox or [0, 0, 2, 2], **kwargs}


def frame(gt=None, pred=None, id="f"):
    return {"frame_id": id, "gt": [] if gt is None else gt,
            "pred": [] if pred is None else pred}


def test_perfect_detection_has_explicit_support_and_ap():
    result = evaluate([frame([obj()], [obj("p", score=.9)])])
    point = result["operating_point"]
    assert (point["tp"], point["fp"], point["fn"]) == (1, 0, 0)
    assert (point["precision"], point["recall"], point["f1"]) == (1, 1, 1)
    assert result["support"] == {
        "frames": 1, "frames_with_gt": 1, "ground_truth": 1,
        "predictions": 1, "predictions_at_operating_point": 1,
        "classes_with_gt": 1,
    }
    assert result["bbox_ap"]["ap50_95"] == 1
    assert result["bbox_ap"]["ap50"] == 1
    assert result["bbox_ap"]["ap75"] == 1
    assert result["mask_ap"]["available"] is False
    assert result["mask_ap"]["missing_gt_masks"] == 1
    assert result["mask_ap"]["missing_prediction_masks"] == 1
    json.dumps(result, allow_nan=False)


def test_duplicate_prediction_is_false_positive():
    result = evaluate([frame([obj()], [obj("p", score=.9), obj("duplicate", score=.8)])])
    point = result["operating_point"]
    assert (point["tp"], point["fp"], point["fn"]) == (1, 1, 0)
    assert point["precision"] == .5
    assert point["f1"] == pytest.approx(2 / 3)
    assert result["bbox_ap"]["ap50"] == 1


def test_wrong_class_is_false_positive_and_false_negative():
    result = evaluate([frame([obj()], [obj("p", "table", score=.9)])])
    point = result["operating_point"]
    assert (point["tp"], point["fp"], point["fn"]) == (0, 1, 1)
    assert point["per_class"]["chair"]["fn"] == 1
    assert point["per_class"]["table"]["fp"] == 1
    assert point["per_class"]["table"]["recall"] is None
    assert result["bbox_ap"]["per_class"]["table"]["ap50"] is None
    assert result["bbox_ap"]["ap50"] == 0


def test_missing_prediction_frame_remains_in_recall_and_ap_denominator():
    result = evaluate([frame([obj()], [obj("p", score=.9)]),
                       frame([obj()], id="missing"), frame(id="empty")])
    assert result["operating_point"]["recall"] == .5
    assert result["operating_point"]["fn"] == 1
    assert result["bbox_ap"]["ap50"] == pytest.approx(51 / 101)
    assert result["support"]["frames"] == 3


def test_ap_confidence_ranking_is_global_across_frames():
    result = evaluate([frame([obj()], [obj("tp", score=.8)]),
                       frame(pred=[obj("fp", score=.9)], id="empty")])
    assert result["bbox_ap"]["ap50"] == .5


def test_ap_averages_only_gt_supported_classes():
    result = evaluate([frame([obj(), obj("g2", "table")],
                             [obj("p", score=.9), obj("ghost", "lamp", score=.8)])])
    assert result["bbox_ap"]["ap50"] == .5
    assert result["bbox_ap"]["per_class"]["lamp"]["ap50"] is None
    assert result["bbox_ap"]["per_class"]["lamp"]["predictions"] == 1
    assert result["support"]["classes_with_gt"] == 2


def test_localization_changes_ap_at_each_iou_threshold():
    result = evaluate([frame([obj()], [obj("p", bbox=[0, 0, 3, 2], score=.9)])])
    assert result["bbox_ap"]["ap50"] == 1
    assert result["bbox_ap"]["ap75"] == 0
    assert result["bbox_ap"]["ap50_95"] == .4


def test_confidence_and_iou_thresholds_are_inclusive_and_ap_keeps_low_scores():
    result = evaluate([frame([obj()], [obj("p", bbox=[0, 0, 4, 2], score=.25)])])
    assert result["operating_point"]["tp"] == 1
    excluded = evaluate([frame([obj()], [obj("p", score=.249)])])
    assert excluded["operating_point"]["fn"] == 1
    assert excluded["operating_point"]["precision"] is None
    assert excluded["bbox_ap"]["ap50"] == 1


def test_greedy_matching_uses_confidence_best_iou_and_stable_id_ties():
    gt = [obj("a"), obj("b", bbox=[1, 0, 3, 2])]
    pred = [obj("high", bbox=[.5, 0, 2.5, 2], score=.9), obj("low", score=.8)]
    result = evaluate([frame(gt, pred)])
    assert (result["operating_point"]["tp"], result["operating_point"]["fp"]) == (1, 1)
    assert evaluate([frame(list(reversed(gt)), list(reversed(pred)))]) == result


def test_score_ties_use_frame_and_prediction_ids_independent_of_source_order():
    inputs = [frame([obj()], [obj("p", score=.8)], id="z"),
              frame(pred=[obj("p", score=.8)], id="a")]
    result = evaluate(inputs)
    assert result["bbox_ap"]["ap50"] == .5
    assert evaluate(list(reversed(inputs))) == result


def test_mask_ap_is_separate_from_bbox_ap():
    result = evaluate([frame([obj(mask=[[True, False]])],
                             [obj("p", score=.9, mask=[[False, True]])])])
    assert result["bbox_ap"]["ap50_95"] == 1
    assert result["mask_ap"]["available"] is True
    assert result["mask_ap"]["ap50_95"] == 0


def test_complete_masks_match_and_empty_prediction_masks_do_not():
    result = evaluate([frame([obj(mask=[[True, False]])],
                             [obj("p", score=.9, mask=[[True, False]])])])
    assert result["mask_ap"]["ap50_95"] == 1
    result = evaluate([frame([obj(mask=[[True, False]])],
                             [obj("p", score=.9, mask=[[False, False]])])])
    assert result["mask_ap"]["ap50_95"] == 0


def test_partial_masks_disable_whole_mask_metric_without_dropping_gt():
    result = evaluate([frame([obj(mask=[[True]]), obj("missing")],
                             [obj("p", score=.9, mask=[[True]])])])
    assert result["mask_ap"]["available"] is False
    assert result["mask_ap"]["reason"] == "incomplete_masks"
    assert result["mask_ap"]["ap50"] is None
    assert result["mask_ap"]["per_class"]["chair"]["ground_truth"] == 2


@pytest.mark.parametrize("frames,precision,recall,f1", [
    ([], None, None, None),
    ([frame()], None, None, None),
    ([frame([obj()])], None, 0, 0),
    ([frame(pred=[obj("p", score=.9)])], 0, None, 0),
])
def test_zero_support_is_explicit(frames, precision, recall, f1):
    result = evaluate(frames)
    point = result["operating_point"]
    assert (point["precision"], point["recall"], point["f1"]) == (precision, recall, f1)
    assert result["bbox_ap"]["ap50"] == (0 if recall == 0 else None)


@pytest.mark.parametrize("box", [[0, 0, 0, 1], [1, 0, 0, 1], [0, 0, 1],
                                  [0, 0, float("nan"), 1], [0, 0, float("inf"), 1],
                                  [False, 0, 1, 1], ["0", 0, 1, 1]])
def test_rejects_malformed_boxes(box):
    with pytest.raises(ValueError):
        evaluate([frame([obj(bbox=box)])])


@pytest.mark.parametrize("mask", [[], [[]], [[1]], [[True], [True, False]],
                                   [True], "mask", [[None]]])
def test_rejects_malformed_masks(mask):
    with pytest.raises(ValueError):
        evaluate([frame([obj(mask=mask)])])


@pytest.mark.parametrize("score", [-.1, 1.1, float("nan"), float("inf"), True, ".9", None])
def test_rejects_malformed_scores(score):
    with pytest.raises(ValueError):
        evaluate([frame(pred=[obj("p", score=score)])])


@pytest.mark.parametrize("kwargs", [{"iou_threshold": 0}, {"iou_threshold": 1.1},
                                     {"iou_threshold": True},
                                     {"confidence_threshold": -.1},
                                     {"confidence_threshold": float("nan")}])
def test_rejects_invalid_thresholds(kwargs):
    with pytest.raises(ValueError):
        evaluate([], **kwargs)


@pytest.mark.parametrize("inputs", [None, {}, [None], [{}],
    [frame(), frame()], [frame([obj(), obj()])],
    [frame(pred=[obj("p", score=.9), obj("p", score=.8)])],
    [frame([obj(id="")])], [frame([obj(label="")])],
    [{"frame_id": 2, "gt": [], "pred": []}],
    [{"frame_id": "f", "gt": {}, "pred": []}],
    [frame([obj(mask=[[True]])], [obj("p", score=.9, mask=[[True, False]])])],
    [frame(pred=[obj("p")])],
])
def test_rejects_invalid_frame_or_observation_structure(inputs):
    with pytest.raises(ValueError):
        evaluate(inputs)


def test_evaluation_does_not_mutate_caller_inputs():
    inputs = [frame([obj(mask=[[True]])], [obj("p", score=.9, mask=[[True]])])]
    original = deepcopy(inputs)
    evaluate(inputs)
    assert inputs == original
