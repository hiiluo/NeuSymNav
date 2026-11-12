"""Opt-in, local-only llama.cpp backend for offline room-label proposals."""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Callable, TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from ..contracts._base import digest, integer, text
from ..contracts.room_semantics import RoomLabelProposal
from .labels import MAX_RESPONSE_BYTES, adapt_model_reply
from .prompt import MAX_INPUT_TOKENS, OUTPUT_SCHEMA_SHA256, PromptBudget, PromptRecord, RoomPromptError, render_room_prompt
from .requests import RoomLabelRequest


if TYPE_CHECKING:
    from .output_grammar import RoomOutputGrammar


MAX_OUTPUT_TOKENS = 384
MAX_CONTEXT_TOKENS = 4096
MAX_TIMEOUT_S = 60.0
MAX_THREADS = 32
PROMPT_POLICIES = frozenset({'json-v1', 'compact-v2'})


@dataclass(frozen=True, slots=True)
class RoomSlmBackendConfig:
    enabled: bool = False
    model_id: str = 'Qwen/Qwen3-1.7B'
    model_revision: str | None = None
    model_path: str | None = None
    model_sha256: str | None = None
    model_license: str | None = None
    runtime_binary_path: str | None = None
    runtime_sha256: str | None = None
    runtime_commit: str | None = None
    tokenizer_sha256: str | None = None
    chat_template_sha256: str | None = None
    supports_non_thinking: bool = False
    supports_json_schema: bool = False
    threads: int = 1
    context_tokens: int = MAX_CONTEXT_TOKENS
    max_input_tokens: int = MAX_INPUT_TOKENS
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    startup_timeout_s: float = 60.0
    inference_timeout_s: float = 60.0
    # Scheduling of the model server only; never shared with control workers.
    nice: int = 0
    cpu_affinity: tuple[int, ...] | None = None
    # json-v1 keeps the original verbose prompt/JSON grammar for offline
    # reproducibility; compact-v2 is the low-latency live policy.
    prompt_policy: str = 'json-v1'
    gpu_device: str | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('enabled must be bool')
        text(self.model_id, 'model_id')
        for name in ('model_revision', 'model_path', 'model_license', 'runtime_binary_path',
                     'runtime_commit'):
            value = getattr(self, name)
            if value is not None:
                text(value, name)
        for name in ('model_sha256', 'runtime_sha256', 'tokenizer_sha256', 'chat_template_sha256'):
            value = getattr(self, name)
            if value is not None:
                digest(value, name)
        for name in ('supports_non_thinking', 'supports_json_schema'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be bool')
        integer(self.threads, 'threads', minimum=1)
        if self.threads > MAX_THREADS:
            raise ValueError(f'threads must be <= {MAX_THREADS}')
        integer(self.nice, 'nice', minimum=0)
        if self.nice > 19:
            raise ValueError('nice must be in [0, 19]')
        if self.cpu_affinity is not None:
            if isinstance(self.cpu_affinity, (str, bytes)) or not isinstance(self.cpu_affinity, (list, tuple)):
                raise ValueError('cpu_affinity must be a list of CPU indices or null')
            cpus = tuple(self.cpu_affinity)
            if not cpus or len(set(cpus)) != len(cpus):
                raise ValueError('cpu_affinity must list distinct CPU indices')
            for cpu in cpus:
                integer(cpu, 'cpu_affinity item', minimum=0)
            object.__setattr__(self, 'cpu_affinity', cpus)
        if self.prompt_policy not in PROMPT_POLICIES:
            raise ValueError(f'prompt_policy must be one of {sorted(PROMPT_POLICIES)}')
        if self.gpu_device is not None:
            text(self.gpu_device, 'gpu_device')
            if self.gpu_device.lower() == 'none' or ',' in self.gpu_device:
                raise ValueError('gpu_device must name one accelerator')
        integer(self.context_tokens, 'context_tokens', minimum=1)
        integer(self.max_input_tokens, 'max_input_tokens', minimum=1)
        integer(self.max_output_tokens, 'max_output_tokens', minimum=1)
        if self.context_tokens != MAX_CONTEXT_TOKENS or self.max_input_tokens > MAX_INPUT_TOKENS:
            raise ValueError('context and input budgets exceed the pilot contract')
        if self.max_output_tokens > MAX_OUTPUT_TOKENS:
            raise ValueError('output budget exceeds the pilot contract')
        for name in ('startup_timeout_s', 'inference_timeout_s'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= MAX_TIMEOUT_S:
                raise ValueError(f'{name} must be in (0, {MAX_TIMEOUT_S}]')

    @property
    def effective_threads(self) -> int:
        """Requested threads clamped to the CPUs this process may use."""
        try:
            available = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            available = os.cpu_count() or 1
        if self.cpu_affinity is not None:
            available = min(available, len(self.cpu_affinity))
        return max(1, min(self.threads, available))

    @property
    def offload_args(self) -> list[str]:
        if self.gpu_device is None:
            return ['--n-gpu-layers', '0']
        return ['--device', self.gpu_device, '--n-gpu-layers', 'all']

    @property
    def model_manifest_hash(self) -> str:
        payload = {item.name: getattr(self, item.name) for item in fields(self)}
        if self.gpu_device is None:
            del payload['gpu_device']
        if payload['cpu_affinity'] is not None:
            payload['cpu_affinity'] = list(payload['cpu_affinity'])
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(b'NeuSymNav:room-slm-model-manifest:v1\0' + encoded.encode()).hexdigest()

    @classmethod
    def from_json(cls, path: str | Path) -> 'RoomSlmBackendConfig':
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise ValueError('unsupported room SLM config schema')
        return cls(**{item.name: value[item.name] for item in fields(cls) if item.name in value})


def render_prompt_for(config: RoomSlmBackendConfig, request: RoomLabelRequest, tokenizer,
                      budget: PromptBudget) -> PromptRecord:
    """Render the prompt of the configured policy (json-v1 or compact-v2)."""
    if config.prompt_policy == 'compact-v2':
        from .compact_policy import render_compact_room_prompt
        return render_compact_room_prompt(request, tokenizer, budget)
    return render_room_prompt(request, tokenizer, budget)


def adapt_reply_for(config: RoomSlmBackendConfig, raw, request: RoomLabelRequest, *,
                    model_hash: str, prompt_hash: str) -> RoomLabelProposal:
    if config.prompt_policy == 'compact-v2':
        from .compact_policy import adapt_compact_reply
        return adapt_compact_reply(raw, request, model_hash=model_hash, prompt_hash=prompt_hash)
    return adapt_model_reply(raw, request, model_hash=model_hash, prompt_hash=prompt_hash)


def build_room_completion_body(config: RoomSlmBackendConfig, request: RoomLabelRequest,
                               prompt: PromptRecord, *, cache_prompt: bool = False
                               ) -> tuple[dict, "RoomOutputGrammar"]:
    """One shared transport for the offline backend and controlled KV measurements."""
    from .output_grammar import build_room_output_grammar
    if not isinstance(config, RoomSlmBackendConfig) or not isinstance(request, RoomLabelRequest):
        raise TypeError('config/request must be room SLM contracts')
    if not isinstance(prompt, PromptRecord):
        raise TypeError('prompt must be PromptRecord')
    if prompt.retained_object_ids != tuple(item.native_id for item in request.context.objects):
        raise ValueError('prompt object IDs do not match request context')
    if type(cache_prompt) is not bool:
        raise TypeError('cache_prompt must be bool')
    max_tokens = config.max_output_tokens
    if config.prompt_policy == 'compact-v2':
        from .compact_policy import COMPACT_MAX_OUTPUT_TOKENS, build_compact_output_grammar
        grammar = build_compact_output_grammar(request)
        max_tokens = min(max_tokens, COMPACT_MAX_OUTPUT_TOKENS)
    else:
        grammar = build_room_output_grammar(request)
    body = {'model': config.model_id,
        'messages': [{'role': 'user', 'content': prompt.prompt_text}],
        'temperature': 0, 'seed': 0, 'max_tokens': max_tokens,
        'stream': False, 'cache_prompt': cache_prompt,
        'chat_template_kwargs': {'enable_thinking': False},
        'grammar': grammar.grammar_text}
    # Do not send response_format/json_schema as well: llama.cpp rejects both.
    return body, grammar


class _BackendUnavailable(RuntimeError):
    pass


class LlamaCppRoomLabelBackend:
    """Launch a pinned local CPU server per request; never contacts remote APIs."""

    def __init__(self, config: RoomSlmBackendConfig, *, process_factory: Callable = subprocess.Popen):
        if not isinstance(config, RoomSlmBackendConfig):
            raise TypeError('config must be RoomSlmBackendConfig')
        self.config = config
        self._process_factory = process_factory
        self.last_metrics: dict[str, object] = {}
        self._lock = threading.Lock()

    def infer(self, request: RoomLabelRequest) -> RoomLabelProposal:
        if not isinstance(request, RoomLabelRequest):
            raise TypeError('request must be RoomLabelRequest')
        started = time.monotonic_ns()
        self.last_metrics = {'launched': False, 'reason': None}
        if request.inference_block_reason:
            return self._proposal(request, 'insufficient_evidence', request.inference_block_reason)
        if not self.config.enabled:
            return self._proposal(request, 'unavailable', 'model_runtime_disabled')
        with self._lock:
            return self._infer_locked(request, started)

    def _infer_locked(self, request: RoomLabelRequest, started: int) -> RoomLabelProposal:
        config = self.config
        job_deadline = time.monotonic() + config.inference_timeout_s
        try:
            model_path = self._verified_file(config.model_path, config.model_sha256, 'model')
            runtime_path = self._verified_file(config.runtime_binary_path, config.runtime_sha256, 'runtime')
            if not config.model_revision or not config.runtime_commit or not config.model_license:
                raise _BackendUnavailable('model_or_runtime_revision_unpinned')
            if not config.tokenizer_sha256 or not config.chat_template_sha256:
                raise _BackendUnavailable('tokenizer_or_chat_template_hash_missing')
            if not config.supports_non_thinking:
                raise _BackendUnavailable('non_thinking_chat_template_unsupported')
            if not config.supports_json_schema:
                raise _BackendUnavailable('json_schema_grammar_unsupported')
        except _BackendUnavailable as exc:
            return self._failure(request, 'unavailable', str(exc), started)

        port = self._free_port()
        command = [str(runtime_path), '--model', str(model_path), '--host', '127.0.0.1',
            '--port', str(port), '--threads', str(config.effective_threads),
            '--threads-batch', str(config.effective_threads), '--ctx-size', str(config.context_tokens),
            '--parallel', '1', *config.offload_args, '--no-webui',
            '--chat-template-kwargs', '{"enable_thinking":false}']
        env = dict(os.environ)
        env['HF_HUB_OFFLINE'] = '1'
        process = None
        prompt = None
        sampler = None
        sampler_stop = threading.Event()
        metrics = {'launched': False, 'reason': None, 'prompt_tokens': None,
            'sampled_peak_rss_bytes': 0, 'sampled_peak_pss_bytes': 0,
            'resource_samples': 0, 'host_available_bytes_start': _meminfo('MemAvailable'),
            'swap_used_bytes_start': _meminfo('SwapTotal') - _meminfo('SwapFree')}
        # Failure paths update last_metrics; keep it attached to this request's
        # live measurements so timeout/invalid responses retain launch and RSS.
        self.last_metrics = metrics
        try:
            process = self._process_factory(command, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, env=env)
            metrics['launched'] = True
            metrics['scheduling'] = apply_server_scheduling(process, config)
            sampler = threading.Thread(target=self._sample_child, args=(process.pid, sampler_stop, metrics),
                name='room-slm-resource-sampler', daemon=True)
            sampler.start()
            startup_deadline = min(time.monotonic() + config.startup_timeout_s, job_deadline)
            base = f'http://127.0.0.1:{port}'
            while True:
                if process.poll() is not None:
                    raise _BackendUnavailable(f'runtime_process_crashed:{process.returncode}')
                try:
                    _http_json('GET', base + '/health', None,
                        min(.5, self._remaining(startup_deadline)))
                    break
                except (URLError, TimeoutError, OSError):
                    if time.monotonic() >= startup_deadline:
                        raise TimeoutError('runtime_startup_timeout')
                    time.sleep(.05)

            class EndpointTokenizer:
                def encode(self, prompt_text):
                    result = _http_json('POST', base + '/tokenize', {'content':prompt_text},
                        LlamaCppRoomLabelBackend._remaining(job_deadline))
                    tokens = result.get('tokens') if isinstance(result, dict) else None
                    if not isinstance(tokens, list):
                        raise _BackendUnavailable('runtime_tokenize_endpoint_invalid')
                    metrics['prompt_tokens'] = len(tokens)
                    return tokens

            prompt = render_prompt_for(config, request, EndpointTokenizer(),
                PromptBudget(config.max_input_tokens))
            metrics['prompt_sha256'] = prompt.prompt_sha256
            metrics['schema_sha256'] = prompt.schema_sha256
            grammar_started = time.monotonic_ns()
            body, grammar = build_room_completion_body(config, request, prompt)
            metrics['grammar_policy_version'] = grammar.policy_version
            metrics['grammar_sha256'] = grammar.grammar_sha256
            metrics['grammar_bytes'] = len(grammar.grammar_text.encode())
            metrics['grammar_build_ms'] = (time.monotonic_ns() - grammar_started) / 1e6
            metrics['constraint_transport'] = 'request_bound_gbnf'
            response = _http_json('POST', base + '/v1/chat/completions', body,
                self._remaining(job_deadline), max_response_bytes=128 * 1024)
            choice = response['choices'][0]
            raw = choice['message']['content']
            metrics['native_timings'] = response.get('timings')
            metrics['native_usage'] = response.get('usage')
            metrics['finish_reason'] = choice.get('finish_reason')
            if isinstance(raw, str):
                metrics['raw_output_sha256'] = hashlib.sha256(raw.encode('utf-8')).hexdigest()
                metrics['raw_output_bytes'] = len(raw.encode('utf-8'))
            if choice.get('finish_reason') == 'length':
                return self._failure(request, 'invalid_output', 'generation_truncated', started, prompt)
            result = adapt_reply_for(config, raw, request, model_hash=config.model_sha256,
                prompt_hash=prompt.prompt_sha256)
            metrics['latency_ms'] = (time.monotonic_ns() - started) / 1e6
            metrics['model_manifest_hash'] = config.model_manifest_hash
            self.last_metrics = metrics
            return result
        except RoomPromptError as exc:
            return self._failure(request, 'insufficient_evidence', exc.reason, started, prompt)
        except TimeoutError as exc:
            return self._failure(request, 'timeout', str(exc) or 'inference_timeout', started, prompt)
        except _BackendUnavailable as exc:
            return self._failure(request, 'unavailable', str(exc), started, prompt)
        except HTTPError as exc:
            reason = 'generation_grammar_unsupported' if exc.code in {400, 404, 422} else f'local_runtime_http_{exc.code}'
            return self._failure(request, 'unavailable', reason, started, prompt)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(request, 'unavailable', f'local_runtime_response_invalid:{type(exc).__name__}:{str(exc)}', started, prompt)
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return self._failure(request, 'timeout', 'local_runtime_request_timeout', started, prompt)
            return self._failure(request, 'unavailable', f'local_runtime_transport_error:{type(exc.reason).__name__}', started, prompt)
        except (OSError, subprocess.SubprocessError) as exc:
            return self._failure(request, 'unavailable', f'local_runtime_transport_error:{type(exc).__name__}', started, prompt)
        finally:
            sampler_stop.set()
            if sampler is not None:
                sampler.join(timeout=1.0)
            clean = True
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        clean = False
            metrics.update(self.last_metrics)
            self.last_metrics = metrics
            self.last_metrics.update({'clean_shutdown':clean,
                'latency_ms':(time.monotonic_ns()-started)/1e6,
                'host_available_bytes_end':_meminfo('MemAvailable'),
                'swap_used_bytes_end':_meminfo('SwapTotal')-_meminfo('SwapFree')})

    @staticmethod
    def _verified_file(path, expected_hash, label):
        if not path or not expected_hash:
            raise _BackendUnavailable(f'{label}_asset_not_configured')
        candidate = Path(path)
        if not candidate.is_absolute() or not candidate.is_file():
            raise _BackendUnavailable(f'{label}_asset_missing')
        actual = _sha256(candidate)
        if actual != expected_hash:
            raise _BackendUnavailable(f'{label}_hash_mismatch')
        return candidate

    @staticmethod
    def _free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('room_label_job_deadline')
        return remaining

    @staticmethod
    def _sample_child(pid, stop, metrics):
        while not stop.is_set():
            status = Path(f'/proc/{pid}/status')
            rollup = Path(f'/proc/{pid}/smaps_rollup')
            try:
                text_status = status.read_text()
                rss = next((int(line.split()[1])*1024 for line in text_status.splitlines()
                    if line.startswith('VmRSS:')), 0)
                pss_text = rollup.read_text()
                pss = next((int(line.split()[1])*1024 for line in pss_text.splitlines()
                    if line.startswith('Pss:')), 0)
                metrics['sampled_peak_rss_bytes'] = max(metrics['sampled_peak_rss_bytes'], rss)
                metrics['sampled_peak_pss_bytes'] = max(metrics['sampled_peak_pss_bytes'], pss)
                metrics['resource_samples'] += 1
            except (OSError, StopIteration, ValueError):
                pass
            stop.wait(.1)

    @staticmethod
    def _proposal(request, status, reason):
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'unknown', (), (), status, reason[:256], None, None)

    def _failure(self, request, status, reason, started, prompt=None):
        model_hash = self.config.model_sha256 if prompt is not None else None
        prompt_hash = prompt.prompt_sha256 if prompt is not None else None
        self.last_metrics.update({'launched':self.last_metrics.get('launched',False),
            'reason':reason[:256], 'latency_ms':(time.monotonic_ns()-started)/1e6,
            'prompt_tokens':self.last_metrics.get('prompt_tokens'),
            'model_manifest_hash':self.config.model_manifest_hash if prompt is not None else None})
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'unknown', (), (), status, reason[:256], model_hash, prompt_hash)


