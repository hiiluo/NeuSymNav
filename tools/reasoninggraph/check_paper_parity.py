#!/usr/bin/env python3
"""Compare the evidence available in Paper trajectories and optional action audits."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def load_rows(path):
    rows = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get('schema_version') != 1 or not isinstance(row.get('uid'), str):
            raise ValueError('invalid trajectory row')
        uid = row['uid']
        if uid in rows:
            raise ValueError('duplicate trajectory uid: ' + uid)
        rows[uid] = row
    return rows


def _audit(diag, steps):
    value = diag.get('action_audit')
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        return None
    rows = value.get('steps')
    if not isinstance(rows, list) or type(steps) is not int or len(rows) != steps:
        return None
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or row.get('input_step') != index or row.get('result_step') != index + 1
                or not isinstance(row.get('dispatched_action'), str) or type(row.get('collided')) is not bool
                or type(row.get('simulator_done')) is not bool):
            return None
    return rows


def _source_signature(source):
    if not isinstance(source, dict) or not isinstance(source.get('key'), dict):
        return None
    for field in ('arrays_sha256', 'geometry_sha256'):
        if not isinstance(source.get(field), str) or not re.fullmatch('[0-9a-f]{64}', source[field]):
            return None
    serialized = source['key']
    payload = serialized.get('payload')
    if (type(serialized.get('schema_version')) is not int or serialized['schema_version'] != 1
            or not isinstance(payload, dict) or payload.get('type') != 'FrameKey'):
        return None
    key = payload.get('fields')
    if (not isinstance(key, dict) or not key.get('sensor_id')
            or type(key.get('frame_index')) is not int or not source.get('calibration_id')):
        return None
    return key['sensor_id'], key['frame_index'], source['calibration_id'], source.get('pose_version'), source['arrays_sha256']


def _pose_signature(pose):
    if not isinstance(pose, dict) or not isinstance(pose.get('robot_xy'), list) or len(pose['robot_xy']) != 2:
        return None
    values = (*pose['robot_xy'], pose.get('z_m'), pose.get('yaw_rad'), pose.get('tilt_rad'))
    return values if all(type(x) in (int, float) and math.isfinite(x) for x in values) else None


def _compare_execution(checks, left, right):
    checks['requested_vs_simulator_command'] = 'unavailable'
    checks['simulator_safety_outcomes'] = 'unavailable'

    def receipts(rows):
        result = []
        for row in rows:
            receipt = row.get('simulator_execution')
            if (not isinstance(row.get('requested_action'), str) or not isinstance(receipt, dict)
                    or type(receipt.get('schema_version')) is not int or receipt['schema_version'] != 1
                    or not isinstance(receipt.get('action'), str)):
                return None
            result.append(receipt)
        return result or None

    aa, bb = receipts(left), receipts(right)
    if aa is None or bb is None:
        return
    runs = ((left, aa), (right, bb))
    signatures = [[(row['requested_action'], row['dispatched_action'], receipt['action'])
                   for row, receipt in zip(rows, values)] for rows, values in runs]
    consistent = all(requested == dispatched == executed for sequence in signatures
                     for requested, dispatched, executed in sequence)
    checks['requested_vs_simulator_command'] = 'pass' if consistent and signatures[0] == signatures[1] else 'fail'
    reasons = [[receipt.get('reason') for receipt in values] for _, values in runs]
    for rows, values in runs:
        for row, receipt in zip(rows, values):
            reason = receipt.get('reason')
            if reason == 'collision_flag_unavailable' and receipt['action'] != 'stop' and not row['collided']:
                continue
            expected = ('episode_stopped' if receipt['action'] == 'stop' else
                        'collision_reported' if row['collided'] else 'no_collision_reported')
            if reason != expected or (expected == 'episode_stopped' and
                                      (row['collided'] or not row['simulator_done'])):
                checks['simulator_safety_outcomes'] = 'fail'
                return
    if all('collision_flag_unavailable' not in group for group in reasons):
        checks['simulator_safety_outcomes'] = 'pass' if reasons[0] == reasons[1] else 'fail'


def _compare_terminal(checks, left, right, left_steps, right_steps, tolerance):
    if 'terminal_observation' not in left and 'terminal_observation' not in right:
        return
    if ('terminal_observation' in left) != ('terminal_observation' in right):
        checks['terminal_decision'] = 'fail'
        return
    checks['terminal_decision'] = 'unavailable'
    signatures = []
    for audit, steps in ((left, left_steps), (right, right_steps)):
        row = audit['terminal_observation']
        if (not isinstance(row, dict) or type(row.get('input_step')) is not int
                or row['input_step'] != steps or not isinstance(row.get('reason'), str)
                or not row['reason'] or not _planner_trace(row.get('planner_decisions'))):
            return
        pose, pin = _pose_signature(row.get('input_pose')), _source_signature(row.get('input_source'))
        if pose is None or pin is None:
            return
        signatures.append((pose, pin, row['reason'], row['planner_decisions']))
    a, b = signatures
    equivalent = math.dist(a[0][:3], b[0][:3]) <= tolerance and a[0][3:] == b[0][3:] and a[1:] == b[1:]
    checks['terminal_decision'] = 'pass' if equivalent else 'fail'


def _planner_trace(entries):
    return isinstance(entries, list) and all(
        isinstance(entry, dict) and set(entry) == {'status', 'action', 'relaxed'}
        and entry['status'] in ('moving', 'reached', 'unreachable', 'stuck', 'blocked')
        and type(entry['relaxed']) is bool
        and (isinstance(entry['action'], str) if entry['status'] == 'moving' else entry['action'] is None)
        for entry in entries)


def _compare_audit(checks, left, right, tolerance):
    def values(rows, key):
        return [row[key] for row in rows]

    checks['action_sequence'] = 'pass' if values(left, 'dispatched_action') == values(right, 'dispatched_action') else 'fail'
    checks['collision_outcomes'] = 'pass' if (
        values(left, 'collided') == values(right, 'collided')
        and values(left, 'simulator_done') == values(right, 'simulator_done')) else 'fail'
    _compare_execution(checks, left, right)
    planner = [[row.get('planner_decisions') for row in rows] for rows in (left, right)]
    checks['planner_decisions'] = 'unavailable'
    if all(_planner_trace(entry) for side in planner for entry in side) and any(
            entry for side in planner for entry in side):
        checks['planner_decisions'] = 'pass' if planner[0] == planner[1] else 'fail'
    left_pins, right_pins = ([_source_signature(row.get('input_source')) for row in rows] for rows in (left, right))
    if left_pins and right_pins and all(pin is not None for pin in left_pins + right_pins):
        checks['input_frame_pins'] = 'pass' if left_pins == right_pins else 'fail'
    left_pose, right_pose = ([_pose_signature(row.get(key)) for row in rows
        for key in ('input_pose', 'result_pose')] for rows in (left, right))
    if left_pose and right_pose and all(pose is not None for pose in left_pose + right_pose):
        equivalent = len(left_pose) == len(right_pose) and all(
            math.dist(a[:3], b[:3]) <= tolerance and a[3:] == b[3:] for a, b in zip(left_pose, right_pose))
        checks['full_pose'] = 'pass' if equivalent else 'fail'


def compare(a, b, tolerance):
    checks = {name: 'unavailable' for name in (
        'action_sequence', 'requested_vs_applied_actions', 'safety_reasons',
        'input_frame_pins', 'full_pose', 'called_stop', 'steps', 'positions',
        'action_counts', 'protocol_sha256')}
    for key in ('called_stop', 'steps'):
        valid = (lambda v: type(v) is bool) if key == 'called_stop' else (lambda v: type(v) is int and v >= 0)
        if valid(a.get(key)) and valid(b.get(key)):
            checks[key] = 'pass' if a[key] == b[key] else 'fail'
    da, db = a.get('diagnostics'), b.get('diagnostics')
    if isinstance(da, dict) and isinstance(db, dict):
        for field, check in (('actions', 'action_counts'), ('protocol_sha256', 'protocol_sha256')):
            va, vb = da.get(field), db.get(field)
            valid = (lambda v: isinstance(v, dict) and bool(v) and all(isinstance(k, str) and type(n) is int and n >= 0 for k, n in v.items())) if field == 'actions' else (lambda v: isinstance(v, str) and bool(v))
            if valid(va) and valid(vb):
                checks[check] = 'pass' if va == vb else 'fail'
        aa, ab = _audit(da, a.get('steps')), _audit(db, b.get('steps'))
        if aa is not None and ab is not None:
            _compare_audit(checks, aa, ab, tolerance)
            _compare_terminal(checks, da['action_audit'], db['action_audit'], a['steps'], b['steps'], tolerance)
    def valid_positions(row):
        values, steps = row.get('positions'), row.get('steps')
        return (type(steps) is int and steps >= 0 and isinstance(values, list) and len(values) == steps + 1
                and all(isinstance(p, list) and len(p) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in p) for p in values))
    if valid_positions(a) and valid_positions(b):
        pa, pb = a['positions'], b['positions']
        checks['positions'] = 'pass' if len(pa) == len(pb) and all(math.dist(x, y) <= tolerance for x, y in zip(pa, pb)) else 'fail'
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True, help='Paper manifest with expected uids')
    parser.add_argument('--off', type=Path, required=True)
    parser.add_argument('--shadow', type=Path, required=True)
    parser.add_argument('--position-tolerance', type=float, required=True, help='Euclidean metres, fixed before comparison')
    args = parser.parse_args()
    report = {'status': 'unavailable'}
    try:
        if not math.isfinite(args.position_tolerance) or args.position_tolerance < 0:
            raise ValueError('position tolerance must be finite and nonnegative')
        manifest = json.loads(args.manifest.read_text())
        uids = manifest.get('uids')
        if manifest.get('schema_version') != 1 or not isinstance(uids, list) or not uids or any(not isinstance(u, str) or not u for u in uids) or len(set(uids)) != len(uids):
            raise ValueError('invalid expected uid manifest')
        off, shadow = load_rows(args.off), load_rows(args.shadow)
        if (set(off) | set(shadow)) - set(uids):
            raise ValueError('trajectory contains uid outside manifest')
        report.update(denominator=len(uids), position_tolerance_m=args.position_tolerance,
                      input_sha256={name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in [('manifest', args.manifest), ('off', args.off), ('shadow', args.shadow)]}, episodes={})
        for uid in uids:
            if uid not in off or uid not in shadow:
                report['episodes'][uid] = {'status': 'unavailable', 'missing': [name for name, rows in [('off', off), ('shadow', shadow)] if uid not in rows]}
                continue
            checks = compare(off[uid], shadow[uid], args.position_tolerance)
            status = 'fail' if 'fail' in checks.values() else 'unavailable' if 'unavailable' in checks.values() else 'pass'
            report['episodes'][uid] = {'status': status, 'checks': checks}
        statuses = [r['status'] for r in report['episodes'].values()]
        report['status'] = 'fail' if 'fail' in statuses else 'unavailable' if 'unavailable' in statuses else 'pass'
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        report['error'] = str(exc)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return {'pass': 0, 'fail': 1, 'unavailable': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
