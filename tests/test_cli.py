from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from neusymnav import cli


def _json(stream: str) -> dict:
    return json.loads(stream)


def test_cli_import_does_not_load_optional_runtime_stacks() -> None:
    project = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    probe = (
        "import sys; sys.path.insert(0, " + repr(str(project / "src")) + "); "
        "import neusymnav.cli; "
        "forbidden = ('PyQt5', 'torch', 'ultralytics', 'open_clip', 'habitat_sim'); "
        "assert not any(name == prefix or name.startswith(prefix + '.') "
        "for prefix in forbidden for name in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe], cwd=Path("/tmp"), env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_preflight_emits_json_and_uses_ready_exit_status(monkeypatch, capsys) -> None:
    calls = []
    launcher = SimpleNamespace(preflight=lambda config: calls.append(config) or {"ready": True, "profile": "fixture"})
    monkeypatch.setattr(cli, "_load_launcher", lambda: launcher)

    assert cli.main(["preflight", "--config", "profiles/base.yaml"]) == 0
    captured = capsys.readouterr()
    assert _json(captured.out) == {"profile": "fixture", "ready": True}
    assert captured.err == ""
    assert calls == ["profiles/base.yaml"]


def test_preflight_not_ready_is_a_json_result_with_failure_exit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_load_launcher", lambda: SimpleNamespace(preflight=lambda _: {"ready": False, "missing": ["scene"]}))

    assert cli.main(["preflight", "--config", "base.yaml"]) == 1
    assert _json(capsys.readouterr().out) == {"missing": ["scene"], "ready": False}


def test_run_passes_locked_arguments_and_maps_outcomes(monkeypatch, capsys) -> None:
    calls = []
    launcher = SimpleNamespace(
        run=lambda config, *, duration_s, out: calls.append((config, duration_s, out)) or {"outcome": "completed", "run_id": "r1"}
    )
    monkeypatch.setattr(cli, "_load_launcher", lambda: launcher)

    assert cli.main(["run", "--config", "base.yaml", "--duration-s", "12.5", "--out", "runs/r1"]) == 0
    assert _json(capsys.readouterr().out) == {"outcome": "completed", "run_id": "r1"}
    assert calls == [("base.yaml", 12.5, "runs/r1")]


def test_run_accepts_campaign_bound(monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(cli, "_load_launcher", lambda: SimpleNamespace(
        run=lambda config, *, duration_s, out: calls.append(duration_s) or {"outcome": "completed"}
    ))

    assert cli.main(["run", "--config", "base.yaml", "--duration-s", "300", "--out", "out"]) == 0
    capsys.readouterr()
    assert calls == [300.0]


@pytest.mark.parametrize("outcome", ["failed", "incomplete"])
def test_run_failed_or_incomplete_outcome_returns_one(monkeypatch, capsys, outcome) -> None:
    monkeypatch.setattr(cli, "_load_launcher", lambda: SimpleNamespace(
        run=lambda *_args, **_kwargs: {"outcome": outcome, "reason": "fixture"}
    ))

    assert cli.main(["run", "--config", "base.yaml", "--duration-s", "1", "--out", "out"]) == 1
    assert _json(capsys.readouterr().out)["outcome"] == outcome


def test_replay_passes_input_config_and_output(monkeypatch, capsys) -> None:
    calls = []
    launcher = SimpleNamespace(
        replay=lambda input_path, config, *, out: calls.append((input_path, config, out)) or {"outcome": "completed"}
    )
    monkeypatch.setattr(cli, "_load_launcher", lambda: launcher)

    assert cli.main(["replay", "--input", "data/episode", "--config", "replay.yaml", "--out", "result"]) == 0
    assert _json(capsys.readouterr().out) == {"outcome": "completed"}
    assert calls == [("data/episode", "replay.yaml", "result")]


@pytest.mark.parametrize("duration", ["0", "-1", "600.001", "nan", "inf", "-inf", "nope"])
def test_invalid_campaign_duration_is_json_argument_error(duration, capsys) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["run", "--config", "base.yaml", "--duration-s", duration, "--out", "out"])
    assert exited.value.code == 2
    assert _json(capsys.readouterr().err)["error"] == "invalid_arguments"


def test_missing_arguments_are_json_argument_errors(capsys) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["replay", "--config", "base.yaml"])
    assert exited.value.code == 2
    assert "--input" in _json(capsys.readouterr().err)["message"]


def test_unavailable_evaluation_has_actionable_p10_error(monkeypatch, capsys) -> None:
    original = cli.importlib.import_module

    def import_module(name: str):
        if name == "neusymnav.evaluation.protocol":
            raise ModuleNotFoundError("missing protocol", name=name)
        return original(name)

    monkeypatch.setattr(cli.importlib, "import_module", import_module)

    assert cli.main(["evaluate", "--suite", "suite.json", "--out", "report"]) == 1
    error = _json(capsys.readouterr().err)
    assert error["error"] == "RuntimeError"
    assert "P10" in error["message"]


def test_evaluate_calls_offline_suite_protocol_when_available(monkeypatch, capsys) -> None:
    calls = []
    protocol = SimpleNamespace(
        evaluate_suite=lambda suite, *, out: calls.append((suite, out)) or {"outcome": "completed", "runs": 1}
    )
    monkeypatch.setattr(cli.importlib, "import_module", lambda name: protocol)

    assert cli.main(["evaluate", "--suite", "suite.json", "--out", "report.json"]) == 0
    assert _json(capsys.readouterr().out) == {"outcome": "completed", "runs": 1}
    assert calls == [("suite.json", "report.json")]


def test_malformed_launcher_outcome_is_an_actionable_json_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_load_launcher", lambda: SimpleNamespace(
        run=lambda *_args, **_kwargs: {"status": "done"}
    ))

    assert cli.main(["run", "--config", "base.yaml", "--duration-s", "1", "--out", "out"]) == 1
    error = _json(capsys.readouterr().err)
    assert error["error"] == "ValueError"
    assert "outcome" in error["message"]


def test_runtime_exception_is_json_on_stderr_and_nonzero(monkeypatch, capsys) -> None:
    def fail(*_args, **_kwargs):
        raise FileNotFoundError("configured scene is missing: /assets/scene.glb")

    monkeypatch.setattr(cli, "_load_launcher", lambda: SimpleNamespace(
        replay=fail
    ))

    assert cli.main(["replay", "--input", "recording", "--config", "base.yaml", "--out", "out"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = _json(captured.err)
    assert error["error"] == "FileNotFoundError"
    assert "/assets/scene.glb" in error["message"]
