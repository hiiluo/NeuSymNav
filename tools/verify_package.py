"""Audit NeuSymNav source packaging and exercise an isolated fixture replay."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "neusymnav"
NOTICES_PATH = PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"
PROVENANCE_PATH = PROJECT_ROOT / "docs" / "source-provenance.json"
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "package"
REPORT_PATH = PROJECT_ROOT / "runs" / "p09-cli" / "source-only-report.json"
FORBIDDEN_IMPORT_ROOTS = {"NewOH3DSG", "3DSG", "standalone_sg"}
DEFERRED_MODULES = {"neusymnav.evaluation.protocol"}
_USER_PATH = re.compile(r"/home/[^/]+/Works/NeuSym-Nav(?:/|$)")


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("neusymnav", *parts)) if parts else "neusymnav"


def _non_docstring_strings(tree: ast.AST):
    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", ())
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstring_ids.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids:
            yield node.value


def _package_source_audit() -> tuple[dict, list[str]]:
    failures: list[str] = []
    if not SOURCE_ROOT.is_dir() or SOURCE_ROOT.is_symlink():
        return {"python_files": 0, "source_sha256": None}, ["source package directory is missing or symlinked"]

    all_paths = list(SOURCE_ROOT.rglob("*"))
    symlinks = [str(path.relative_to(PROJECT_ROOT)) for path in all_paths if path.is_symlink()]
    if symlinks:
        failures.append("source package contains symlinks: " + ", ".join(symlinks))

    source_files = sorted(path for path in all_paths if path.is_file() and path.suffix == ".py")
    modules = {_module_name(path) for path in source_files}
    package_dirs = {"neusymnav"}
    for path in source_files:
        module = _module_name(path)
        parts = module.split(".")
        package_dirs.update(".".join(parts[:index]) for index in range(1, len(parts)))

    source_hash = hashlib.sha256()
    for path in source_files:
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        content = path.read_bytes()
        source_hash.update(relative.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError as exc:
            failures.append(f"cannot parse {relative}: {exc}")
            continue

        current_module = _module_name(path)
        is_package = path.name == "__init__.py"
        package_name = current_module if is_package else current_module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in FORBIDDEN_IMPORT_ROOTS:
                        failures.append(f"legacy source import in {relative}: {alias.name}")
                    if alias.name == "neusymnav" or alias.name.startswith("neusymnav."):
                        if alias.name not in modules and alias.name not in package_dirs:
                            failures.append(f"unresolved package import in {relative}: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    target = importlib.util.resolve_name("." * node.level + (node.module or ""), package_name)
                else:
                    target = node.module or ""
                root = target.split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    failures.append(f"legacy source import in {relative}: {target}")
                if target == "neusymnav" or target.startswith("neusymnav."):
                    if target not in modules and target not in package_dirs:
                        failures.append(f"unresolved package import in {relative}: {target}")
            elif isinstance(node, ast.Call) and node.args:
                function = node.func
                is_dynamic_import = (
                    isinstance(function, ast.Attribute) and function.attr == "import_module"
                ) or (isinstance(function, ast.Name) and function.id == "__import__")
                if is_dynamic_import and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    target = node.args[0].value
                    root = target.split(".", 1)[0]
                    if root in FORBIDDEN_IMPORT_ROOTS:
                        failures.append(f"legacy dynamic import in {relative}: {target}")
                    if (target == "neusymnav" or target.startswith("neusymnav.")) and target not in DEFERRED_MODULES:
                        if target not in modules and target not in package_dirs:
                            failures.append(f"unresolved dynamic package import in {relative}: {target}")

        for value in _non_docstring_strings(tree):
            if _USER_PATH.search(value):
                failures.append(f"hardcoded user workspace path in {relative}")
            if any(fragment in value for fragment in ("../NewOH3DSG", "../3DSG/", "NewOH3DSG/", "3DSG/")):
                failures.append(f"hardcoded sibling source path in {relative}")

    return {"python_files": len(source_files), "source_sha256": source_hash.hexdigest()}, failures


def _metadata_audit() -> tuple[dict, list[str]]:
    failures: list[str] = []
    try:
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        return {}, [f"cannot read project dependency metadata: {exc}"]
    dependencies = {item.lower().split("[", 1)[0].split(",", 1)[0].split(">", 1)[0].strip() for item in project.get("dependencies", [])}
    required = {"numpy", "scipy", "pyyaml"}
    missing = sorted(required - dependencies)
    if missing:
        failures.append("core dependency closure is missing: " + ", ".join(missing))
    script = project.get("scripts", {}).get("neusymnav")
    if script != "neusymnav.cli:main":
        failures.append("project script entry point must be neusymnav.cli:main")

    try:
        notices = NOTICES_PATH.read_text(encoding="utf-8").lower()
    except OSError as exc:
        return {"core_dependencies": sorted(dependencies)}, [f"third-party notice file is unavailable: {exc}"]
    required_notice_text = ("does not grant rights", "commercial license")
    absent_notice = [phrase for phrase in required_notice_text if phrase not in notices]
    if "infer further permissions" not in notices or not (
        "does not infer further permissions" in notices
        or re.search(r"did not [^.\n]*infer further permissions", notices)
    ):
        absent_notice.append("a clear statement that no further permissions are inferred")
    if absent_notice:
        failures.append("third-party notices omit required rights caveats: " + ", ".join(absent_notice))

    try:
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"core_dependencies": sorted(dependencies)}, failures + [f"source provenance is unavailable or invalid: {exc}"]
    if provenance.get("schema_version") != 1 or not isinstance(provenance.get("assets"), list):
        failures.append("source provenance does not have the expected schema-v1 asset manifest")
    return {
        "core_dependencies": sorted(dependencies),
        "notice_file": str(NOTICES_PATH.relative_to(PROJECT_ROOT)),
        "provenance_file": str(PROVENANCE_PATH.relative_to(PROJECT_ROOT)),
        "asset_records": len(provenance.get("assets", [])),
    }, failures


def _fixture_smoke() -> dict:
    """Copy source and fixture data to a temporary tree, then run a real CLI replay.

    The fixture is immutable data generated with the package contracts and
    ReplayWriter. The child process runs from an unrelated directory, filters
    the editable source root from sys.path, and blocks opens of either legacy
    source tree or the original package source.
    """
    if not FIXTURE_ROOT.is_dir():
        return {"status": "failed", "error": f"fixture directory is missing: {FIXTURE_ROOT}"}
    for tree, label in ((SOURCE_ROOT, "source package"), (FIXTURE_ROOT, "fixture")):
        links = [path for path in tree.rglob("*") if path.is_symlink()]
        if links:
            return {"status": "failed", "error": f"{label} tree contains symlinks: " + ", ".join(str(path) for path in links)}
    report: dict = {}
    with tempfile.TemporaryDirectory(prefix="neusymnav-source-only-") as temporary:
        temp_root = Path(temporary)
        isolated_source = temp_root / "package" / "src"
        isolated_source.mkdir(parents=True)
        shutil.copytree(
            SOURCE_ROOT,
            isolated_source / "neusymnav",
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        copied_fixtures = temp_root / "fixtures"
        shutil.copytree(FIXTURE_ROOT, copied_fixtures, symlinks=False)
        output = temp_root / "run-output"
        expected_path = copied_fixtures / "expected.json"
        config_path = copied_fixtures / "config.yaml"
        input_path = copied_fixtures / "recording"
        required = (expected_path, config_path, input_path)
        missing = [path.name for path in required if not path.exists()]
        if missing:
            return {"status": "failed", "error": "fixture data is incomplete: " + ", ".join(missing)}

        forbidden_roots = [
            PROJECT_ROOT / "src",
            PROJECT_ROOT.parent / "NewOH3DSG",
            PROJECT_ROOT.parent / "3DSG",
        ]
        code = f"""
