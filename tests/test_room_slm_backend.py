import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from neusymnav.rooms.slm_backend import LlamaCppRoomLabelBackend, RoomSlmBackendConfig
from test_room_context import candidate, query, support
from neusymnav.rooms.requests import make_room_label_request


FAKE_SERVER = Path(__file__).parent / 'fixtures' / 'room_label_fake_llama_server.py'


def config(tmp_path, *, mode='valid', **kwargs):
    model = tmp_path / 'model.gguf'
    model.write_bytes(b'fake model payload')
    binary = tmp_path / 'llama-server'
    binary.write_bytes(b'fake runtime payload')
    base = dict(enabled=True, model_path=str(model), model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        runtime_binary_path=str(binary), runtime_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        runtime_commit='a'*40, model_revision='b'*40, tokenizer_sha256='c'*64,
        chat_template_sha256='d'*64, model_license='Apache-2.0',
        supports_non_thinking=True, supports_json_schema=True,
        startup_timeout_s=1.0, inference_timeout_s=1.0)
    base.update(kwargs)
    return RoomSlmBackendConfig(**base)


def backend(config_value, *, mode='valid'):
    def popen(command, **kwargs):
        args = [sys.executable, str(FAKE_SERVER)]
        port = command[command.index('--port') + 1]
        env = dict(kwargs.get('env') or os.environ)
        env['ROOM_SLM_TEST_MODE'] = mode
        return subprocess.Popen(args + ['--port', port], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env)
    return LlamaCppRoomLabelBackend(config_value, process_factory=popen)


def request():
    return make_room_label_request(query([candidate('O(0)', 'toilet')]), {}, support())[0]


def test_gpu_offload_is_explicit_and_bound_to_model_manifest(tmp_path):
    cpu = config(tmp_path)
    gpu = config(tmp_path, gpu_device='Vulkan0')
    assert cpu.offload_args == ['--n-gpu-layers', '0']
    assert gpu.offload_args == ['--device', 'Vulkan0', '--n-gpu-layers', 'all']
    assert gpu.model_manifest_hash != cpu.model_manifest_hash


def test_missing_model_and_runtime_fail_closed_without_launch(tmp_path):
    missing = config(tmp_path, model_path=str(tmp_path/'absent.gguf'))
    service = LlamaCppRoomLabelBackend(missing)
    assert service.infer(request()).status == 'unavailable'
    assert service.last_metrics['launched'] is False


@pytest.mark.parametrize('field', ['model_sha256', 'runtime_sha256'])
def test_hash_mismatch_fails_before_subprocess_start(tmp_path, field):
    value = config(tmp_path, **{field:'0'*64})
    service = LlamaCppRoomLabelBackend(value)
    result = service.infer(request())
    assert result.status == 'unavailable'
    assert 'hash_mismatch' in result.reason
    assert service.last_metrics['launched'] is False


def test_real_subprocess_fixture_uses_loopback_single_thread_non_thinking_and_json_schema(tmp_path):
    value = config(tmp_path)
    service = backend(value)
    result = service.infer(request())
    assert result.status == 'proposed'
    assert result.supporting_object_ids == ('O(0)',)
    assert service.last_metrics['prompt_tokens'] == 16
    assert service.last_metrics['launched'] is True
    assert service.last_metrics['clean_shutdown'] is True
    assert service.last_metrics['latency_ms'] > 0


def test_oversized_model_response_becomes_invalid_output(tmp_path):
    service = backend(config(tmp_path), mode='oversized')
    assert service.infer(request()).status == 'invalid_output'


def test_timeout_crash_missing_template_and_unsupported_grammar_are_typed(tmp_path):
    slow = backend(config(tmp_path, inference_timeout_s=0.1), mode='timeout')
    slow_result = slow.infer(request())
    assert slow_result.status == 'timeout', slow_result.reason
    assert slow.last_metrics['launched'] is True
    assert slow.last_metrics['clean_shutdown'] is True

    crashed = backend(config(tmp_path), mode='crash')
    assert crashed.infer(request()).status == 'unavailable'
    assert 'crashed' in crashed.last_metrics['reason']

    missing_template_cfg = config(tmp_path, supports_non_thinking=False)
    assert LlamaCppRoomLabelBackend(missing_template_cfg).infer(request()).status == 'unavailable'

    no_grammar = backend(config(tmp_path, supports_json_schema=False))
    assert no_grammar.infer(request()).status == 'unavailable'
    assert 'json_schema' in no_grammar.last_metrics['reason']


def test_grammar_transport_and_native_diagnostic_metrics_are_retained(tmp_path):
    service = backend(config(tmp_path), mode='inspect_grammar')
    result = service.infer(request())
    assert result.status == 'proposed'
    metrics = service.last_metrics
    assert metrics['constraint_transport'] == 'request_bound_gbnf'
    assert metrics['grammar_policy_version'] == 'room-output-consistency-v1'
    assert len(metrics['grammar_sha256']) == 64
    assert metrics['native_timings']['cache_n'] == 0
    assert metrics['native_usage']['completion_tokens'] == 5
    assert metrics['finish_reason'] == 'stop'
    assert len(metrics['raw_output_sha256']) == 64


def test_token_budget_exhaustion_is_not_accepted_as_completed_proposal(tmp_path):
    service = backend(config(tmp_path), mode='finish_length')
    result = service.infer(request())
    assert result.status == 'invalid_output'
    assert result.reason == 'generation_truncated'
    assert service.last_metrics['finish_reason'] == 'length'
