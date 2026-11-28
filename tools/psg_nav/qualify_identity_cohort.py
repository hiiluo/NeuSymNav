"""Find real category transitions using exact-source offline instance masks."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

from neusymnav.evaluation.quality_dataset import load_quality_pair
from neusymnav.objectnav.detector_eval.masks import iou


def qualify_frames(frames, *, min_mask_iou):
    """Accept mutually unique mask matches and group them by physical GT ID."""
    if not math.isfinite(min_mask_iou) or not 0 < min_mask_iou <= 1:
        raise ValueError("mask IoU threshold must be in (0, 1]")

    tracks = defaultdict(list)
    frame_status = Counter()
    ambiguous = eligible_predictions = ground_truth_observations = 0
    for frame in frames:
        frame_status[frame["status"]] += 1
        eligible_predictions += len(frame["pred"])
        ground_truth_observations += len(frame["gt"])
        candidates = []
        for pred in frame["pred"]:
            for gt in frame["gt"]:
                overlap = iou(pred["mask"], gt["mask"])
                if overlap >= min_mask_iou:
                    candidates.append((pred, gt["id"], overlap))
        detection_degree = Counter(pred["id"] for pred, _, _ in candidates)
        instance_degree = Counter(gt_id for _, gt_id, _ in candidates)
        for pred, gt_id, overlap in candidates:
            if detection_degree[pred["id"]] != 1 or instance_degree[gt_id] != 1:
                ambiguous += 1
                continue
            tracks[gt_id].append({
                "frame_id": frame["frame_id"],
                "detection_id": pred["id"],
                "label": pred["label"],
                "mask_iou": overlap,
            })
    return {
        "frames": sum(frame_status.values()),
        "prediction_frame_status": dict(sorted(frame_status.items())),
        "missing_prediction_frames": frame_status["missing"],
        "predicted_observations": eligible_predictions,
        "ground_truth_observations": ground_truth_observations,
        "min_mask_iou": min_mask_iou,
        "matched_observations": sum(map(len, tracks.values())),
        "unique_tracks": len(tracks),
        "multi_view_tracks": sum(len(rows) > 1 for rows in tracks.values()),
        "ambiguous_candidate_pairs": ambiguous,
        "category_flip_tracks": {
            gt_id: rows for gt_id, rows in sorted(tracks.items())
            if len({row["label"] for row in rows}) > 1
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-mask-iou", type=float, default=0.5)
    args = parser.parse_args()

    pair = load_quality_pair(args.ground_truth, args.predictions)
    if any("mask" not in obj for frame in pair["frames"]
           for kind in ("gt", "pred") for obj in frame[kind]):
        parser.error("all objects must have exact-source instance masks")
    result = {
        "schema_version": 1,
        "scope": "offline physical-instance cohort qualification",
        "provenance_kind": pair["gt"]["provenance"]["kind"],
        "binding": pair["gt"]["binding"],
        "input_hashes": pair["input_hashes"],
        **qualify_frames(pair["frames"], min_mask_iou=args.min_mask_iou),
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
