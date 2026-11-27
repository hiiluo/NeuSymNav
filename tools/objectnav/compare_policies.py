#!/usr/bin/env python3
"""Compare locked ObjectNav policy outcomes on an exact paired cohort.

This is an offline evaluator. It reads schema-3 outcome JSONL and run locks,
never imports simulator code, and refuses to calculate metrics for incomplete,
invalid, or unmatched episodes.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from neusymnav.objectnav.b0.trace import offline_failure_labels


INVALID_FAILURE_MODES = {"invalid_episode", "start_not_navigable"}
IGNORED_INPUT_KEYS = {
    "options", "trace", "trace_path", "trace_sha256", "run_path", "run_dir",
    "out_dir", "output_dir", "output_path", "trajectory_path", "run_id",
}
PATH_PIN_KEYS = {"path"}
RUN_PATH_KEYS = {"run_path", "run_dir", "out_dir", "output_dir", "output_path", "trajectory_path"}


class PairingError(ValueError):
    """Raised when one or more inputs make a paired comparison invalid."""

    def __init__(self, issues: Sequence[dict[str, Any]]):
        self.issues = list(issues)
        detail = "; ".join(
            f"{issue.get('code', 'invalid_input')}: {issue.get('message', issue)}"
            for issue in self.issues[:4]
        )
        if len(self.issues) > 4:
            detail += f"; and {len(self.issues) - 4} more issue(s)"
        super().__init__(detail or "paired comparison inputs are invalid")


def compare_paired(
    arms: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    iterations: int = 10_000,
    seed: int = 20261114,
    expected_uids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return paired episode/scene bootstrap statistics for matched outcome rows.

    ``expected_uids`` is the exact cohort from a frozen manifest. If omitted,
    every arm must still contain the same exact UID set.
    """
    if not isinstance(arms, Mapping) or len(arms) < 2:
        raise PairingError([_issue("invalid_arms", "at least two named arms are required")])
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations <= 0:
        raise ValueError("iterations must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    names = list(arms)
    issues: list[dict[str, Any]] = []
    if any(not isinstance(name, str) or not name.strip() for name in names):
        issues.append(_issue("invalid_arm_name", "arm names must be non-empty strings"))
    rows_by_arm: dict[str, dict[str, Mapping[str, Any]]] = {}
    for name, rows in arms.items():
        if not isinstance(name, str) or not name.strip():
            continue
        rows_by_arm[name] = _index_rows(name, rows, issues)

    expected: list[str] | None = None
    if expected_uids is not None:
        if isinstance(expected_uids, (str, bytes)):
            issues.append(_issue("invalid_manifest", "expected_uids must be a sequence of UID strings"))
        else:
            expected = list(expected_uids)
            if any(not isinstance(uid, str) or not uid for uid in expected):
                issues.append(_issue("invalid_manifest", "manifest UIDs must be non-empty strings"))
            dupes = sorted({uid for uid in expected if expected.count(uid) > 1})
            issues.extend(_issue("duplicate_manifest_uid", "manifest contains a duplicate UID", uid=uid)
                          for uid in dupes)
            expected = [uid for uid in expected if isinstance(uid, str) and uid]

    union_uids = set().union(*(set(rows) for rows in rows_by_arm.values())) if rows_by_arm else set()
    cohort_uids = set(expected) if expected is not None else union_uids
    if not cohort_uids:
        issues.append(_issue("empty_cohort", "no episode outcomes were supplied"))
    for name, rows in rows_by_arm.items():
        missing = cohort_uids - set(rows)
        extra = set(rows) - cohort_uids
        issues.extend(_issue("missing_uid", "arm is missing a cohort UID", arm=name, uid=uid)
                      for uid in sorted(missing))
        issues.extend(_issue("unexpected_uid", "arm contains a UID outside the frozen cohort", arm=name, uid=uid)
                      for uid in sorted(extra))

    # Metadata is itself paired input: all arms must preserve scene/category
    # for each UID before metrics can be aligned.
    for uid in sorted(cohort_uids):
        present = [(name, rows[uid]) for name, rows in rows_by_arm.items() if uid in rows]
        if len(present) < 2:
            continue
        first_name, first = present[0]
        for field in ("scene", "category"):
            reference = first.get(field)
            for name, row in present[1:]:
                if row.get(field) != reference:
                    issues.append(_issue(
                        f"{field}_mismatch", f"{field} differs for paired UID {uid}",
                        uid=uid, reference_arm=first_name, reference=reference,
                        arm=name, value=row.get(field),
                    ))

    if issues:
        raise PairingError(issues)

    uid_order = expected if expected is not None else sorted(cohort_uids)
    assert uid_order is not None
    scenes = {uid: str(rows_by_arm[names[0]][uid]["scene"]) for uid in uid_order}
    categories = {uid: str(rows_by_arm[names[0]][uid]["category"]) for uid in uid_order}
    scene_labels = np.asarray([scenes[uid] for uid in uid_order])
    without_scene = {scene: scene_labels != scene for scene in sorted(set(scenes.values()))}
    arm_metrics = {
        name: {
            "sr": np.asarray([float(rows_by_arm[name][uid]["success"]) for uid in uid_order], dtype=float),
            "spl": np.asarray([float(rows_by_arm[name][uid]["spl"]) for uid in uid_order], dtype=float),
        }
        for name in names
    }

    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete",
        "cohort": {
            "episodes": len(uid_order),
            "scenes": len(set(scenes.values())),
            "categories": len(set(categories.values())),
            "uids": uid_order,
        },
        "bootstrap": {"iterations": iterations, "seed": seed, "confidence": 0.95,
                      "scene_cluster_weighting": "episode_weighted"},
        "arms": {},
        "pairwise": {},
    }

    for name in names:
        result["arms"][name] = _arm_summary(
            arm_metrics[name], uid_order, scenes, categories, iterations, seed,
        )

    for name in names:
        rows = rows_by_arm[name].values()
        secondary = {}
        for field in ('oracle_success', 'soft_spl', 'path_length_m', 'dtg_start_m'):
            values = [float(row[field]) for row in rows if _finite_metric(row.get(field))]
            secondary[field] = {'samples': len(values), 'mean': float(np.mean(values)) if values else None}
        result["arms"][name]["secondary"] = secondary

    for left, right in itertools.combinations(names, 2):
        left_by_uid = rows_by_arm[left]
        right_by_uid = rows_by_arm[right]
        deltas = {
            "sr": arm_metrics[right]["sr"] - arm_metrics[left]["sr"],
            "spl": arm_metrics[right]["spl"] - arm_metrics[left]["spl"],
        }
        wins = sum(bool(right_by_uid[uid]["success"]) and not bool(left_by_uid[uid]["success"])
                   for uid in uid_order)
        losses = sum(bool(left_by_uid[uid]["success"]) and not bool(right_by_uid[uid]["success"])
                     for uid in uid_order)
        both_success = [uid for uid in uid_order if left_by_uid[uid]["success"] and right_by_uid[uid]["success"]
                        and all(_finite_metric(rows[uid].get("path_length_m"))
                                for rows in (left_by_uid, right_by_uid))]
        path_delta = [right_by_uid[uid]["path_length_m"] - left_by_uid[uid]["path_length_m"]
                      for uid in both_success]
        result["pairwise"][f"{left} -> {right}"] = {
            "arm_a": left,
            "arm_b": right,
            "episodes": len(uid_order),
            "both_success_path_m": {
                "samples": len(path_delta),
                "delta": float(np.mean(path_delta)) if path_delta else None,
            },
            "mcnemar": {"wins": wins, "losses": losses,
                        "p_exact_two_sided": _mcnemar_exact_two_sided(wins, losses)},
            "leave_one_scene_out": {
                scene: {"episodes": int(keep.sum()),
                        **{f"{metric}_delta": float(values[keep].mean())
                           for metric, values in deltas.items()}}
                for scene, keep in without_scene.items() if keep.any()
            },
            "metrics": {
                metric: _paired_metric_summary(values, uid_order, scenes, iterations, seed)
                for metric, values in deltas.items()
            },
        }

    return result


