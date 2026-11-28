#!/usr/bin/env python3
"""Audit paired lockstep ObjectNav arms; absence is never counted as success."""
import argparse
import gzip
import json
import math
import random
from pathlib import Path

ARMS = ('off', 'shadow', 'probabilistic')
METRICS = {'sr': 'success', 'spl': 'spl', 'soft_spl': 'soft_spl', 'dtg_m': 'dtg_end_m'}
PARITY = ('requested', 'guarded', 'guard_reason', 'worker_reason', 'executor_actions',
          'executor_executed', 'executor_proof_validated', 'pose_delta_m', 'yaw_delta_rad',
          'state_before', 'state_after', 'reason', 'goal_id', 'map_revision', 'source', 'now_ns')


def read_rows(path, missing, violations):
    if not path.exists():
        missing.append(str(path))
        return []
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        violations.append(f'{path}: invalid JSON: {exc}')
        return []


def indexed(rows, label, violations):
    result = {}
    for row in rows:
        uid = row.get('uid') if isinstance(row, dict) else None
        if not isinstance(uid, str) or uid in result:
            violations.append(f'{label}: missing or duplicate uid {uid!r}')
        else:
            result[uid] = row
    return result


def trace_check(path, rows, violations):
    if not rows or rows[-1].get('kind') != 'summary':
        violations.append(f'{path}: missing trace summary')
        return None, None
    summary, decisions = rows[-1], rows[:-1]
    if summary.get('aborted') is not False or summary.get('dropped') != 0 or summary.get('cycles') != len(decisions) or not decisions:
        violations.append(f'{path}: incomplete trace summary')
    uid = decisions[0].get('uid') if decisions else None
    for i, row in enumerate(decisions):
        label = f'{path}: cycle {i}'
        if row.get('kind') != 'decision' or row.get('uid') != uid or row.get('cycle') != i:
            violations.append(f'{label}: malformed sequence')
        if row.get('guard_reason') is None:
            if i != len(decisions) - 1 or row.get('state_after') != 'STOPPED':
                violations.append(f'{label}: invalid terminal')
            continue
        if not isinstance(row.get('guard_reason'), str):
            violations.append(f'{label}: invalid guard reason')
        for key in ('pose_delta_m', 'yaw_delta_rad'):
            value = row.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                violations.append(f'{label}: invalid pose measurement {key}')
        requested, guarded, actions = row.get('requested'), row.get('guarded'), row.get('executor_actions')
        if not isinstance(requested, list) or len(requested) != 2 or not isinstance(guarded, list) or len(guarded) != 2 or not isinstance(actions, list) or not isinstance(row.get('worker_reason'), str):
            violations.append(f'{label}: missing guard/execution evidence')
            continue
        executed = row.get('executor_executed')
        if not isinstance(executed, bool) or executed != bool(actions):
            violations.append(f'{label}: inconsistent executor actions')
        if guarded == [0, 0]:
            if actions or row.get('pose_delta_m') != 0 or row.get('yaw_delta_rad') != 0 or row.get('worker_reason') != 'expired_or_zero':
                violations.append(f'{label}: zero_guard action or movement')
        elif executed and row.get('executor_proof_validated') is not True:
            violations.append(f'{label}: execution proof missing')
        elif not executed and (row.get('pose_delta_m') != 0 or row.get('yaw_delta_rad') != 0):
            violations.append(f'{label}: movement without execution')
    return uid, decisions


def bootstrap(rows):
    scenes = sorted({r['scene'] for r in rows})
    if len(scenes) < 2:
        return {'status': 'unavailable', 'reason': 'fewer than two scenes', 'scenes': len(scenes)}
    by_scene = {s: [r for r in rows if r['scene'] == s] for s in scenes}
    rng = random.Random(20261128)
    samples = {m: [] for m in METRICS}
    for _ in range(1000):
        sample = [r for _ in scenes for r in by_scene[rng.choice(scenes)]]
        for metric in METRICS:
            values = [r['delta'][metric] for r in sample if r['delta'][metric] is not None]
            if values:
                samples[metric].append(sum(values) / len(values))
    result = {}
    for metric, values in samples.items():
        values.sort()
        result[metric] = [values[int(.025 * len(values))], values[int(.975 * len(values))]] if values else None
    return {'status': 'available', 'seed': 20261128, 'replicates': 1000, 'scenes': len(scenes), 'percentile_95_ci': result}


