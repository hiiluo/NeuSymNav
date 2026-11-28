import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/psg_nav/compare_live_ablation.py'
UID = 'hm3d_v2/val/scene/0#1'


def fixture(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps({'uids': [UID]}))
    for arm in ('off', 'shadow', 'probabilistic'):
        base = tmp_path / arm
        (base / 'trace').mkdir(parents=True)
        inputs = {key: {'sha256': 'same'} for key in ('source', 'dataset', 'manifest', 'runner_config', 'detector', 'habitat')}
        inputs['semantic_candidates'] = {'mode': arm, 'config': {}, 'interpreter': 'same'}
        (base / 'baseline-lock.json').write_text(json.dumps({'inputs': inputs}))
        policy = {'semantic_candidates': {'mode': arm, 'decisions': [], 'native_tap': {'clean_shutdown': True}}, 'events': [], 'stop': None}
        traj = {'uid': UID, 'positions': [[0, 0, 0]], 'steps': 1, 'called_stop': False, 'sim_time_s': 1, 'diagnostics': {'policy': policy}}
        (base / 'trajectories.jsonl').write_text(json.dumps(traj) + '\n')
        score = {'uid': UID, 'scene': 'scene', 'success': False, 'spl': 0., 'soft_spl': 0., 'dtg_end_m': 2.}
        (base / 'score-outcomes.jsonl').write_text(json.dumps(score) + '\n')
        row = {'kind': 'decision', 'uid': UID, 'cycle': 0, 'requested': [0., 0.], 'guarded': [0., 0.], 'guard_reason': 'blocked', 'worker_reason': 'expired_or_zero', 'executor_actions': [], 'executor_executed': False, 'executor_proof_validated': False, 'pose_delta_m': 0., 'yaw_delta_rad': 0., 'state_after': 'SPIN'}
        summary = {'kind': 'summary', 'aborted': False, 'dropped': 0, 'cycles': 1}
        (base / 'trace/t.jsonl').write_text(json.dumps(row) + '\n' + json.dumps(summary) + '\n')
    return tmp_path


def run(root):
    proc = subprocess.run([sys.executable, str(SCRIPT), '--manifest', str(root / 'manifest.json'), '--root', str(root), '--out', str(root / 'report.json')], capture_output=True, text=True)
    return proc, json.loads((root / 'report.json').read_text()) if (root / 'report.json').exists() else None