def apply_server_scheduling(process, config: RoomSlmBackendConfig) -> dict:
    """Lower the model server's priority and pin it right after spawn.

    llama.cpp creates its compute threads only after loading weights, so
    setting the main thread here is inherited by every worker thread.
    """
    pid = getattr(process, 'pid', None)
    report = {'threads': config.effective_threads, 'nice': None, 'cpu_affinity': None}
    if not isinstance(pid, int) or pid <= 0:
        return report
    if config.nice:
        try:
            os.setpriority(os.PRIO_PROCESS, pid, config.nice)
            report['nice'] = config.nice
        except (AttributeError, OSError, PermissionError):
            report['nice'] = 'failed'
    if config.cpu_affinity is not None:
        try:
            os.sched_setaffinity(pid, set(config.cpu_affinity))
            report['cpu_affinity'] = list(config.cpu_affinity)
        except (AttributeError, OSError, PermissionError):
            report['cpu_affinity'] = 'failed'
    return report


def _output_schema():
    from .prompt import _OUTPUT_SCHEMA
    return _OUTPUT_SCHEMA


def _http_json(method, url, payload, timeout, *, max_response_bytes=1024*1024):
    started = time.monotonic()
    data = None if payload is None else json.dumps(payload, separators=(',', ':')).encode()
    req = UrlRequest(url, data=data, method=method,
        headers={} if data is None else {'Content-Type':'application/json'})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(max_response_bytes + 1)
    if len(raw) > max_response_bytes:
        raise _BackendUnavailable('local_runtime_response_exceeds_transport_limit')
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        if not raw or time.monotonic() - started >= timeout * .9:
            raise TimeoutError('local_runtime_empty_response_timeout') from exc
        raise _BackendUnavailable('local_runtime_response_not_json') from exc


def _sha256(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def _meminfo(name):
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value, *_ = line.split()
            if key.rstrip(':') == name:
                return int(value) * 1024
    except (OSError, ValueError):
        pass
    return None