import json, os, pathlib, sys
isolated_source = {str(isolated_source)!r}
forbidden_roots = {[str(path.resolve()) for path in forbidden_roots]!r}
def is_within(path, root):
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except (OSError, ValueError, TypeError):
        return False
sys.path[:] = [isolated_source] + [entry for entry in sys.path if entry and not any(is_within(entry, root) for root in forbidden_roots)]
def audit(event, args):
    if event in ('open', 'open_code') and args and isinstance(args[0], (str, bytes, os.PathLike)):
        target = os.fsdecode(args[0])
        if any(is_within(target, root) for root in forbidden_roots):
            raise RuntimeError('isolated runtime attempted to open forbidden source: ' + target)
    if event == 'import' and args:
        name = args[0]
        if isinstance(name, str) and name.split('.', 1)[0] in ('NewOH3DSG', '3DSG', 'standalone_sg'):
            raise RuntimeError('isolated runtime attempted a legacy import: ' + name)
        target = args[1] if len(args) > 1 else None
        if isinstance(target, (str, bytes, os.PathLike)) and any(is_within(os.fsdecode(target), root) for root in forbidden_roots):
            raise RuntimeError('isolated runtime imported module from forbidden source: ' + os.fsdecode(target))
sys.addaudithook(audit)
from neusymnav.cli import main
import neusymnav
if not is_within(neusymnav.__file__, isolated_source):
    raise RuntimeError('neusymnav did not resolve to the copied package')
exit_code = main(['replay', '--input', {str(input_path)!r}, '--config', {str(config_path)!r}, '--out', {str(output)!r}])
for name, module in tuple(sys.modules.items()):
    if name == 'neusymnav' or name.startswith('neusymnav.'):
        module_path = getattr(module, '__file__', None)
        if module_path and not is_within(module_path, isolated_source):
            raise RuntimeError('module escaped copied package: ' + name + ' -> ' + module_path)
