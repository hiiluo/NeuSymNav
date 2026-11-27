import json

import pytest

from neusymnav.objectnav.b0.trace import DecisionTrace, TraceWriter, completed_uids, resume_key
from neusymnav.objectnav.runner import LockstepRunner
from test_objectnav_runner import FakeSensor, ForwardPolicy, config, episode, identity_snap


def test_resume_key_pins_order_and_assets():
    run = {'episodes': ['one', 'two'], 'policy': 'b0'}
    lock = {'assets': {'scene': 'abc', 'navmesh': 'def'}}
    assert resume_key(run, lock) == resume_key(dict(reversed(list(run.items()))), lock)
    assert resume_key(run, lock) != resume_key({**run, 'episodes': ['two', 'one']}, lock)
    assert resume_key(run, lock) != resume_key(run, {'assets': {'scene': 'changed'}})


def test_trajectory_partial_tail_is_saved_and_duplicates_fail(tmp_path):
    out = tmp_path / 'trajectories.jsonl'
    row = json.dumps({'uid': 'one', 'run_id': 'run'})
    out.write_text(row + '\n{"uid":')
    assert completed_uids(out, {'one', 'two'}, 'run') == {'one'}
    assert out.read_text() == row + '\n'
    assert (tmp_path / 'trajectory-recovery.jsonl').read_text()
    out.write_text(row + '\n' + row + '\n')
    with pytest.raises(ValueError, match='duplicate'):
        completed_uids(out, {'one', 'two'}, 'run')


def test_complete_unterminated_line_is_not_lost(tmp_path):
    out = tmp_path / 'trajectories.jsonl'
    row = json.dumps({'uid': 'one', 'run_id': 'run'})
    out.write_text(row)
    assert completed_uids(out, {'one'}, 'run') == {'one'}
    assert out.read_text() == row + '\n'


def test_trace_cap_keeps_summary(tmp_path):
    path = tmp_path / 'trace.jsonl'
    with TraceWriter(path, limit=1) as trace:
        for cycle in range(2):
            trace.write_trace(DecisionTrace('one', cycle, cycle, 'sim', 'frame', cycle,
                                            reason='bootstrap_blocked', policy_ns=cycle + 1))
    event, summary = map(json.loads, path.read_text().splitlines())
    assert event['cycle'] == 0
    assert summary['dropped'] == 1
    assert summary['reason_counts'] == {'bootstrap_blocked': 2}
    assert summary['policy_latency_ns']['p95'] == 2


def test_trace_has_no_effect_on_actions_or_trajectory(tmp_path):
    outcomes = []
    for enabled in (False, True):
        runner = LockstepRunner(config(), habitat_python='unused', out_dir=tmp_path / str(enabled),
                                run_id='same', policy_factory=ForwardPolicy, sensor_factory=FakeSensor,
                                start_snapper=identity_snap, trace_enabled=enabled, log=lambda *_: None)
        row = json.loads(runner.run([episode()]).read_text())
        outcomes.append(tuple(row[k] for k in ('positions', 'called_stop', 'steps', 'sim_time_s')))
    assert outcomes[0] == outcomes[1]
    trace, = (tmp_path / 'True/trace').glob('*.jsonl')
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert rows[0]['source'] and rows[0]['map_revision'] >= 0
    assert rows[-1]['kind'] == 'summary'


def test_run_lock_rejects_changed_inputs(tmp_path):
    from neusymnav.objectnav.b0.trace import lock_run
    run = {'run_id': 'a', 'episodes': ['one', 'two']}
    inputs = {'source': 'v1', 'policy': {'trace': False}}
    lock_run(tmp_path, run, inputs)
    lock_run(tmp_path, run, inputs)
    saved = (tmp_path / 'run.json').read_bytes()
    with pytest.raises(ValueError, match='different run lock'):
        lock_run(tmp_path, run, {**inputs, 'source': 'v2'})
    assert (tmp_path / 'run.json').read_bytes() == saved


def test_trace_keeps_critical_events_after_detail_cap(tmp_path):
    path = tmp_path / 'trace.jsonl'
    with TraceWriter(path, limit=1) as trace:
        trace.write_trace(DecisionTrace('one', 0, 0, 'sim', 'frame', 0, 'tracking', 1))
        trace.write_trace(DecisionTrace('one', 1, 1, 'sim', 'frame', 1, 'verified', 1), terminal=True)
    event, stop, summary = map(json.loads, path.read_text().splitlines())
    assert stop['reason'] == 'verified'
    assert summary['reason_counts']['verified'] == 1


def test_whitespace_tail_is_removed_before_appending(tmp_path):
    out = tmp_path / 'trajectories.jsonl'
    row = json.dumps({'uid': 'one', 'run_id': 'run'})
    out.write_bytes((row + '\n').encode() + b' \t')
    assert completed_uids(out, {'one'}, 'run') == {'one'}
    assert out.read_bytes() == (row + '\n').encode()


def test_failure_labels_include_verification_with_out_of_range_support():
    from neusymnav.objectnav.b0.trace import offline_failure_labels

    outcome = {'oracle_success': True, 'called_stop': False}
    diagnostics = {'policy': {'events': [{'note': 'VERIFY_OUT_OF_RANGE'}]}}
    assert offline_failure_labels(outcome, {}, diagnostics) == ('MISSED_STOP', 'VERIFY_OUT_OF_RANGE')