def _finite_metric(value):
    return isinstance(value, (bool, int, float)) and math.isfinite(value)


def _index_rows(name: str, rows: Sequence[Mapping[str, Any]], issues: list[dict[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        issues.append(_issue("invalid_arm_rows", "arm outcomes must be a sequence", arm=name))
        return indexed
    if not rows:
        issues.append(_issue("empty_arm", "arm contains no outcomes", arm=name))
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            issues.append(_issue("invalid_row", "outcome row must be an object", arm=name, row=index))
            continue
        uid = row.get("uid")
        if not isinstance(uid, str) or not uid:
            issues.append(_issue("invalid_value", "outcome UID must be a non-empty string", arm=name, row=index))
            continue
        if uid in indexed:
            issues.append(_issue("duplicate_uid", "arm contains duplicate outcome UID", arm=name, uid=uid))
            continue
        indexed[uid] = row
        for field in ("scene", "category"):
            if not isinstance(row.get(field), str) or not row[field]:
                issues.append(_issue("invalid_value", f"{field} must be a non-empty string", arm=name, uid=uid))
        if type(row.get("success")) is not bool:
            issues.append(_issue("invalid_value", "success must be a boolean", arm=name, uid=uid))
        spl = row.get("spl")
        if isinstance(spl, bool) or not isinstance(spl, (int, float)) or not math.isfinite(float(spl)) or not 0 <= float(spl) <= 1:
            issues.append(_issue("invalid_value", "spl must be a finite number in [0, 1]", arm=name, uid=uid))
        for field in ("called_stop",):
            if field in row and type(row[field]) is not bool:
                issues.append(_issue("invalid_value", f"{field} must be a boolean when present", arm=name, uid=uid))
        if row.get("failure_mode") in INVALID_FAILURE_MODES:
            issues.append(_issue("invalid_episode", "scorer marked episode as invalid", arm=name, uid=uid,
                                 failure_mode=row.get("failure_mode")))
    return indexed


def _arm_summary(metrics, uid_order, scenes, categories, iterations, seed):
    summary: dict[str, Any] = {"episodes": len(uid_order), "scene_count": len(set(scenes.values())),
                               "category_count": len(set(categories.values())), "metrics": {}}
    for metric, values in metrics.items():
        summary["metrics"][metric] = _mean_ci_summary(values, uid_order, scenes, iterations, seed)
    groups = {}
    for field, labels in (("scene", scenes), ("category", categories)):
        group_values: dict[str, list[int]] = defaultdict(list)
        for index, uid in enumerate(uid_order):
            group_values[labels[uid]].append(index)
        groups[field] = {}
        for label in sorted(group_values):
            indexes = group_values[label]
            group_uids = [uid_order[index] for index in indexes]
            groups[field][label] = {
                "episodes": len(indexes),
                "metrics": {
                    metric: _mean_ci_summary(values[indexes], group_uids,
                                             {uid: scenes[uid] for uid in group_uids},
                                             iterations, seed)
                    for metric, values in metrics.items()
                },
            }
    summary["by_scene"] = groups["scene"]
    summary["by_category"] = groups["category"]
    categories_summary = list(groups["category"].values())
    summary["macro_by_category"] = {
        metric: float(np.mean([entry["metrics"][metric]["mean"] for entry in categories_summary]))
        for metric in metrics
    }
    return summary


def _mean_ci_summary(values, uid_order, scenes, iterations, seed):
    values = np.asarray(values, dtype=float)
    episode_low, episode_high = _episode_bootstrap_ci(values, iterations, seed)
    scene_low, scene_high = _scene_bootstrap_ci(values, uid_order, scenes, iterations, seed)
    return {"mean": float(np.mean(values)),
            "episode_ci95": [episode_low, episode_high],
            "scene_cluster_ci95": [scene_low, scene_high]}


def _paired_metric_summary(values, uid_order, scenes, iterations, seed):
    values = np.asarray(values, dtype=float)
    low, high = _episode_bootstrap_ci(values, iterations, seed)
    scene_low, scene_high = _scene_bootstrap_ci(values, uid_order, scenes, iterations, seed)
    return {"delta": float(np.mean(values)), "episode_ci95": [low, high],
            "scene_cluster_ci95": [scene_low, scene_high]}


def _episode_bootstrap_ci(values: np.ndarray, iterations: int, seed: int) -> tuple[float, float]:
    if len(values) == 1:
        value = float(values[0])
        return value, value
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(values), size=(iterations, len(values)))
    means = values[samples].mean(axis=1)
    return _percentile_ci(means)


def _scene_bootstrap_ci(values: np.ndarray, uid_order, scenes, iterations: int, seed: int) -> tuple[float, float]:
    names = sorted({scenes[uid] for uid in uid_order})
    if len(names) == 1:
        value = float(np.mean(values))
        return value, value
    positions = {uid: index for index, uid in enumerate(uid_order)}
    sums = np.asarray([sum(float(values[positions[uid]]) for uid in uid_order if scenes[uid] == scene)
                        for scene in names], dtype=float)
    counts = np.asarray([sum(scenes[uid] == scene for uid in uid_order) for scene in names], dtype=float)
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(names), size=(iterations, len(names)))
    resampled = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)
    return _percentile_ci(resampled)


