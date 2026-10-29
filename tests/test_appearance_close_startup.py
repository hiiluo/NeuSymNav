"""Lifecycle tests for cancelling an appearance worker that is still starting."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from test_appearance_contract import source_and_batch

from neusymnav.perception import AppearanceShutdownPending
from neusymnav.perception import appearance_client as client


def _encoder(tmp_path: Path) -> client.AppearanceWorkerEncoder:
    checkpoint = tmp_path / "fixture.safetensors"
    checkpoint.write_bytes(b"close/start race fixture; not model weights")
    worker = Path(__file__).parent / "fixtures" / "appearance" / "worker_stub.py"
    return client.AppearanceWorkerEncoder(
        worker_python=Path(sys.executable).resolve(),
        checkpoint_path=checkpoint.resolve(),
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        model_name=client.SUPPORTED_MODEL_NAME,
        preprocessing_id=client.SUPPORTED_PREPROCESSING_ID,
        timeout_s=0.1,
        startup_timeout_s=3.0,
        _worker_command=(str(Path(sys.executable).resolve()), str(worker), "--mode", "startup_stall"),
    )


def test_close_cancels_process_published_after_spawn_return_gap(tmp_path, monkeypatch):
    encoder = _encoder(tmp_path)
    spawned = threading.Event()
    allow_popen_return = threading.Event()
    close_entered = threading.Event()
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen] = []
    encode_errors: list[BaseException] = []

    def delayed_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        spawned.set()
        if not allow_popen_return.wait(timeout=2.0):
            raise TimeoutError("test did not release delayed Popen")
        return process

    monkeypatch.setattr(client.subprocess, "Popen", delayed_popen)

    def encode():
        try:
            encoder.encode(*source_and_batch(count=1))
        except BaseException as error:
            encode_errors.append(error)

    encode_thread = threading.Thread(target=encode, name="appearance-encode-race", daemon=True)
    encode_thread.start()
    assert spawned.wait(timeout=1.0), "worker was not spawned"

    original_close = encoder.close

    def observed_close():
        close_entered.set()
        original_close()

    monkeypatch.setattr(encoder, "close", observed_close)
    close_thread = threading.Thread(target=encoder.close, name="appearance-close-race", daemon=True)
    close_started = time.monotonic()
    close_thread.start()
    try:
        assert close_entered.wait(timeout=1.0), "close did not start"
        # The event is set before close snapshots the process and waits on the
        # encode lock. Popen still withholds the already-running child handle.
        assert encoder._close_requested.wait(timeout=1.0), "close did not request cancellation"
        allow_popen_return.set()
        close_thread.join(timeout=1.5)
        assert not close_thread.is_alive(), "close exceeded its bounded wait"
        assert processes[0].poll() is not None, "close returned while the startup worker remained alive"
        encode_thread.join(timeout=0.5)
        assert not encode_thread.is_alive(), "close returned while encode was still starting"
        assert len(encode_errors) == 1
        assert isinstance(encode_errors[0], client.AppearanceUnavailable)
        assert "closed" in encode_errors[0].reason.lower()
        assert not encoder.is_alive
        assert encoder._process is None
        assert encoder._stderr_done.is_set()
        assert time.monotonic() - close_started < 1.5

        # Closing is terminal for this encoder and cannot launch a replacement.
        with pytest.raises(client.AppearanceUnavailable, match="closed"):
            encoder.encode(*source_and_batch(count=1))
        with pytest.raises(client.AppearanceUnavailable, match="closed"):
            encoder.encode(*source_and_batch(count=0))
        assert len(processes) == 1
    finally:
        allow_popen_return.set()
        for process in processes:
            if process.poll() is None:
                client._terminate_process_group(process)
        close_thread.join(timeout=1.0)
        encode_thread.join(timeout=1.0)
        encoder.close()


def test_close_reports_pending_if_process_creation_has_not_returned(tmp_path, monkeypatch):
    encoder = _encoder(tmp_path)
    spawned = threading.Event()
    allow_popen_return = threading.Event()
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen] = []
    encode_errors: list[BaseException] = []

    def delayed_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        spawned.set()
        if not allow_popen_return.wait(timeout=3.0):
            raise TimeoutError("test did not release delayed Popen")
        return process

    monkeypatch.setattr(client.subprocess, "Popen", delayed_popen)

    def encode():
        try:
            encoder.encode(*source_and_batch(count=1))
        except BaseException as error:
            encode_errors.append(error)

    encode_thread = threading.Thread(target=encode, name="appearance-encode-pending", daemon=True)
    encode_thread.start()
    assert spawned.wait(timeout=1.0), "worker was not spawned"
    try:
        start = time.monotonic()
        with pytest.raises(AppearanceShutdownPending, match="cleanup is pending"):
            encoder.close()
        assert time.monotonic() - start < 1.5
        assert encoder._close_requested.is_set()

        # Popen can return only when the OS launch call returns. Its handle is
        # then published, observed as cancelled, and synchronously reaped.
        allow_popen_return.set()
        encode_thread.join(timeout=1.0)
        assert not encode_thread.is_alive()
        assert processes[0].poll() is not None
        assert len(encode_errors) == 1
        assert isinstance(encode_errors[0], client.AppearanceUnavailable)
        assert "closed" in encode_errors[0].reason.lower()
        assert not encoder.is_alive
        assert encoder._process is None
    finally:
        allow_popen_return.set()
        for process in processes:
            if process.poll() is None:
                client._terminate_process_group(process)
        encode_thread.join(timeout=1.0)

