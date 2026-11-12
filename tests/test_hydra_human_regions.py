import hashlib
import json

import pytest

from tools.evaluate_hydra_human_regions import (
    evaluate_revision,
    label_point,
    load_annotation,
)
from neusymnav.evaluation.room_quality import RoomSupportSnapshot, evaluate_room_geometry


def polygon(room_id, points):
    return {"room_id": room_id, "polygon_xy_m": points}


def write_bundle(tmp_path, *, rooms=None, door=None, uncertainty=0.1, source_prefix=None):
    episode = "ep"
    prefix = source_prefix or "b" * 64
    source = {
        "episode_id": episode,
        "capture_monotonic_ns": 123,
        "frame_index": 0,
        "calibration_hash": "c" * 64,
        "clock_domain": "host_monotonic:test",
        "sensor_id": "primary-rgbd",
        "labelspace_hash": "d" * 64,
        "labelspace_id": "labels:v1",
        "source_geometry_hash": "e" * 64,
        "vocabulary_id": "vocab:v1",
    }
    source_manifest = {
        "schema_version": 1,
        "episode_id": episode,
        "annotation_coordinate_convention": "canonical_z_up_m_v1",
        "selected_input_count": 1,
        "source_input_prefix_sha256": prefix,
        "selected_inputs": [{"graph_revision": 1, "source": source}],
    }
    source_path = tmp_path / "source-manifest.json"
    source_bytes = json.dumps(source_manifest, sort_keys=True).encode()
    source_path.write_bytes(source_bytes)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    annotation = {
        "schema_version": 1,
        "coordinate_convention": "canonical_z_up_m_v1",
        "annotation_source": {
            "annotator": "user",
            "marked_image_sha256": "1" * 64,
            "reference_image_sha256": "2" * 64,
            "source_manifest_path": str(source_path),
            "source_manifest_sha256": source_sha,
            "source_input_prefix_sha256": prefix,
            "episode_id": episode,
            "recording_key": "long300",
            "selected_frame_count": 1,
            "user_instruction": "green bathroom; cyan hallway; red door opening range",
        },
        "mapping": {
            "kind": "grid_registered_pixel_to_world",
            "reference_pixel_to_world": {
                "left": 0, "top": 0, "xmin": 0, "ymax": 3,
                "pixels_per_meter": 100,
            },
            "reference_image_size": [100, 100],
            "marked_image_size": [100, 100],
            "marked_to_reference_x_anchors": [[0, 0], [99, 99]],
            "marked_to_reference_y_anchors": [[0, 0], [99, 99]],
            "polygon_extraction": "test extraction",
        },
        "rooms": rooms or [
            polygon("bathroom", [[0, 0], [1, 0], [1, 1], [0, 1]]),
            polygon("hallway", [[2, 0], [3, 0], [3, 1], [2, 1]]),
        ],
        "door_opening_polyline_xy_m": door or [[1.4, 0.5], [1.6, 0.5]],
        "uncertainty_m": uncertainty,
        "scope": "human_marked_interior_regions_partial_not_exhaustive_room_boundary",
    }
    annotation_path = tmp_path / "human-regions.json"
    annotation_path.write_text(json.dumps(annotation))
    return load_annotation(annotation_path), source


def point_node(native_id, xy, room_id):
    return {
        "layer_id": 3,
        "native_id": native_id,
        "parent_native_id": room_id,
        "position": [xy[0], xy[1], 0.7],
    }


def revision_fixture(bundle, source, *, nodes=None, revision=1, prefix="b" * 64,
                     graph_sha="a" * 64):
    selected = [{"graph_revision": 1, "input_prefix_sha256": prefix, "source": source}]
    manifest = {
        "schema_version": 1,
        "complete": True,
        "episode_id": "ep",
        "run_id": "run-1",
        "graph_revision": 1,
        "graph_sha256": graph_sha,
        "input_prefix_sha256": prefix,
        "selected_inputs": selected,
    }
    record = {
        "episode_id": "ep",
        "capture_monotonic_ns": 123,
        "clock_domain": source["clock_domain"],
        "frame_index": source["frame_index"],
        "sensor_id": source["sensor_id"],
        "calibration_hash": source["calibration_hash"],
        "source_geometry_hash": source["source_geometry_hash"],
        "graph_revision": revision,
        "graph_sha256": graph_sha,
        "input_prefix_sha256": prefix,
        "summary": {
            "episode_id": "ep",
            "graph_revision": revision,
            "input_prefix_sha256": prefix,
            "nodes": nodes or [],
        },
    }
    return record, manifest


def test_point_in_concave_polygon_uses_interior_not_bounding_box(tmp_path):
    bundle, _ = write_bundle(
        tmp_path,
        rooms=[polygon("bathroom", [[0, 0], [3, 0], [3, 1], [1, 1], [1, 3], [0, 3]]),
               polygon("hallway", [[4, 0], [5, 0], [5, 1], [4, 1]])],
        door=[[3.5, 0], [3.5, 1]],
    )

    assert label_point((0.5, 2.0), bundle) == ("bathroom", None)
    assert label_point((2.0, 0.5), bundle) == ("bathroom", None)
    assert label_point((2.0, 2.0), bundle) == (None, "outside_human_regions")