def _percentile_ci(samples: np.ndarray) -> tuple[float, float]:
    low, high = np.quantile(samples, [0.025, 0.975])
    return float(low), float(high)


def _mcnemar_exact_two_sided(wins: int, losses: int) -> float:
    discordant = wins + losses
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(wins, losses) + 1))
    return min(1.0, (2.0 * tail) / (2 ** discordant))


def _issue(code: str, message: str, **details) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lock_resume_key(run_info: dict, inputs: dict) -> str:
    payload = json.dumps([run_info, inputs], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _normalize_inputs(value, key: str | None = None):
    if isinstance(value, Mapping):
        normalized = {}
        for child_key in sorted(value):
            lowered = str(child_key).lower()
            if lowered in IGNORED_INPUT_KEYS:
                continue
            normalized[child_key] = _normalize_inputs(value[child_key], str(child_key))
        return normalized
    if isinstance(value, list):
        return [_normalize_inputs(item) for item in value]
    # File pins compare by content; location can vary between run folders.
    if key in PATH_PIN_KEYS and isinstance(value, str):
        return "<pinned-file-path>"
    if key in RUN_PATH_KEYS and isinstance(value, str):
        return "<run-path>"
    return value


def _diff_paths(left, right, prefix="inputs"):
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        differences = []
        for key in sorted(set(left) | set(right), key=str):
            path = f"{prefix}.{key}"
            if key not in left or key not in right:
                differences.append(path)
            else:
                differences.extend(_diff_paths(left[key], right[key], path))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [prefix]
        differences = []
        for index, (a, b) in enumerate(zip(left, right)):
            differences.extend(_diff_paths(a, b, f"{prefix}[{index}]"))
        return differences
    return [] if left == right else [prefix]


def _read_outcomes(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    issues = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    issues.append(_issue("invalid_jsonl", "could not parse outcome line", path=str(path),
                                         line=line_number, error=str(exc)))
                    continue
                rows.append(row)
    except OSError as exc:
        issues.append(_issue("outcomes_unreadable", "could not read outcome JSONL", path=str(path),
                             error=str(exc)))
    return rows, issues


def _read_manifest(path: Path) -> tuple[list[str] | None, list[dict[str, Any]]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [_issue("manifest_unreadable", "could not read frozen manifest", path=str(path),
                             error=str(exc))]
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        return None, [_issue("invalid_manifest", "manifest must be a schema-version-1 object", path=str(path))]
    uids = manifest.get("uids")
    if not isinstance(uids, list) or any(not isinstance(uid, str) or not uid for uid in uids):
        return None, [_issue("invalid_manifest", "manifest uids must be a list of non-empty strings", path=str(path))]
    if len(set(uids)) != len(uids):
        duplicates = sorted(uid for uid in set(uids) if uids.count(uid) > 1)
        return None, [_issue("duplicate_manifest_uid", "manifest contains duplicate UIDs", uid=uid)
                      for uid in duplicates]
    if not uids:
        return None, [_issue("empty_manifest", "frozen manifest has no UIDs", path=str(path))]
    return uids, []


def _read_lock(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    lock_path = path.parent / "baseline-lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [_issue("lock_unreadable", "could not read sibling baseline-lock.json",
                             path=str(lock_path), error=str(exc))]
    if (not isinstance(lock, Mapping) or lock.get("schema_version") != 1
            or not isinstance(lock.get("inputs"), Mapping)
            or not isinstance(lock.get("run_info"), Mapping)
            or not isinstance(lock.get("resume_key"), str)):
        return None, [_issue("invalid_lock", "lock must contain schema_version, inputs, run_info, resume_key",
                             path=str(lock_path))]
    try:
        expected = _lock_resume_key(dict(lock["run_info"]), dict(lock["inputs"]))
    except (TypeError, ValueError) as exc:
        return None, [_issue("invalid_lock", "lock cannot be canonically hashed", path=str(lock_path),
                             error=str(exc))]
    if lock["resume_key"] != expected:
        return None, [_issue("invalid_lock", "resume_key does not match lock content", path=str(lock_path))]
    return dict(lock), []


def _manifest_pin_issue(lock: Mapping[str, Any], manifest_path: Path) -> dict[str, Any] | None:
    pin = lock["inputs"].get("manifest")
    if not isinstance(pin, Mapping) or not isinstance(pin.get("sha256"), str):
        return _issue("manifest_pin_missing", "run lock does not pin the frozen manifest",
                      path=str(manifest_path))
    try:
        actual = _sha256(manifest_path)
    except OSError as exc:
        return _issue("manifest_unreadable", "could not hash frozen manifest", path=str(manifest_path),
                      error=str(exc))
    if pin["sha256"] != actual:
        return _issue("manifest_pin_mismatch", "run lock manifest hash differs from supplied manifest",
                      path=str(manifest_path), locked_sha256=pin["sha256"], actual_sha256=actual)
    return None


def _trajectory_diagnostics(path, outcomes):
    """Join offline outcomes with optional guarded trajectory evidence by UID."""
    candidates = (path.parent / "trajectories+evidence.jsonl", path.parent / "trajectories.jsonl")
    source = next((item for item in candidates if item.is_file()), None)
    if source is None:
        return {"status": "unavailable", "reason": "missing trajectories"}
    rows, errors = _read_outcomes(source)
    if errors or any(not isinstance(row, dict) or not isinstance(row.get("uid"), str) for row in rows):
        return {"status": "unavailable", "reason": "invalid trajectories"}
    by_uid = {row["uid"]: row for row in rows}
    expected = {row["uid"] for row in outcomes}
    if len(by_uid) != len(rows) or set(by_uid) != expected:
        return {"status": "unavailable", "reason": "trajectory UID mismatch"}
    counts, stop_counts, result = defaultdict(int), defaultdict(int), {}
    for row in outcomes:
        trajectory = by_uid[row["uid"]]
        evidence = trajectory.get("evidence") or {}
        diagnostics = trajectory.get("diagnostics") or {}
        stop = (diagnostics.get("policy") or {}).get("stop") or {}
        note = stop.get("note")
        if not trajectory.get("called_stop"):
            stop_kind = "no_stop"
        else:
            stop_kind = {"STOP_VERIFIED": "verified_target", "stuck": "legacy_failure",
                         "frontiers_exhausted": "legacy_failure", "confirmed_target": "legacy_target",
                         "fallback_target": "legacy_target"}.get(note, "other_stop")
        stop_counts[stop_kind] += 1
        labels = offline_failure_labels(row, evidence, diagnostics)
        for label in labels:
            counts[label] += 1
        result[row["uid"]] = {"failure_labels": labels, "evidence_available": "target_seen" in evidence,
                               "target_seen": evidence.get("target_seen"),
                               "target_detected": evidence.get("target_detected"),
                               "confirmed_goal": evidence.get("confirmed_goal"),
                               "committed_goal": evidence.get("committed_goal"),
                               "stop_kind": stop_kind, "stop_note": note,
                               "executed_commands": diagnostics.get("executed_commands"),
                               "end_reason": diagnostics.get("end_reason")}
    return {"status": "available", "source": str(source), "label_counts": dict(counts),
            "stop_counts": dict(stop_counts), "by_uid": result}


def _write_json(path: Path, value: Mapping[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _markdown_report(report: Mapping[str, Any]) -> str:
    lines = ["# Paired ObjectNav policy comparison", ""]
    if report.get("status") != "complete":
        lines += ["Status: **declined**", "", "## Input issues", ""]
        lines.extend(f"- `{issue.get('code')}`: {issue.get('message')}" for issue in report.get("issues", []))
        return "\n".join(lines) + "\n"
    cohort = report["cohort"]
    lines += [f"Status: **complete** — {cohort['episodes']} paired episodes, "
              f"{cohort['scenes']} scenes, {cohort['categories']} categories.", "",
              "## Arms", "", "| Arm | n | SR | SPL | Macro SR | Macro SPL |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, arm in report["arms"].items():
        lines.append(
            f"| {name} | {arm['episodes']} | {arm['metrics']['sr']['mean']:.4f} | "
            f"{arm['metrics']['spl']['mean']:.4f} | {arm['macro_by_category']['sr']:.4f} | "
            f"{arm['macro_by_category']['spl']:.4f} |"
        )
    lines += ["", "## Paired comparisons", "", "Positive deltas favor arm B; scene-cluster intervals retain episode weighting.", "",
              "| A → B | Metric | Δ | Episode bootstrap 95% CI | Scene-cluster 95% CI |",
              "|---|---|---:|---:|---:|"]
    for label, comparison in report["pairwise"].items():
        for metric, stats in comparison["metrics"].items():
            lines.append(f"| {label} | {metric.upper()} | {stats['delta']:.4f} | "
                         f"[{stats['episode_ci95'][0]:.4f}, {stats['episode_ci95'][1]:.4f}] | "
                         f"[{stats['scene_cluster_ci95'][0]:.4f}, {stats['scene_cluster_ci95'][1]:.4f}] |")
    lines += ["", "Full per-UID outcomes, subgroup summaries, pins, and diagnostics are in the JSON report.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", action="append", required=True, metavar="NAME=PATH",
                        help="arm outcome JSONL; each file needs a sibling baseline-lock.json")
    parser.add_argument("--manifest", type=Path, required=True, help="schema-1 JSON file with ordered uids")
    parser.add_argument("--out", type=Path, required=True, help="output paired JSON report path")
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20261114)
    args = parser.parse_args(argv)

    issues: list[dict[str, Any]] = []
    arm_paths: dict[str, Path] = {}
    for spec in args.arm:
        if "=" not in spec:
            issues.append(_issue("invalid_arm_argument", "--arm must be NAME=PATH", value=spec))
            continue
        name, raw_path = spec.split("=", 1)
        if not name.strip() or not raw_path:
            issues.append(_issue("invalid_arm_argument", "--arm must have a non-empty name and path", value=spec))
            continue
        if name in arm_paths:
            issues.append(_issue("duplicate_arm", "arm name was supplied more than once", arm=name))
            continue
        arm_paths[name] = Path(raw_path)
    if len(arm_paths) < 2:
        issues.append(_issue("invalid_arms", "at least two distinct --arm values are required"))

    expected_uids, manifest_issues = _read_manifest(args.manifest)
    issues.extend(manifest_issues)
    arm_rows: dict[str, list[dict[str, Any]]] = {}
    arm_locks: dict[str, dict[str, Any]] = {}
    for name, path in arm_paths.items():
        rows, row_issues = _read_outcomes(path)
        arm_rows[name] = rows
        issues.extend({**issue, "arm": name} for issue in row_issues)
        lock, lock_issues = _read_lock(path)
        issues.extend({**issue, "arm": name} for issue in lock_issues)
        if lock is not None:
            arm_locks[name] = lock
            manifest_issue = _manifest_pin_issue(lock, args.manifest)
            if manifest_issue:
                issues.append({**manifest_issue, "arm": name})

    normalized_locks = {name: _normalize_inputs(lock["inputs"])
                        for name, lock in arm_locks.items()}
    if len(normalized_locks) == len(arm_paths) and normalized_locks:
        reference_name = next(iter(normalized_locks))
        reference = normalized_locks[reference_name]
        for name, normalized in normalized_locks.items():
            if normalized != reference:
                issues.append(_issue(
                    "pins_mismatch", "common locked inputs differ between arms",
                    reference_arm=reference_name, arm=name,
                    paths=_diff_paths(reference, normalized),
                ))

    try:
        if len(arm_rows) >= 2:
            paired = compare_paired(arm_rows, iterations=args.iterations, seed=args.seed,
                                    expected_uids=expected_uids)
        else:
            paired = None
    except PairingError as exc:
        issues.extend(exc.issues)
        paired = None
    except ValueError as exc:
        issues.append(_issue("invalid_comparison_options", str(exc)))
        paired = None

    if issues or paired is None:
        diagnostic = {
            "schema_version": 1,
            "status": "declined",
            "manifest": str(args.manifest),
            "arms": {name: str(path) for name, path in arm_paths.items()},
            "issues": issues or [_issue("comparison_unavailable", "comparison could not be computed")],
        }
        _write_json(args.out, diagnostic)
        md_path = args.out.with_suffix(".md")
        md_path.write_text(_markdown_report(diagnostic), encoding="utf-8")
        print(f"comparison declined; see {args.out}", file=sys.stderr)
        return 2

    paired["inputs"] = {
        "manifest": {"path": str(args.manifest), "sha256": _sha256(args.manifest)},
        "common_inputs_sha256": hashlib.sha256(json.dumps(
            next(iter(normalized_locks.values())), sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest(),
        "arms": {
            name: {
                "outcomes": str(path),
                "outcomes_sha256": _sha256(path),
                "baseline_lock": str(path.parent / "baseline-lock.json"),
                "baseline_lock_sha256": _sha256(path.parent / "baseline-lock.json"),
                "run_info": arm_locks[name]["run_info"],
            }
            for name, path in arm_paths.items()
        },
    }
    paired["outcomes"] = {
        name: [{key: (None if isinstance(value, float) and not math.isfinite(value) else value)
                for key, value in row.items()} for row in arm_rows[name]]
        for name in arm_paths
    }
    paired["diagnostics"] = {name: _trajectory_diagnostics(path, arm_rows[name])
                             for name, path in arm_paths.items()}
    _write_json(args.out, paired)
    args.out.with_suffix(".md").write_text(_markdown_report(paired), encoding="utf-8")
    print(f"wrote paired comparison: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
