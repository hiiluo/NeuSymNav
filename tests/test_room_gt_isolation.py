from neusymnav.evaluation.gt_isolation import audit_runtime_imports


def test_room_quality_and_room_annotations_stay_outside_runtime_import_graph():
    audit = audit_runtime_imports()
    assert audit['violations'] == []
    assert any(path == 'evaluation/room_quality.py' for path in audit['checked_files']) is False