def test_outline_uncertainty_overlap_and_red_door_range_are_unassigned(tmp_path):
    bundle, _ = write_bundle(
        tmp_path,
        rooms=[polygon("bathroom", [[0, 0], [2, 0], [2, 2], [0, 2]]),
               polygon("hallway", [[1.5, 0.5], [3, 0.5], [3, 1.5], [1.5, 1.5]])],
        door=[[0.5, 1.0], [1.5, 1.0]],
    )

    assert label_point((0.05, 0.5), bundle) == (None, "room_outline_uncertainty")
    assert label_point((1.0, 1.0), bundle) == (None, "door_opening_uncertainty")
    assert label_point((1.8, 1.0), bundle) == (None, "overlapping_human_regions")
    assert label_point((3.5, 1.0), bundle) == (None, "outside_human_regions")


def test_revision_emits_all_place_ids_and_rejects_malformed_graph_hash(tmp_path):
    bundle, source = write_bundle(tmp_path)
    record, manifest = revision_fixture(bundle, source, nodes=[
        point_node("p(1)", (0.5, 0.5), "R(0)"),
        point_node("p(2)", (1.5, 0.5), "R(0)"),
        point_node("p(3)", (4.0, 4.0), None),
    ])
    result = evaluate_revision(record, manifest, bundle)
    assert set(result["human_assignments"]) == {"p(1)", "p(2)", "p(3)"}
    assert result["human_assignments"]["p(3)"] is None
    assert result["graph_sha256"] == "a" * 64
    assert result["outside_human_region_count"] == 1

    bad_record = {**record, "graph_sha256": "not-a-digest"}
    with pytest.raises(ValueError, match="graph_sha256"):
        evaluate_revision(bad_record, manifest, bundle)


def test_revision_must_match_annotation_source_frame_chain(tmp_path):
    bundle, source = write_bundle(tmp_path)
    record, manifest = revision_fixture(bundle, source, nodes=[
        point_node("p(1)", (0.5, 0.5), "R(0)"),
    ])
    bad_manifest = {**manifest, "selected_inputs": [{
        **manifest["selected_inputs"][0],
        "source": {**source, "frame_index": 99},
    }]}

    with pytest.raises(ValueError, match="source frame list differs"):
        evaluate_revision(record, bad_manifest, bundle)


def test_missing_human_room_support_makes_room_quality_unavailable(tmp_path):
    bundle, source = write_bundle(tmp_path)
    record, manifest = revision_fixture(bundle, source, nodes=[
        point_node("p(1)", (0.5, 0.5), "R(0)"),
        point_node("p(2)", (0.6, 0.6), "R(0)"),
        point_node("p(3)", (1.5, 0.5), None),
    ])

    result = evaluate_revision(record, manifest, bundle)
    assert result["quality"]["status"] == "unavailable"
    assert result["quality"]["unavailable_reason"] == "no_confident_points_for_human_room:hallway"
    assert result["quality"]["metrics"]["pairwise_recall"] is None
    assert result["human_region_counts"] == {"bathroom": 2, "hallway": 0}


def test_human_room_with_only_unassigned_graph_places_cannot_pass_quality(tmp_path):
    bundle, source = write_bundle(tmp_path)
    record, manifest = revision_fixture(bundle, source, nodes=[
        point_node("p(1)", (0.5, 0.5), None),
        point_node("p(2)", (2.5, 0.5), "R(0)"),
    ])

    result = evaluate_revision(record, manifest, bundle)
    assert result["human_region_counts"] == {"bathroom": 1, "hallway": 1}
    assert result["quality"]["status"] == "unavailable"
    assert result["quality"]["unavailable_reason"] == "no_graph_assigned_points_for_human_room:bathroom"
    assert result["quality"]["metrics"]["pairwise_f1"] is None


def test_target_cross_region_coassignment_distinguishes_merge_from_separation(tmp_path):
    bundle, source = write_bundle(tmp_path)
    merged, manifest = revision_fixture(bundle, source, nodes=[
        point_node("p(1)", (0.5, 0.5), "R(0)"),
        point_node("p(2)", (2.5, 0.5), "R(0)"),
    ])
    split = {**merged, "graph_sha256": "f" * 64}
    split["summary"] = {**merged["summary"], "nodes": [
        point_node("p(1)", (0.5, 0.5), "R(0)"),
        point_node("p(2)", (2.5, 0.5), "R(1)"),
    ]}

    merged_result = evaluate_revision(merged, manifest, bundle)
    split_result = evaluate_revision(split, manifest, bundle)
    assert merged_result["target_cross_region_coassignment"]["same_graph_room_fraction"] == 1.0
    assert split_result["target_cross_region_coassignment"]["same_graph_room_fraction"] == 0.0


def test_existing_room_evaluator_rejects_annotation_for_another_graph_hash():
    prediction = RoomSupportSnapshot(
        episode_id="ep", run_id="run-1", graph_revision=1,
        frame_convention="canonical_z_up_m_v1",
        observed_support={"p(1)": (0.5, 0.5, 0.7)},
        support_domain="place_points", room_assignments={"p(1)": "R(0)"},
        unassigned=(), source_hashes={"graph": "a" * 64},
    )
    mismatched = {
        "schema_version": 1, "annotation_version": "human-regions-v1",
        "support_domain": "place_points", "annotated": True,
        "assignments": {"p(1)": "bathroom"}, "provenance": "manual",
        "episode_id": "ep", "run_id": "run-1", "graph_revision": 1,
        "graph_sha256": "f" * 64,
    }

    report = evaluate_room_geometry(prediction, mismatched, protocol="human-regions-v1")
    assert report.status == "unavailable"
    assert report.reasons == ("annotation_graph_hash_mismatch",)
