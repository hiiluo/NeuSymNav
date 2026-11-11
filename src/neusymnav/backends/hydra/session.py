"""Bounded, nonblocking host session for one Hydra worker and episode."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import threading
import time
import uuid

from ...contracts import dumps, loads
from ...contracts.hydra_graph import HydraFrame, validate_hydra_frame_order
from .wire import serialize_frame_buffers


MAX_QUEUE_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 32 * 1024 * 1024
MAX_STDERR_LINES = 64


_FRAME_FIELD=b',"frame":'
_FRAME_END=b'}\n'


def _frame_header(frame_index: int, request_id: str) -> bytes:
    return json.dumps({'type':'frame','request_id':request_id,'frame_index':frame_index},
        separators=(',',':')).encode('utf-8')


def _frame_request(frame_index: int, request_id: str, frame_literal: bytes) -> bytes:
    """Build the legacy frame request around a trusted pre-encoded JSON string."""
    header=_frame_header(frame_index,request_id)
    return b''.join((header[:-1],_FRAME_FIELD,frame_literal,_FRAME_END))


def _frame_request_size(frame_index: int, frame_literal: bytes) -> int:
    header=_frame_header(frame_index,'0'*32)
    return len(header)-1+len(_FRAME_FIELD)+len(frame_literal)+len(_FRAME_END)


def _journal_line(run_id: str, event: dict, selected_frame_literal: bytes | None = None) -> bytes:
    encoded_event=json.dumps({'run_id':run_id,**event},sort_keys=True,
        separators=(',',':'),allow_nan=False).encode('utf-8')
    if selected_frame_literal is not None:
        marker=b'"selected_frame":null'
        if (type(selected_frame_literal) is not bytes or not selected_frame_literal.startswith(b'"')
                or not selected_frame_literal.endswith(b'"') or encoded_event.count(marker)!=1):
            raise ValueError('selected frame journal splice requires a trusted literal and unique marker')
        encoded_event=encoded_event.replace(marker,b'"selected_frame":'+selected_frame_literal,1)
    return encoded_event+b'\n'


@dataclass(frozen=True)
class HydraAdmission:
    status: str
    source_key: object | None
    payload_bytes: int
    queued: int
    in_flight: int
    reason: str | None = None


@dataclass(frozen=True)
class HydraGraphSnapshot:
    episode_id: str
    graph_revision: int
    last_source_key: object | None
    last_capture_monotonic_ns: int | None
    last_clock_domain: str | None
    input_prefix_sha256: str | None
    config_sha256: str | None
    source_sha256: str | None
    build_sha256: str | None
    graph_asset_path: str | None
    graph_asset_sha256: str | None
    graph_asset_bytes: int | None
    node_counts: dict[str, int] | None
    edge_count: int | None
    last_transform: dict | None
    stale: bool
    replay_required: bool
    failure_reason: str | None
    graph_summary: dict | None = None
    last_semantics: dict | None = None
    room_stability: dict | None = None


class HydraSession:
    """Own one child process; `offer` never waits for a native step or reply."""

    def __init__(self, episode_id: str, *, command: tuple[str, ...],
                 journal_path: str | Path, worker_timeout_s: float = 30.0,
                 startup_timeout_s: float = 10.0, fps_limit_hz: float | None = None,
                 artifact_quota_bytes: int = 2 * 1024 * 1024 * 1024):
        if not isinstance(episode_id, str) or not episode_id.strip():
            raise ValueError('episode_id must be nonempty')
        if not 0.1 <= float(worker_timeout_s) <= 120.0:
            raise ValueError('worker_timeout_s must be between 0.1 and 120 seconds')
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError('command must be a nonempty argument vector')
        self.episode_id = episode_id
        self.run_id = uuid.uuid4().hex
        self.worker_timeout_s = float(worker_timeout_s)
        if fps_limit_hz is not None and (not 0 < float(fps_limit_hz) <= 60):
            raise ValueError('fps_limit_hz must be in (0, 60]')
        if type(artifact_quota_bytes) is not int or artifact_quota_bytes <= 0:
            raise ValueError('artifact_quota_bytes must be positive')
        self.fps_limit_hz = None if fps_limit_hz is None else float(fps_limit_hz)
        self.artifact_quota_bytes = artifact_quota_bytes
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._condition = threading.Condition()
        self._journal_lock = threading.Lock()
        self._journal_events: deque[dict] = deque()
        # frame, raw serialized payload, wire size, offer time, escaped JSON literal
        self._pending: tuple[HydraFrame, bytes, int, float, bytes] | None = None
        self._last_offered: HydraFrame | None = None
        self._last_offer_time: float | None = None
        self._in_flight = False
        self._in_flight_bytes = 0
        self._closed = False
        self._failure: str | None = None
        self._replay_required = False
        self._revision = 0
        self._last_accepted: HydraFrame | None = None
        self._last_transform: dict | None = None
        self._prefix_hash: str | None = None
        self._stderr_tail: deque[str] = deque(maxlen=MAX_STDERR_LINES)
        self._worker_metadata: dict = {}
        self._worker_close_result: dict | None = None
        self._graph_summary: dict | None = None
        self._room_stability_diagnostics: dict | None = None
        self._stdout_buffer = bytearray()
        self._stats = {'candidates': 0, 'queued': 0, 'replaced': 0, 'started': 0,
                       'accepted': 0, 'step_rejected': 0, 'failed': 0, 'dropped': 0,
                       'fps_limited': 0}
        self._service_ms: deque[float] = deque(maxlen=256)
        self._queue_ms: deque[float] = deque(maxlen=256)
        self._source_age_ms: deque[float] = deque(maxlen=256)

        env = dict(os.environ)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['OMP_NUM_THREADS'] = '1'
        env['OPENBLAS_NUM_THREADS'] = '1'
        env['MKL_NUM_THREADS'] = '1'
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0, start_new_session=True, env=env)
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            self._terminate()
            raise RuntimeError('Hydra worker pipes were not created')
        for stream in (self.process.stdin, self.process.stdout):
            os.set_blocking(stream.fileno(), False)
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        try:
            ready = self._read_message(startup_timeout_s)
            if ready.get('type') != 'ready' or ready.get('protocol') != 1:
                raise RuntimeError('Hydra worker sent invalid ready message')
            self._worker_metadata = ready
        except BaseException:
            self._terminate()
            raise
        self._thread = threading.Thread(target=self._run, name=f'hydra-{self.run_id[:8]}', daemon=True)
        self._thread.start()

    @property
    def stats(self) -> dict:
        with self._condition:
            values = dict(self._stats)
            values['pending'] = int(self._pending is not None)
            values['in_flight'] = int(self._in_flight)
            values['pending_bytes'] = 0 if self._pending is None else len(self._pending[1])+len(self._pending[4])
            values['in_flight_bytes'] = self._in_flight_bytes
            values['queue_bytes'] = values['pending_bytes'] + values['in_flight_bytes']
            values['queue_bytes_scope'] = 'serialized payload plus escaped frame literal; excludes frame object and transient request'
            samples = sorted(self._service_ms)
            values['service_p50_ms'] = _percentile(samples, .50)
            values['service_p95_ms'] = _percentile(samples, .95)
            queue_samples = sorted(self._queue_ms)
            values['queue_p50_ms'] = _percentile(queue_samples, .50)
            values['queue_p95_ms'] = _percentile(queue_samples, .95)
            age_samples = sorted(self._source_age_ms)
            values['source_age_p50_ms'] = _percentile(age_samples, .50)
            values['source_age_p95_ms'] = _percentile(age_samples, .95)
            values['worker_rss_bytes'] = _process_rss_bytes(self.process.pid)
            try:
                values['artifact_bytes'] = self.journal_path.stat().st_size
            except OSError:
                values['artifact_bytes'] = 0
            values['artifact_quota_bytes'] = self.artifact_quota_bytes
            values['stderr_tail'] = tuple(self._stderr_tail)
            values['worker_metadata'] = dict(self._worker_metadata)
            return values

    def offer(self, frame: HydraFrame, *, now_monotonic_ns: int | None = None,
              now_domain: str | None = None) -> HydraAdmission:
        if not isinstance(frame, HydraFrame):
            raise ValueError('frame must be HydraFrame')
        if frame.source_key.episode_id != self.episode_id:
            return self._rejection(frame, 'wrong_episode')
        if (self._worker_metadata.get('labelspace_hash') is not None and
                self._worker_metadata['labelspace_hash'] != frame.labelspace_hash):
            return self._rejection(frame, 'worker_labelspace_mismatch')
        if (self._worker_metadata.get('labelspace_id') is not None and
                self._worker_metadata['labelspace_id'] != frame.labelspace_id):
            return self._rejection(frame, 'worker_labelspace_mismatch')
        source_age_ms = None
        if (now_monotonic_ns is not None or now_domain is not None):
            if type(now_monotonic_ns) is not int or not isinstance(now_domain, str):
                return self._rejection(frame, 'invalid_now_clock')
            if now_domain == frame.clock_domain:
                try:
                    age_ns = frame.validate_now(now_monotonic_ns, now_domain)
                except ValueError as exc:
                    return self._rejection(frame, 'invalid_source_age', str(exc))
                source_age_ms = age_ns / 1e6
        try:
            if self._last_offered is not None:
                validate_hydra_frame_order(self._last_offered, frame)
            frame_payload, frame_literal = serialize_frame_buffers(frame)
        except ValueError as exc:
            return self._rejection(frame, 'replayed_frame', str(exc))
        size = _frame_request_size(frame.source_key.frame_index,frame_literal)
        queue_charge=len(frame_payload)+len(frame_literal)
        with self._condition:
            if source_age_ms is not None:
                self._source_age_ms.append(source_age_ms)
            self._stats['candidates'] += 1
            now = time.monotonic()
            if (self.fps_limit_hz is not None and self._last_offer_time is not None and
                    now - self._last_offer_time < 1.0 / self.fps_limit_hz):
                self._stats['fps_limited'] += 1
                self._stats['dropped'] += 1
                self._journal_events.append({'event': 'fps_limited', 'source': _source(frame),
                    'reason': 'configured_rate_limit'})
                self._condition.notify_all()
                return self._admission('fps_limited', frame, size, 'configured_rate_limit')
            if self._failure:
                self._stats['dropped'] += 1
                return self._admission('failed', frame, size, self._failure)
            if self._closed:
                self._stats['dropped'] += 1
                return self._admission('closed', frame, size, 'session_closed')
            if size > MAX_LINE_BYTES:
                self._stats['dropped'] += 1
                return self._admission('payload_too_large', frame, size, 'frame exceeds 32 MiB')
            # Latest-wins replaces the pending serialized buffers; retain only
            # the in-flight charge plus the new payload and escaped literal.
            projected = self._in_flight_bytes + queue_charge
            if projected > MAX_QUEUE_BYTES:
                self._stats['dropped'] += 1
                return self._admission('payload_too_large', frame, size, 'in-flight plus pending exceeds 32 MiB')
            self._last_offered = frame
            self._last_offer_time = now
            replaced = self._pending is not None
            replaced_frame = None if self._pending is None else self._pending[0]
            if replaced:
                self._stats['replaced'] += 1
                status = 'replaced'
            else:
                self._stats['queued'] += 1
                status = 'queued'
            self._pending = (frame, frame_payload, size, now, frame_literal)
            self._journal_events.append({'event': 'replaced' if replaced else 'queued',
                'source': _source(frame), 'payload_sha256': hashlib.sha256(frame_payload).hexdigest(),
                'replaced_source': None if replaced_frame is None else _source(replaced_frame),
                'payload_bytes': size, 'reason': 'live_latest_wins' if replaced else None})
            self._condition.notify_all()
            return self._admission(status, frame, size)

    def _validate_native_metadata(self, metadata, diagnostics):
        if metadata is None:
            if diagnostics is not None:
                raise RuntimeError('room diagnostics require native metadata')
            return
        allowed = {'config_sha256', 'source_sha256', 'build_sha256',
                   'native_binding_sha256', 'room_stability'}
        if not isinstance(metadata, dict) or set(metadata) != allowed:
            raise RuntimeError('invalid native metadata schema')
        for key in ('config_sha256', 'source_sha256'):
            if metadata[key] != self._worker_metadata.get(key):
                raise RuntimeError('native metadata changed ready provenance')
        for key in ('build_sha256', 'native_binding_sha256'):
            value = metadata[key]
            if (not isinstance(value, str) or len(value) != 64 or
                    any(c not in '0123456789abcdef' for c in value)):
                raise RuntimeError('invalid native build hash')
            previous = self._worker_metadata.get(key)
            if previous is not None and value != previous:
                raise RuntimeError('native build changed within episode')
        policy = metadata['room_stability']
        previous = self._worker_metadata.get('room_stability')
        if 'build_sha256' in self._worker_metadata and policy != previous:
            raise RuntimeError('native policy changed within episode')
        if policy is not None:
            if (not isinstance(policy, dict) or policy.get('enabled') is not True or
                    policy.get('version') != 'neusymnav-room-stability-v1'):
                raise RuntimeError('invalid native room stability policy')
            for key in ('library_sha256', 'policy_sha256'):
                value = policy.get(key)
                if (not isinstance(value, str) or len(value) != 64 or
                        any(c not in '0123456789abcdef' for c in value)):
                    raise RuntimeError('invalid room stability hash')
        if diagnostics is not None and (policy is None or not isinstance(diagnostics, dict)):
            raise RuntimeError('invalid room stability diagnostics')
        if len(json.dumps([metadata, diagnostics], allow_nan=False).encode()) > 65536:
            raise RuntimeError('native metadata exceeds 64 KiB')

    def state_token(self):
        """Cheap token that changes whenever ``snapshot()`` content can change.

        ``snapshot()`` deep-copies the growing graph summary; pollers compare
        this token first and request a new snapshot only after a change.
        """
        with self._condition:
            return (self._revision, self._failure, self._replay_required,
                    id(self._worker_metadata), id(self._worker_close_result))

    def snapshot(self) -> HydraGraphSnapshot:
        return self._build_snapshot()

    def _build_snapshot(self) -> HydraGraphSnapshot:
        with self._condition:
            frame = self._last_accepted
            worker = self._worker_close_result or self._worker_metadata
            asset_path = worker.get('asset_path')
            asset_hash = worker.get('asset_sha256')
            asset_bytes = worker.get('asset_bytes')
            node_counts = deepcopy(worker.get('layer_counts'))
            edge_count = worker.get('edge_count')
            return HydraGraphSnapshot(self.episode_id, self._revision,
                None if frame is None else frame.source_key,
                None if frame is None else frame.capture_monotonic_ns,
                None if frame is None else frame.clock_domain, self._prefix_hash,
                worker.get('config_sha256'), worker.get('source_sha256'), worker.get('build_sha256'),
                asset_path, asset_hash, asset_bytes, node_counts, edge_count,
                deepcopy(self._last_transform),
                stale=self._failure is not None,
                replay_required=self._replay_required,
                failure_reason=self._failure,graph_summary=deepcopy(self._graph_summary),
                room_stability=(None if worker.get('room_stability') is None else
                    {**deepcopy(worker['room_stability']),
                     'last_decision': deepcopy(self._room_stability_diagnostics)}),
                last_semantics=None if frame is None else {
                    'vocabulary_id':frame.vocabulary_id,
                    'labelspace_id':frame.labelspace_id,
                    'labelspace_hash':frame.labelspace_hash,
                    'source_geometry_hash':frame.source_geometry_hash})

    def wait_for_revision(self, revision: int, timeout_s: float) -> bool:
        """Blocking helper for offline replay/close; never used by offer callers."""
        if type(revision) is not int or revision < 0 or timeout_s < 0:
            raise ValueError('revision and timeout must be nonnegative')
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while self._revision < revision and self._failure is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return self._revision >= revision

    def close(self, timeout_s: float = 5.0) -> dict:
        if not 0 <= float(timeout_s) <= 120:
            raise ValueError('timeout_s must be between 0 and 120 seconds')
        with self._condition:
            self._closed = True
            self._journal_events.append({'event': 'close_requested', 'run_id': self.run_id})
            self._condition.notify_all()
        self._thread.join(float(timeout_s))
        if self._thread.is_alive():
            with self._condition:
                self._failure = self._failure or 'worker_close_timeout'
                self._replay_required = True
                self._stats['failed'] += 1
            self._terminate()
            self._thread.join(.5)
        try:
            self.process.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            self._terminate()
        self._flush_journal()
        complete = not self._thread.is_alive() and self.process.poll() is not None and self._failure is None
        return {'complete': complete, 'failure_reason': self._failure,
                'returncode': self.process.poll(), 'stats': self.stats,
                'stderr_tail': tuple(self._stderr_tail),
                'worker_result': self._worker_close_result,
                'worker_metadata': dict(self._worker_metadata)}

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._journal_events and not self._closed and not self._failure:
                    self._condition.wait()
                journal_events = self._take_journal_events_locked()
                if self._failure:
                    return
                selected = self._pending
                self._pending = None
                if selected is not None:
                    frame, payload, request_size, offered_at, frame_literal = selected
                    self._in_flight = True
                    self._in_flight_bytes = len(payload)+len(frame_literal)
                    self._stats['started'] += 1
                    self._queue_ms.append((time.monotonic() - offered_at) * 1000)
            if journal_events:
                if not self._append_journal({'event': 'batch', 'events': journal_events}):
                    self._terminate()
                    return
            if selected is None:
                if self._closed:
                    break
                continue
            if not self._append_journal({'event': 'started', 'source': _source(frame),
                'payload_sha256': hashlib.sha256(payload).hexdigest(),
                'selected_frame': None}, reserve_bytes=4096 + 65536,
                selected_frame_literal=frame_literal):
                with self._condition:
                    self._in_flight = False
                    self._in_flight_bytes = 0
                self._terminate()
                return
            started = time.monotonic()
            try:
                request_id = uuid.uuid4().hex
                request = _frame_request(frame.source_key.frame_index,request_id,frame_literal)
                if len(request) > MAX_LINE_BYTES:
                    raise RuntimeError('worker request exceeds 32 MiB')
                self._write(request, self.worker_timeout_s)
                response = self._read_message(self.worker_timeout_s)
                if response.get('type') != 'result' or response.get('request_id') != request_id or type(response.get('accepted')) is not bool:
                    raise RuntimeError('worker response schema/request_id mismatch')
                elapsed = (time.monotonic() - started) * 1000
                accepted = response['accepted']
                graph_summary=response.get('graph_summary')
                previous_prefix=bytes.fromhex(self._prefix_hash) if self._prefix_hash else b''
                expected_prefix=hashlib.sha256(previous_prefix+payload).hexdigest() if accepted else self._prefix_hash
                if graph_summary is not None:
                    if (not isinstance(graph_summary,dict) or graph_summary.get('schema_version')!=1
                            or graph_summary.get('graph_revision')!=self._revision+1
                            or graph_summary.get('input_prefix_sha256')!=expected_prefix):
                        raise RuntimeError('worker graph summary revision/prefix mismatch')
                    if len(json.dumps(graph_summary,separators=(',',':'),allow_nan=False).encode())>16*1024*1024:
                        raise RuntimeError('worker graph summary exceeds 16 MiB')
                native_metadata = response.get('native_metadata') if accepted else None
                diagnostics = response.get('room_stability_diagnostics') if accepted else None
                self._validate_native_metadata(native_metadata, diagnostics)
                with self._condition:
                    self._service_ms.append(elapsed)
                    if accepted:
                        self._revision += 1
                        self._last_accepted = frame
                        self._last_transform = {
                            'source_geometry_hash': frame.source_geometry_hash,
                            'calibration_id': frame.calibration_id,
                            'calibration_hash': frame.calibration_hash,
                            'pose_version': frame.pose_version,
                            'coordinate_convention': frame.coordinate_convention,
                            'camera_convention': frame.camera_convention,
                            'depth_convention': frame.depth_convention,
                            'K': frame.K.tolist(),
                            'body_T_camera': frame.body_T_camera.tolist(),
                            'world_T_body': frame.world_T_body.tolist(),
                            'world_t_body': frame.world_t_body.tolist(),
                            'world_R_body_wxyz': frame.world_R_body_wxyz.tolist()}
                        previous = bytes.fromhex(self._prefix_hash) if self._prefix_hash else b''
                        self._prefix_hash = hashlib.sha256(previous + payload).hexdigest()
                        self._graph_summary=graph_summary
                        if native_metadata is not None:
                            self._worker_metadata.update(deepcopy(native_metadata))
                            self._room_stability_diagnostics = deepcopy(diagnostics)
                        self._stats['accepted'] += 1
                        event = 'accepted'
                    else:
                        self._stats['step_rejected'] += 1
                        event = 'step_rejected'
                    self._in_flight = False
                    self._in_flight_bytes = 0
                    self._condition.notify_all()
                native_evidence = ({} if native_metadata is None else {
                    'native_metadata': native_metadata,
                    'room_stability_diagnostics': diagnostics})
                self._append_journal({'event': event, 'source': _source(frame),
                    'accepted': accepted, 'graph_revision': self._revision,
                    'input_prefix_sha256': self._prefix_hash, 'service_ms': elapsed,
                    **native_evidence})
            except BaseException as exc:
                with self._condition:
                    self._failure = f'{type(exc).__name__}: {exc}'
                    self._replay_required = True
                    self._stats['failed'] += 1
                    self._in_flight = False
                    self._in_flight_bytes = 0
                    self._condition.notify_all()
                self._append_journal({'event': 'failed', 'source': _source(frame),
                    'reason': self._failure, 'stderr_tail': list(self._stderr_tail)})
                self._terminate()
                return
            finally:
                # Drop retained serialized buffers before the next condition wait.
                payload=None
                frame_literal=None
                request=None
                selected=None
        try:
            self._write(b'{"type":"close"}\n', min(self.worker_timeout_s, 1.0))
            try:
                response = self._read_message(min(self.worker_timeout_s, 1.0))
                if response.get('type') == 'closed':
                    self._worker_close_result = response
                elif response.get('type') != 'result':
                    raise RuntimeError('invalid worker close response')
            except RuntimeError:
                if self.process.poll() is None:
                    raise
            if self.process.stdin is not None and not self.process.stdin.closed:
                self.process.stdin.close()
            self.process.wait(timeout=min(self.worker_timeout_s, 1.0))
        except BaseException:
            self._terminate()

    def _read_message(self, timeout_s: float) -> dict:
        deadline = time.monotonic() + max(0.0, timeout_s)
        stream = self.process.stdout
        while True:
            newline = self._stdout_buffer.find(b'\n')
            if newline >= 0:
                if newline > MAX_LINE_BYTES:
                    raise RuntimeError('worker response exceeds 32 MiB')
                line = bytes(self._stdout_buffer[:newline])
                del self._stdout_buffer[:newline + 1]
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise RuntimeError('malformed worker stdout protocol') from exc
                if not isinstance(message, dict):
                    raise RuntimeError('worker protocol message must be an object')
                return message
            if len(self._stdout_buffer) > MAX_LINE_BYTES:
                raise RuntimeError('worker response exceeds 32 MiB')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('worker response deadline exceeded')
            readable, _, _ = select.select([stream], [], [], remaining)
            if not readable:
                continue
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                raise RuntimeError(f'worker stdout closed (exit={self.process.poll()})')
            self._stdout_buffer.extend(chunk)

    def _write(self, payload: bytes, timeout_s: float):
        stream = self.process.stdin
        deadline = time.monotonic() + timeout_s
        offset = 0
        view = memoryview(payload)
        while offset < len(payload):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('worker request write deadline exceeded')
            _, writable, _ = select.select([], [stream], [], remaining)
            if not writable:
                continue
            try:
                offset += os.write(stream.fileno(), view[offset:])
            except BrokenPipeError as exc:
                raise RuntimeError('worker stdin closed') from exc

    def _drain_stderr(self):
        stream = self.process.stderr
        for raw in iter(stream.readline, b''):
            line = raw.decode('utf-8', errors='replace').rstrip()
            with self._condition:
                self._stderr_tail.append(line[-4096:])

    def _take_journal_events_locked(self):
        events = []
        while self._journal_events:
            events.append(self._journal_events.popleft())
        return events

    def _flush_journal(self):
        with self._condition:
            events = self._take_journal_events_locked()
        if events:
            self._append_journal({'event': 'batch', 'events': events})

    def _append_journal(self, event: dict, *, reserve_bytes: int = 0,
                        selected_frame_literal: bytes | None = None) -> bool:
        line=_journal_line(self.run_id,event,selected_frame_literal)
        with self._journal_lock:
            try:
                current_bytes = self.journal_path.stat().st_size
            except OSError:
                current_bytes = 0
            if current_bytes + len(line) + reserve_bytes > self.artifact_quota_bytes:
                with self._condition:
                    self._failure = 'artifact_quota_exceeded'
                    self._replay_required = True
                    self._stats['failed'] += 1
                    self._condition.notify_all()
                return False
            with self.journal_path.open('ab') as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        return True

    def _terminate(self):
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            self.process.kill()

    def _rejection(self, frame: HydraFrame, reason: str, detail: str | None = None) -> HydraAdmission:
        with self._condition:
            self._stats['candidates'] += 1
            self._stats['dropped'] += 1
            self._journal_events.append({'event': 'dropped', 'source': _source(frame), 'reason': reason})
            self._condition.notify_all()
            return self._admission(reason, frame, 0, detail or reason)

    def _admission(self, status, frame, size, reason=None):
        return HydraAdmission(status, frame.source_key, size, int(self._pending is not None),
                              int(self._in_flight), reason)


def _source(frame: HydraFrame) -> dict:
    return {'episode_id': frame.source_key.episode_id, 'sensor_id': frame.source_key.sensor_id,
            'frame_index': frame.source_key.frame_index,
            'capture_monotonic_ns': frame.capture_monotonic_ns,
            'clock_domain': frame.clock_domain,
            'source_geometry_hash': frame.source_geometry_hash,
            'calibration_hash': frame.calibration_hash,
            'vocabulary_id': frame.vocabulary_id,
            'labelspace_id': frame.labelspace_id,
            'labelspace_hash': frame.labelspace_hash}


def _percentile(samples: list[float], fraction: float) -> float | None:
    if not samples:
        return None
    return float(samples[min(len(samples) - 1, round((len(samples) - 1) * fraction))])


def _process_rss_bytes(pid: int) -> int | None:
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def replay_selected_prefix(journal_path: str | Path, *, command: tuple[str, ...],
                           journal_output_path: str | Path, timeout_s: float = 120.0,
                           worker_timeout_s: float = 30.0) -> HydraSession:
    """Start a fresh episode process and replay precisely the journaled accepted prefix."""
    source_payloads: dict[str, str] = {}
    accepted_sources: set[str] = set()
    path = Path(journal_path)
    if not path.exists():
        raise ValueError('selected-input journal does not exist')
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            records.append(json.loads(line))
        except ValueError as exc:
            raise ValueError('selected-input journal contains malformed JSON') from exc
    target_run = next((record.get('run_id') for record in reversed(records)
        if (record.get('event') == 'accepted' and record.get('accepted') is True) or
           (record.get('event') == 'batch' and any(item.get('event') == 'accepted' and
             item.get('accepted') is True for item in record.get('events', [])))), None)
    if target_run is None:
        raise ValueError('journal contains no accepted selected inputs')
    for event in records:
        if event.get('run_id') != target_run:
            continue
        nested = event.get('events', []) if event.get('event') == 'batch' else [event]
        for item in nested:
            source = item.get('source')
            if not isinstance(source, dict):
                continue
            source_key = json.dumps(source, sort_keys=True, separators=(',', ':'))
            if item.get('event') == 'started' and isinstance(item.get('selected_frame'), str):
                source_payloads[source_key] = item['selected_frame']
            elif item.get('event') == 'accepted' and item.get('accepted') is True:
                accepted_sources.add(source_key)
    selected = [source_payloads[key] for key in source_payloads if key in accepted_sources]
    if not selected:
        raise ValueError('journal contains no accepted selected inputs')
    frames = [loads(payload) for payload in selected]
    if any(not isinstance(frame, HydraFrame) for frame in frames):
        raise ValueError('journal selected input is not a HydraFrame')
    episode_ids = {frame.source_key.episode_id for frame in frames}
    if len(episode_ids) != 1:
        raise ValueError('journal selected inputs cross episode boundaries')
    session = HydraSession(next(iter(episode_ids)), command=command,
        journal_path=journal_output_path, worker_timeout_s=worker_timeout_s)
    deadline = time.monotonic() + timeout_s
    try:
        for index, frame in enumerate(frames, start=1):
            result = session.offer(frame)
            if result.status not in {'queued', 'replaced'}:
                raise RuntimeError(f'cannot replay selected input: {result.status}')
            if not session.wait_for_revision(index, max(0., deadline - time.monotonic())):
                raise TimeoutError('selected-prefix replay did not complete')
        return session
    except BaseException:
        session.close(0.1)
        raise
