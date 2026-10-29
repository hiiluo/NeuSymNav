from __future__ import annotations

from tools.verify_package import _fixture_smoke


def test_copied_source_package_replays_real_fixture_without_legacy_source_access() -> None:
    result = _fixture_smoke()

    assert result["status"] == "passed", result
    assert result["return_code"] == 0
    assert result["outcome"] == "completed"
    assert result["object_id"] == "0aa4a5c2-aff5-5f7f-9d6e-4ccf6d090e17"
    assert result["evidence_event_id"] == "a1c738303238f0416a288485c5ca46369dcca05878d9a9f3d4c187b2ca0e0441"
    assert result["source_frame"] == {
        "episode_id": "p09-fixture",
        "sensor_id": "rgbd",
        "frame_index": 0,
    }
    assert result["unrelated_working_directory"] is True
    assert result["source_pythonpath_removed"] is True
    assert result["legacy_source_open_audit"] == "passed"
