from __future__ import annotations

import hashlib
from pathlib import Path

from tools.inventory_sources import inventory_sources


def test_inventory_records_relative_hash_and_license_evidence(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    package = source_root / "src" / "sample"
    package.mkdir(parents=True)
    source = package / "module.py"
    source.write_text("VALUE = 7\n", encoding="utf-8")
    notice = source_root / "LICENSE"
    notice.write_text("MIT License\n", encoding="utf-8")
    (source_root / "__pycache__").mkdir()
    (source_root / "__pycache__" / "ignored.pyc").write_bytes(b"compiled")

    result = inventory_sources((source_root,))

    assert result["schema_version"] == 1
    assert result["summary"] == {"selected_files": 1, "deferred_files": 0}
    assert result["files"] == [
        {
            "root": "source",
            "path": "src/sample/module.py",
            "sha256": hashlib.sha256(b"VALUE = 7\n").hexdigest(),
            "size_bytes": 10,
            "selection": "selected",
            "reason": "root explicitly included in the audited source closure",
            "origin": "local filesystem snapshot",
            "license": {
                "status": "notice_present",
                "path": "LICENSE",
                "sha256": hashlib.sha256(b"MIT License\n").hexdigest(),
            },
        }
    ]


def test_inventory_marks_unlicensed_files_unknown_and_keeps_roots_distinct(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one" / "mapping"
    second = tmp_path / "two" / "mapping"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "grid.py").write_text("FIRST = 1\n", encoding="utf-8")
    (second / "grid.py").write_text("SECOND = 2\n", encoding="utf-8")

    result = inventory_sources((first, second))

    assert [item["root"] for item in result["files"]] == [
        "one/mapping",
        "two/mapping",
    ]
    assert [item["path"] for item in result["files"]] == ["grid.py", "grid.py"]
    assert [item["license"]["status"] for item in result["files"]] == [
        "not_found",
        "not_found",
    ]
    assert result["summary"] == {"selected_files": 2, "deferred_files": 0}


def test_inventory_rejects_missing_roots(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    try:
        inventory_sources((missing,))
    except FileNotFoundError as error:
        assert str(missing) in str(error)
    else:
        raise AssertionError("missing roots must fail instead of producing a partial inventory")
def test_fist_notice_uses_bundled_makefile_instead_of_paper_readme(tmp_path):
    import hashlib
    from tools.inventory_sources import inventory_sources

    root=tmp_path/'dude_final'
    fist=root/'FIST'
    fist.mkdir(parents=True)
    (root/'README').write_text('DuDe paper citation, no license terms')
    notice=fist/'makefile'
    notice.write_text('Copyright: internal non-commercial use; consent required')
    archive=fist/'libFIST.linux64.a'
    archive.write_bytes(b'fixture archive')
    record=inventory_sources((archive,))['files'][0]
    assert record['license']['path']=='makefile'
    assert record['license']['sha256']==hashlib.sha256(notice.read_bytes()).hexdigest()

