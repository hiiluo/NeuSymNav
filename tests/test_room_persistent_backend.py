from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from test_room_context import candidate, query, support
from neusymnav.rooms.requests import make_room_label_request
from neusymnav.rooms.slm_backend import RoomSlmBackendConfig


FAKE_SERVER = Path(__file__).parent / 'fixtures' / 'room_persistent_fake_server.py'


def backend_class():
    name = 'neusymnav.rooms.persistent_backend'
    spec = importlib.util.find_spec(name)
    assert spec is not None, 'persistent room backend module is missing'
    module = importlib.import_module(name)
    backend_type = getattr(module, 'PersistentRoomLabelBackend', None)
    assert backend_type is not None, 'PersistentRoomLabelBackend is missing'
    return backend_type


def make_config(tmp_path: Path, *, enabled=True, **overrides):
    model = tmp_path / 'model.gguf'
    model.write_bytes(b'persistent fake model')
    runtime = tmp_path / 'llama-server'
    runtime.write_bytes(b'persistent fake runtime')
    fields = dict(enabled=enabled, model_path=str(model),
        model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
        runtime_binary_path=str(runtime),
        runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
        runtime_commit='a' * 40, model_revision='b' * 40,
        tokenizer_sha256='c' * 64, chat_template_sha256='d' * 64,
        model_license='Apache-2.0', supports_non_thinking=True,
        supports_json_schema=True, startup_timeout_s=1.0,
        inference_timeout_s=1.0)
    fields.update(overrides)
    return RoomSlmBackendConfig(**fields)


def make_request(native_id='O(0)'):
    return make_room_label_request(query([candidate(native_id, 'toilet')]), {}, support())[0]


class FakeServerLauncher:
    def __init__(self, *, modes=('valid',), events_path=None):
        self.modes = tuple(modes)
        self.events_path = events_path
        self.processes = []
        self.commands = []
        self.environments = []
        self.lock = threading.Lock()

    def __call__(self, command, **kwargs):
        with self.lock:
            index = len(self.processes)
            mode = self.modes[min(index, len(self.modes) - 1)]
        port = command[command.index('--port') + 1]
        env = dict(kwargs['env'])
        env['ROOM_PERSISTENT_TEST_MODE'] = mode
        if self.events_path is not None:
            env['ROOM_PERSISTENT_TEST_EVENTS'] = str(self.events_path)
        process = subprocess.Popen([sys.executable, str(FAKE_SERVER), '--port', port],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, env=env)
        with self.lock:
            self.processes.append(process)
            self.commands.append(tuple(command))
            self.environments.append(dict(kwargs['env']))
        return process


