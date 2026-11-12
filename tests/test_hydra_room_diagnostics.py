from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from neusymnav.evaluation.room_diagnostics import (
    diagnose_room_finder_result,
    passes_strict_native_cutoff,
    render_room_overlay_svg,
)


def _native_result_with_a_pruned_component() -> dict:
    retained = [f"p({i})" for i in range(10)]
    pruned = [f"p({i})" for i in range(10, 19)]
    propagated = ["p(19)"]
    place_ids = retained + pruned + propagated
    return {
        "places": [
            {"id": place_id, "position_xyz": [float(i), 0.0, 0.0],
             "clearance_m": 0.9 if i < 19 else 0.2,
             "recorded_room_id": "R0"}
            for i, place_id in enumerate(place_ids)
        ],
        "edges": [
            {"source": "p(0)", "target": "p(1)", "weight_m": 0.8,
             "survives_threshold": False}
        ],
        "room_finder": {
            "config": {"min_component_size": 10, "min_room_size": 10,
                       "clustering_mode": "NEIGHBORS"},
            "selected_threshold_m": 0.8,
            "raw_components": [
                {"component_id": 0, "place_ids": retained, "size": 10,
                 "retained_as_seed": True},
                {"component_id": 1, "place_ids": pruned, "size": 9,
                 "retained_as_seed": False},
            ],
            "seeds_before_neighbors": [
                {"seed_id": 0, "source_component_id": 0,
                 "place_ids": retained, "size": 10}
            ],
            "post_neighbor_clusters": [
                {"cluster_index": 0, "room_id": "R0",
                 "place_ids": place_ids, "seed_place_ids": retained,
                 "size": 20, "accepted_as_room": True}
            ],
            "room_count": 1,
        },
        "native_log": {"filtration": [{"c": 1, "d": 0.8}]},
    }


def test_diagnostic_reports_pruned_graph_component_without_room_claim():
    report = diagnose_room_finder_result(_native_result_with_a_pruned_component())

    assert report["diagnosis"]["code"] == "one_seed_after_component_size_filter"
    assert report["diagnosis"]["retained_seed_count"] == 1
    assert report["diagnosis"]["pruned_component_sizes"] == [9]
    assert report["diagnosis"]["neighbor_propagated_place_count"] == 10
    assert "physical room" in report["diagnosis"]["limitation"]


def test_quality_claim_is_unsupported_without_independent_annotation():
    report = diagnose_room_finder_result(_native_result_with_a_pruned_component())

    assert report["quality_claim"]["status"] == "unsupported"
    assert report["quality_claim"]["accuracy_claimed"] is False
    assert report["quality_claim"]["metrics"] == {}


def test_roomfinder_strict_cutoff_excludes_equal_clearance_and_edge_weight():
    threshold = 0.8

    assert not passes_strict_native_cutoff(threshold, threshold)
    assert not passes_strict_native_cutoff(0.79, threshold)
    assert passes_strict_native_cutoff(0.81, threshold)


def test_overlay_displays_clearance_seed_edge_weight_and_membership():
    svg = render_room_overlay_svg(_native_result_with_a_pruned_component())

    assert 'data-clearance-m="0.9"' in svg
    assert 'data-seed-id="0"' in svg
    assert 'data-post-room="R0"' in svg
    assert 'data-edge-weight-m="0.8"' in svg
    assert "threshold 0.800000 m" in svg
    assert "diagnostic-only" in svg


def test_native_synthetic_two_room_bottleneck_fixture(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    binary = Path(os.environ.get(
        "NEUSYMNAV_HYDRA_ROOM_DIAGNOSTIC_NATIVE",
        repo / "runs/hydra-objectnav/B1-diagnostic-20261106/worker/hydra_room_diagnostic",
    ))
    if not binary.is_file():
        pytest.skip("native diagnostic binary is produced by the native-owner task")

    completed = subprocess.run(
        [sys.executable, str(repo / "tools/diagnose_hydra_rooms.py"),
         "--native-binary", str(binary), "--synthetic-fixture",
         "--output-dir", str(tmp_path)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((tmp_path / "room-diagnostic.json").read_text())
    room_finder = report["native_result"]["room_finder"]

    assert sorted(component["size"] for component in room_finder["raw_components"]) == [16, 16]
    assert len(room_finder["seeds_before_neighbors"]) == 2
    assert room_finder["room_count"] == 2
    assert report["quality_claim"]["status"] == "unsupported"


def test_rejects_inconsistent_component_size_filter():
    value = _native_result_with_a_pruned_component()
    value['room_finder']['raw_components'][0]['retained_as_seed'] = False
    with pytest.raises(ValueError, match='size filtering'):
        diagnose_room_finder_result(value)


def test_rejects_overlapping_component_membership():
    value = _native_result_with_a_pruned_component()
    value['room_finder']['raw_components'][1]['place_ids'][0] = 'p(0)'
    with pytest.raises(ValueError, match='partition'):
        diagnose_room_finder_result(value)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True])
def test_rejects_non_numeric_native_threshold(value):
    with pytest.raises(ValueError, match='finite numeric'):
        passes_strict_native_cutoff(0.8, value)
