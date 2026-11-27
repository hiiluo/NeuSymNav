import hashlib
import json
from pathlib import Path

import pytest

from tools.objectnav.compare_policies import PairingError, compare_paired, main


def outcomes(successes, spls=None, *, prefix="ep"):
    spls = spls or [float(success) for success in successes]
    return [
        {
            "uid": f"{prefix}-{index}",
            "scene": f"scene-{index % 2}",
            "category": "chair" if index % 2 else "sofa",
            "called_stop": bool(success),
            "success": bool(success),
            "spl": float(spls[index]),
            "failure_mode": None,
        }
        for index, success in enumerate(successes)
    ]


def pair_key(left, right):
    return f"{left} -> {right}"


def write_run(path: Path, rows, *, name, options_digest, manifest_digest="manifest-pin", root="/same/root"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    inputs = {
        "dataset": {
            "root": root,
            "files": [{"path": f"{root}/dataset.json.gz", "sha256": "dataset-pin"}],
        },
        "manifest": {"path": f"{root}/manifest.json", "sha256": manifest_digest},
        "detector": {
            "options": {"path": f"{path.parent}/options.json", "sha256": options_digest},
            "trace": {"path": f"{path.parent}/trace.jsonl", "sha256": name},
        },
        "run_path": str(path.parent),
    }
    run_info = {"run_id": name, "out_dir": str(path.parent), "trace_path": f"{path.parent}/trace.jsonl"}
    resume_key = hashlib.sha256(
        json.dumps([run_info, inputs], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    (path.parent / "baseline-lock.json").write_text(json.dumps({
        "schema_version": 1,
        "inputs": inputs,
        "run_info": run_info,
        "resume_key": resume_key,
    }))
    return path


def test_four_episode_paired_success_rate_delta_is_exact():
    baseline = outcomes([False, False, True, True], [0.0, 0.0, 0.4, 0.6])
    candidate = outcomes([True, False, True, True], [0.2, 0.0, 0.5, 0.7])

    report = compare_paired({"B0": baseline, "C": candidate}, iterations=200, seed=9)

    comparison = report["pairwise"][pair_key("B0", "C")]
    assert comparison["metrics"]["sr"]["delta"] == pytest.approx(0.25)
    assert comparison["metrics"]["spl"]["delta"] == pytest.approx(0.1)
    assert comparison["mcnemar"] == {"wins": 1, "losses": 0, "p_exact_two_sided": 1.0}


def test_paired_sensitivity_excludes_each_scene_in_turn():
    baseline = outcomes([False, True, False, False])
    candidate = outcomes([True, True, True, False], [0.5, 1.0, 0.7, 0.0])
    report = compare_paired({'B0': baseline, 'Full': candidate}, iterations=20)
    sensitivity = report['pairwise']['B0 -> Full']['leave_one_scene_out']
    assert sensitivity['scene-0'] == {'episodes': 2, 'sr_delta': 0., 'spl_delta': 0.}
    assert sensitivity['scene-1']['episodes'] == 2
    assert sensitivity['scene-1']['sr_delta'] == 1.
    assert sensitivity['scene-1']['spl_delta'] == pytest.approx(.6)


def test_missing_manifest_uid_declines_comparison_and_reports_it():
    with pytest.raises(PairingError) as caught:
        compare_paired(
            {"B0": outcomes([False, True]), "C": outcomes([True, True])[:1]},
            expected_uids=["ep-0", "ep-1"],
        )

    assert any(issue["code"] == "missing_uid" and issue["uid"] == "ep-1"
               for issue in caught.value.issues)


@pytest.mark.parametrize("field,value", [("scene", "other-scene"), ("category", "bed")])
def test_scene_and_category_must_match_for_each_uid(field, value):
    baseline = outcomes([False])
    candidate = outcomes([False])
    candidate[0][field] = value

    with pytest.raises(PairingError) as caught:
        compare_paired({"B0": baseline, "C": candidate})

    assert any(issue["code"] == f"{field}_mismatch" for issue in caught.value.issues)


@pytest.mark.parametrize("mutate,expected_code", [
    (lambda rows: rows.append(dict(rows[0])), "duplicate_uid"),
    (lambda rows: rows[0].update(spl=float("nan")), "invalid_value"),
    (lambda rows: rows[0].update(success=1), "invalid_value"),
    (lambda rows: rows[0].update(failure_mode="invalid_episode"), "invalid_episode"),
])
def test_duplicate_or_invalid_outcomes_decline_without_dropping_rows(mutate, expected_code):
    baseline = outcomes([False])
    mutate(baseline)

    with pytest.raises(PairingError) as caught:
        compare_paired({"B0": baseline, "C": outcomes([False])})

    assert any(issue["code"] == expected_code for issue in caught.value.issues)


def test_all_ties_have_zero_paired_intervals_and_exact_mcnemar():
    rows = outcomes([False, True, False, True], [0.0, 0.6, 0.0, 0.7])

    report = compare_paired({"B0": rows, "C": [dict(row) for row in rows]}, iterations=300, seed=17)

    comparison = report["pairwise"][pair_key("B0", "C")]
    assert comparison["mcnemar"] == {"wins": 0, "losses": 0, "p_exact_two_sided": 1.0}
    for metric in comparison["metrics"].values():
        assert metric["delta"] == 0.0
        assert metric["episode_ci95"] == [0.0, 0.0]
        assert metric["scene_cluster_ci95"] == [0.0, 0.0]


def test_paired_bootstrap_is_deterministic_for_same_seed():
    arms = {"B0": outcomes([False, False, True, True]), "C": outcomes([True, False, False, True])}

    first = compare_paired(arms, iterations=500, seed=20261114)
    second = compare_paired(arms, iterations=500, seed=20261114)

    assert first == second


def test_cli_accepts_only_intended_lock_variation_and_writes_report(tmp_path):
    rows_b0 = outcomes([False, False, True, True])
    rows_c = outcomes([True, False, True, True])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "uids": [row["uid"] for row in rows_b0]}))
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    path_b0 = write_run(tmp_path / "b0" / "outcomes.jsonl", rows_b0,
                        name="b0", options_digest="b0-options", manifest_digest=manifest_digest)
    path_c = write_run(tmp_path / "c" / "outcomes.jsonl", rows_c,
                       name="c", options_digest="c-options", manifest_digest=manifest_digest)
    output = tmp_path / "paired.json"

    result = main([
        "--arm", f"B0={path_b0}", "--arm", f"C={path_c}",
        "--manifest", str(manifest), "--out", str(output), "--iterations", "100",
    ])

    assert result == 0
    written = json.loads(output.read_text())
    assert written["status"] == "complete"
    assert written["cohort"]["episodes"] == 4
    assert (tmp_path / "paired.md").is_file()


