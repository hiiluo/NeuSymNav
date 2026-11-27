import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path('tools/reasoninggraph/check_paper_parity.py')


def run(tmp_path, off, shadow, uids=('a', 'b')):
    for name, rows in [('off', off), ('shadow', shadow)]:
        (tmp_path / (name + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (tmp_path / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'uids': list(uids)}))
    result = subprocess.run([sys.executable, str(SCRIPT), '--manifest', str(tmp_path / 'manifest.json'),
                             '--off', str(tmp_path / 'off.jsonl'), '--shadow', str(tmp_path / 'shadow.jsonl'),
                             '--position-tolerance', '0.001'], capture_output=True, text=True)
    return result, json.loads(result.stdout)


def row(uid='a'):
    return {'schema_version': 1, 'uid': uid, 'steps': 1, 'called_stop': True,
            'positions': [[0, 0, 0], [1, 0, 0]],
            'diagnostics': {'actions': {'stop': 1}, 'protocol_sha256': 'abc'}}


def test_missing_evidence_and_episode_never_pass_or_shrink_denominator(tmp_path):
    result, report = run(tmp_path, [row()], [row()])
    assert result.returncode == 2
    assert report['denominator'] == 2
    assert report['episodes']['a']['checks']['action_sequence'] == 'unavailable'
    assert report['episodes']['a']['checks']['safety_reasons'] == 'unavailable'
    assert report['episodes']['b']['status'] == 'unavailable'
    assert report['status'] == 'unavailable'


def test_divergence_is_failure_even_when_other_evidence_unavailable(tmp_path):
    changed = row()
    changed['called_stop'] = False
    changed['positions'][1][0] = 2
    result, report = run(tmp_path, [row()], [changed], ('a',))
    assert result.returncode == 1
    assert report['status'] == 'fail'
    assert report['episodes']['a']['checks']['called_stop'] == 'fail'
    assert report['episodes']['a']['checks']['positions'] == 'fail'


def test_duplicate_uid_is_invalid_input(tmp_path):
    result, report = run(tmp_path, [row(), row()], [row()], ('a',))
    assert result.returncode == 2
    assert report['status'] == 'unavailable'
    assert 'duplicate' in report['error']


def test_ordered_audit_detects_action_order_with_equal_action_counts(tmp_path):
    from copy import deepcopy

    left = row()
    left.update(steps=3, positions=[[0, 0, 0]] * 4)
    left['diagnostics']['actions'] = {'turn_left': 1, 'turn_right': 1, 'stop': 1}
    left['diagnostics']['action_audit'] = dict(schema_version=1, steps=[
        dict(input_step=index, result_step=index + 1, dispatched_action=action,
             collided=False, simulator_done=(action == 'stop'))
        for index, action in enumerate(('turn_left', 'turn_right', 'stop'))
    ])
    right = deepcopy(left)
    steps = right['diagnostics']['action_audit']['steps']
    steps[0]['dispatched_action'], steps[1]['dispatched_action'] = 'turn_right', 'turn_left'
    result, report = run(tmp_path, [left], [right], ('a',))
    assert result.returncode == 1
    assert report['episodes']['a']['checks']['action_sequence'] == 'fail'
    assert report['episodes']['a']['checks']['action_counts'] == 'pass'


def test_worker_receipt_proves_dispatch_and_rejects_mismatched_execution(tmp_path):
    from copy import deepcopy

    off = row()
    off['diagnostics']['action_audit'] = dict(schema_version=1, steps=[
        dict(input_step=0, result_step=1, requested_action='stop', dispatched_action='stop',
             collided=False, simulator_done=True,
             simulator_execution=dict(schema_version=1, action='stop', reason='episode_stopped'))])
    _, evidence = run(tmp_path, [off], [off], ('a',))
    checks = evidence['episodes']['a']['checks']
    assert checks['requested_vs_simulator_command'] == checks['simulator_safety_outcomes'] == 'pass'
    assert checks['safety_reasons'] == 'unavailable'
    changed = deepcopy(off)
    changed['diagnostics']['action_audit']['steps'][0]['simulator_execution']['action'] = 'turn_left'
    result, evidence = run(tmp_path, [off], [changed], ('a',))
    assert result.returncode == 1
    assert evidence['episodes']['a']['checks']['requested_vs_simulator_command'] == 'fail'


def test_missing_native_collision_bit_is_unavailable(tmp_path):
    off = row()
    off['diagnostics']['action_audit'] = dict(schema_version=1, steps=[
        dict(input_step=0, result_step=1, requested_action='turn_left', dispatched_action='turn_left',
             collided=False, simulator_done=True,
             simulator_execution=dict(schema_version=1, action='turn_left', reason='collision_flag_unavailable'))])
    _, evidence = run(tmp_path, [off], [off], ('a',))
    checks = evidence['episodes']['a']['checks']
    assert checks['requested_vs_simulator_command'] == 'pass'
    assert checks['simulator_safety_outcomes'] == 'unavailable'


def test_terminal_without_dispatch_is_included_in_parity(tmp_path):
    from copy import deepcopy

    off = row()
    off.update(steps=0, called_stop=False, positions=[[0, 0, 0]])
    pose = dict(robot_xy=[0., 0.], z_m=0., yaw_rad=0., tilt_rad=0.)
    pin = dict(calibration_id='cal', pose_version=0, arrays_sha256='a'*64, geometry_sha256='b'*64,
               key=dict(schema_version=1, payload=dict(type='FrameKey',
                        fields=dict(sensor_id='sensor', frame_index=0))))
    off['diagnostics']['action_audit'] = dict(schema_version=1, steps=[], terminal_observation=dict(
        input_step=0, input_source=pin, input_pose=pose, reason='unreachable', planner_decisions=[]))
    shadow = deepcopy(off)
    shadow['diagnostics']['action_audit']['terminal_observation']['reason'] = 'another_terminal_reason'
    result, report = run(tmp_path, [off], [shadow], ('a',))
    assert result.returncode == 1
    assert report['episodes']['a']['checks']['terminal_decision'] == 'fail'
