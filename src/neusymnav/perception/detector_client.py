"""Local YOLOE process isolation and bounded, no-pickle source-bound IPC.

The worker imports the actual P04 detector. This module imports no Torch,
Ultralytics or tokenizer. A failed exchange is terminal, so late responses can
never be consumed as a later frame. No fixture fallback exists.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time
from typing import Mapping
from types import MappingProxyType

from ..contracts import (DetectionBatch, Observation, Taxonomy, from_dict,
                         require_rgbd, to_dict, validate_detection_batch)
from .appearance_client import _write_all, _terminate_process_group

MAX_REQUEST_BYTES = 32 * 1024**2
MAX_RESPONSE_BYTES = 32 * 1024**2
RECIPE_KEYS = {'checkpoint_path', 'checkpoint_sha256', 'encoder_path', 'encoder_sha256',
               'taxonomy_path', 'taxonomy_sha256', 'checkpoint_license', 'imgsz',
               'max_detections', 'confidence_threshold', 'device'}


def validate_recipe(recipe):
    if not isinstance(recipe, Mapping) or set(recipe) != RECIPE_KEYS:
        raise ValueError('detector recipe requires the closed local YOLOE fields')
    result = dict(recipe)
    for asset in ('checkpoint', 'encoder', 'taxonomy'):
        path = Path(result[asset + '_path'])
        digest = result[asset + '_sha256']
        if not path.is_absolute() or not path.is_file():
            raise ValueError(asset + ' requires an existing absolute local path')
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError(asset + ' checksum mismatch')
        result[asset + '_path'] = str(path.resolve())
    if Path(result['encoder_path']).name not in {'mobileclip_blt.ts', 'mobileclip2_b.ts'}:
        raise ValueError('explicit local MobileCLIP encoder filename required')
    if type(result['imgsz']) is not int or result['imgsz'] not in (480, 512, 544, 640):
        raise ValueError('unsupported detector resolution')
    if type(result['max_detections']) is not int or not 1 <= result['max_detections'] <= 30:
        raise ValueError('unsupported max_detections')
    if (type(result['confidence_threshold']) not in (int, float)
            or not math.isfinite(result['confidence_threshold'])
            or not 0 <= result['confidence_threshold'] <= 1):
        raise ValueError('invalid detector confidence threshold')
    for name in ('checkpoint_license', 'device'):
        if not isinstance(result[name], str) or not result[name].strip():
            raise ValueError(name + ' must be explicit')
    Taxonomy.load(result['taxonomy_path'])
    return result


def _json(data):
    def reject(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    return json.loads(data, parse_constant=reject)


class _BoundedProcess:
    """Shared transport mechanics; framed detector or legacy sensor JSON-lines.

    Closing never waits for a request lock before killing the owned group.
    OS launch is synchronous; a close racing Popen reports incomplete until the
    launcher has observed cancellation, killed/reaped, and quiesced.
    """
    def __init__(self, command, *, timeout_s, response_limit, lines=False):
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('timeout_s must be positive finite')
        self.command, self.timeout_s = tuple(command), float(timeout_s)
        self.response_limit, self.lines = response_limit, lines
        self.process = None
        self.lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.closed = threading.Event()
        self.launch_done = threading.Event()
        self.launch_done.set()
        self.buffer = bytearray()
        self.diagnostics = deque(maxlen=32)
        self.stderr_thread = None

    def start(self):
        with self.process_lock:
            if self.closed.is_set():
                raise RuntimeError('worker is closed')
            self.launch_done.clear()
        process = None
        try:
            environment = os.environ.copy()
            environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                               HF_HUB_DISABLE_TELEMETRY='1', PYTHONNOUSERSITE='1')
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0, close_fds=True, start_new_session=True, env=environment)
            with self.process_lock:
                self.process = process
                cancelled = self.closed.is_set()
            if cancelled:
                _terminate_process_group(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
                raise RuntimeError('worker closed during startup')
            self.stderr_thread = threading.Thread(target=self._stderr, args=(process,), daemon=True)
            self.stderr_thread.start()
        finally:
            self.launch_done.set()

    def _stderr(self, process):
        try:
            while True:
                chunk = process.stderr.read(2048)
                if not chunk:
                    return
                self.diagnostics.append(chunk.decode('utf-8', errors='replace'))
        except (OSError, ValueError):
            pass

    def send(self, payload, deadline, limit=MAX_REQUEST_BYTES):
        encoded = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) > limit:
            raise ValueError('request exceeds wire byte bound')
        data = encoded + b'\n' if self.lines else len(encoded).to_bytes(4, 'big') + encoded
        process = self.process
        if self.closed.is_set() or process is None or process.poll() is not None:
            raise RuntimeError('worker is closed or exited')
        _write_all(process.stdin.fileno(), data, deadline)

    def receive(self, deadline):
        process = self.process
        if process is None or self.closed.is_set():
            raise RuntimeError('worker is closed')
        fd = process.stdout.fileno()
        os.set_blocking(fd, False)
        selector = selectors.DefaultSelector()
        selector.register(fd, selectors.EVENT_READ)
        # A large JSON-lines RGB reply arrives in many pipe fragments. Retain
        # the searched prefix within this receive call; otherwise each read
        # rescans all previous pixels (quadratic work). A new receive starts at
        # zero so any complete buffered next reply is still recognized.
        line_search_start = 0
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError('worker whole-operation deadline exceeded')
                size = None
                if self.lines:
                    end = self.buffer.find(b'\n', line_search_start)
                    if end < 0:
                        line_search_start = len(self.buffer)
                    if end >= 0:
                        size, offset = end, 0
                elif len(self.buffer) >= 4:
                    size, offset = int.from_bytes(self.buffer[:4], 'big'), 4
                if size is not None:
                    if size > self.response_limit:
                        raise ValueError('response exceeds wire byte bound')
                    if len(self.buffer) >= offset + size + (1 if self.lines else 0):
                        data = bytes(self.buffer[offset:offset + size])
                        del self.buffer[:offset + size + (1 if self.lines else 0)]
                        result = _json(data)
                        if not isinstance(result, dict):
                            raise ValueError('worker response must be an object')
                        if time.monotonic() >= deadline:
                            raise TimeoutError('worker whole-operation deadline exceeded during JSON decode')
                        return result
                if len(self.buffer) > self.response_limit + 4:
                    raise ValueError('response exceeds wire byte bound')
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError('worker whole-operation deadline exceeded')
                try:
                    chunk = os.read(fd, min(65536, self.response_limit + 5 - len(self.buffer)))
                except (BlockingIOError, InterruptedError):
                    continue
                if not chunk:
                    raise EOFError('worker stdout closed')
                self.buffer.extend(chunk)
        finally:
            selector.close()

    def close(self, timeout_s=1.):
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s < 0:
            raise ValueError('close timeout must be finite nonnegative')
        deadline = time.monotonic() + timeout_s
        self.closed.set()
        with self.process_lock:
            process = self.process
        if process is not None:
            _terminate_process_group(process, grace_s=min(.1, max(0., deadline-time.monotonic())))
        # After group kill, in-flight read/write wakes and releases its lock.
        quiesced = self.lock.acquire(timeout=max(0., deadline-time.monotonic()))
        if quiesced:
            self.lock.release()
        launch_done = self.launch_done.wait(timeout=max(0., deadline-time.monotonic()))
        if launch_done:
            with self.process_lock:
                process = self.process
            if process is not None:
                _terminate_process_group(process, grace_s=0.)
                # Native CUDA teardown can outlive the signal helper's short
                # grace. Observe exit within the caller's remaining shared
                # deadline instead of immediately publishing a pending child.
                if process.poll() is None:
                    try:process.wait(timeout=max(0.,deadline-time.monotonic()))
                    except subprocess.TimeoutExpired:pass
        if self.stderr_thread:
            self.stderr_thread.join(timeout=max(0., deadline-time.monotonic()))
        readers_stopped = self.stderr_thread is None or not self.stderr_thread.is_alive()
        reaped = process is None or process.poll() is not None
        if reaped and quiesced and launch_done and readers_stopped and process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        clean = reaped and quiesced and launch_done and readers_stopped
        return dict(clean_shutdown=clean, process_reaped=reaped, readers_stopped=readers_stopped,
                    operation_quiesced=quiesced, startup_quiesced=launch_done)


class DetectorClient:
    """Detector.infer implementation with an explicit independent Python 3.12+.

    Recipe fields are closed and hash-pinned. Worker startup loads the real P04
    YOLOE recipe offline, reports actual versions, then processes one source per
    request. Duplicate/nonchronological frames are rejected, never reinferred.
    """
    def __init__(self, *, python, recipe, timeout_s=2., startup_timeout_s=30., worker_script=None):
        path = Path(python)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError('python must be an explicit absolute executable interpreter')
        if type(startup_timeout_s) not in (int, float) or not math.isfinite(startup_timeout_s) or startup_timeout_s <= 0:
            raise ValueError('startup_timeout_s must be positive finite')
        self.recipe = MappingProxyType(validate_recipe(recipe))
        self.taxonomy = Taxonomy.load(self.recipe['taxonomy_path'])
        script = Path(worker_script) if worker_script else Path(__file__).with_name('detector_worker.py')
        self._wire = _BoundedProcess([str(path), '-u', str(script.resolve())],
                                    timeout_s=timeout_s, response_limit=MAX_RESPONSE_BYTES)
        self._startup_timeout_s = startup_timeout_s
        self._started = False
        self._watermarks = {}
        self._episode = None
        self.runtime_metadata = None

    @property
    def is_alive(self):
        p = self._wire.process
        return p is not None and p.poll() is None

    @property
    def diagnostics(self):
        return tuple(self._wire.diagnostics)

    def _start(self):
        self._wire.start()
        deadline = time.monotonic() + self._startup_timeout_s
        self._wire.send(dict(op='initialize', wire_version=1, recipe=dict(self.recipe)), deadline)
        response = self._wire.receive(deadline)
        if (set(response) != {'ok', 'wire_version', 'recipe_sha256', 'runtime'} or response['ok'] is not True
                or type(response['wire_version']) is not int or response['wire_version'] != 1):
            raise RuntimeError('detector worker unavailable: ' + str(response.get('error', response)))
        digest = hashlib.sha256(json.dumps(dict(self.recipe), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        runtime = response['runtime']
        if (response['recipe_sha256'] != digest or not isinstance(runtime, dict)
                or set(runtime) != {'python', 'numpy', 'torch', 'ultralytics', 'clip'}
                or any(not isinstance(v, str) or not v.strip() for v in runtime.values())):
            raise ValueError('detector actual recipe/runtime metadata mismatch')
        self.runtime_metadata, self._started = dict(runtime), True

    def infer(self, observation: Observation) -> DetectionBatch:
        require_rgbd(observation)
        if (observation.clock_domain.startswith('host_monotonic:')
                and observation.capture_monotonic_ns > time.monotonic_ns()):
            raise ValueError('detector observation capture is in the future')
        if not self._wire.lock.acquire(blocking=False):
            raise RuntimeError('detector request already in flight')
        try:
            if self._wire.closed.is_set():
                raise RuntimeError('detector worker is closed')
            sensor = (observation.key.episode_id, observation.key.sensor_id)
            watermark = self._watermarks.get(sensor)
            if self._episode is not None and self._episode != observation.key.episode_id:
                raise ValueError('detector client episode is pinned')
            if watermark is not None and (observation.key.frame_index <= watermark[0]
                                          or observation.capture_monotonic_ns <= watermark[1]):
                raise ValueError('detector source replay/nonchronological frame')
            if not self._started:
                self._start()
            self._episode = observation.key.episode_id
            self._watermarks[sensor] = (observation.key.frame_index, observation.capture_monotonic_ns)
            deadline = time.monotonic() + self._wire.timeout_s
            self._wire.send(dict(op='infer', wire_version=1, observation=to_dict(observation)), deadline)
            response = self._wire.receive(deadline)
            if (set(response) != {'ok', 'wire_version', 'batch'} or response['ok'] is not True
                    or type(response['wire_version']) is not int or response['wire_version'] != 1):
                raise ValueError('invalid detector response envelope')
            result = from_dict(response['batch'])
            validate_detection_batch(observation, result)
            if result.vocabulary_id != self.taxonomy.vocabulary_id or len(result.detections) > self.recipe['max_detections']:
                raise ValueError('detector vocabulary/count mismatch')
            for d in result.detections:
                if d.category != self.taxonomy.canonicalize(d.raw_label):
                    raise ValueError('detector taxonomy mismatch')
            if time.monotonic() >= deadline:
                raise TimeoutError('detector validation exceeded whole-operation deadline')
            return result
        except Exception:
            # Avoid close waiting on this request's own lock.
            self._wire.closed.set()
            if self._wire.process is not None:
                _terminate_process_group(self._wire.process)
            raise
        finally:
            self._wire.lock.release()
            if self._wire.closed.is_set():
                self._wire.close()

    def close(self, timeout_s=1.):
        return self._wire.close(timeout_s)
