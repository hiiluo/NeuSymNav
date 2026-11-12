import base64
import json

import numpy as np

from tools.check_rebuild_rgbd_demo_acceptance import evaluate_run


def _array(value):
    value = np.asarray(value, dtype="<f8")
    return {"ndarray": {
        "data": base64.b64encode(value.tobytes()).decode("ascii"),
        "dtype": value.dtype.str,
        "shape": list(value.shape),
    }}


def _run(tmp_path, *, polygon=((0., 0.), (1., 0.), (1., 1.), (0., 1.)),
         stale=False, outcome="completed", accepted=True):
    summary = {
        "outcome": outcome,
        "recording_certificate": {"complete": True},
        "runtime": {"clean_shutdown": True, "room_pipeline_failed": None, "replay_required": False},
        "cleanup": {"ui": {"status": {"failed": None}}},
        "export_issue": None,
    }
    latest_map = {"type": "RoomMapSnapshot", "fields": {"revision": 4}}
    accepted_map = {"type": "RoomMapSnapshot", "fields": {"revision": 4 if accepted else 3}}
    region = {"type": "Region", "fields": {"polygon": _array(polygon)}}
    region_snapshot = {"type": "RegionSnapshot", "fields": {
        "revision": 2, "source_map_revision": 4, "stale": stale,
        "regions": {"mapping": {"region:floor-0:1": region}},
    }}
    publication = {"type": "RoomPipelinePublication", "fields": {
        "latest_map": latest_map,
        "accepted_map": accepted_map if accepted else None,
        "accepted_map_revision": 4 if accepted else None,
        "regions": region_snapshot,
        "regions_stale": stale,
    }}
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    (tmp_path / "room-pipeline.json").write_text(json.dumps({"payload": publication}))
    return tmp_path


def test_demo_requires_fresh_valid_m5_region_paired_to_latest_map(tmp_path):
    result = evaluate_run(_run(tmp_path))
    assert result["accepted"]
    assert result["valid_m5_regions"] == 1


def test_demo_rejects_self_intersecting_m5_polygon(tmp_path):
    result = evaluate_run(_run(tmp_path, polygon=((0., 0.), (2., 2.), (0., 2.), (2., 0.))))
    assert not result["accepted"]
    assert any("not simple and nonzero" in reason for reason in result["reasons"])


def test_demo_rejects_stale_m5_region(tmp_path):
    result = evaluate_run(_run(tmp_path, stale=True))
    assert not result["accepted"]
    assert any("stale or unavailable" in reason for reason in result["reasons"])


def test_demo_rejects_missing_accepted_m3_pair(tmp_path):
    result = evaluate_run(_run(tmp_path, accepted=False))
    assert not result["accepted"]
    assert any("accepted M3 snapshot is missing" in reason for reason in result["reasons"])


def test_demo_rejects_incomplete_runtime_even_with_valid_region(tmp_path):
    result = evaluate_run(_run(tmp_path, outcome="incomplete"))
    assert not result["accepted"]
    assert any("not 'completed'" in reason for reason in result["reasons"])
