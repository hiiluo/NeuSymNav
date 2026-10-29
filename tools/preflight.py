"""Read-only host import and optional runtime capability preflight."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

REQUIRED_HOST_IMPORTS = ("neusymnav", "numpy", "scipy")
OPTIONAL_CAPABILITY_IMPORTS = {
    "sensor": ("habitat_sim",),
    "detector": ("torch", "ultralytics"),
    "appearance": ("open_clip",),
    "ui": ("PyQt5",),
}


def build_report(
    *,
    python_executable: str,
    python_version: str,
    host_imports: Mapping[str, bool],
    runtime_capabilities: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    missing = sorted(name for name in REQUIRED_HOST_IMPORTS if not host_imports.get(name, False))
    return {
        "schema_version": 1,
        "mode": "contracts-only",
        "host": {
            "python_executable": python_executable,
            "python_version": python_version,
            "imports": {name: bool(host_imports.get(name, False)) for name in REQUIRED_HOST_IMPORTS},
        },
        "contracts": {"ready": not missing, "missing_imports": missing},
        "probe_scope": (
            "current interpreter imports and explicitly declared local asset paths; "
            "declared native candidate path; no alternate interpreter subprocesses, "
            "GPU, network, or worker workloads probed"
        ),
        "runtime_capabilities": {
            name: dict(capability) for name, capability in sorted(runtime_capabilities.items())
        },
        "gpu_probe_performed": False,
        "network_probe_performed": False,
        "preflight_environment_modified": False,
    }


def report_exit_code(report: Mapping[str, Any]) -> int:
    return 0 if report.get("contracts", {}).get("ready") else 1


def _host_import_status() -> dict[str, bool]:
    status: dict[str, bool] = {}
    for name in REQUIRED_HOST_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception:
            status[name] = False
        else:
            status[name] = True
    return status


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _capability(
    modules: tuple[str, ...],
    *,
    asset_path: Path | None = None,
    executable: str | None = None,
    executable_candidates: tuple[Path, ...] = (),
) -> dict[str, Any]:
    missing = [name for name in modules if not _module_exists(name)]
    available = not missing
    result: dict[str, Any] = {
        "available": available,
        "probe_scope": "imports checked in the current interpreter only",
        "required_imports": list(modules),
        "missing_imports": missing,
    }
    if asset_path is not None:
        result["asset_path"] = str(asset_path)
        result["asset_present"] = asset_path.is_file()
        if not asset_path.is_file():
            result["missing_asset"] = True
            available = False
    if executable is not None:
        candidate = next(
            (path.resolve() for path in executable_candidates if path.is_file()),
            None,
        )
        resolved = str(candidate) if candidate is not None else (
            shutil.which(executable) if not Path(executable).is_absolute() else executable
        )
        result["probe_scope"] = "declared candidate path plus named executable PATH lookup"
        result["executable"] = resolved
        result["executable_present"] = bool(resolved and Path(resolved).is_file())
        result["candidate_present"] = result["executable_present"]
        result["execution_validation"] = "not_run"
        result["runtime_validated"] = False
        result["availability_basis"] = (
            "candidate artifact present; native workload execution and parity unverified"
            if result["candidate_present"]
            else "no executable found at declared candidate paths or on PATH"
        )
        if not result["candidate_present"]:
            result["missing_executable"] = True
        # Presence is recorded separately from runtime usability; P00 never
        # invokes the candidate merely to promote it to an available runtime.
        available = False
    result["available"] = available
    return result


def runtime_capabilities(project_root: Path) -> dict[str, dict[str, Any]]:
    workspace_parent = project_root.parent
    capabilities = {
        "sensor": _capability(
            OPTIONAL_CAPABILITY_IMPORTS["sensor"],
            asset_path=workspace_parent
            / "3DSG/assets/scenes/hm3d-00802/wcojb4TFT35.basis.glb",
        ),
        "detector": _capability(
            OPTIONAL_CAPABILITY_IMPORTS["detector"],
            asset_path=workspace_parent
            / "NewOH3DSG/data/models/yoloe/yoloe-11s-seg.pt",
        ),
        "appearance": _capability(
            OPTIONAL_CAPABILITY_IMPORTS["appearance"],
            asset_path=workspace_parent
            / "3DSG/assets/models/openclip/open_clip_model.safetensors",
        ),
        "native_dude": _capability(
            (),
            executable="occusg_dude_worker",
            executable_candidates=(
                workspace_parent
                / "3DSG/prebuilt/linux-x86_64/bin/occusg_dude_worker",
            ),
        ),
        "ui": _capability(OPTIONAL_CAPABILITY_IMPORTS["ui"]),
    }
    for capability in capabilities.values():
        if not capability["available"] and not capability.get("missing_imports"):
            capability["missing_imports"] = []
    alternate_clip = workspace_parent / "NewOH3DSG/weights/clip/ViT-B-32.pt"
    capabilities["appearance"]["alternate_checkpoint_candidate"] = str(alternate_clip)
    capabilities["appearance"]["alternate_checkpoint_present"] = alternate_clip.is_file()
    capabilities["appearance"]["alternate_checkpoint_compatibility"] = "unverified"
    return capabilities


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contracts-only",
        action="store_true",
        help="check CPU host imports and report optional runtime gaps without requiring them",
    )
    args = parser.parse_args(argv)
    if not args.contracts_only:
        parser.error("--contracts-only is the only supported P00 preflight mode")

    project_root = Path(__file__).resolve().parents[1]
    report = build_report(
        python_executable=sys.executable,
        python_version=sys.version.split()[0],
        host_imports=_host_import_status(),
        runtime_capabilities=runtime_capabilities(project_root),
    )
    print(json.dumps(report, indent=2, sort_keys=False))
    return report_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
