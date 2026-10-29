from __future__ import annotations

from pathlib import Path

from tools.preflight import _capability, build_report, report_exit_code


def test_contracts_preflight_passes_with_core_imports_and_reports_runtime_gaps() -> None:
    report = build_report(
        python_executable="/env/bin/python",
        python_version="3.12.3",
        host_imports={"neusymnav": True, "numpy": True, "scipy": True},
        runtime_capabilities={
            "habitat": {"available": False, "missing": ["habitat_sim"]},
            "detector": {"available": False, "missing": ["torch", "ultralytics"]},
        },
    )

    assert report["contracts"]["ready"] is True
    assert report["runtime_capabilities"]["habitat"]["available"] is False
    assert report["runtime_capabilities"]["detector"]["available"] is False
    assert report["gpu_probe_performed"] is False
    assert report_exit_code(report) == 0


def test_contracts_preflight_fails_only_when_a_required_host_import_is_missing() -> None:
    report = build_report(
        python_executable="/env/bin/python",
        python_version="3.12.3",
        host_imports={"neusymnav": True, "numpy": False, "scipy": True},
        runtime_capabilities={"habitat": {"available": False, "missing": ["habitat_sim"]}},
    )

    assert report["contracts"]["ready"] is False
    assert report["contracts"]["missing_imports"] == ["numpy"]
    assert report_exit_code(report) == 1


def test_native_candidate_path_is_reported_without_claiming_execution_validation(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "bin" / "native_worker"
    candidate.parent.mkdir()
    candidate.write_bytes(b"prebuilt-placeholder")
    candidate.chmod(0o755)

    result = _capability(
        (),
        executable="native_worker",
        executable_candidates=(candidate,),
    )

    assert result["available"] is False
    assert result["candidate_present"] is True
    assert result["executable"] == str(candidate)
    assert result["runtime_validated"] is False
    assert result["execution_validation"] == "not_run"
    assert "missing_executable" not in result
