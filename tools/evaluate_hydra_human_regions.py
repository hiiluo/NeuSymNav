#!/usr/bin/env python3
"""Score Hydra place regions against user-marked interior polygons, offline only."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Mapping

from neusymnav.evaluation.room_quality import RoomSupportSnapshot, evaluate_room_geometry


COORDINATE_CONVENTION = "canonical_z_up_m_v1"
ANNOTATION_SCOPE = "human_marked_interior_regions_partial_not_exhaustive_room_boundary"
HUMAN_ROOM_IDS = ("bathroom", "hallway")
PROTOCOL = "human_polygon_place_partition_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CASE_ROOT = Path("runs/hydra-objectnav/B1-support-20261107")
_ALLOWED_CASES = {
    Path("runs/hydra-objectnav/B1-stability-20261107/clean/long300/stable"),
    _CASE_ROOT / "clean/long300/merge-0.5",
    _CASE_ROOT / "clean/long300/merge-0.25",
    _CASE_ROOT / "trace/long300/compression-1",
}


@dataclass(frozen=True)
class AnnotationBundle:
    data: Mapping
    source_manifest: Mapping
    source_manifest_sha256: str
    annotation_sha256: str


def _fail(message: str) -> None:
    raise ValueError(message)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_number(value, field: str) -> float:
    if not _is_number(value) or not math.isfinite(float(value)):
        _fail(f"{field} must be a finite number")
    return float(value)


def _sha256(value, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        _fail(f"{field} must be a lowercase SHA-256 digest")
    return value


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        _fail(f"{path} must contain a JSON object")
    return value


def _xy(point, field: str) -> tuple[float, float]:
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        _fail(f"{field} must be an [x, y] pair")
    return (_finite_number(point[0], f"{field}[0]"),
            _finite_number(point[1], f"{field}[1]"))


def _area(polygon: list[tuple[float, float]]) -> float:
    return sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1]
               - polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
               for i in range(len(polygon))) / 2.0


def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p, eps=1e-12) -> bool:
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
            and abs(_orientation(a, b, p)) <= eps)


def _segments_intersect(a, b, c, d) -> bool:
    eps = 1e-12
    o1, o2, o3, o4 = (_orientation(a, b, c), _orientation(a, b, d),
                      _orientation(c, d, a), _orientation(c, d, b))
    if ((o1 > eps and o2 < -eps or o1 < -eps and o2 > eps)
            and (o3 > eps and o4 < -eps or o3 < -eps and o4 > eps)):
        return True
    return ((abs(o1) <= eps and _on_segment(a, b, c))
            or (abs(o2) <= eps and _on_segment(a, b, d))
            or (abs(o3) <= eps and _on_segment(c, d, a))
            or (abs(o4) <= eps and _on_segment(c, d, b)))


def _validate_simple_polygon(polygon: list[tuple[float, float]], field: str) -> None:
    if len(polygon) < 3:
        _fail(f"{field} must contain at least three vertices")
    if polygon[0] == polygon[-1]:
        polygon.pop()
    if len(polygon) < 3 or abs(_area(polygon)) <= 1e-12:
        _fail(f"{field} must have nonzero area")
    if any(polygon[i] == polygon[(i + 1) % len(polygon)] for i in range(len(polygon))):
        _fail(f"{field} cannot contain duplicate adjacent vertices")
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        for j in range(i + 1, n):
            # Adjacent edges and the first/last pair share a legal endpoint.
            if j == i or j == i + 1 or (i == 0 and j == n - 1):
                continue
            c, d = polygon[j], polygon[(j + 1) % n]
            if _segments_intersect(a, b, c, d):
                _fail(f"{field} must be a simple polygon")


def _validate_mapping(mapping) -> None:
    if not isinstance(mapping, Mapping) or mapping.get("kind") != "grid_registered_pixel_to_world":
        _fail("mapping.kind must be grid_registered_pixel_to_world")
    pixel_map = mapping.get("reference_pixel_to_world")
    if not isinstance(pixel_map, Mapping):
        _fail("mapping.reference_pixel_to_world must be an object")
    for key in ("left", "top", "xmin", "ymax", "pixels_per_meter"):
        _finite_number(pixel_map.get(key), f"mapping.reference_pixel_to_world.{key}")
    if pixel_map["pixels_per_meter"] <= 0:
        _fail("mapping pixels_per_meter must be positive")
    for key in ("reference_image_size", "marked_image_size"):
        size = mapping.get(key)
        if (not isinstance(size, list) or len(size) != 2
                or any(type(v) is not int or v <= 0 for v in size)):
            _fail(f"mapping.{key} must be [width_px, height_px]")
    for key in ("marked_to_reference_x_anchors", "marked_to_reference_y_anchors"):
        anchors = mapping.get(key)
        if not isinstance(anchors, list) or len(anchors) < 2:
            _fail(f"mapping.{key} must contain at least two anchor pairs")
        pairs = [_xy(pair, f"mapping.{key}[{i}]") for i, pair in enumerate(anchors)]
        if any(pairs[i][0] > pairs[i + 1][0] or pairs[i][1] > pairs[i + 1][1]
               for i in range(len(pairs) - 1)):
            _fail(f"mapping.{key} anchors must be monotone")
    if not isinstance(mapping.get("polygon_extraction"), str) or not mapping["polygon_extraction"].strip():
        _fail("mapping.polygon_extraction must describe the extraction")


def _validate_source_manifest(annotation_source: Mapping) -> tuple[dict, str]:
    source_path_value = annotation_source.get("source_manifest_path")
    if not isinstance(source_path_value, str) or not source_path_value:
        _fail("annotation_source.source_manifest_path is required")
    source_path = Path(source_path_value)
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read annotation SourceManifest {source_path}: {exc}") from exc
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    expected_sha = _sha256(annotation_source.get("source_manifest_sha256"),
                           "annotation_source.source_manifest_sha256")
    if actual_sha != expected_sha:
        _fail("annotation SourceManifest SHA-256 mismatch")
    try:
        source_manifest = json.loads(source_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"annotation SourceManifest is invalid JSON: {exc}") from exc
    if not isinstance(source_manifest, dict):
        _fail("annotation SourceManifest must be an object")
    if source_manifest.get("episode_id") != annotation_source.get("episode_id"):
        _fail("annotation SourceManifest episode mismatch")
    if source_manifest.get("annotation_coordinate_convention") != COORDINATE_CONVENTION:
        _fail("annotation SourceManifest coordinate convention mismatch")
    count = annotation_source.get("selected_frame_count")
    rows = source_manifest.get("selected_inputs")
    if (type(count) is not int or count <= 0 or not isinstance(rows, list)
            or len(rows) != count or source_manifest.get("selected_input_count") != count):
        _fail("annotation SourceManifest selected frame count mismatch")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping) or row.get("graph_revision") != index:
            _fail("annotation SourceManifest frame list must be complete and ordered")
        source = row.get("source")
        if (not isinstance(source, Mapping)
                or source.get("episode_id") != annotation_source.get("episode_id")
                or type(source.get("frame_index")) is not int):
            _fail("annotation SourceManifest has invalid source metadata")
    if source_manifest.get("source_input_prefix_sha256") != annotation_source.get("source_input_prefix_sha256"):
        _fail("annotation SourceManifest input prefix mismatch")
    return source_manifest, actual_sha


def load_annotation(path: str | Path) -> AnnotationBundle:
    """Load and validate polygon, registration, and source provenance metadata."""
    try:
        raw_annotation = Path(path).read_bytes()
        data = json.loads(raw_annotation)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read annotation JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        _fail("human-region annotation must be a JSON object")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        _fail("unsupported human-region annotation schema")
    if data.get("coordinate_convention") != COORDINATE_CONVENTION:
        _fail("unsupported human-region coordinate convention")
    if data.get("scope") != ANNOTATION_SCOPE:
        _fail("human-region annotation scope mismatch")
    source = data.get("annotation_source")
    if not isinstance(source, Mapping) or source.get("annotator") != "user":
        _fail("annotation_source must identify the user as annotator")
    for key in ("marked_image_sha256", "reference_image_sha256",
                "source_manifest_sha256", "source_input_prefix_sha256"):
        _sha256(source.get(key), f"annotation_source.{key}")
    if source.get("recording_key") != "long300":
        _fail("human-region annotation is only registered to long300")
    if not isinstance(source.get("user_instruction"), str) or "door opening range" not in source["user_instruction"]:
        _fail("annotation source must preserve the user's door-opening instruction")
    source_manifest, source_sha = _validate_source_manifest(source)
    _validate_mapping(data.get("mapping"))
    uncertainty = _finite_number(data.get("uncertainty_m"), "uncertainty_m")
    if uncertainty < 0:
        _fail("uncertainty_m cannot be negative")

    rooms = data.get("rooms")
    if not isinstance(rooms, list) or len(rooms) != len(HUMAN_ROOM_IDS):
        _fail("human annotation must contain bathroom and hallway polygons")
    seen = set()
    for index, room in enumerate(rooms):
        if not isinstance(room, Mapping):
            _fail(f"rooms[{index}] must be an object")
        room_id = room.get("room_id")
        if room_id not in HUMAN_ROOM_IDS or room_id in seen:
            _fail("human room IDs must be unique bathroom and hallway labels")
        seen.add(room_id)
        polygon = room.get("polygon_xy_m")
        if not isinstance(polygon, list):
            _fail(f"rooms[{index}].polygon_xy_m must be a list")
        normalized = [_xy(point, f"rooms[{index}].polygon_xy_m[{i}]")
                      for i, point in enumerate(polygon)]
        _validate_simple_polygon(normalized, f"rooms[{index}].polygon_xy_m")
        room["polygon_xy_m"] = [list(point) for point in normalized]
    if seen != set(HUMAN_ROOM_IDS):
        _fail("both bathroom and hallway polygons are required")
    door = data.get("door_opening_polyline_xy_m")
    if not isinstance(door, list) or len(door) < 2:
        _fail("door_opening_polyline_xy_m must contain at least two points")
    data["door_opening_polyline_xy_m"] = [list(_xy(point, f"door_opening_polyline_xy_m[{i}]"))
                                          for i, point in enumerate(door)]
    return AnnotationBundle(data, source_manifest, source_sha,
                            hashlib.sha256(raw_annotation).hexdigest())


def _point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2))
    projection = (start[0] + t * dx, start[1] + t * dy)
    return math.dist(point, projection)


def _distance_to_polyline(point, polyline) -> float:
    return min(_point_segment_distance(point, a, b) for a, b in zip(polyline, polyline[1:]))


def _point_in_polygon(point, polygon) -> bool:
    inside = False
    x, y = point
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y):
            cross_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < cross_x:
                inside = not inside
    return inside


def label_point(point_xy, annotation: AnnotationBundle | Mapping) -> tuple[str | None, str | None]:
    """Return a room label only inside exactly one confidently marked interior."""
    point = _xy(point_xy, "point_xy")
    data = annotation.data if isinstance(annotation, AnnotationBundle) else annotation
    uncertainty = _finite_number(data.get("uncertainty_m"), "uncertainty_m")
    rooms = data.get("rooms", [])
    for room in rooms:
        polygon = [tuple(p) for p in room["polygon_xy_m"]]
        if _distance_to_polyline(point, polygon + [polygon[0]]) <= uncertainty + 1e-12:
            return None, "room_outline_uncertainty"
    door = [tuple(p) for p in data["door_opening_polyline_xy_m"]]
    if _distance_to_polyline(point, door) <= uncertainty + 1e-12:
        return None, "door_opening_uncertainty"
    containing = [room["room_id"] for room in rooms
                  if _point_in_polygon(point, [tuple(p) for p in room["polygon_xy_m"]])]
    if len(containing) > 1:
        return None, "overlapping_human_regions"
    if len(containing) == 1:
        return containing[0], None
    return None, "outside_human_regions"


def _validate_revision_binding(revision: Mapping, replay_manifest: Mapping,
                                bundle: AnnotationBundle) -> Mapping:
    if replay_manifest.get("schema_version") != 1 or replay_manifest.get("complete") is not True:
        _fail("replay graph manifest is incomplete or unsupported")
    ann_source = bundle.data["annotation_source"]
    episode = replay_manifest.get("episode_id")
    run_id = replay_manifest.get("run_id")
    rows = replay_manifest.get("selected_inputs")
    human_rows = bundle.source_manifest.get("selected_inputs")
    if (not isinstance(episode, str) or episode != ann_source.get("episode_id")
            or not isinstance(run_id, str) or not run_id):
        _fail("replay manifest episode/run identity mismatch")
    count = ann_source.get("selected_frame_count")
    if not isinstance(rows, list) or len(rows) != count or len(human_rows) != count:
        _fail("replay manifest selected input list does not match annotation SourceManifest")
    for index, (selected, human) in enumerate(zip(rows, human_rows), start=1):
        if (not isinstance(selected, Mapping) or selected.get("graph_revision") != index
                or selected.get("source") != human.get("source")):
            _fail("replay manifest selected source frame list differs from annotation SourceManifest")
        _sha256(selected.get("input_prefix_sha256"), f"selected_inputs[{index}].input_prefix_sha256")
    final = rows[-1]
    if (final.get("input_prefix_sha256") != ann_source.get("source_input_prefix_sha256")
            or replay_manifest.get("input_prefix_sha256") != final.get("input_prefix_sha256")
            or replay_manifest.get("graph_revision") != final.get("graph_revision")):
        _fail("annotation input prefix does not match final replay source prefix")
    _sha256(replay_manifest.get("graph_sha256"), "manifest graph_sha256")
    expected_revision = revision.get("graph_revision")
    if type(expected_revision) is not int or not 1 <= expected_revision <= count:
        _fail("revision is outside the annotation's accepted source sequence")
    selected = rows[expected_revision - 1]
    source = selected["source"]
    summary = revision.get("summary")
    if not isinstance(summary, Mapping):
        _fail("revision summary is missing")
    if (revision.get("episode_id") != episode or summary.get("graph_revision") != expected_revision
            or summary.get("input_prefix_sha256") != selected.get("input_prefix_sha256")
            or revision.get("input_prefix_sha256") != selected.get("input_prefix_sha256")):
        _fail("revision graph/source prefix does not bind to selected source frame")
    for field in ("episode_id", "capture_monotonic_ns", "clock_domain", "frame_index",
                  "sensor_id", "calibration_hash", "source_geometry_hash"):
        if revision.get(field) != source.get(field):
            _fail(f"revision source metadata mismatch at {field}")
    graph_sha = _sha256(revision.get("graph_sha256"), "revision graph_sha256")
    return summary


def _point_nodes(summary: Mapping) -> list[Mapping]:
    nodes = summary.get("nodes")
    if not isinstance(nodes, list):
        _fail("revision summary.nodes must be a list")
    places = [node for node in nodes if isinstance(node, Mapping) and node.get("layer_id") == 3]
    ids = [node.get("native_id") for node in places]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        _fail("place point IDs must be present and unique")
    return places


def _quality_unavailable(reason: str, *, annotation_coverage: float | None = None) -> dict:
    metric_names = ("adjusted_rand_index", "pairwise_precision", "pairwise_recall", "pairwise_f1",
                    "purity", "best_match_mean_iou", "merge_count", "split_count",
                    "boundary_f1_020m", "boundary_f1_010m", "boundary_f1_030m",
                    "temporal_geometry_consistency", "room_id_churn")
    return {
        "status": "unavailable", "protocol": PROTOCOL,
        "support_count": 0, "annotation_coverage": annotation_coverage,
        "metrics": {name: None for name in metric_names},
        "unavailable_reason": reason,
        "reasons": [reason],
    }


def evaluate_revision(revision: Mapping, replay_manifest: Mapping,
                      bundle: AnnotationBundle) -> dict:
    """Bind one saved graph revision to its source and score its observed places."""
    if not isinstance(bundle, AnnotationBundle):
        raise TypeError("bundle must come from load_annotation")
    summary = _validate_revision_binding(revision, replay_manifest, bundle)
    graph_sha = _sha256(revision.get("graph_sha256"), "revision graph_sha256")
    graph_revision = revision["graph_revision"]
    episode_id, run_id = replay_manifest["episode_id"], replay_manifest["run_id"]
    places = _point_nodes(summary)

    support = {}
    predicted = {}
    human_assignments = {}
    exclusion_counts = {}
    graph_region_counts = {}
    human_region_counts = {room_id: 0 for room_id in HUMAN_ROOM_IDS}
    graph_unassigned_by_human = {room_id: 0 for room_id in HUMAN_ROOM_IDS}
    assigned_graph_counts_by_human = {room_id: {} for room_id in HUMAN_ROOM_IDS}
    confusion = {}
    for node in places:
        native_id = node["native_id"]
        position = node.get("position")
        if not isinstance(position, list) or len(position) != 3:
            _fail(f"place point {native_id} needs a finite XYZ position")
        xyz = tuple(_finite_number(value, f"{native_id}.position") for value in position)
        support[native_id] = xyz
        parent = node.get("parent_native_id")
        if parent is not None and (not isinstance(parent, str) or not parent.startswith("R(")):
            _fail(f"place point {native_id} has invalid parent room ID")
        predicted[native_id] = parent
        if parent is not None:
            graph_region_counts[parent] = graph_region_counts.get(parent, 0) + 1
        label, reason = label_point(xyz[:2], bundle)
        human_assignments[native_id] = label
        if label is not None:
            human_region_counts[label] += 1
            if parent is None:
                graph_unassigned_by_human[label] += 1
            else:
                room_row = confusion.setdefault(parent, {room_id: 0 for room_id in HUMAN_ROOM_IDS})
                room_row[label] += 1
                class_counts = assigned_graph_counts_by_human[label]
                class_counts[parent] = class_counts.get(parent, 0) + 1
        else:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1

    total_points = len(places)
    confident_points = sum(human_region_counts.values())
    gt_coverage = confident_points / total_points if total_points else 0.0
    missing_rooms = [room_id for room_id in HUMAN_ROOM_IDS if human_region_counts[room_id] == 0]
    missing_assigned_rooms = [room_id for room_id in HUMAN_ROOM_IDS
                              if not assigned_graph_counts_by_human[room_id]]
    graph_unassigned_ids = sorted(key for key, room_id in predicted.items() if room_id is None)
    graph_unassigned_by_gt = {room_id: graph_unassigned_by_human[room_id]
                              for room_id in HUMAN_ROOM_IDS}
    bathroom_graph_counts = assigned_graph_counts_by_human["bathroom"]
    hallway_graph_counts = assigned_graph_counts_by_human["hallway"]
    bathroom_assigned_count = sum(bathroom_graph_counts.values())
    hallway_assigned_count = sum(hallway_graph_counts.values())
    cross_region_pair_count = bathroom_assigned_count * hallway_assigned_count
    same_region_pair_count = sum(
        bathroom_graph_counts.get(graph_room, 0) * hallway_graph_counts.get(graph_room, 0)
        for graph_room in set(bathroom_graph_counts) | set(hallway_graph_counts)
    )
    cross_region_coassignment_rate = (
        same_region_pair_count / cross_region_pair_count if cross_region_pair_count else None
    )
    room_fragments_by_human = {
        room_id: len(assigned_graph_counts_by_human[room_id]) for room_id in HUMAN_ROOM_IDS
    }
    annotation_source = bundle.data["annotation_source"]
    graph_bound_annotation = {
        "schema_version": 1,
        "annotation_version": "human-regions-v1",
        "support_domain": "place_points",
        "annotated": True,
        "assignments": human_assignments,
        "provenance": (
            f"annotation_sha256={bundle.annotation_sha256};"
            f"source_manifest_sha256={bundle.source_manifest_sha256};"
            f"source_input_prefix_sha256={annotation_source['source_input_prefix_sha256']};"
            f"marked_image_sha256={annotation_source['marked_image_sha256']};"
            f"reference_image_sha256={annotation_source['reference_image_sha256']}"
        ),
        "episode_id": episode_id,
        "run_id": run_id,
        "graph_revision": graph_revision,
        "graph_sha256": graph_sha,
    }

    if missing_rooms:
        quality = _quality_unavailable(
            "no_confident_points_for_human_room:" + ",".join(missing_rooms),
            annotation_coverage=gt_coverage)
    elif missing_assigned_rooms:
        quality = _quality_unavailable(
            "no_graph_assigned_points_for_human_room:" + ",".join(missing_assigned_rooms),
            annotation_coverage=gt_coverage)
    else:
        snapshot = RoomSupportSnapshot(
            episode_id=episode_id,
            run_id=run_id,
            graph_revision=graph_revision,
            frame_convention=COORDINATE_CONVENTION,
            observed_support=support,
            support_domain="place_points",
            room_assignments=predicted,
            unassigned=tuple(graph_unassigned_ids),
            source_hashes={"graph": graph_sha},
        )
        report = evaluate_room_geometry(snapshot, graph_bound_annotation, protocol=PROTOCOL).to_dict()
        quality = {
            "status": report["status"], "protocol": report["protocol"],
            "support_count": report["support_count"],
            "annotation_coverage": report["annotation_coverage"],
            "metrics": report["metrics"], "unavailable": report["unavailable"],
            "reasons": report["reasons"],
            "unavailable_reason": report["reasons"][0] if report["status"] == "unavailable" else None,
        }

    return {
        "schema_version": 1,
        "status": quality["status"],
        "report_status": "available" if total_points else "unavailable",
        "episode_id": episode_id,
        "run_id": run_id,
        "graph_revision": graph_revision,
        "graph_sha256": graph_sha,
        "replay_manifest_graph_sha256": replay_manifest["graph_sha256"],
        "graph_artifact_scope": (
            "revision snapshot saved without mesh; replay manifest SHA covers the close export with mesh; "
            "the two artifact hashes are intentionally distinct"
        ),
        "input_prefix_sha256": revision["input_prefix_sha256"],
        "annotation_source_manifest_sha256": bundle.source_manifest_sha256,
        "human_regions_annotation_sha256": bundle.annotation_sha256,
        "marked_image_sha256": annotation_source["marked_image_sha256"],
        "reference_image_sha256": annotation_source["reference_image_sha256"],
        "annotation_source_input_prefix_sha256": bundle.data["annotation_source"]["source_input_prefix_sha256"],
        "scope": ANNOTATION_SCOPE,
        "door_opening_semantics": "uncertainty_only_not_obstacle_occupancy_or_true_width",
        "support_domain": "place_points",
        "place_point_count": total_points,
        "graph_region_counts": dict(sorted(graph_region_counts.items())),
        "human_region_counts": human_region_counts,
        "human_assignments": human_assignments,
        "human_gt_confident_count": confident_points,
        "human_gt_coverage_all_place_points": gt_coverage,
        "confusion_graph_room_by_human_room": confusion,
        "assigned_graph_room_fragments_by_human_room": room_fragments_by_human,
        "assigned_graph_points_by_human_room": {
            room_id: dict(sorted(assigned_graph_counts_by_human[room_id].items()))
            for room_id in HUMAN_ROOM_IDS
        },
        "target_cross_region_coassignment": {
            "scope": "confident_bathroom_hallway_place_pairs_assigned_to_a_graph_room",
            "bathroom_graph_assigned_count": bathroom_assigned_count,
            "hallway_graph_assigned_count": hallway_assigned_count,
            "eligible_cross_region_pair_count": cross_region_pair_count,
            "same_graph_room_pair_count": same_region_pair_count,
            "same_graph_room_fraction": cross_region_coassignment_rate,
        },
        "graph_unassigned_count": len(graph_unassigned_ids),
        "graph_unassigned_place_ids": graph_unassigned_ids,
        "graph_unassigned_by_human_room": graph_unassigned_by_gt,
        "human_unassigned_exclusion_counts": exclusion_counts,
        "boundary_excluded_count": exclusion_counts.get("room_outline_uncertainty", 0),
        "door_opening_uncertainty_excluded_count": exclusion_counts.get("door_opening_uncertainty", 0),
        "overlap_excluded_count": exclusion_counts.get("overlapping_human_regions", 0),
        "outside_human_region_count": exclusion_counts.get("outside_human_regions", 0),
        "human_ground_truth_available_for_two_regions": not missing_rooms,
        "human_regions_without_confident_points": missing_rooms,
        "human_regions_without_graph_assigned_points": missing_assigned_rooms,
        "graph_bound_annotation": graph_bound_annotation,
        "quality": quality,
    }


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _load_and_verify_revision(path: Path) -> dict:
    revision = _read_json(path)
    graph_path_value = revision.get("graph_path")
    graph_path = Path(graph_path_value) if isinstance(graph_path_value, str) else path.with_suffix(".sparkdsg")
    if not graph_path.is_file():
        graph_path = path.with_suffix(".sparkdsg")
    if not graph_path.is_file():
        _fail(f"revision graph artifact is missing for {path}")
    expected = _sha256(revision.get("graph_sha256"), "revision graph_sha256")
    if _sha256_file(graph_path) != expected:
        _fail(f"revision graph artifact SHA-256 mismatch for {path}")
    return revision


def _case_slug(case_dir: Path) -> str:
    try:
        relative = case_dir.resolve().relative_to(Path(__file__).resolve().parents[1])
    except ValueError as exc:
        raise ValueError(f"case directory is outside this repository: {case_dir}") from exc
    if relative not in _ALLOWED_CASES:
        _fail(f"case directory is not one of the three registered long300 profiles: {relative}")
    return str(relative).replace("/", "-")


def evaluate_case(case_dir: str | Path, bundle: AnnotationBundle, output_dir: str | Path) -> dict:
    case_dir = Path(case_dir).resolve()
    slug = _case_slug(case_dir)
    manifest = _read_json(case_dir / "replay-graph-manifest.json")
    if manifest.get("graph_revision") != bundle.data["annotation_source"]["selected_frame_count"]:
        _fail("registered long300 profile must contain all 58 accepted source revisions")
    close_graph_path_value = manifest.get("graph_path")
    close_graph_path = Path(close_graph_path_value) if isinstance(close_graph_path_value, str) else None
    close_graph_sha = _sha256(manifest.get("graph_sha256"), "manifest graph_sha256")
    if close_graph_path is None or not close_graph_path.is_file():
        _fail("replay manifest close graph artifact is missing")
    if _sha256_file(close_graph_path) != close_graph_sha:
        _fail("replay manifest close graph artifact SHA-256 mismatch")
    revisions_dir = case_dir / "revisions"
    paths = sorted(revisions_dir.glob("[0-9][0-9][0-9][0-9].json"))
    if len(paths) != manifest["graph_revision"]:
        _fail("revision snapshots do not cover the complete replay manifest")
    case_output = Path(output_dir) / slug
    case_output.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, path in enumerate(paths, start=1):
        if path.stem != f"{index:04d}":
            _fail("revision snapshot sequence has a gap or misordered filename")
        revision = _load_and_verify_revision(path)
        result = evaluate_revision(revision, manifest, bundle)
        target = case_output / f"revision-{index:04d}.json"
        target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        rows.append(result)
    summary = {
        "schema_version": 1,
        "case": str(case_dir),
        "run_id": manifest["run_id"],
        "episode_id": manifest["episode_id"],
        "source_input_prefix_sha256": manifest["input_prefix_sha256"],
        "source_manifest_sha256": bundle.source_manifest_sha256,
        "revision_count": len(rows),
        "final_revision": rows[-1] if rows else None,
        "quality_available_revision_count": sum(row["quality"]["status"] == "available" for row in rows),
        "revision_trend": [
            {
                "graph_revision": row["graph_revision"],
                "graph_sha256": row["graph_sha256"],
                "quality_status": row["quality"]["status"],
                "quality_unavailable_reason": row["quality"].get("unavailable_reason"),
                "graph_region_counts": row["graph_region_counts"],
                "human_region_counts": row["human_region_counts"],
                "graph_unassigned_count": row["graph_unassigned_count"],
                "boundary_excluded_count": row["boundary_excluded_count"],
                "door_opening_uncertainty_excluded_count": row["door_opening_uncertainty_excluded_count"],
                "target_cross_region_coassignment": row["target_cross_region_coassignment"],
                "assigned_graph_room_fragments_by_human_room": row["assigned_graph_room_fragments_by_human_room"],
                "pairwise_precision": row["quality"]["metrics"].get("pairwise_precision"),
                "pairwise_recall": row["quality"]["metrics"].get("pairwise_recall"),
                "pairwise_f1": row["quality"]["metrics"].get("pairwise_f1"),
            }
            for row in rows
        ],
        "revision_files": [f"revision-{i:04d}.json" for i in range(1, len(rows) + 1)],
    }
    (case_output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation", required=True, type=Path)
    parser.add_argument("--case-dir", required=True, type=Path, nargs="+",
                        help="one or more registered long300 graph replay directories")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        bundle = load_annotation(args.annotation)
        summaries = [evaluate_case(case_dir, bundle, args.output_dir) for case_dir in args.case_dir]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"human-region evaluation failed: {exc}", file=sys.stderr)
        return 2
    index = {
        "schema_version": 1,
        "annotation_sha256": bundle.annotation_sha256,
        "source_manifest_sha256": bundle.source_manifest_sha256,
        "cases": [
            {
                "case": summary["case"],
                "run_id": summary["run_id"],
                "revision_count": summary["revision_count"],
                "quality_available_revision_count": summary["quality_available_revision_count"],
                "final_revision": {
                    "graph_sha256": summary["final_revision"]["graph_sha256"],
                    "quality_status": summary["final_revision"]["quality"]["status"],
                    "quality_metrics": summary["final_revision"]["quality"]["metrics"],
                    "human_region_counts": summary["final_revision"]["human_region_counts"],
                    "graph_region_counts": summary["final_revision"]["graph_region_counts"],
                    "graph_unassigned_count": summary["final_revision"]["graph_unassigned_count"],
                    "target_cross_region_coassignment": summary["final_revision"]["target_cross_region_coassignment"],
                },
            }
            for summary in summaries
        ],
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(json.dumps(index, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