def test_cli_declines_common_input_pin_mismatch_and_writes_diagnostic(tmp_path):
    rows = outcomes([False, True])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "uids": [row["uid"] for row in rows]}))
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    path_b0 = write_run(tmp_path / "b0" / "outcomes.jsonl", rows,
                        name="b0", options_digest="b0-options", manifest_digest=manifest_digest)
    path_c = write_run(tmp_path / "c" / "outcomes.jsonl", rows,
                       name="c", options_digest="c-options", manifest_digest=manifest_digest)
    lock_path = path_c.parent / "baseline-lock.json"
    lock = json.loads(lock_path.read_text())
    lock["inputs"]["manifest"]["sha256"] = "different-manifest-pin"
    info, inputs = lock["run_info"], lock["inputs"]
    lock["resume_key"] = hashlib.sha256(
        json.dumps([info, inputs], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    lock_path.write_text(json.dumps(lock))
    output = tmp_path / "declined.json"

    result = main([
        "--arm", f"B0={path_b0}", "--arm", f"C={path_c}",
        "--manifest", str(manifest), "--out", str(output),
    ])

    assert result != 0
    written = json.loads(output.read_text())
    assert written["status"] == "declined"
    assert any(issue["code"] == "pins_mismatch" for issue in written["issues"])


def test_secondary_metrics_preserve_missing_values_and_paired_efficiency():
    base = outcomes([True, False])
    full = outcomes([True, False])
    for row, meters in ((base[0], 4.), (full[0], 3.)):
        row.update(oracle_success=True, soft_spl=.7, path_length_m=meters, dtg_start_m=2.)
    report = compare_paired({'B0': base, 'Full': full}, iterations=10)
    assert report['arms']['B0']['secondary']['oracle_success']['samples'] == 1
    pair = report['pairwise']['B0 -> Full']['both_success_path_m']
    assert pair['samples'] == 1 and pair['delta'] == pytest.approx(-1.)


def test_trajectory_report_distinguishes_verified_and_failure_stop(tmp_path):
    from tools.objectnav.compare_policies import _trajectory_diagnostics

    rows = outcomes([True, False, False])
    records = [{'uid': row['uid'], 'called_stop': index < 2,
                'diagnostics': {'policy': {'stop': {'note': note}}}}
               for index, (row, note) in enumerate(zip(rows, ('STOP_VERIFIED', 'stuck', None)))]
    path = tmp_path / 'trajectories.jsonl'
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    report = _trajectory_diagnostics(tmp_path / 'outcomes.jsonl', rows)
    assert report['stop_counts'] == {'verified_target': 1, 'legacy_failure': 1, 'no_stop': 1}
