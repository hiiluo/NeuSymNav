"""Opt-in persistent local llama.cpp backend for asynchronous room labels."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError

from ..contracts.room_semantics import RoomLabelProposal
from .prompt import PromptBudget, RoomPromptError
from .requests import RoomLabelRequest
from .slm_backend import (RoomSlmBackendConfig, _http_json, adapt_reply_for,
    apply_server_scheduling, build_room_completion_body, render_prompt_for)


class _BackendUnavailable(RuntimeError):
    pass


class _InferenceCancelled(RuntimeError):
    pass


class _JobDeadline(RuntimeError):
    pass


class PersistentRoomLabelBackend:
    """Own one reusable, single-slot loopback llama.cpp server.

    Inference calls serialize through ``_infer_lock``.  Cancellation and close
    touch only the process condition, so they can terminate a server while an
    HTTP request is in flight without waiting for inference to release its
    lock.
    """

    _HTTP_POLL_S = 0.025
    _HEALTH_POLL_S = 0.05
    _STOP_GRACE_S = 0.5

    def __init__(self, config: RoomSlmBackendConfig, *,
                 process_factory: Callable = subprocess.Popen):
        if not isinstance(config, RoomSlmBackendConfig):
            raise TypeError('config must be RoomSlmBackendConfig')
        self.config = config
        self._process_factory = process_factory
        self.last_metrics: dict[str, object] = {}

        self._infer_lock = threading.Lock()
        self._condition = threading.Condition(threading.Lock())
        self._generation = 0
        self._closed = False
        self._process = None
        self._process_generation: int | None = None
        self._base_url: str | None = None
        self._asset_signatures: dict[str, tuple] | None = None
        self._spawning = 0
        self._stopping = 0
        self._unreaped: list[object] = []
        self._close_clean: bool | None = None
        self._metrics_lock = threading.Lock()
        self.last_warmup: dict[str, object] | None = None

    def infer(self, request: RoomLabelRequest) -> RoomLabelProposal:
        if not isinstance(request, RoomLabelRequest):
            raise TypeError('request must be RoomLabelRequest')
        started_ns = time.monotonic_ns()
        deadline = time.monotonic() + self.config.inference_timeout_s
        metrics = self._initial_metrics(request)

        with self._condition:
            closed = self._closed
        if closed:
            result = self._failure(request, 'unavailable', 'room_label_backend_closed')
            return self._finish(result, metrics, started_ns)
        if request.inference_block_reason:
            result = self._failure(request, 'insufficient_evidence',
                request.inference_block_reason)
            return self._finish(result, metrics, started_ns)
        if not self.config.enabled:
            result = self._failure(request, 'unavailable', 'model_runtime_disabled')
            return self._finish(result, metrics, started_ns)

        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._infer_lock.acquire(timeout=max(0.0, remaining)):
            result = self._failure(request, 'timeout', 'room_label_job_deadline')
            return self._finish(result, metrics, started_ns)

        process = None
        generation = None
        try:
            with self._condition:
                if self._closed:
                    raise _InferenceCancelled('room_label_backend_closed')
                generation = self._generation
            self._check_active(generation, deadline)
            result, process = self._infer_one(request, generation, deadline, metrics)
            return self._finish(result, metrics, started_ns, process=process)
        except _InferenceCancelled as exc:
            result = self._failure(request, 'unavailable', str(exc) or 'inference_cancelled')
        except _JobDeadline as exc:
            self._drop_generation_process(generation)
            result = self._failure(request, 'timeout', str(exc) or 'room_label_job_deadline')
        except TimeoutError as exc:
            self._drop_generation_process(generation)
            result = self._failure(request, 'timeout', str(exc) or 'local_runtime_request_timeout')
        except _BackendUnavailable as exc:
            result = self._failure(request, 'unavailable', str(exc))
        except RoomPromptError as exc:
            result = self._failure(request, 'insufficient_evidence', exc.reason)
        except HTTPError as exc:
            self._drop_generation_process(generation)
            reason = ('generation_grammar_unsupported' if exc.code in {400, 404, 422}
                else f'local_runtime_http_{exc.code}')
            result = self._failure(request, 'unavailable', reason)
        except URLError as exc:
            self._drop_generation_process(generation)
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                result = self._failure(request, 'timeout', 'local_runtime_request_timeout')
            else:
                result = self._failure(request, 'unavailable',
                    f'local_runtime_transport_error:{type(exc.reason).__name__}')
        except (OSError, subprocess.SubprocessError) as exc:
            self._drop_generation_process(generation)
            result = self._failure(request, 'unavailable',
                f'local_runtime_transport_error:{type(exc).__name__}')
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result = self._failure(request, 'unavailable',
                f'local_runtime_response_invalid:{type(exc).__name__}:{str(exc)}')
        finally:
            self._infer_lock.release()
        return self._finish(result, metrics, started_ns, process=process)

    def warm(self) -> dict:
        """Start the server and prefill the static compact prefix once.

        Runs on a background thread owned by the debug service; it shares the
        inference lock, so a first real request simply waits for it. Failures
        are reported, never raised, and leave later requests to start the
        server through the normal path.
        """
        started_ns = time.monotonic_ns()
        report = {'warmed': False, 'reason': None, 'startup_ms': None,
            'native_timings': None, 'latency_ms': None}
        if not self.config.enabled:
            report['reason'] = 'model_runtime_disabled'
            return report
        if self.config.prompt_policy != 'compact-v2':
            report['reason'] = 'warmup_only_for_compact_policy'
            return report
        from .compact_policy import STATIC_PREFIX
        deadline = time.monotonic() + self.config.startup_timeout_s + self.config.inference_timeout_s
        if not self._infer_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            report['reason'] = 'warmup_lock_timeout'
            return report
        generation = None
        metrics = {}
        try:
            with self._condition:
                if self._closed:
                    raise _InferenceCancelled('room_label_backend_closed')
                generation = self._generation
            self._validate_runtime_pins()
            process, base_url, reused = self._existing_or_start(None, generation, deadline, metrics)
            report['startup_ms'] = metrics.get('startup_ms')
            report['server_reused'] = reused
            report['scheduling'] = metrics.get('scheduling')
            body = {'model': self.config.model_id,
                'messages': [{'role': 'user', 'content': STATIC_PREFIX}],
                'temperature': 0, 'seed': 0, 'max_tokens': 1, 'stream': False,
                'cache_prompt': True, 'chat_template_kwargs': {'enable_thinking': False}}
            response = self._http_deadlined('POST', base_url + '/v1/chat/completions',
                body, deadline, generation, max_response_bytes=128 * 1024)
            report['native_timings'] = response.get('timings') if isinstance(response, dict) else None
            report['warmed'] = True
        except (_JobDeadline, TimeoutError, HTTPError, URLError, OSError) as exc:
            self._drop_generation_process(generation)
            report['reason'] = f'{type(exc).__name__}: {exc}'[:256]
        except (_InferenceCancelled, _BackendUnavailable, KeyError, TypeError, ValueError) as exc:
            report['reason'] = f'{type(exc).__name__}: {exc}'[:256]
        finally:
            self._infer_lock.release()
        report['latency_ms'] = (time.monotonic_ns() - started_ns) / 1e6
        with self._metrics_lock:
            self.last_warmup = dict(report)
        return report

    def cancel(self) -> None:
        deadline = time.monotonic() + 1.5
        with self._condition:
            if not self._closed:
                self._generation += 1
            processes = self._detach_process_locked()
            self._condition.notify_all()
        self._stop_and_track(processes, deadline)
        self._wait_for_spawns(deadline)
        with self._condition:
            pending = self._take_unreaped_locked()
        self._stop_and_track(pending, deadline)

    def close(self, timeout_s: float = 3) -> dict:
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or timeout_s < 0):
            raise ValueError('timeout_s must be a finite non-negative number')
        deadline = time.monotonic() + float(timeout_s)
        with self._condition:
            if not self._closed:
                self._closed = True
                self._generation += 1
            processes = self._detach_process_locked()
            self._condition.notify_all()
        clean = self._stop_and_track(processes, deadline)
        spawn_clean = self._wait_for_spawns(deadline)
        with self._condition:
            pending = self._take_unreaped_locked()
        pending_clean = self._stop_and_track(pending, deadline)
        with self._condition:
            clean = (clean and spawn_clean and pending_clean and self._spawning == 0
                and self._stopping == 0 and not self._unreaped and self._process is None)
            self._close_clean = clean
        return {'clean_shutdown': clean, 'spawning': self._spawning,
            'stopping': self._stopping,
            'unreaped_processes': len(self._unreaped)}

    def _infer_one(self, request, generation, deadline, metrics):
        self._validate_runtime_pins()
        process, base_url, reused = self._existing_or_start(
            request, generation, deadline, metrics)
        metrics['server_reused'] = reused
        metrics['server_pid'] = getattr(process, 'pid', None)
        class EndpointTokenizer:
            def encode(inner_self, prompt_text):
                response = self._http_deadlined('POST', base_url + '/tokenize',
                    {'content': prompt_text}, deadline, generation)
                tokens = response.get('tokens') if isinstance(response, dict) else None
                if not isinstance(tokens, list):
                    raise _BackendUnavailable('runtime_tokenize_endpoint_invalid')
                metrics['prompt_tokens'] = len(tokens)
                return tokens

        try:
            prompt = render_prompt_for(self.config, request, EndpointTokenizer(),
                PromptBudget(self.config.max_input_tokens))
        except RoomPromptError:
            raise
        metrics['prompt_sha256'] = prompt.prompt_sha256
        metrics['schema_sha256'] = prompt.schema_sha256
        self._check_active(generation, deadline)
        grammar_started = time.monotonic_ns()
        body, grammar = build_room_completion_body(self.config, request, prompt,
            cache_prompt=True)
        metrics.update({'grammar_policy_version': grammar.policy_version,
            'grammar_sha256': grammar.grammar_sha256,
            'grammar_bytes': len(grammar.grammar_text.encode('utf-8')),
            'grammar_build_ms': (time.monotonic_ns() - grammar_started) / 1e6,
            'constraint_transport': 'request_bound_gbnf'})
        response = self._http_deadlined('POST', base_url + '/v1/chat/completions',
            body, deadline, generation, max_response_bytes=128 * 1024)
        choice = response['choices'][0]
        raw = choice['message']['content']
        metrics['native_timings'] = response.get('timings')
        metrics['native_usage'] = response.get('usage')
        metrics['finish_reason'] = choice.get('finish_reason')
        if isinstance(raw, str):
            raw_bytes = raw.encode('utf-8')
            metrics['raw_output_sha256'] = hashlib.sha256(raw_bytes).hexdigest()
            metrics['raw_output_bytes'] = len(raw_bytes)
        self._check_active(generation, deadline)
        if choice.get('finish_reason') == 'length':
            return self._failure(request, 'invalid_output', 'generation_truncated',
                model_hash=self.config.model_sha256, prompt_hash=prompt.prompt_sha256), process
        proposal = adapt_reply_for(self.config, raw, request,
            model_hash=self.config.model_sha256, prompt_hash=prompt.prompt_sha256)
        self._check_active(generation, deadline)
        return proposal, process

    def _existing_or_start(self, request, generation, deadline, metrics):
        changed_process = None
        with self._condition:
            self._assert_generation_locked(generation)
            process = self._process
            base_url = self._base_url
            signatures = self._asset_signatures
            if process is not None:
                if process.poll() is not None:
                    self._clear_process_locked(process)
                    process = None
                    base_url = None
                else:
                    changed = self._asset_signature_changes(signatures)
                    if changed:
                        self._detach_process_locked()
                        changed_process = process
                        process = None
                        base_url = None
                    else:
                        changed_process = None
                        metrics['startup_ms'] = 0.0
                        return process, base_url, True
            else:
                changed_process = None
        if changed_process is not None:
            self._stop_and_track([changed_process], time.monotonic() + 1.5)
            raise _BackendUnavailable(f'{changed}_asset_changed')
        self._check_active(generation, deadline)
        assets, signatures = self._verify_assets(generation, deadline)
        self._check_active(generation, deadline)
        process, base_url, startup_ms = self._start_server(
            request, generation, deadline, assets, signatures, metrics)
        metrics['startup_ms'] = startup_ms
        metrics['launched'] = True
        return process, base_url, False

    def _start_server(self, request, generation, deadline, assets, signatures, metrics):
        port = self._free_port()
        model_path, runtime_path = assets['model'], assets['runtime']
        command = [str(runtime_path), '--model', str(model_path), '--host', '127.0.0.1',
            '--port', str(port), '--threads', str(self.config.effective_threads),
            '--threads-batch', str(self.config.effective_threads), '--ctx-size',
            str(self.config.context_tokens), '--parallel', '1', '--n-gpu-layers', '0',
            '--no-webui', '--chat-template-kwargs', '{"enable_thinking":false}']
        env = dict(os.environ)
        env['HF_HUB_OFFLINE'] = '1'
        self._check_active(generation, deadline)
        with self._condition:
            self._assert_generation_locked(generation)
            self._spawning += 1
            self._condition.notify_all()
        spawn_started = time.monotonic()
        try:
            process = self._process_factory(command, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, env=env)
        except BaseException:
            with self._condition:
                self._spawning -= 1
                self._condition.notify_all()
            raise

        base_url = f'http://127.0.0.1:{port}'
        metrics['launched'] = True
        metrics['scheduling'] = apply_server_scheduling(process, self.config)
        with self._condition:
            accepted = not self._closed and self._generation == generation
            if accepted:
                self._process = process
                self._process_generation = generation
                self._base_url = base_url
                self._asset_signatures = signatures
                self._spawning -= 1
                self._condition.notify_all()
        if not accepted:
            clean = self._stop_process(process, time.monotonic() + 1.5)
            with self._condition:
                if not clean and process not in self._unreaped:
                    self._unreaped.append(process)
                self._spawning -= 1
                self._condition.notify_all()
            with self._condition:
                self._assert_generation_locked(generation)
            raise _InferenceCancelled('inference_cancelled')

        startup_deadline = min(deadline, time.monotonic() + self.config.startup_timeout_s)
        try:
            self._wait_for_health(process, base_url, generation, startup_deadline, deadline)
            changed = self._asset_signature_changes(signatures)
            if changed:
                raise _BackendUnavailable(f'{changed}_asset_changed_during_startup')
        except BaseException:
            self._drop_owned_process(process, generation)
            raise
        startup_ms = (time.monotonic() - spawn_started) * 1000.0
        return process, base_url, startup_ms

    def _wait_for_health(self, process, base_url, generation, startup_deadline, job_deadline):
        while True:
            self._check_active(generation, job_deadline)
            if process.poll() is not None:
                raise _BackendUnavailable(f'runtime_process_crashed:{process.returncode}')
            if time.monotonic() >= startup_deadline:
                reason = ('room_label_job_deadline' if job_deadline <= startup_deadline
                    else 'runtime_startup_timeout')
                raise _JobDeadline(reason)
            try:
                self._http_deadlined('GET', base_url + '/health', None,
                    startup_deadline, generation, overall_deadline=job_deadline)
                return
            except (URLError, HTTPError, OSError, TimeoutError, _JobDeadline) as exc:
                if isinstance(exc, _InferenceCancelled):
                    raise
                self._check_active(generation, job_deadline)
                if process.poll() is not None:
                    raise _BackendUnavailable(f'runtime_process_crashed:{process.returncode}')
                if time.monotonic() >= startup_deadline:
                    reason = ('room_label_job_deadline' if job_deadline <= startup_deadline
                        else 'runtime_startup_timeout')
                    raise _JobDeadline(reason) from exc
                time.sleep(min(self._HEALTH_POLL_S,
                    max(0.0, startup_deadline - time.monotonic())))

    def _http_deadlined(self, method, url, payload, deadline, generation,
                        *, overall_deadline=None, max_response_bytes=1024 * 1024):
        self._check_active(generation, overall_deadline or deadline)
        result = {}
        done = threading.Event()
        http_timeout = max(0.01, deadline - time.monotonic())

        def run_request():
            try:
                result['value'] = _http_json(method, url, payload, http_timeout,
                    max_response_bytes=max_response_bytes)
            except BaseException as exc:
                result['error'] = exc
            finally:
                done.set()

        worker = threading.Thread(target=run_request,
            name='room-label-local-http', daemon=True)
        worker.start()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason_deadline = overall_deadline or deadline
                reason = ('room_label_job_deadline' if reason_deadline <= deadline
                    else 'runtime_startup_timeout')
                raise _JobDeadline(reason)
            if done.wait(min(self._HTTP_POLL_S, remaining)):
                self._check_active(generation, overall_deadline or deadline)
                error = result.get('error')
                if error is not None:
                    raise error
                return result.get('value')
            self._check_active(generation, overall_deadline or deadline)

    def _verify_assets(self, generation, deadline):
        config = self.config
        assets = {}
        signatures = {}
        for label, path_value, expected in (
                ('model', config.model_path, config.model_sha256),
                ('runtime', config.runtime_binary_path, config.runtime_sha256)):
            if not path_value or not expected:
                raise _BackendUnavailable(f'{label}_asset_not_configured')
            path = Path(path_value)
            if not path.is_absolute() or not path.is_file():
                raise _BackendUnavailable(f'{label}_asset_missing')
            before = self._stat_signature(path, label)
            actual = self._hash_asset(path, generation, deadline)
            after = self._stat_signature(path, label)
            if before != after:
                raise _BackendUnavailable(f'{label}_asset_changed_during_verification')
            if actual != expected:
                raise _BackendUnavailable(f'{label}_hash_mismatch')
            assets[label] = path
            signatures[label] = after
        return assets, signatures

    def _hash_asset(self, path, generation, deadline):
        sha = hashlib.sha256()
        try:
            with path.open('rb') as stream:
                while True:
                    self._check_active(generation, deadline)
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    sha.update(chunk)
        except OSError as exc:
            raise _BackendUnavailable('asset_read_failed') from exc
        return sha.hexdigest()

    def _stat_signature(self, path, label):
        try:
            stat = path.stat()
        except OSError as exc:
            raise _BackendUnavailable(f'{label}_asset_missing') from exc
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
            stat.st_ctime_ns)

    def _asset_signature_changes(self, signatures):
        if not isinstance(signatures, dict):
            return 'model'
        for label in ('model', 'runtime'):
            path_value = (self.config.model_path if label == 'model'
                else self.config.runtime_binary_path)
            if not path_value:
                return label
            try:
                current = self._stat_signature(Path(path_value), label)
            except _BackendUnavailable:
                return label
            if signatures.get(label) != current:
                return label
        return None

    def _validate_runtime_pins(self):
        config = self.config
        if not config.model_revision or not config.runtime_commit or not config.model_license:
            raise _BackendUnavailable('model_or_runtime_revision_unpinned')
        if not config.tokenizer_sha256 or not config.chat_template_sha256:
            raise _BackendUnavailable('tokenizer_or_chat_template_hash_missing')
        if not config.supports_non_thinking:
            raise _BackendUnavailable('non_thinking_chat_template_unsupported')
        if not config.supports_json_schema:
            raise _BackendUnavailable('json_schema_grammar_unsupported')

    def _check_active(self, generation, deadline):
        with self._condition:
            self._assert_generation_locked(generation)
        if time.monotonic() >= deadline:
            raise _JobDeadline('room_label_job_deadline')

    def _assert_generation_locked(self, generation):
        if self._closed:
            raise _InferenceCancelled('room_label_backend_closed')
        if generation != self._generation:
            raise _InferenceCancelled('inference_cancelled')

    def _drop_owned_process(self, process, generation):
        if process is None:
            return
        with self._condition:
            if (self._process is process and self._process_generation == generation):
                processes = self._detach_process_locked()
            else:
                processes = []
        if processes:
            self._stop_and_track(processes, time.monotonic() + 1.5)

    def _drop_generation_process(self, generation):
        if generation is None:
            return
        with self._condition:
            if self._process is None or self._process_generation != generation:
                processes = []
            else:
                processes = self._detach_process_locked()
        if processes:
            self._stop_and_track(processes, time.monotonic() + 1.5)

    def _clear_process_locked(self, process):
        if self._process is process:
            self._process = None
            self._process_generation = None
            self._base_url = None
            self._asset_signatures = None

    def _detach_process_locked(self):
        process = self._process
        self._process = None
        self._process_generation = None
        self._base_url = None
        self._asset_signatures = None
        if process is not None:
            self._stopping += 1
            return [process]
        return []

    def _stop_and_track(self, processes, deadline):
        clean = True
        for process in processes:
            stopped = self._stop_process(process, deadline)
            with self._condition:
                if stopped:
                    self._unreaped = [item for item in self._unreaped if item is not process]
                elif process not in self._unreaped:
                    self._unreaped.append(process)
                self._stopping = max(0, self._stopping - 1)
                self._condition.notify_all()
            clean = clean and stopped
        return clean

    def _stop_process(self, process, deadline):
        try:
            if process.poll() is not None:
                process.wait(timeout=min(0.05, max(0.0, deadline - time.monotonic())))
                return process.poll() is not None
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass
            grace = min(self._STOP_GRACE_S, max(0.0, deadline - time.monotonic()))
            try:
                process.wait(timeout=grace)
                return process.poll() is not None
            except subprocess.TimeoutExpired:
                pass
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                return False
            return process.poll() is not None
        except (OSError, subprocess.SubprocessError):
            try:
                return process.poll() is not None
            except OSError:
                return False

    def _wait_for_spawns(self, deadline):
        with self._condition:
            while self._spawning or self._stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def _take_unreaped_locked(self):
        processes = self._unreaped
        self._unreaped = []
        self._stopping += len(processes)
        return processes

    @staticmethod
    def _free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def _initial_metrics(self, request):
        config = self.config
        request_wire = request.to_json()
        request_sha256 = hashlib.sha256(
            b'NeuSymNav:room-label-persistent-request:v1\0'
            + request_wire.encode('utf-8')).hexdigest()
        return {'launched': False, 'server_reused': False, 'reason': None,
            'request_id': request.request_id, 'request_sha256': request_sha256,
            'input_prefix_sha256': request.key.input_prefix_sha256,
            'geometry_hash': request.key.geometry_hash,
            'context_hash': request.key.context_hash,
            'model_sha256': config.model_sha256,
            'runtime_sha256': config.runtime_sha256,
            'model_manifest_hash': config.model_manifest_hash,
            'prompt_policy': config.prompt_policy,
            'prompt_sha256': None, 'grammar_sha256': None,
            'native_timings': None, 'native_usage': None,
            'raw_output_sha256': None, 'finish_reason': None}

    def _failure(self, request, status, reason, *, model_hash=None, prompt_hash=None):
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'unknown', (), (), status, str(reason)[:256],
            model_hash, prompt_hash)

    def _finish(self, result, metrics, started_ns, *, process=None):
        metrics['latency_ms'] = (time.monotonic_ns() - started_ns) / 1e6
        metrics['reason'] = result.reason
        if process is not None:
            try:
                metrics['server_running'] = process.poll() is None
            except OSError:
                metrics['server_running'] = False
        else:
            metrics['server_running'] = False
        with self._metrics_lock:
            self.last_metrics = dict(metrics)
        return result
