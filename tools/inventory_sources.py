"""Build a content-hashed inventory of an explicitly selected source closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
}
_IGNORED_SUFFIXES = {
    ".d",
    ".nbc",
    ".nbi",
    ".obj",
    ".o",
    ".orig",
    ".pyc",
    ".pyo",
}
_LICENSE_NAMES = {"COPYING", "LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE"}
_REPOSITORY_ANCHORS = {"3DSG", "NewOH3DSG"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_anchor(path: Path) -> Path | None:
    for parent in reversed((path, *path.parents)):
        if parent.name in _REPOSITORY_ANCHORS:
            return parent
    return None


def _root_label(root: Path, duplicate_names: set[str]) -> str:
    anchor = _repository_anchor(root)
    if anchor is not None:
        return root.as_posix()[len(anchor.parent.as_posix()) + 1 :]
    label = root.name
    if label in duplicate_names and root.parent.name:
        return f"{root.parent.name}/{label}"
    return label


def _candidate_files(root: Path) -> Iterable[tuple[Path, str | None]]:
    if root.is_file():
        if root.is_symlink():
            yield root, "symbolic links are not followed or hashed"
        elif root.name in _LICENSE_NAMES:
            return
        elif root.suffix.lower() not in _IGNORED_SUFFIXES:
            yield root, None
        return

    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in _IGNORED_DIRS
            and not (current_path / name).is_symlink()
        )
        for name in sorted(files):
            path = current_path / name
            if name in _LICENSE_NAMES:
                continue
            if path.suffix.lower() in _IGNORED_SUFFIXES:
                continue
            if path.is_symlink():
                yield path, "symbolic links are not followed or hashed"
            elif path.is_file():
                yield path, None


def _license_evidence(path: Path, scope_root: Path, inventory_root: Path) -> dict[str, Any]:
    current = path.parent
    while True:
        candidates = [current / name for name in sorted(_LICENSE_NAMES)]
        # FIST's restrictive notice is embedded in its makefile. The DuDe
        # parent README is a paper citation, not that component's notice.
        if "FIST" in path.parts and current.name == "FIST":
            candidates.append(current / "makefile")
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                return {
                    "status": "notice_present",
                    "path": candidate.relative_to(inventory_root).as_posix()
                    if candidate.is_relative_to(inventory_root)
                    else os.path.relpath(candidate, inventory_root).replace(os.sep, "/"),
                    "sha256": _sha256(candidate),
                }
        if current == scope_root or current.parent == current:
            break
        current = current.parent
    return {"status": "not_found", "path": None, "sha256": None}


def inventory_sources(roots: tuple[Path, ...]) -> dict[str, Any]:
    """Hash every regular file beneath explicitly selected roots.

    Roots may be files or directories. Paths in the result are portable and
    relative to their declared root. Generated caches and symbolic links are
    excluded from hashing.
    """

    normalized_roots = tuple(Path(root).expanduser().absolute() for root in roots)
    for root in normalized_roots:
        if not root.exists():
            raise FileNotFoundError(f"inventory root does not exist: {root}")
        if root.is_symlink():
            raise ValueError(f"inventory root must not be a symbolic link: {root}")

    names: dict[str, int] = {}
    for root in normalized_roots:
        names[root.name] = names.get(root.name, 0) + 1
    duplicate_names = {name for name, count in names.items() if count > 1}

    files: list[dict[str, Any]] = []
    for root in normalized_roots:
        root_label = _root_label(root, duplicate_names)
        inventory_root = root if root.is_dir() else root.parent
        scope_root = _repository_anchor(root) or inventory_root
        for path, deferred_reason in _candidate_files(root):
            relative = (
                path.relative_to(root).as_posix()
                if root.is_dir()
                else path.name
            )
            selected = deferred_reason is None
            files.append(
                {
                    "root": root_label,
                    "path": relative,
                    "sha256": _sha256(path) if selected else None,
                    "size_bytes": path.stat().st_size if selected else None,
                    "selection": "selected" if selected else "deferred",
                    "reason": (
                        "root explicitly included in the audited source closure"
                        if selected
                        else deferred_reason
                    ),
                    "origin": "local filesystem snapshot",
                    "license": _license_evidence(path, scope_root, inventory_root),
                }
            )

    files.sort(key=lambda item: (item["root"], item["path"]))
    selected_count = sum(item["selection"] == "selected" for item in files)
    deferred_count = len(files) - selected_count
    return {
        "schema_version": 1,
        "files": files,
        "summary": {
            "selected_files": selected_count,
            "deferred_files": deferred_count,
        },
    }


def _source_roots(workspace_parent: Path) -> tuple[Path, ...]:
    new = workspace_parent / "NewOH3DSG"
    three = workspace_parent / "3DSG"
    fusion = three / "projects/Fusion_Concept_OccuSG"
    exploration = three / "projects/3DSG/exploration"
    rebuild = three / "projects/Rebuild_3DScene_OccuSG"
    dude_package = (
        rebuild
        / "ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2"
    )
    dude_final = dude_package / "Third_Party/dude_final"

    roots: list[Path] = [
        three / "ASSET_MANIFEST.json",
        three / "prebuilt/linux-x86_64/SHA256SUMS.json",
        new / "core",
        new / "association",
        new / "scene_graph",
        new / "recording",
        new / "simulation/habitat_adapter.py",
        new / "simulation/pose_provider.py",
        new / "simulation/controller.py",
        new / "mapping/grid.py",
        new / "mapping/occupancy.py",
        new / "mapping/projection.py",
        new / "mapping/raycast_kernel.py",
        new / "mapping/tile_archive.py",
        new / "perception/base.py",
        new / "perception/yoloe.py",
        new / "perception/local_text.py",
        new / "perception/verification.py",
        new / "perception/best_view.py",
        new / "visualization/hierarchy_graph.py",
        new / "visualization/best_view_gallery.py",
        new / "runtime/health.py",
        new / "runtime/online_verification.py",
        new / "runtime/process_detector.py",
        new / "runtime/queues.py",
        new / "runtime/scheduler.py",
        new / "runtime/semantic_pipeline.py",
        new / "runtime/supervisor.py",
        new / "evaluation/gt_isolation.py",
        new / "evaluation/graph_metrics.py",
        new / "evaluation/metrics.py",
        new / "evaluation/m3_box_quality.py",
        new / "evaluation/protocol.py",
        new / "evaluation/replay_integrity.py",
        new / "configs/perception/selected_backend.json",
        new / "configs/evaluation/indoor-v1-taxonomy.json",
        fusion / "src/standalone_sg/contracts",
        fusion / "src/standalone_sg/config/schema.py",
        fusion / "src/standalone_sg/geometry",
        fusion / "src/standalone_sg/objects",
        fusion / "src/standalone_sg/regions",
        fusion / "src/standalone_sg/rooms",
        fusion / "integration_v2/perception_feature_sessions.py",
        fusion / "scripts/extract_u2_appearance.py",
        fusion / "integration_v2/unified_scene_graph.py",
        fusion / "ref_ConceptGraph/concept-graphs/LICENSE",
        fusion / "ref_ConceptGraph/concept-graphs/conceptgraph/slam/mapping.py",
        fusion / "ref_ConceptGraph/concept-graphs/conceptgraph/slam/utils.py",
    ]
    roots.extend(
        exploration / name
        for name in (
            "contracts.py",
            "habitat_online.py",
            "habitat_factory.py",
            "controller.py",
            "depth_safety.py",
            "desktop.py",
            "frontier.py",
            "graph_bridge.py",
            "keyframe_policy.py",
            "keyframe_scheduler.py",
            "keyframe_store.py",
            "live_dashboard.py",
            "planner.py",
            "policy.py",
            "scene_graph_provider.py",
        )
    )
    roots.extend(
        (
            rebuild / "native/dude",
            rebuild / "native/CMakeLists.txt",
            dude_package / "include",
            dude_package / "package.xml",
            dude_package / "Third_Party/dude_final/src",
            dude_package / "Third_Party/dude_final/mathtool",
            dude_package / "Third_Party/dude_final/README",
            dude_package / "Third_Party/dude_final/FIST/triangulate.h",
            dude_package / "Third_Party/dude_final/FIST/header.h",
            dude_package / "Third_Party/dude_final/FIST/makefile",
            dude_package / "Third_Party/dude_final/FIST/libFIST.linux64.a",
            rebuild / "native/dude/CMakeLists.txt",
            rebuild / "locks/sources.json",
            rebuild / "ref_OccuSG/OccuSG/LICENSE",
            rebuild / "configs/habitat/hm3d_minival_v02_00802_main_route.json",
            rebuild / "configs/perception/yolo11n_seg_replica_cad_dev.json",
        )
    )
    return tuple(roots)


def _asset_record(
    workspace_parent: Path,
    relative_path: str,
    *,
    selection: str,
    reason: str,
    license_status: str,
    license_evidence: str | None = None,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
    technical_status: str | None = None,
    compatibility: str | None = None,
) -> dict[str, Any]:
    path = (workspace_parent / relative_path).resolve()
    present = path.is_file()
    base: dict[str, Any] = {
        "path": relative_path,
        "present": present,
        "selection": selection,
        "reason": reason,
        "origin": "locally present workspace asset" if present else "declared local asset path",
        "license": {"status": license_status, "evidence": license_evidence},
    }
    base["sha256"] = _sha256(path) if present else None
    base["size_bytes"] = path.stat().st_size if present else None
    if expected_sha256 is not None:
        base["expected_sha256_from_ASSET_MANIFEST"] = expected_sha256
    if expected_size_bytes is not None:
        base["expected_size_bytes_from_ASSET_MANIFEST"] = expected_size_bytes
    if technical_status is not None:
        base["technical_status"] = technical_status
    if compatibility is not None:
        base["compatibility"] = compatibility
    return base


def build_source_provenance(workspace_parent: Path) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[1]
    inventory = inventory_sources(_source_roots(workspace_parent))
    assets = [
        _asset_record(
            workspace_parent,
            "NewOH3DSG/data/models/yoloe/yoloe-11s-seg.pt",
            selection="selected",
            reason="YOLOE11s is the proposed detector baseline; model execution remains blocked by missing imports.",
            license_status="declared_AGPL-3.0_in_selected_backend_config",
            license_evidence="NewOH3DSG/configs/perception/selected_backend.json",
        ),
        _asset_record(
            workspace_parent,
            "NewOH3DSG/data/models/yoloe/mobileclip_blt.ts",
            selection="selected",
            reason="Text encoder referenced by the selected YOLOE11s profile.",
            license_status="not_found_in_selected_profile",
            license_evidence="NewOH3DSG/configs/perception/selected_backend.json",
        ),
        _asset_record(
            workspace_parent,
            "3DSG/assets/scenes/hm3d-00802/wcojb4TFT35.basis.glb",
            selection="selected",
            reason="Available HM3D v0.2 minival scene candidate for sensor replay; Habitat runtime is missing.",
            license_status="academic_noncommercial_note_in_route_config",
            license_evidence="3DSG/projects/Rebuild_3DScene_OccuSG/configs/habitat/hm3d_minival_v02_00802_main_route.json",
        ),
        _asset_record(
            workspace_parent,
            "3DSG/assets/scenes/hm3d-00802/wcojb4TFT35.basis.navmesh",
            selection="selected",
            reason="Route-only support asset; prohibited as predictor/map free-space input by architecture.",
            license_status="academic_noncommercial_note_in_route_config",
            license_evidence="3DSG/projects/Rebuild_3DScene_OccuSG/configs/habitat/hm3d_minival_v02_00802_main_route.json",
        ),
        _asset_record(
            workspace_parent,
            "3DSG/assets/scenes/hm3d-00802/demo.scene_dataset_config.json",
            selection="selected",
            reason="HM3D scene dataset metadata pinned by ASSET_MANIFEST; no Habitat load performed.",
            license_status="academic_noncommercial_note_in_route_config",
            license_evidence="3DSG/projects/Rebuild_3DScene_OccuSG/configs/habitat/hm3d_minival_v02_00802_main_route.json",
            expected_sha256="22d0485c749193e19e4ac0502610d51a9022183a3387f36395630ae6dd30a9f4",
            expected_size_bytes=503,
        ),
        _asset_record(
            workspace_parent,
            "3DSG/assets/models/openclip/checkpoint_metadata.json",
            selection="deferred",
            reason="Metadata for the declared optional OpenCLIP appearance profile; profile remains off for the baseline.",
            license_status="not_assessed_in_P00",
            expected_sha256="f25cb4ac28807fc8734ab5d1db2764ead5a2db902c301d59eae6656bb9c1db04",
            expected_size_bytes=645,
        ),
        _asset_record(
            workspace_parent,
            "3DSG/assets/models/openclip/open_clip_model.safetensors",
            selection="deferred",
            reason="OpenCLIP checkpoint declared in the local asset manifest but absent; appearance profile is optional.",
            license_status="not_assessed_in_P00",
            expected_sha256="e6d1bd7789aa45192b3bf90570a789b478bae1b74ebcce7eddd908e83a2b7c31",
            expected_size_bytes=605143284,
            technical_status="missing at declared path",
        ),
        _asset_record(
            workspace_parent,
            "NewOH3DSG/weights/clip/ViT-B-32.pt",
            selection="deferred",
            reason="Alternate local CLIP checkpoint; format/model compatibility with declared OpenCLIP safetensors is unverified.",
            license_status="not_assessed_in_P00",
            compatibility="unverified",
        ),
        _asset_record(
            workspace_parent,
            "3DSG/prebuilt/linux-x86_64/bin/occusg_dude_worker",
            selection="selected candidate",
            reason="Prebuilt native DuDe worker candidate listed by ASSET_MANIFEST; not invoked in P00.",
            license_status="native_source_and_FIST_rights_unresolved; no redistribution permission inferred",
            license_evidence="3DSG/projects/Rebuild_3DScene_OccuSG/ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2/package.xml and Third_Party/dude_final/FIST/makefile",
            expected_sha256="e41f5824c70b968f65b71a448ff46dde47450cb4a3027892f31c569717a96125",
            expected_size_bytes=787712,
            technical_status="present; dynamic libraries resolved by ldd; execution and parity unverified",
        ),
        _asset_record(
            workspace_parent,
            "3DSG/prebuilt/linux-x86_64/lib/libgmp.so.10",
            selection="selected native dependency",
            reason="Bundled library declared by ASSET_MANIFEST and resolved by the native worker ldd probe.",
            license_status="GMP license status not assessed in P00",
            expected_sha256="0ccdfb6d6f5c039465f6d002cf7e4c072d48ac6a2cffc8dd6c748dec31592804",
            expected_size_bytes=534896,
        ),
        _asset_record(
            workspace_parent,
            "3DSG/prebuilt/linux-x86_64/lib/libmpfr.so.6",
            selection="selected native dependency",
            reason="Bundled library declared by ASSET_MANIFEST and resolved by the native worker ldd probe.",
            license_status="MPFR license status not assessed in P00",
            expected_sha256="2156351fa3dedd04a7381c6ac7a8a26efa2d6fb08b80f8a2d644ccdd653710ae",
            expected_size_bytes=760464,
        ),
        _asset_record(
            workspace_parent,
            "3DSG/prebuilt/linux-x86_64/bin/standalone_sg_octomap_fixture_runner",
            selection="deferred",
            reason="Native fixture runner listed in ASSET_MANIFEST; deferred pending later worker/runtime tasks.",
            license_status="native source/dependency rights unresolved",
            expected_sha256="c132c842d42e0d4127dff0f34721dbfa703c688f66e7cf4f12d655137e3a62c1",
            expected_size_bytes=371064,
            technical_status="not invoked in P00",
        ),
        _asset_record(
            workspace_parent,
            "3DSG/assets/models/yolo11n-seg.onnx",
            selection="deferred",
            reason="Legacy/reference detector asset; YOLOE11s is the proposed NeuSymNav baseline.",
            license_status="AGPL-3.0_note_in_reference_profile_local_use_only",
            license_evidence="3DSG/projects/Rebuild_3DScene_OccuSG/configs/perception/yolo11n_seg_replica_cad_dev.json",
        ),
    ]
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace": "NeuSym-Nav/NeuSymNav and read-only sibling sources",
        "snapshot_method": "SHA-256 of current filesystem bytes; no source Git commit assumed",
        "scope": {
            "selected_source_files": inventory["summary"]["selected_files"],
            "deferred_source_files": inventory["summary"]["deferred_files"],
            "source_inventory_is_exhaustive": False,
            "omitted": [
                "unselected source modules",
                "runs and caches",
                "datasets and unrelated model weights",
                "generated binaries except the selected FIST archive",
            ],
        },
        "source_resolution": {
            "newoh3dsg": "../NewOH3DSG; selected core, association, map, graph, runtime and recording modules",
            "fusion_python": "../3DSG/projects/Fusion_Concept_OccuSG/src/standalone_sg",
            "fusion_integration": "../3DSG/projects/Fusion_Concept_OccuSG/integration_v2",
            "native_dude": "../3DSG/projects/Rebuild_3DScene_OccuSG/native/dude",
            "native_upstream": "../3DSG/projects/Rebuild_3DScene_OccuSG/ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2",
            "resolution_rule": "Use Fusion standalone_sg for Python region/contracts source; build native DuDe only from Rebuild_3DScene_OccuSG. Do not mix the two standalone_sg package roots on one sys.path.",
            "source_git_commit": None,
        },
        "baseline_profiles": [
            {
                "id": "core-frontier-yoloe11s",
                "selection": "selected candidate",
                "detector": "YOLOE11s",
                "appearance": "off",
                "scene": "HM3D v0.2 minival 00802 local candidate",
                "runtime_status": "blocked: habitat_sim, torch, and ultralytics are unavailable in the probed interpreters; no runtime workload executed",
                "quality_status": "not validated in NeuSymNav",
            },
            {
                "id": "appearance-openclip",
                "selection": "deferred optional profile",
                "detector": "YOLOE11s",
                "appearance": "OpenCLIP ViT-B/32",
                "runtime_status": "blocked: open_clip is unavailable; manifest-pinned safetensors checkpoint is absent and alternate local checkpoint compatibility is unverified",
                "quality_status": "not validated in NeuSymNav",
            },
            {
                "id": "geometry-only",
                "selection": "deferred ablation profile",
                "detector": "same canonical owner with appearance off; deterministic fixture detector for CPU correctness tests",
                "appearance": "off",
                "runtime_status": "contract/fixture profile only until later task integration",
                "quality_status": "not validated in NeuSymNav",
            },
        ],
        "runtime_probe": {
            "host_python": ".venv/bin/python 3.12.3; neusymnav, numpy, scipy imports passed",
            "alternate_interpreters": [
                {
                    "path": "/home/hiiluo08/miniforge3/bin/python",
                    "python_version": "3.13.13",
                    "optional_imports_missing": ["habitat_sim", "torch", "ultralytics", "open_clip"],
                    "probe_log": "runs/p00-main/alternate-runtime-probe.log",
                },
                {
                    "path": "/home/hiiluo08/.local/share/uv/python/cpython-3.10.21-linux-x86_64-gnu/bin/python",
                    "python_version": "3.10.21",
                    "optional_imports_missing": ["habitat_sim", "torch", "ultralytics", "open_clip"],
                    "probe_log": "runs/p00-main/alternate-runtime-probe.log",
                },
            ],
            "scope": "read-only bounded environment and declared-config audit; no GPU inference or environment installation",
            "environment_audit": "runs/p00-main/environment-audit.json",
            "environment_search_scope": ["Works", "Desktop", "Documents", ".local", ".conda", "miniforge3/envs", "Conda environments.txt", "source runtime configs"],
            "known_interpreters_optional_imports_missing": ["habitat_sim", "torch", "ultralytics", "open_clip"],
            "declared_legacy_runtime_paths": "checked and absent; see environment-audit.json",
            "native_worker": "prebuilt candidate present and ldd dependencies resolved; execution not run",
        },
        "assets": assets,
        "licenses": [
            {
                "component": "NewOH3DSG source",
                "status": "no top-level LICENSE/NOTICE found in selected source scope",
                "action": "retain filesystem hashes; do not infer redistribution permission",
            },
            {
                "component": "Fusion standalone_sg and integration_v2 source",
                "status": "no top-level LICENSE/NOTICE found in selected source scope",
                "action": "retain filesystem hashes; do not infer redistribution permission",
            },
            {
                "component": "ConceptGraphs mapping reference",
                "status": "MIT license file present",
                "evidence": "../3DSG/projects/Fusion_Concept_OccuSG/ref_ConceptGraph/concept-graphs/LICENSE",
            },
            {
                "component": "OccuSG baseline source",
                "status": "MIT license file present; does not resolve separately bundled dependencies",
                "evidence": "../3DSG/projects/Rebuild_3DScene_OccuSG/ref_OccuSG/OccuSG/LICENSE",
            },
            {
                "component": "Incremental DuDe package",
                "status": "package.xml declares TODO; no package-specific license resolved",
                "evidence": "../3DSG/projects/Rebuild_3DScene_OccuSG/ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2/package.xml",
            },
            {
                "component": "FIST archive and headers",
                "status": "bundled FIST/makefile notice restricts use to non-commercial internal institutional/academic use; duplication, alteration, sale, redistribution require prior written consent; commercial use requires a commercial license",
                "evidence": "../3DSG/projects/Rebuild_3DScene_OccuSG/ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2/Third_Party/dude_final/FIST/makefile",
                "archive_sha256": "84875da959aae5a1abdddc993075d0f91d4afdbdda1a29dd856f77254a63c684",
                "permission_inferred": False,
            },
            {
                "component": "mathtool",
                "status": "license file referenced by upstream metadata but absent from inspected package scope",
                "permission_inferred": False,
            },
            {
                "component": "CGAL",
                "status": "required by Rebuild native DuDe CMake target; ../3DSG/third_party/m4-prefix exists, but package-specific licensing and prefix compatibility remain unresolved",
                "permission_inferred": False,
            },
            {
                "component": "OctoMap",
                "status": "New BSD per Rebuild source lock and installed system package; deferred extension, not the selected DuDe target",
                "version": "1.9.7+dfsg-3.1build3",
            },
            {
                "component": "HM3D v0.2 minival scene",
                "status": "local route config records academic non-commercial use and publication EULA notice; semantic GT files are absent from selected asset directory",
                "permission_inferred": False,
            },
        ],
        "inventory": inventory,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/source-provenance.json"),
        help="JSON output path (default: docs/source-provenance.json)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        help="optional text summary path for the P00 run log",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    workspace_parent = project_root.parent
    manifest = build_source_provenance(workspace_parent)
    output = args.output if args.output.is_absolute() else project_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    message = (
        f"wrote {output}; selected_source_files="
        f"{manifest['scope']['selected_source_files']}; assets={len(manifest['assets'])}"
    )
    print(message)
    if args.log:
        log_path = args.log if args.log.is_absolute() else project_root / args.log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(message + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
