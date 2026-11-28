"""Lockstep run identity, trajectory recovery and bounded decision telemetry."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from ...recording.replay import _write_atomic


def resume_key(run_info: dict, lock: dict) -> str:
    payload = json.dumps([run_info, lock], sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def completed_uids(path: Path, expected: set[str], run_id: str) -> set[str]:
    """Validate completed rows; quarantine an interrupted final write before resuming."""
    if not path.exists():
        return set()
    done: set[str] = set()
    repair = None
    with path.open('rb') as stream:
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.strip():
                if not line.endswith(b'\n'):
                    repair = (offset, line)
                    break
                continue
            try:
                row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if line.endswith(b'\n'):
                    raise ValueError(f'invalid complete trajectory row at byte {offset}') from exc
                repair = (offset, line)
                break
            if not isinstance(row, dict) or row.get('run_id') != run_id or row.get('uid') not in expected:
                raise ValueError(f'trajectory outside this run at byte {offset}')
            uid = row['uid']
            if uid in done:
                raise ValueError(f'duplicate completed trajectory: {uid}')
            done.add(uid)
            if not line.endswith(b'\n'):
                repair = (offset + len(line), b'')
    if repair is not None:
        offset, discarded = repair
        if discarded:
            with path.with_name('trajectory-recovery.jsonl').open('a') as recovery:
                recovery.write(json.dumps({'offset': offset, 'discarded_hex': discarded.hex()}) + '\n')
        with path.open('rb+') as stream:
            if discarded:
                stream.truncate(offset)
            else:
                stream.seek(offset)
                stream.write(b'\n')
    return done


def lock_run(out_dir: Path, run_info: dict, inputs: dict) -> None:
    path = out_dir / 'baseline-lock.json'
    lock = {'schema_version': 1, 'inputs': inputs, 'run_info': run_info,
            'resume_key': resume_key(run_info, inputs)}
    if path.exists():
        if json.loads(path.read_text()) != lock:
            raise ValueError('output directory holds a different run lock; use a new --out-dir')
    elif (out_dir / 'trajectories.jsonl').exists() or (out_dir / 'run.json').exists():
        raise ValueError('existing run predates baseline locking; use a new --out-dir')
    else:
        _write_atomic(path, (json.dumps(lock, sort_keys=True, indent=2) + '\n').encode())
    _write_atomic(out_dir / 'run.json', (json.dumps(run_info, indent=2) + '\n').encode())


@dataclass(frozen=True)
class DecisionTrace:
    uid: str
    cycle: int
    now_ns: int
    clock_domain: str
    source: str
    map_revision: int
    reason: str
    policy_ns: int
    state_before: str | None = None
    state_after: str | None = None
    goal_id: str | None = None
    guard_reason: str | None = None
    worker_reason: str | None = None
    requested: tuple[float, float] | None = None
    guarded: tuple[float, float] | None = None
    pose_delta_m: float | None = None
    yaw_delta_rad: float | None = None
    executor_executed: bool | None = None
    executor_actions: list | None = None
    executor_proof_validated: bool | None = None
    schema_version: int = 1


class TraceWriter:
    def __init__(self, path: Path, *, limit: int = 1000):
        self.path = path
        self.limit = limit
        self.count = 0
        self.dropped = 0
        self.reasons = Counter()
        self.guard_reasons = Counter()
        self.latency = Counter()

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('w', encoding='utf-8')
        return self

    def write_trace(self, event: DecisionTrace, *, terminal: bool = False) -> None:
        self.count += 1
        self.reasons[event.reason] += 1
        if event.guard_reason:
            self.guard_reasons[event.guard_reason] += 1
        # Logarithmic buckets with <= 1/16 relative rounding.
        quantum = 1 << max(0, event.policy_ns.bit_length() - 4)
        upper = ((event.policy_ns + quantum - 1) // quantum) * quantum
        self.latency[upper] += 1
        if self.count <= self.limit or terminal:
            self._write({'kind': 'decision', **asdict(event)})
        else:
            self.dropped += 1

    def _write(self, row: dict) -> None:
        self.stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')

    def __exit__(self, exc_type, exc, tb):
        stats = {}
        if self.latency:
            total = sum(self.latency.values())
            stats = {'samples': total}
            ordered = sorted(self.latency.items())
            for name, quantile in [('p50', .5), ('p95', .95), ('p99', .99)]:
                remaining = math.ceil(total * quantile)
                for upper, count in ordered:
                    remaining -= count
                    if remaining <= 0:
                        stats[name] = upper
                        break
        try:
            self._write({'schema_version': 1, 'kind': 'summary', 'cycles': self.count,
                         'dropped': self.dropped, 'aborted': exc_type is not None,
                         'reason_counts': dict(self.reasons), 'guard_counts': dict(self.guard_reasons),
                         'policy_latency_ns': stats})
        finally:
            self.stream.close()


def offline_failure_labels(outcome: dict, evidence: dict, diagnostics: dict) -> tuple[str, ...]:
    """Independent diagnostics derived after schema-3 scoring and semantic replay."""
    labels = []
    if evidence.get('target_seen') is False:
        labels.append('NEVER_SAMPLED_TARGET')
    if evidence.get('target_seen') and evidence.get('target_detected') is False:
        labels.append('SEEN_NOT_DETECTED')
    if evidence.get('target_detected') and evidence.get('confirmed_goal') is False:
        labels.append('DETECTED_NOT_CONFIRMED')
    if evidence.get('confirmed_goal') and evidence.get('committed_goal') is False:
        labels.append('CONFIRMED_NOT_COMMITTED')
    if outcome.get('oracle_success') and not outcome.get('called_stop'):
        labels.append('MISSED_STOP')
    if outcome.get('called_stop') and not outcome.get('success'):
        labels.append('FALSE_STOP')
    if evidence.get('stop_near_false_detection'):
        labels.append('WRONG_INSTANCE_STOP')
    if diagnostics.get('end_reason') in ('max_cycles', 'max_sim_time'):
        labels.append('BUDGET')
    if diagnostics.get('blocked_moves', 0):
        labels.append('ACTUATION_NO_PROGRESS')
    command_reasons = diagnostics.get('command_reasons', {})
    if any(key in command_reasons for key in ('approach_no_path', 'no_reachable_frontier_path')):
        labels.append('PATH_BLOCKED')
    if any(key in command_reasons for key in ('bootstrap_blocked', 'path_segment_blocked',
                                               'footprint_not_observed', 'collision_blocked')):
        labels.append('GUARD_BLOCKED')
    events = (diagnostics.get('policy') or {}).get('events', ())
    notes = {event.get('note') for event in events}
    labels.extend(reason for reason in ('VERIFY_NO_FRESH_MATCH', 'VERIFY_OUT_OF_RANGE') if reason in notes)
    return tuple(labels)