def report(manifest, root):
    doc = json.loads(manifest.read_text())
    uids = doc.get('uids')
    if not isinstance(uids, list) or not uids or any(not isinstance(u, str) for u in uids) or len(set(uids)) != len(uids):
        raise ValueError('manifest must contain a nonempty unique uids list')
    expected = set(uids)
    missing, violations, arms, pins = [], [], {}, {}
    rejected = {}
    coverage = {'expected': len(uids), 'uids': uids, 'scope': 'caller manifest', 'arms': {}}
    for arm in ARMS:
        base = root / arm
        pin_path = base / 'baseline-lock.json'
        try:
            pins[arm] = json.loads(pin_path.read_text())['inputs']
        except (OSError, ValueError, KeyError, TypeError):
            missing.append(f'{arm}: baseline lock unavailable')
        traj = indexed(read_rows(base / 'trajectories.jsonl', missing, violations), arm + ' trajectories', violations)
        rejected[arm] = {uid for uid, row in traj.items() if
                         row.get('evidence', {}).get('start_not_navigable') is True
                         and row.get('diagnostics', {}).get('end_reason') == 'start_not_navigable_for_robot'
                         and row.get('steps') == 0 and row.get('called_stop') is False
                         and row.get('sim_time_s') == 0 and len(row.get('positions', [])) == 1}
        scores = indexed(read_rows(base / 'score-outcomes.jsonl', missing, violations), arm + ' scores', violations)
        traces = {}
        for path in sorted((base / 'trace').glob('*.jsonl')):
            uid, rows = trace_check(path, read_rows(path, missing, violations), violations)
            if uid in traces:
                violations.append(f'{path}: duplicate trace uid {uid}')
            elif uid:
                traces[uid] = rows
        for name, records in (('trajectories', traj), ('scores', scores), ('traces', traces)):
            exception = rejected[arm] if name == 'traces' else set()
            for uid in sorted(expected - records.keys() - exception):
                missing.append(f'{arm}: {name} missing for {uid}')
            for uid in sorted(records.keys() - expected):
                violations.append(f'{arm}: unexpected {name} uid {uid}')
        coverage['arms'][arm] = {name: len(expected & records.keys()) for name, records in (('trajectories', traj), ('scores', scores), ('traces', traces))}
        for uid in expected & traj.keys() & scores.keys():
            if uid in rejected[arm] and (scores[uid].get('success') is not False
                    or scores[uid].get('failure_mode') != 'start_not_navigable' or uid in traces):
                violations.append(f'{arm}: {uid}: rejected start has execution or inconsistent score')
            if 'called_stop' in scores[uid] and scores[uid]['called_stop'] != traj[uid].get('called_stop'):
                violations.append(f'{arm}: {uid}: score STOP disagrees with trajectory')
            for key in METRICS.values():
                value = scores[uid].get(key)
                if uid in rejected[arm] and key == 'dtg_end_m':
                    continue
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    missing.append(f'{arm}: {uid}: score {key} unavailable')
        for uid in expected & traj.keys() & traces.keys():
            terminal = bool(traces[uid] and traces[uid][-1].get('state_after') == 'STOPPED' and traces[uid][-1].get('guard_reason') is None)
            if terminal != traj[uid].get('called_stop'):
                violations.append(f'{arm}: {uid}: trace STOP disagrees with trajectory')
        arms[arm] = (traj, scores, traces)
    if len(pins) == len(ARMS):
        for key in ('source', 'dataset', 'manifest', 'runner_config', 'detector', 'habitat'):
            if any(key not in pins[arm] for arm in ARMS):
                missing.append(f'baseline lock missing {key}')
            elif any(pins[arm][key] != pins['off'][key] for arm in ARMS[1:]):
                violations.append(f'baseline lock {key} mismatch')
        for arm in ('shadow', 'probabilistic'):
            state = pins[arm].get('semantic_candidates', {})
            if state.get('mode') != arm:
                violations.append(f'{arm}: baseline lock mode mismatch')
        for key in ('config', 'interpreter'):
            a = pins['shadow'].get('semantic_candidates', {})
            b = pins['probabilistic'].get('semantic_candidates', {})
            if key not in a or key not in b:
                missing.append(f'baseline semantic candidates {key} missing')
            elif a[key] != b[key]:
                violations.append(f'baseline semantic candidates {key} mismatch')
    off, shadow, b2 = (arms[x] for x in ARMS)
    agreed_rejected = set.intersection(*rejected.values())
    coverage['rejected_start_uids'] = sorted(agreed_rejected)
    for uid in set.union(*rejected.values()) - agreed_rejected:
        if all(uid in arm[0] for arm in (off, shadow, b2)):
            violations.append(f'{uid}: rejected start differs across arms')
    for uid in uids:
        if uid in agreed_rejected:
            records = [arm[0][uid] for arm in (off, shadow, b2)]
            for field in ('positions', 'diagnostics'):
                if any(row.get(field) != records[0].get(field) for row in records[1:]):
                    violations.append(f'{uid}: rejected start {field} differs across arms')
            continue
        if uid in shadow[0]:
            state = shadow[0][uid].get('diagnostics', {}).get('policy', {}).get('semantic_candidates')
            if not isinstance(state, dict) or not isinstance(state.get('decisions'), list):
                missing.append(f'{uid}: shadow semantic decisions missing')
            else:
                if state.get('mode') != 'shadow':
                    violations.append(f'{uid}: incorrect shadow mode')
                if state.get('native_tap', {}).get('clean_shutdown') is not True:
                    missing.append(f'{uid}: shadow native tap clean shutdown unproved')
                for decision in state['decisions']:
                    if 'applied' not in decision or 'deterministic' not in decision:
                        missing.append(f'{uid}: shadow choice missing')
                    elif decision['applied'] != decision['deterministic']:
                        violations.append(f'{uid}: shadow changed deterministic choice')
        if uid in off[0] and uid in shadow[0]:
            for key in ('positions', 'steps', 'called_stop', 'sim_time_s'):
                if key not in off[0][uid] or key not in shadow[0][uid]:
                    missing.append(f'{uid}: trajectory {key} missing')
                elif off[0][uid][key] != shadow[0][uid][key]:
                    violations.append(f'{uid}: off/shadow trajectory {key} mismatch')
        if uid in off[2] and uid in shadow[2]:
            a, b = off[2][uid], shadow[2][uid]
            if len(a) != len(b):
                violations.append(f'{uid}: off/shadow trace length mismatch')
            for i, (x, y) in enumerate(zip(a, b)):
                for key in PARITY:
                    if x.get(key) != y.get(key):
                        violations.append(f'{uid}: off/shadow cycle {i} {key} mismatch')
    counts = dict(decisions=0, ranked=0, eligible=0, applied=0, different=0, stale=0, fallback=0, stop=0, stop_verified=0)
    details, unproved = [], []
    for uid in uids:
        if uid not in b2[0] or uid in agreed_rejected:
            continue
        episode = b2[0][uid]
        policy = episode.get('diagnostics', {}).get('policy', {})
        semantic = policy.get('semantic_candidates')
        if not isinstance(semantic, dict) or not isinstance(semantic.get('decisions'), list):
            missing.append(f'{uid}: B2 semantic decisions missing')
            continue
        if semantic.get('mode') != 'probabilistic':
            violations.append(f'{uid}: incorrect B2 mode')
        if semantic.get('native_tap', {}).get('clean_shutdown') is not True:
            missing.append(f'{uid}: B2 native tap clean shutdown unproved')
        for d in semantic['decisions']:
            counts['decisions'] += 1
            ranked, eligible, rank = d.get('ranked'), d.get('eligible'), d.get('reachable_rank')
            if not isinstance(ranked, list) or not isinstance(eligible, list):
                missing.append(f'{uid}: candidate list missing at cycle {d.get("cycle")}')
                continue
            counts['ranked'] += bool(ranked)
            counts['eligible'] += bool(eligible)
            applied = rank is not None and d.get('applied') == rank
            counts['applied'] += applied
            counts['different'] += applied and d.get('applied') != d.get('deterministic')
            counts['fallback'] += rank is None
            stale = False
            if applied:
                if rank not in ranked or rank not in eligible:
                    violations.append(f'{uid}: applied rank not ranked and eligible at cycle {d.get("cycle")}')
                if not d.get('input_prefix_sha256') or d.get('revision') is None:
                    missing.append(f'{uid}: applied revision/prefix provenance missing at cycle {d.get("cycle")}')
                try:
                    age = d['decision_ns'] - d['source_ns']
                    frames = d['policy_frame'] - d['source_frame']
                    stale = not (0 <= age <= 2_000_000_000 and 0 <= frames <= 16)
                except (KeyError, TypeError):
                    missing.append(f'{uid}: applied freshness evidence missing at cycle {d.get("cycle")}')
                if stale:
                    counts['stale'] += 1
                    violations.append(f'{uid}: stale applied candidate at cycle {d.get("cycle")}')
                unproved.append(f'{uid}: applied cycle {d.get("cycle")} physical instance/receipt attribution not independently audited')
            details.append({'uid': uid, 'decision': d, 'applied_rank': applied, 'stale': stale if applied else None})
        stop = policy.get('stop')
        if episode.get('called_stop'):
            counts['stop'] += 1
            if not isinstance(stop, dict) or stop.get('note') != 'confirmed_target':
                violations.append(f'{uid}: STOP lacks confirmed target')
                continue
            events = [e for e in policy.get('events', []) if e.get('state') == 'VERIFY' and e.get('target') == stop.get('cid') and e.get('cycle', -1) < stop.get('cycle', -1)]
            if not events:
                violations.append(f'{uid}: STOP lacks prior VERIFY')
                continue
            trace = b2[2].get(uid, [])
            try:
                verify_ns = trace[events[-1]['cycle']]['now_ns']
                stop_ns = trace[stop['cycle']]['now_ns']
                with gzip.open(policy['evidence_file'], 'rt') as stream:
                    evidence = any(verify_ns <= f['capture_ns'] <= f['released_ns'] <= stop_ns for f in map(json.loads, stream))
                if not evidence:
                    violations.append(f'{uid}: STOP lacks post-VERIFY observation')
                else:
                    counts['stop_verified'] += 1
            except (KeyError, IndexError, OSError, ValueError, TypeError):
                missing.append(f'{uid}: STOP observation verification unavailable')
            unproved.append(f'{uid}: STOP physical-instance correctness requires independent offline attribution')
        elif stop is not None:
            violations.append(f'{uid}: policy STOP disagrees with trajectory')
    paired = []
    for uid in uids:
        if uid not in off[1] or uid not in b2[1]:
            continue
        a, b = off[1][uid], b2[1][uid]
        if not isinstance(a.get('scene'), str) or a.get('scene') != b.get('scene'):
            violations.append(f'{uid}: score scene mismatch or missing')
            continue
        delta = {}
        for name, key in METRICS.items():
            x, y = a.get(key), b.get(key)
            if name == 'dtg_m' and uid in agreed_rejected and not all(
                    isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
                delta[name] = None
                continue
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not math.isfinite(x) or not math.isfinite(y):
                missing.append(f'{uid}: {key} score unavailable')
            else:
                delta[name] = float(y) - float(x)
        if len(delta) == len(METRICS):
            paired.append({'uid': uid, 'scene': a['scene'], 'delta': delta})
    status = 'fail' if violations else 'unavailable' if missing else 'pass'
    return {'status': status, 'coverage': coverage, 'violations': violations, 'missing': missing,
            'unproved_attribution': unproved, 'b2': {**counts, 'stale_scope': 'applied rank decisions', 'freshness_limits': {'age_ns': 2000000000, 'frame_lag': 16}, 'applied_episode_denominator': len(uids), 'applied_coverage': len({x['uid'] for x in details if x['applied_rank']}) / len(uids), 'details': details},
            'paired_deltas_b2_minus_off': paired, 'bootstrap': bootstrap(paired)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = report(args.manifest, args.root)
    except (OSError, ValueError, TypeError) as exc:
        result = {'status': 'unavailable', 'missing': [str(exc)], 'violations': []}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return {'pass': 0, 'fail': 1, 'unavailable': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