def read_events(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def wait_for_event(path: Path, name: str, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(row.get('event') == name for row in read_events(path)):
            return
        time.sleep(0.01)
    raise AssertionError(f'timed out waiting for fixture event {name!r}')


def test_disabled_backend_returns_typed_unavailable_without_launch(tmp_path):
    launcher = FakeServerLauncher()
    backend = backend_class()(make_config(tmp_path, enabled=False), process_factory=launcher)

    result = backend.infer(make_request())

    assert result.status == 'unavailable'
    assert result.reason == 'model_runtime_disabled'
    assert launcher.processes == []
    assert backend.last_metrics['launched'] is False


def test_enabled_backend_with_missing_assets_fails_closed_without_launch(tmp_path):
    launcher = FakeServerLauncher()
    backend = backend_class()(make_config(tmp_path,
        model_path=str(tmp_path / 'missing.gguf')), process_factory=launcher)

    result = backend.infer(make_request())

    assert result.status == 'unavailable'
    assert result.reason == 'model_asset_missing'
    assert launcher.processes == []
    assert backend.last_metrics['launched'] is False


def test_close_is_idempotent_and_inference_after_close_never_relaunches(tmp_path):
    launcher = FakeServerLauncher()
    backend = backend_class()(make_config(tmp_path), process_factory=launcher)

    first = backend.close(timeout_s=0.1)
    second = backend.close(timeout_s=0.1)
    result = backend.infer(make_request())

    assert first['clean_shutdown'] is True
    assert second['clean_shutdown'] is True
    assert result.status == 'unavailable'
    assert result.reason == 'room_label_backend_closed'
    assert launcher.processes == []


def test_successful_calls_reuse_one_server_and_send_request_bound_cached_grammar(tmp_path):
    events = tmp_path / 'server-events.jsonl'
    launcher = FakeServerLauncher(events_path=events)
    backend = backend_class()(make_config(tmp_path), process_factory=launcher)

    first = backend.infer(make_request('O(0)'))
    first_metrics = dict(backend.last_metrics)
    second = backend.infer(make_request('O(1)'))

    assert first.status == second.status == 'proposed'
    assert first.supporting_object_ids == ('O(0)',)
    assert second.supporting_object_ids == ('O(1)',)
    assert len(launcher.processes) == 1
    assert first_metrics['server_reused'] is False
    assert backend.last_metrics['server_reused'] is True
    assert backend.last_metrics['native_timings']['cache_n'] > 0
    assert len(backend.last_metrics['request_sha256']) == 64
    assert backend.last_metrics['model_sha256'] == backend.config.model_sha256
    assert backend.last_metrics['runtime_sha256'] == backend.config.runtime_sha256
    completions = [row for row in read_events(events) if row['event'] == 'completion']
    assert len(completions) == 2
    assert [row['supporting_id'] for row in completions] == ['O(0)', 'O(1)']
    assert all(row['cache_prompt'] is True for row in completions)
    assert all('root ::=' in row['grammar'] for row in completions)
    assert all(row['enable_thinking'] is False for row in completions)
    command = launcher.commands[0]
    assert command[command.index('--threads') + 1] == '1'
    assert command[command.index('--parallel') + 1] == '1'
    assert command[command.index('--n-gpu-layers') + 1] == '0'
    assert command[command.index('--host') + 1] == '127.0.0.1'
    assert launcher.environments[0]['HF_HUB_OFFLINE'] == '1'
    process = launcher.processes[0]
    closed = backend.close(timeout_s=1.0)
    assert closed['clean_shutdown'] is True
    assert process.poll() is not None


def test_timeout_kills_server_and_next_call_restarts_without_hidden_retry(tmp_path):
    events = tmp_path / 'server-events.jsonl'
    launcher = FakeServerLauncher(modes=('timeout_first_completion', 'valid'),
        events_path=events)
    backend = backend_class()(make_config(tmp_path, inference_timeout_s=0.25),
        process_factory=launcher)

    timed_out = backend.infer(make_request('O(0)'))
    first_process = launcher.processes[0]
    recovered = backend.infer(make_request('O(1)'))

    assert timed_out.status == 'timeout'
    assert timed_out.reason == 'room_label_job_deadline'
    assert first_process.poll() is not None
    assert recovered.status == 'proposed'
    assert len(launcher.processes) == 2
    assert backend.last_metrics['server_reused'] is False
    starts = [row for row in read_events(events) if row['event'] == 'completion_start']
    assert [row['supporting_id'] for row in starts] == ['O(0)', 'O(1)']


def test_crashed_server_is_reaped_and_next_request_starts_a_fresh_server(tmp_path):
    events = tmp_path / 'server-events.jsonl'
    launcher = FakeServerLauncher(modes=('crash_first_completion', 'valid'),
        events_path=events)
    backend = backend_class()(make_config(tmp_path), process_factory=launcher)

    crashed = backend.infer(make_request('O(0)'))
    first_process = launcher.processes[0]
    recovered = backend.infer(make_request('O(1)'))

    assert crashed.status == 'unavailable'
    assert first_process.poll() is not None
    assert recovered.status == 'proposed'
    assert len(launcher.processes) == 2


def test_generation_truncation_is_rejected_even_when_json_is_valid(tmp_path):
    launcher = FakeServerLauncher(modes=('finish_length',))
    backend = backend_class()(make_config(tmp_path), process_factory=launcher)

    result = backend.infer(make_request())

    assert result.status == 'invalid_output'
    assert result.reason == 'generation_truncated'
    assert backend.last_metrics['finish_reason'] == 'length'
    assert len(backend.last_metrics['raw_output_sha256']) == 64


@pytest.mark.parametrize(('phase', 'mode', 'signal_event'), [
    ('health', 'delay_start', 'startup_wait'),
    ('tokenize', 'block_tokenize', 'tokenize_start'),
    ('completion', 'block_completion', 'completion_start'),
])
def test_cancel_aborts_active_phase_and_next_inference_can_restart(
        tmp_path, phase, mode, signal_event):
    events = tmp_path / f'{phase}-events.jsonl'
    launcher = FakeServerLauncher(modes=(mode, 'valid'), events_path=events)
    backend = backend_class()(make_config(tmp_path, inference_timeout_s=4.0),
        process_factory=launcher)
    outcomes = []
    worker = threading.Thread(target=lambda: outcomes.append(backend.infer(make_request())))
    worker.start()
    wait_for_event(events, signal_event)
    first_process = launcher.processes[0]
    cancel_started = time.monotonic()

    backend.cancel()

    assert time.monotonic() - cancel_started < 1.5
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert len(outcomes) == 1
    assert outcomes[0].status == 'unavailable'
    assert outcomes[0].reason == 'inference_cancelled'
    assert first_process.poll() is not None
    assert backend.infer(make_request('O(1)')).status == 'proposed'
    assert len(launcher.processes) == 2


def test_close_during_startup_reaps_server_and_prevents_later_relaunch(tmp_path):
    events = tmp_path / 'startup-events.jsonl'
    launcher = FakeServerLauncher(modes=('delay_start', 'valid'), events_path=events)
    backend = backend_class()(make_config(tmp_path, inference_timeout_s=4.0),
        process_factory=launcher)
    outcomes = []
    worker = threading.Thread(target=lambda: outcomes.append(backend.infer(make_request())))
    worker.start()
    wait_for_event(events, 'startup_wait')
    first_process = launcher.processes[0]

    closed = backend.close(timeout_s=1.0)
    worker.join(timeout=2.0)
    after_close = backend.infer(make_request('O(1)'))

    assert closed['clean_shutdown'] is True
    assert first_process.poll() is not None
    assert not worker.is_alive()
    assert outcomes[0].status == 'unavailable'
    assert after_close.status == 'unavailable'
    assert after_close.reason == 'room_label_backend_closed'
    assert len(launcher.processes) == 1
    assert backend.close(timeout_s=0.1)['clean_shutdown'] is True


def test_close_during_process_factory_cannot_leave_a_late_server_running(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    launcher = FakeServerLauncher(modes=('delay_start',))

    def delayed_factory(command, **kwargs):
        entered.set()
        release.wait(timeout=2.0)
        return launcher(command, **kwargs)

    backend = backend_class()(make_config(tmp_path, inference_timeout_s=4.0),
        process_factory=delayed_factory)
    outcomes = []
    worker = threading.Thread(target=lambda: outcomes.append(backend.infer(make_request())))
    worker.start()
    assert entered.wait(timeout=1.0)

    first_close = backend.close(timeout_s=0.05)
    release.set()
    worker.join(timeout=2.0)
    second_close = backend.close(timeout_s=1.0)

    assert first_close['clean_shutdown'] is False
    assert second_close['clean_shutdown'] is True
    assert not worker.is_alive()
    assert outcomes[0].status == 'unavailable'
    assert launcher.processes[0].poll() is not None


def test_asset_stat_mutation_kills_loaded_server_and_fails_closed(tmp_path):
    launcher = FakeServerLauncher()
    config = make_config(tmp_path)
    backend = backend_class()(config, process_factory=launcher)
    assert backend.infer(make_request()).status == 'proposed'
    running = launcher.processes[0]
    Path(config.model_path).write_bytes(b'mutated model payload')

    changed = backend.infer(make_request('O(1)'))
    repeated = backend.infer(make_request('O(0)'))

    assert changed.status == 'unavailable'
    assert changed.reason == 'model_asset_changed'
    assert running.poll() is not None
    assert repeated.status == 'unavailable'
    assert repeated.reason == 'model_hash_mismatch'
    assert len(launcher.processes) == 1


def test_first_startup_is_inside_the_single_job_deadline(tmp_path):
    events = tmp_path / 'slow-start-events.jsonl'
    launcher = FakeServerLauncher(modes=('delay_start',), events_path=events)
    backend = backend_class()(make_config(tmp_path, startup_timeout_s=1.0,
        inference_timeout_s=0.2), process_factory=launcher)
    started = time.monotonic()

    result = backend.infer(make_request())

    elapsed = time.monotonic() - started
    assert result.status == 'timeout'
    assert result.reason == 'room_label_job_deadline'
    assert elapsed < 0.8
    assert launcher.processes[0].poll() is not None