def test_complete_no_applied_or_stop_is_negative_observation(tmp_path):
    proc, report = run(fixture(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert report['status'] == 'pass'
    assert report['b2']['applied'] == 0
    assert report['b2']['stop'] == 0
    assert report['coverage']['expected'] == 1


def test_missing_score_is_unavailable(tmp_path):
    root = fixture(tmp_path)
    (root / 'probabilistic/score-outcomes.jsonl').unlink()
    proc, report = run(root)
    assert proc.returncode == 2
    assert report['status'] == 'unavailable'
    assert report['coverage']['arms']['probabilistic']['scores'] == 0


def test_off_shadow_motion_mismatch_fails(tmp_path):
    root = fixture(tmp_path)
    p = root / 'shadow/trace/t.jsonl'
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    rows[0]['requested'] = [0., 1.]
    p.write_text(''.join(json.dumps(x) + '\n' for x in rows))
    proc, report = run(root)
    assert proc.returncode == 1
    assert report['status'] == 'fail'


def test_zero_guard_with_action_is_violation(tmp_path):
    root = fixture(tmp_path)
    p = root / 'probabilistic/trace/t.jsonl'
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    rows[0]['executor_actions'] = [{'action': 'turn_left'}]
    rows[0]['executor_executed'] = True
    rows[0]['executor_proof_validated'] = True
    p.write_text(''.join(json.dumps(x) + '\n' for x in rows))
    proc, report = run(root)
    assert proc.returncode == 1
    assert any('zero_guard' in x for x in report['violations'])


def test_stale_applied_rank_is_failure(tmp_path):
    root = fixture(tmp_path)
    p = root / 'probabilistic/trajectories.jsonl'
    traj = json.loads(p.read_text())
    traj['diagnostics']['policy']['semantic_candidates']['decisions'] = [{'cycle': 0, 'ranked': [1], 'eligible': [1], 'reachable_rank': 1, 'deterministic': 1, 'applied': 1, 'decision_ns': 3_000_000_001, 'source_ns': 0, 'policy_frame': 1, 'source_frame': 1}]
    p.write_text(json.dumps(traj) + '\n')
    proc, report = run(root)
    assert proc.returncode == 1
    assert report['b2']['stale'] == 1


def test_stop_requires_post_verify_observation(tmp_path):
    root = fixture(tmp_path)
    p = root / 'probabilistic/trajectories.jsonl'
    traj = json.loads(p.read_text())
    traj['called_stop'] = True
    traj['diagnostics']['policy']['stop'] = {'cid': 1, 'cycle': 0, 'note': 'confirmed_target'}
    p.write_text(json.dumps(traj) + '\n')
    proc, report = run(root)
    assert proc.returncode == 1
    assert any('prior VERIFY' in x for x in report['violations'])


def test_shadow_does_not_apply_semantic_choice(tmp_path):
    root = fixture(tmp_path)
    p = root / 'shadow/trajectories.jsonl'
    traj = json.loads(p.read_text())
    traj['diagnostics']['policy']['semantic_candidates']['decisions'] = [{'deterministic': 1, 'applied': 2}]
    p.write_text(json.dumps(traj) + '\n')
    proc, report = run(root)
    assert proc.returncode == 1
    assert any('shadow' in x for x in report['violations'])


def test_score_scene_and_stop_must_match_trajectory(tmp_path):
    root = fixture(tmp_path)
    p = root / 'probabilistic/score-outcomes.jsonl'
    score = json.loads(p.read_text())
    score['called_stop'] = True
    p.write_text(json.dumps(score) + '\n')
    proc, report = run(root)
    assert proc.returncode == 1
    assert any('score STOP' in x for x in report['violations'])


def test_missing_parity_field_is_unavailable(tmp_path):
    root = fixture(tmp_path)
    p = root / 'shadow/trace/t.jsonl'
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    del rows[0]['requested']
    p.write_text(''.join(json.dumps(x) + '\n' for x in rows))
    proc, report = run(root)
    assert proc.returncode != 0


def test_different_profile_pins_cannot_pass(tmp_path):
    root = fixture(tmp_path)
    for arm in ('off', 'shadow', 'probabilistic'):
        inputs = {key: {'sha256': 'same'} for key in ('source', 'dataset', 'manifest', 'runner_config', 'detector', 'habitat')}
        inputs['semantic_candidates'] = {'mode': arm, 'config': {}, 'interpreter': 'same'}
        if arm == 'shadow':
            inputs['detector'] = {'sha256': 'different'}
        (root / arm / 'baseline-lock.json').write_text(json.dumps({'inputs': inputs}))
    proc, report = run(root)
    assert proc.returncode == 1
    assert any('detector' in x for x in report['violations'])


def test_executed_action_requires_pose_measurement(tmp_path):
    root = fixture(tmp_path)
    p = root / 'probabilistic/trace/t.jsonl'
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    rows[0].update(guarded=[0., 1.], executor_actions=[{'action': 'turn_left'}], executor_executed=True, executor_proof_validated=True, pose_delta_m=None)
    p.write_text(''.join(json.dumps(x) + '\n' for x in rows))
    proc, report = run(root)
    assert proc.returncode != 0
    assert any('pose' in x for x in report['violations'] + report['missing'])


def test_identically_rejected_starts_remain_in_the_episode_denominator(tmp_path):
    root = fixture(tmp_path)
    for arm in ('off', 'shadow', 'probabilistic'):
        base = root / arm
        traj = {'uid': UID, 'positions': [[0, 0, 0]], 'steps': 0, 'called_stop': False,
                'sim_time_s': 0.0, 'evidence': {'start_not_navigable': True},
                'diagnostics': {'end_reason': 'start_not_navigable_for_robot',
                                'start_snap': {'navigable': False}}}
        (base / 'trajectories.jsonl').write_text(json.dumps(traj) + '\n')
        score = json.loads((base / 'score-outcomes.jsonl').read_text())
        score.update(failure_mode='start_not_navigable', dtg_end_m=None)
        (base / 'score-outcomes.jsonl').write_text(json.dumps(score) + '\n')
        (base / 'trace/t.jsonl').unlink()
    proc, report = run(root)
    assert proc.returncode == 0, (proc.stderr, report)
    assert report['coverage']['expected'] == 1
    assert report['coverage']['rejected_start_uids'] == [UID]
    assert report['paired_deltas_b2_minus_off'][0]['delta']['sr'] == 0
    assert report['paired_deltas_b2_minus_off'][0]['delta']['dtg_m'] is None