if any(is_within(entry, root) for entry in sys.path if entry for root in forbidden_roots):
    raise RuntimeError('original source root remains on sys.path')
raise SystemExit(exit_code)
"""
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        child = subprocess.run(
            [sys.executable, "-I", "-c", code], cwd=temp_root, env=environment,
            capture_output=True, text=True, check=False,
        )
        report["return_code"] = child.returncode
        report["stdout"] = child.stdout.strip()
        report["stderr"] = child.stderr.strip()
        if child.returncode != 0:
            return {"status": "failed", **report}
        try:
            result = json.loads(child.stdout)
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {"status": "failed", **report, "error": f"CLI output or expected fixture is invalid JSON: {exc}"}
        if result.get("outcome") != "completed":
            return {"status": "failed", **report, "error": "isolated fixture replay did not complete"}
        if result.get("mode") != "fixture_cpu_no_models" or result.get("frames") != 1:
            return {"status": "failed", **report, "error": "fixture replay did not report the expected CPU-only source frame"}
        session = result.get("replay_session")
        if not isinstance(session, dict) or not str(session.get("clock_domain", "")).startswith("replay:"):
            return {"status": "failed", **report, "error": "replay output omitted its restored private session clock"}
        summary_path = output / "summary.json"
        try:
            disk_result = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"status": "failed", **report, "error": f"replay summary export is missing or invalid: {exc}"}
        if disk_result != result:
            return {"status": "failed", **report, "error": "stdout result does not match the exported summary"}

        expected_ids = expected.get("object_ids")
        expected_events = expected.get("events")
        if not isinstance(expected_ids, list) or not expected_ids or not isinstance(expected_events, list) or not expected_events:
            return {"status": "failed", **report, "error": "fixture expectation needs canonical IDs and evidence events"}
        if result.get("object_ids") != expected_ids:
            return {"status": "failed", **report, "error": "replay canonical object IDs differ from frozen fixture expectation"}
        expected_event = expected_events[0]
        if not all(key in expected_event for key in ("event_id", "object_id", "source")):
            return {"status": "failed", **report, "error": "fixture expectation contains an incomplete evidence event"}
        object_id = expected_event["object_id"]
        evidence = next((item for item in result.get("events", [])
                         if item.get("event_id") == expected_event["event_id"]), None)
        if evidence is None or evidence.get("object_id") != object_id:
            return {"status": "failed", **report, "error": "replay output omitted the expected object evidence event"}
        source = evidence.get("source") or {}
        expected_source = expected_event.get("source") or {}
        actual_source = {key: source.get(key) for key in ("episode_id", "sensor_id", "frame_index")}
        expected_source = {key: expected_source.get(key) for key in actual_source}
        if actual_source != expected_source:
            return {"status": "failed", **report, "error": "expected evidence event has a different source frame"}
        if result.get("native_runtime_validated") is not False:
            return {"status": "failed", **report, "error": "fixture result must keep native runtime unvalidated"}
        return {
            "status": "passed",
            "return_code": child.returncode,
            "outcome": result.get("outcome"),
            "object_id": object_id,
            "evidence_event_id": expected_event["event_id"],
            "replay_clock_domain": session["clock_domain"],
            "source_frame": {
                "episode_id": expected_source["episode_id"],
                "sensor_id": expected_source["sensor_id"],
                "frame_index": expected_source["frame_index"],
            },
            "unrelated_working_directory": True,
            "source_pythonpath_removed": "PYTHONPATH" not in environment,
            "legacy_source_open_audit": "passed",
        }


def verify_source_only() -> dict:
    source_result, source_failures = _package_source_audit()
    metadata_result, metadata_failures = _metadata_audit()
    failures = source_failures + metadata_failures
    try:
        smoke = _fixture_smoke()
    except Exception as exc:
        smoke = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    if smoke.get("status") != "passed":
        failures.append(smoke.get("error", "isolated fixture replay failed"))
    return {
        "schema_version": 1,
        "mode": "source-only",
        "profile": "fixture_cpu_no_models",
        "source": source_result,
        "packaging": metadata_result,
        "isolated_fixture_replay": smoke,
        "runtime_capabilities": {
            "models": {"available": False, "runtime_validated": False, "reason": "source-only verification does not load model assets"},
            "native": {"available": False, "runtime_validated": False, "reason": "source-only verification does not execute native workers"},
            "simulator": {"available": False, "runtime_validated": False, "reason": "source-only verification uses a recorded RGB-D fixture"},
        },
        "failures": failures,
        "passed": not failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true", help="audit source closure and run copied-package fixture replay")
    args = parser.parse_args(argv)
    if not args.source_only:
        parser.error("--source-only is the only supported verification mode")
    result = verify_source_only()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
