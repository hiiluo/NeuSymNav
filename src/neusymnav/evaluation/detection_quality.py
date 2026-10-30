"""Pure offline, class-aware detection scoring over normalized observations.

Boxes use continuous xyxy coordinates (no inclusive-pixel ``+1``). AP follows
the 101-point interpolated precision convention of COCOeval, over IoU .50:.05:
.95, but is a COCO-style subset: no crowd/ignore, maxDet cap, or size bins. It is
not official full COCO AP. All supplied predictions enter AP, including scores
below the operating threshold; upstream score filtering cannot be recovered.

Prediction order is descending score, then lexical frame ID and prediction ID.
Matching is greedy per frame/class, by greatest IoU then lexical GT ID. IDs are
unique within each frame's GT or prediction namespace. No runtime, detector,
dataset, or semantic vocabulary module is imported here.
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np


_IOU_THRESHOLDS = tuple(index / 100 for index in range(50, 100, 5))


def _number(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _normalize(frames: object) -> list[dict]:
    if not isinstance(frames, list):
        raise ValueError("frames must be a list")
    normalized = []
    frame_ids = set()
    for frame in frames:
        if not isinstance(frame, dict) or not {"frame_id", "gt", "pred"} <= frame.keys():
            raise ValueError("each frame requires frame_id, gt and pred")
        frame_id = _identifier(frame["frame_id"], "frame_id")
        if frame_id in frame_ids:
            raise ValueError("duplicate frame_id")
        frame_ids.add(frame_id)
        output = {"frame_id": frame_id}
        mask_shape = None
        for kind in ("gt", "pred"):
            if not isinstance(frame[kind], list):
                raise ValueError(f"{kind} must be a list")
            ids = set()
            rows = []
            for obj in frame[kind]:
                required = {"id", "label", "bbox"} | ({"score"} if kind == "pred" else set())
                if not isinstance(obj, dict) or not required <= obj.keys():
                    raise ValueError(f"{kind} observation missing required fields")
                # Unsupported ignore/crowd flags must never silently change support.
                if obj.keys() - (required | {"mask"}):
                    raise ValueError("unsupported observation fields")
                identifier = _identifier(obj["id"], "observation id")
                if identifier in ids:
                    raise ValueError(f"duplicate {kind} observation id")
                ids.add(identifier)
                label = _identifier(obj["label"], "label")
                box = obj["bbox"]
                if not isinstance(box, list) or len(box) != 4:
                    raise ValueError("bbox must be [x1, y1, x2, y2]")
                box = tuple(_number(value, "bbox coordinate") for value in box)
                width, height = box[2] - box[0], box[3] - box[1]
                area = width * height
                if width <= 0 or height <= 0 or not math.isfinite(area) or area <= 0:
                    raise ValueError("bbox must have finite positive width, height and area")
                row = {"id": identifier, "label": label, "bbox": box, "area": area}
                if kind == "pred":
                    score = _number(obj["score"], "score")
                    if not 0 <= score <= 1:
                        raise ValueError("score must be between zero and one")
                    row["score"] = score
                if "mask" in obj:
                    mask = obj["mask"]
                    if (
                        not isinstance(mask, list) or not mask
                        or any(not isinstance(part, list) or not part for part in mask)
                        or any(len(part) != len(mask[0]) for part in mask)
                        or any(type(value) is not bool for part in mask for value in part)
                    ):
                        raise ValueError("mask must be a nonempty rectangular 2D boolean list")
                    array = np.asarray(mask, dtype=bool)
                    if mask_shape is not None and array.shape != mask_shape:
                        raise ValueError("all masks in one frame must have the same dimensions")
                    mask_shape = array.shape
                    row["mask"] = array
                rows.append(row)
            output[kind] = rows
        normalized.append(output)
    return normalized


def _overlaps(frames: list[dict], mode: str) -> dict:
    result = {}
    for frame in frames:
        for pred in frame["pred"]:
            for gt in frame["gt"]:
                if pred["label"] != gt["label"]:
                    continue
                if mode == "mask":
                    union = int(np.count_nonzero(pred["mask"] | gt["mask"]))
                    intersection = int(np.count_nonzero(pred["mask"] & gt["mask"]))
                    overlap = intersection / union if union else 0.0
                else:
                    a, b = pred["bbox"], gt["bbox"]
                    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
                    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
                    intersection = width * height
                    union = pred["area"] + gt["area"] - intersection
                    if math.isfinite(union):
                        overlap = intersection / union
                    else:
                        exponent = math.frexp(max(pred["area"],gt["area"]))[1]
                        a,b,i = (math.ldexp(value,-exponent) for value in
                                 (pred["area"],gt["area"],intersection))
                        overlap = i/(a+b-i)
                result[frame["frame_id"], pred["id"], gt["id"]] = overlap
    return result


def _ranked(frames: list[dict], label: str, floor: float = 0) -> list[tuple[str, dict]]:
    return sorted(
        ((frame["frame_id"], pred) for frame in frames for pred in frame["pred"]
         if pred["label"] == label and pred["score"] >= floor),
        key=lambda item: (-item[1]["score"], item[0], item[1]["id"]),
    )


def _match(ranked: list[tuple[str, dict]], gt_by_frame: dict, overlaps: dict,
           threshold: float) -> list[int]:
    matched = set()
    true_positives = []
    for frame_id, pred in ranked:
        best_id, best_overlap = None, -1.0
        for gt in gt_by_frame.get(frame_id, []):
            if (frame_id, gt["id"]) in matched:
                continue
            overlap = overlaps[frame_id, pred["id"], gt["id"]]
            if overlap >= threshold and overlap > best_overlap:
                best_id, best_overlap = gt["id"], overlap
        true_positives.append(int(best_id is not None))
        if best_id is not None:
            matched.add((frame_id, best_id))
    return true_positives


def _point(tp: int, pred_count: int, gt_count: int) -> dict:
    fp, fn = pred_count - tp, gt_count - tp
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "ground_truth": gt_count, "predictions": pred_count,
        "precision": tp / pred_count if pred_count else None,
        "recall": tp / gt_count if gt_count else None,
        "f1": 2 * tp / (pred_count + gt_count) if pred_count + gt_count else None,
    }


def _interpolated_ap(true_positives: list[int], gt_count: int) -> float | None:
    if not gt_count:
        return None
    if not true_positives:
        return 0.0
    cumulative = np.cumsum(true_positives)
    recall = cumulative / gt_count
    precision = cumulative / np.arange(1, len(cumulative) + 1)
    precision = np.maximum.accumulate(precision[::-1])[::-1]
    indices = np.searchsorted(recall, np.linspace(0, 1, 101), side="left")
    samples = np.zeros(101)
    valid = indices < len(precision)
    samples[valid] = precision[indices[valid]]
    return float(samples.mean())


def _ap_summary(values: dict[str, float | None]) -> dict:
    supported = [value for value in values.values() if value is not None]
    return {"ap50": values["0.50"], "ap75": values["0.75"],
            "ap50_95": sum(supported) / len(supported) if supported else None,
            "ap_by_iou": values}


def _ap(frames: list[dict], labels: list[str], overlaps: dict | None) -> dict:
    per_class = {}
    for label in labels:
        ranked = _ranked(frames, label)
        gt_by_frame = {
            frame["frame_id"]: sorted(
                (gt for gt in frame["gt"] if gt["label"] == label), key=lambda gt: gt["id"]
            ) for frame in frames
        }
        gt_count = sum(len(rows) for rows in gt_by_frame.values())
        values = {
            f"{threshold:.2f}": _interpolated_ap(
                _match(ranked, gt_by_frame, overlaps, threshold), gt_count
            ) if overlaps is not None else None
            for threshold in _IOU_THRESHOLDS
        }
        per_class[label] = {"ground_truth": gt_count, "predictions": len(ranked),
                            **_ap_summary(values)}
    supported = [row for row in per_class.values() if row["ground_truth"]]
    values = {}
    for threshold in _IOU_THRESHOLDS:
        key = f"{threshold:.2f}"
        values[key] = (
            sum(row["ap_by_iou"][key] for row in supported) / len(supported)
            if supported and overlaps is not None else None
        )
    return {"available": overlaps is not None, **_ap_summary(values), "per_class": per_class}


def evaluate_detection(frames: list[dict], *, iou_threshold: float = 0.5,
                       confidence_threshold: float = 0.25) -> dict:
    """Score normalized offline frames; reject malformed/unsupported observations.

    Empty frames and missing predictions (represented by ``pred=[]``) are valid.
    Precision is null without predictions, recall/AP null without GT. F1 is null
    only when both supports are empty. Prediction-only classes retain FP support
    but do not enter macro AP. Missing any supplied GT/prediction mask disables
    the entire mask AP result; it never removes unmasked observations.
    """
    iou_threshold = _number(iou_threshold, "iou_threshold")
    confidence_threshold = _number(confidence_threshold, "confidence_threshold")
    if not 0 < iou_threshold <= 1 or not 0 <= confidence_threshold <= 1:
        raise ValueError("require 0 < iou_threshold <= 1 and 0 <= confidence_threshold <= 1")
    frames = _normalize(frames)
    labels = sorted({obj["label"] for frame in frames for kind in ("gt", "pred")
                     for obj in frame[kind]})
    overlaps = _overlaps(frames, "bbox")
    per_class = {}
    for label in labels:
        ranked = _ranked(frames, label, confidence_threshold)
        gt_by_frame = {
            frame["frame_id"]: sorted(
                (gt for gt in frame["gt"] if gt["label"] == label), key=lambda gt: gt["id"]
            ) for frame in frames
        }
        tp = sum(_match(ranked, gt_by_frame, overlaps, iou_threshold))
        per_class[label] = _point(tp, len(ranked), sum(map(len, gt_by_frame.values())))
    gt_count = sum(len(frame["gt"]) for frame in frames)
    pred_count = sum(len(frame["pred"]) for frame in frames)
    point_count = sum(row["predictions"] for row in per_class.values())
    point = _point(sum(row["tp"] for row in per_class.values()), point_count, gt_count)
    # Overall support lives in the support section as well, to make denominators
    # visible without requiring consumers to infer them from rounded ratios.
    point.pop("ground_truth")
    point.pop("predictions")
    missing = {kind: sum("mask" not in obj for frame in frames for obj in frame[kind])
               for kind in ("gt", "pred")}
    mask_ap = _ap(frames, labels, _overlaps(frames, "mask") if not any(missing.values()) else None)
    mask_ap.update({"reason": "incomplete_masks" if any(missing.values()) else None,
                    "missing_gt_masks": missing["gt"], "missing_prediction_masks": missing["pred"]})
    return {
        "schema_version": "detection-quality-v1",
        "protocol": {
            "ap_convention": "COCO-style subset; not official full COCO AP",
            "recall_samples": 101, "iou_thresholds": list(_IOU_THRESHOLDS),
            "excluded_features": ["crowd", "ignore", "maxDet", "size_bins"],
            "ap_prediction_scope": "all supplied predictions; upstream score floor may restrict AP",
            "class_average": "macro over classes with GT only",
            "tie_break": "descending score, lexical frame_id, prediction id; GT greatest IoU then lexical id",
            "bbox_convention": "continuous xyxy; no inclusive pixel adjustment",
        },
        "support": {
            "frames": len(frames), "frames_with_gt": sum(bool(frame["gt"]) for frame in frames),
            "ground_truth": gt_count, "predictions": pred_count,
            "predictions_at_operating_point": point_count,
            "classes_with_gt": sum(row["ground_truth"] > 0 for row in per_class.values()),
        },
        "operating_point": {"iou_threshold": iou_threshold,
                            "confidence_threshold": confidence_threshold, **point,
                            "per_class": per_class},
        "bbox_ap": _ap(frames, labels, overlaps), "mask_ap": mask_ap,
    }
