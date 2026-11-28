import numpy as np

from tools.psg_nav.qualify_identity_cohort import qualify_frames


def instance(object_id, label, pixels):
    return {"id": object_id, "label": label, "mask": np.array([pixels], dtype=bool)}


def frame(frame_id, gt, pred, status="complete"):
    return {"frame_id": frame_id, "gt": gt, "pred": pred, "status": status}


def test_matches_physical_tracks_without_using_category_or_predicted_identity():
    chair = instance("physical-chair", "chair", [1, 1, 0, 0])
    nearby = instance("physical-nearby", "armchair", [0, 0, 1, 1])
    result = qualify_frames([
        frame("rgbd:0", [chair, nearby], [
            instance("0", "chair", [1, 1, 0, 0]),
            instance("1", "armchair", [0, 0, 1, 1]),
        ]),
        frame("rgbd:7", [chair], [instance("9", "sofa", [1, 1, 0, 0])]),
    ], min_mask_iou=0.5)

    assert result["unique_tracks"] == 2
    assert result["matched_observations"] == 3
    assert result["category_flip_tracks"] == {
        "physical-chair": [
            {"frame_id": "rgbd:0", "detection_id": "0", "label": "chair", "mask_iou": 1.0},
            {"frame_id": "rgbd:7", "detection_id": "9", "label": "sofa", "mask_iou": 1.0},
        ]
    }


def test_rejects_competing_pairs_and_reports_missing_frames():
    chair = instance("physical-chair", "chair", [1, 1])
    result = qualify_frames([
        frame("rgbd:1", [chair], [
            instance("0", "chair", [1, 1]),
            instance("1", "sofa", [1, 0]),
        ]),
        frame("rgbd:2", [chair], [], status="missing"),
    ], min_mask_iou=0.5)

    assert result["ambiguous_candidate_pairs"] == 2
    assert result["matched_observations"] == 0
    assert result["missing_prediction_frames"] == 1
    assert result["category_flip_tracks"] == {}
