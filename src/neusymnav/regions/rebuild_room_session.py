"""Bounded host session and process boundary for one Rebuild M1--M5 episode."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
import base64
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
from typing import Any
import uuid

import numpy as np

from ..contracts import (
    FrameKey, Observation, Region, RegionSnapshot, RoomMapSnapshot,
    RoomPipelinePublication,
)
from .rebuild_rgbd_input import (
    RebuildRGBDConfig, RebuildRGBDInputAdapter,
)
from .rebuild_room_worker import (
    EXPECTED_M23_SHA256, EXPECTED_M4_SHA256, EXPECTED_SOURCE_TREE_SHA256,
    M3_STATE_CONVERSION,
    MAX_CELLS, MAX_LINE_BYTES,
)
from .geometry import valid_ring
from .rebuild_room_worker import _decode_array as _decode_input_array


MAX_QUEUE_BYTES = 32 * 1024 * 1024
MAX_PENDING = 2
MAX_RECORDS = 8192
MAX_JOURNAL_EVENTS = 4 * MAX_RECORDS + 2048
MAX_REPLAY_BYTES = 2 * 1024 * 1024 * 1024
MAX_PROCESS_TREE_RSS_BYTES = 10 * 1024 * 1024 * 1024


class _RecordingLimitError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _descendant_groups(root_pid: int) -> set[int]:
    """Find process groups belonging to this worker's descendants on Linux."""
    parents: dict[int, tuple[int, int]] = {}
    proc = Path("/proc")
    try:
        entries = tuple(proc.iterdir())
    except OSError:
        return set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "stat").read_text()
            right = content.rfind(")")
            fields = content[right + 2:].split()
            parents[int(entry.name)] = (int(fields[1]), int(fields[2]))
        except (OSError, ValueError, IndexError):
            continue
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _pgid) in parents.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return {parents[pid][1] for pid in descendants if pid in parents}


def _descendant_pids(root_pid: int) -> set[int]:
    parents: dict[int, int] = {}
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError:
        return {root_pid}
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "stat").read_text()
            right = content.rfind(")")
            fields = content[right + 2:].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return descendants


def _process_tree_rss_bytes(root_pid: int) -> int | None:
    pages = 0
    found = False
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None
    for pid in _descendant_pids(root_pid):
        try:
            statm = (Path("/proc") / str(pid) / "statm").read_text().split()
            if len(statm) < 2:
                continue
            pages += int(statm[1])
            found = True
        except (OSError, ValueError):
            continue
    return pages * page_size if found else None


class _WorkerProcess:
    def __init__(self, config: dict[str, Any], *, timeout_s: float,
                 python: str | Path | None = None,
                 command: tuple[str, ...] | None = None):
        if not 0.1 <= timeout_s <= 120.0:
            raise ValueError("worker timeout must be between 0.1 and 120 seconds")
        self.timeout_s = float(timeout_s)
        if command is None:
            interpreter = str(python or sys.executable)
            module_root = str(Path(__file__).resolve().parents[2])
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPATH"] = module_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            command = (
                interpreter, "-c",
                "from neusymnav.regions.rebuild_room_worker import main; raise SystemExit(main())",
                "--config-json",
                json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False),
            )
        else:
            env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        expected_config_sha256 = hashlib.sha256(json.dumps(
            {**config, "m3_state_conversion": M3_STATE_CONVERSION},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()
        env["NEUSYMNAV_EXPECTED_ROOM_CONFIG_SHA256"] = expected_config_sha256
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, start_new_session=True, env=env,
        )
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            self._terminate_tree()
            raise RuntimeError("worker pipes were not created")
        for stream in (self.process.stdin, self.process.stdout):
            os.set_blocking(stream.fileno(), False)
        self._stdout_buffer = bytearray()
        self._stderr_tail: deque[str] = deque(maxlen=64)
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        try:
            hello = self._read_message(self.timeout_s)
            if hello.get("status") != "ready":
                raise RuntimeError(hello.get("error", "worker failed during startup"))
            for key, expected in (
                ("source_sha256", config.get("expected_source_sha256", EXPECTED_SOURCE_TREE_SHA256)),
                ("m23_sha256", config.get("expected_m23_sha256", EXPECTED_M23_SHA256)),
                ("m4_sha256", config.get("expected_m4_sha256", EXPECTED_M4_SHA256)),
                ("config_sha256", expected_config_sha256),
            ):
                if hello.get(key) != expected:
                    raise RuntimeError(f"worker startup pin mismatch: {key}")
            self.startup = hello
        except BaseException:
            self._terminate_tree()
            raise

    def _drain_stderr(self):
        stream = self.process.stderr
        if stream is None:
            return
        for line in stream:
            self._stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr_tail)

    def _read_message(self, timeout_s: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        deadline = time.monotonic() + timeout_s
        while True:
            newline = self._stdout_buffer.find(b"\n")
            if newline >= 0:
                if newline > MAX_LINE_BYTES:
                    raise RuntimeError("worker response exceeds 32 MiB")
                line = bytes(self._stdout_buffer[:newline])
                del self._stdout_buffer[:newline + 1]
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise RuntimeError("worker returned a non-object message")
                return value
            if len(self._stdout_buffer) > MAX_LINE_BYTES:
                raise RuntimeError("worker response exceeds 32 MiB")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("worker response deadline exceeded")
            readable, _, _ = select.select([self.process.stdout], [], [], remaining)
            if not readable:
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                code = self.process.poll()
                raise RuntimeError(f"worker stdout closed (exit={code}; stderr={self.stderr_tail[-4:]})")
            self._stdout_buffer.extend(chunk)

    def _exchange(self, payload: bytes, timeout_s: float) -> dict[str, Any]:
        if len(payload) > MAX_LINE_BYTES:
            raise ValueError("IPC request exceeds 32 MiB")
        stream_in = self.process.stdin
        if stream_in is None:
            raise RuntimeError("worker stdin is closed")
        deadline = time.monotonic() + timeout_s
        offset = 0
        while offset < len(payload):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("worker request write deadline exceeded")
            _, writable, _ = select.select([], [stream_in], [], remaining)
            if not writable:
                continue
            try:
                offset += os.write(stream_in.fileno(), payload[offset:])
            except BrokenPipeError as exc:
                raise RuntimeError(f"worker stdin closed (stderr={self.stderr_tail[-4:]})") from exc
        return self._read_message(max(0.001, deadline - time.monotonic()))

    def request(self, value: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        return self._exchange(payload, self.timeout_s)

    def request_frame(self, frame_json: bytes) -> dict[str, Any]:
        # frame_json is already canonical JSON; wrap it without materializing
        # a second Python object tree containing another copy of each image.
        payload = b'{"frame":' + frame_json + b',"op":"update"}\n'
        return self._exchange(payload, self.timeout_s)

    def _terminate_tree(self):
        proc = getattr(self, "process", None)
        if proc is None:
            return
        groups = _descendant_groups(proc.pid)
        for group in groups:
            if group != os.getpgrp():
                try:
                    os.killpg(group, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        try:
            if proc.poll() is None:
                proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            for group in groups:
                if group != os.getpgrp():
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if proc.poll() is None:
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=0.5)

    def close(self):
        if self.process.poll() is not None:
            self._terminate_tree()
            return {"clean_shutdown": False, "exit_code": self.process.returncode}
        try:
            result = self.request({"op": "close"})
            clean = result.get("status") == "closed" and result.get("clean_shutdown") is True
        except BaseException:
            clean = False
        try:
            self.process.wait(timeout=min(2.0, self.timeout_s))
        except subprocess.TimeoutExpired:
            self._terminate_tree()
            clean = False
        return {"clean_shutdown": clean, "exit_code": self.process.returncode,
                "stderr_tail": self.stderr_tail}


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    admission_id: str
    reason: str
    payload_bytes: int


def _decode_response_array(value: Any, name: str) -> np.ndarray:
    if not isinstance(value, dict) or set(value) != {"dtype", "shape", "sha256", "data"}:
        raise ValueError(f"worker response {name} envelope invalid")
    dtype = np.dtype(value["dtype"])
    allowed = {"|i1", "<f8", "|b1"}
    if dtype.str not in allowed:
        raise ValueError(f"worker response {name} dtype invalid")
    shape = value["shape"]
    if not isinstance(shape, list) or not shape or any(type(n) is not int or n <= 0 for n in shape):
        raise ValueError(f"worker response {name} shape invalid")
    count = int(np.prod(shape, dtype=np.int64))
    if count > MAX_CELLS:
        raise ValueError(f"worker response {name} exceeds cell cap")
    raw = base64.b64decode(value["data"], validate=True)
    if len(raw) != count * dtype.itemsize or hashlib.sha256(raw).hexdigest() != value["sha256"]:
        raise ValueError(f"worker response {name} checksum/length mismatch")
    return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()


class RebuildRoomSession:
    """One asynchronous admission lane and one pinned Rebuild episode worker."""

    def __init__(self, *, source_root: str | Path, m23_binary: str | Path,
                 m4_binary: str | Path, episode_id: str, floor_id: str,
                 config: RebuildRGBDConfig = RebuildRGBDConfig(),
                 m23_timeout_s: float = 15.0, m4_timeout_s: float = 30.0,
                 ipc_timeout_s: float = 60.0, max_cells: int = MAX_CELLS,
                 max_pending: int = MAX_PENDING, max_queue_bytes: int = MAX_QUEUE_BYTES,
                 run_dir: str | Path | None = None,
                 worker_command: tuple[str, ...] | None = None):
        if not episode_id or not floor_id:
            raise ValueError("episode_id and floor_id are required")
        if max_cells != MAX_CELLS:
            raise ValueError("M3 cell cap is pinned at 1,000,000")
        if max_pending != MAX_PENDING or max_queue_bytes != MAX_QUEUE_BYTES:
            raise ValueError("queue caps are pinned at 2 pending / 32 MiB")
        self.episode_id = episode_id
        self.floor_id = floor_id
        self.config = config
        if run_dir is None:
            run_dir = (Path(__file__).resolve().parents[3] / "runs" / "rebuild-room" /
                       f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:12]}")
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.frames_dir = self.run_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=False)
        self._recorded_bytes = 0
        self._admitted_frames = 0
        self._recorded_frames: list[dict[str, Any]] = []
        self._processed_frames = 0
        self._close_result: dict[str, Any] | None = None
        self._incomplete_reason: str | None = None
        self._journal_stream = (self.run_dir / "admission-journal.jsonl").open("ab", buffering=0)
        self.m23_path = Path(m23_binary).expanduser().resolve(strict=True)
        self.m4_path = Path(m4_binary).expanduser().resolve(strict=True)
        source = Path(source_root).expanduser().resolve(strict=True)
        self.worker_config = {
            "source_root": str(source), "m23_binary": str(self.m23_path),
            "m4_binary": str(self.m4_path), "episode_id": episode_id,
            "floor_id": floor_id, "resolution_m": config.resolution_m,
            "backprojection_stride": config.backprojection_stride,
            "min_depth_m": config.min_depth_m, "max_depth_m": config.max_depth_m,
            "max_range_m": config.max_range_m,
            "decomp_threshold_m": 1.5, "safety_distance_m": 0.5,
            "m23_timeout_s": float(m23_timeout_s), "m4_timeout_s": float(m4_timeout_s),
            "expected_source_sha256": EXPECTED_SOURCE_TREE_SHA256,
            "expected_m23_sha256": EXPECTED_M23_SHA256,
            "expected_m4_sha256": EXPECTED_M4_SHA256,
        }
        self.ipc_timeout_s = float(ipc_timeout_s)
        self.adapter = RebuildRGBDInputAdapter(config)
        self._condition = threading.Condition()
        self._queue: deque[tuple[bytes, str, int, int, dict[str, Any]]] = deque()
        self._inflight_bytes = 0
        self._queued_bytes = 0
        self._journal: deque[dict[str, Any]] = deque(maxlen=MAX_JOURNAL_EVENTS)
        self._journal_count = 0
        self._publication: RoomPipelinePublication | None = None
        self._failure: str | None = None
        self._replay_required = False
        self._closed = False
        self._shutdown_complete = False
        self._worker = _WorkerProcess(self.worker_config, timeout_s=ipc_timeout_s,
                                      command=worker_command)
        self._write_json_atomic(self.run_dir / "run-profile.json", {
            "schema_version": 1, "episode_id": self.episode_id, "floor_id": self.floor_id,
            "source_root": str(source), "m23_binary": str(self.m23_path),
            "m4_binary": str(self.m4_path), "m23_binary_sha256": _sha256(self.m23_path),
            "m4_binary_sha256": _sha256(self.m4_path),
            "source_python_sha256": EXPECTED_SOURCE_TREE_SHA256,
            "mapping": {
                "resolution_m": config.resolution_m,
                "backprojection_stride": config.backprojection_stride,
                "min_depth_m": config.min_depth_m, "max_depth_m": config.max_depth_m,
                "max_range_m": config.max_range_m,
            },
            "m3_state_conversion": M3_STATE_CONVERSION,
            "m4_m5": {"decomp_threshold_m": 1.5, "safety_distance_m": 0.5,
                      "preprocessing_policy": "source"},
            "limits": {"pending_frames": MAX_PENDING, "queue_bytes": MAX_QUEUE_BYTES,
                       "m3_cells": MAX_CELLS, "recording_bytes": MAX_REPLAY_BYTES,
                       "process_tree_rss_bytes": MAX_PROCESS_TREE_RSS_BYTES},
            "worker_startup": self._worker.startup,
        })
        self._thread = threading.Thread(target=self._run, name="rebuild-room-session", daemon=True)
        self._rss_stop = threading.Event()
        self._rss_samples = 0
        self._rss_peak_bytes = 0
        self._rss_last_bytes: int | None = None
        self._rss_thread = threading.Thread(target=self._monitor_rss,
                                            name="rebuild-room-rss", daemon=True)
        self._thread.start()
        self._rss_thread.start()

    @property
    def journal(self) -> tuple[dict[str, Any], ...]:
        with self._condition:
            return tuple(dict(item) for item in self._journal)

    @property
    def health(self) -> dict[str, Any]:
        with self._condition:
            return {
                "episode_id": self.episode_id, "closed": self._closed,
                "failed": self._failure is not None, "replay_required": self._replay_required,
                "failure_reason": self._failure, "queued_frames": len(self._queue),
                "inflight_bytes": self._inflight_bytes, "queued_bytes": self._queued_bytes,
                "queue_bytes": self._inflight_bytes + self._queued_bytes,
                "worker_pid": self._worker.process.pid,
                "child_process_groups": self.child_process_groups(),
                "process_tree_rss_bytes": self._rss_last_bytes,
                "process_tree_rss_peak_bytes": self._rss_peak_bytes,
                "process_tree_rss_samples": self._rss_samples,
                "process_tree_rss_cap_bytes": MAX_PROCESS_TREE_RSS_BYTES,
            }

    def child_process_groups(self) -> tuple[int, ...]:
        return tuple(sorted(pid for pid in _descendant_groups(self._worker.process.pid)
                            if pid != self._worker.process.pid))

    def snapshot(self) -> RoomPipelinePublication | None:
        with self._condition:
            return self._publication

    def submit(self, observation) -> AdmissionResult:
        with self._condition:
            admission_id = hashlib.sha256(
                f"{self.episode_id}:{getattr(getattr(observation, 'key', None), 'frame_index', -1)}".encode()
            ).hexdigest()[:24]
            if self._failure is not None:
                reason = "replay_required" if self._replay_required else "session_incomplete"
                return self._record_rejection(admission_id, reason, 0)
            if self._closed:
                return self._record_rejection(admission_id, "session_closed", 0)
            if len(self._queue) >= MAX_PENDING:
                return self._record_rejection(admission_id, "pending_queue_full", 0)
            if self._admitted_frames >= MAX_RECORDS:
                self._incomplete_reason = "admitted frame record cap 8192 reached"
                self._failure = self._incomplete_reason
                self._closed = True
                self._condition.notify_all()
                return self._record_rejection(admission_id, "admission_record_cap_reached", 0)
            depth_input = getattr(observation, "depth_m", None)
            if isinstance(depth_input, np.ndarray) and depth_input.size > MAX_CELLS:
                return self._record_rejection(admission_id, "input_pixel_cap_exceeded", depth_input.nbytes)
            raw_nbytes = 0
            for name in ("rgb", "depth_m", "valid_depth", "K", "T_world_camera"):
                value = getattr(observation, name, None)
                if isinstance(value, np.ndarray):
                    raw_nbytes += value.nbytes
            projected_size = raw_nbytes * 4 // 3 + 8192
            projected_budget = projected_size * 2 + raw_nbytes
            if projected_budget > MAX_QUEUE_BYTES:
                return self._record_rejection(admission_id, "frame_payload_exceeds_32MiB", projected_budget)
            if self._inflight_bytes + self._queued_bytes + projected_budget > MAX_QUEUE_BYTES:
                return self._record_rejection(admission_id, "byte_queue_full", projected_budget)
            prior_adapter = deepcopy(self.adapter)
            try:
                frame = self.adapter.adapt(observation)
                payload = frame.wire_bytes()
            except BaseException as exc:
                self.adapter = prior_adapter
                return self._record_rejection(admission_id, f"input_rejected:{type(exc).__name__}", 0)
            size = len(payload)
            budget = 2 * size + raw_nbytes
            if size > MAX_LINE_BYTES or self._inflight_bytes + self._queued_bytes + budget > MAX_QUEUE_BYTES:
                self.adapter = prior_adapter
                return self._record_rejection(admission_id, "serialized_payload_exceeds_queue_cap", size)
            metadata = {
                "frame_id": frame.frame_id, "frame_index": frame.frame_index,
                "prefix_sha256": frame.prefix_sha256,
                "source": {
                    "scene_id": frame.scene_id, "sequence_id": frame.sequence_id,
                    "sensor_id": frame.sensor_id, "frame_id": frame.frame_id,
                    "frame_index": frame.frame_index, "timestamp_s": frame.timestamp_s,
                    "capture_monotonic_ns": frame.capture_monotonic_ns,
                    "clock_domain": frame.clock_domain,
                    "calibration_id": frame.calibration_id,
                    "pose_version": frame.pose_version,
                    "geometry_sha256": frame.geometry_sha256,
                    "prefix_sha256": frame.prefix_sha256,
                    "pose_source": frame.config.pose_source,
                    "coordinate_convention": "canonical_z_up_optical_v1",
                    "depth_units": "m", "depth_representation": "axial",
                    "source_masks_present": {
                        "no_return": frame.no_return_mask is not None,
                        "far_plane": frame.far_plane_mask is not None,
                    },
                    "no_return_range_m": frame.no_return_range_m,
                    "far_plane_range_m": frame.far_plane_range_m,
                },
            }
            self._queue.append((payload, admission_id, size, budget, metadata))
            self._queued_bytes += budget
            self._admitted_frames += 1
            self._append_journal({
                "admission_id": admission_id, "accepted": True,
                "reason": "admitted", "frame_index": frame.frame_index,
                "frame_id": frame.frame_id, "prefix_sha256": frame.prefix_sha256,
                "payload_bytes": size,
            })
            self._condition.notify_all()
            return AdmissionResult(True, admission_id, "admitted", size)

    def _record_rejection(self, admission_id: str, reason: str, payload_bytes: int):
        self._append_journal({"admission_id": admission_id, "accepted": False,
                              "reason": reason, "payload_bytes": payload_bytes})
        return AdmissionResult(False, admission_id, reason, payload_bytes)

    def _monitor_rss(self):
        while not self._rss_stop.wait(0.05):
            value = _process_tree_rss_bytes(self._worker.process.pid)
            if value is None:
                continue
            with self._condition:
                self._rss_last_bytes = value
                self._rss_peak_bytes = max(self._rss_peak_bytes, value)
                self._rss_samples += 1
                if value <= MAX_PROCESS_TREE_RSS_BYTES or self._failure is not None:
                    continue
                self._failure = f"process-tree sampled RSS cap exceeded: {value} > {MAX_PROCESS_TREE_RSS_BYTES}"
                self._incomplete_reason = self._failure
                self._replay_required = True
                self._closed = True
                self._queue.clear()
                self._queued_bytes = 0
                self._append_journal({"accepted": False, "reason": "process_tree_rss_cap_exceeded",
                                      "rss_bytes": value, "cap_bytes": MAX_PROCESS_TREE_RSS_BYTES})
                self._mark_previous_stale()
                self._condition.notify_all()
            self._worker._terminate_tree()
            return

    def _append_journal(self, value: dict[str, Any]):
        with self._condition:
            if self._journal_count >= MAX_JOURNAL_EVENTS:
                return
            self._journal.append(dict(value))
            self._journal_count += 1
            if not self._journal_stream.closed:
                line = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                self._journal_stream.write(line + b"\n")

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]):
        temporary = path.with_name(path.name + ".tmp")
        raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _persist_frame(self, payload: bytes, admission_id: str, metadata: dict[str, Any]):
        if self._recorded_bytes + len(payload) > MAX_REPLAY_BYTES:
            raise _RecordingLimitError("admitted replay input would exceed the 2 GiB run cap")
        filename = f"{int(metadata['frame_index']):010d}-{admission_id}.json"
        path = self.frames_dir / filename
        temporary = path.with_name(path.name + ".tmp")
        digest = hashlib.sha256(payload).hexdigest()
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        self._recorded_bytes += len(payload)
        entry = {
            "admission_id": admission_id, "frame_index": int(metadata["frame_index"]),
            "frame_id": metadata["frame_id"], "prefix_sha256": metadata["prefix_sha256"],
            "payload_path": str(path.relative_to(self.run_dir)),
            "payload_sha256": digest, "payload_bytes": len(payload),
        }
        self._recorded_frames.append(entry)
        self._append_journal({"admission_id": admission_id, "accepted": True,
                              "reason": "input_durable", **entry})

    def _run(self):
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if self._closed and not self._queue:
                    return
                payload, admission_id, size, budget, metadata = self._queue.popleft()
                self._queued_bytes -= budget
                self._inflight_bytes = budget
            try:
                try:
                    self._persist_frame(payload, admission_id, metadata)
                except (OSError, _RecordingLimitError) as exc:
                    with self._condition:
                        self._incomplete_reason = str(exc)
                        self._failure = str(exc)
                        self._closed = True
                        self._queue.clear()
                        self._queued_bytes = 0
                        self._mark_previous_stale()
                        self._condition.notify_all()
                    return
                response = self._worker.request_frame(payload)
                if response.get("status") != "ok":
                    fatal = bool(response.get("replay_required", False))
                    if not fatal:
                        with self._condition:
                            self._append_journal({
                                "admission_id": admission_id, "accepted": False,
                                "reason": f"worker_rejected_before_mutation:{response.get('error', 'unknown')}",
                                "payload_bytes": size,
                            })
                        continue
                    raise RuntimeError(f"room worker response: {response.get('error', response.get('status'))}; fatal={fatal}")
                self._validate_worker_response(response, metadata)
                publication = self._publication_from_response(response, admission_id)
                with self._condition:
                    self._publication = publication
                    self._processed_frames += 1
                    self._append_journal({
                        "admission_id": admission_id, "accepted": True,
                        "reason": "processed", "request_revision": response["request_revision"],
                        "m3_projection_mode": response.get("record", {}).get("m3_mode"),
                        "timings_ms": dict(response.get("timings_ms", {})),
                        "mapping_work": {
                            key: value for key, value in response.get("record", {}).items()
                            if key in {
                                "input_pixel_count", "finite_depth_pixel_count",
                                "valid_mask_pixel_count", "backprojected_hit_count",
                                "point_count", "m1_runtime_ms", "m2_runtime_ms",
                                "m3_runtime_ms", "m1_m2_m3_runtime_ms",
                            }
                        },
                        "m3_revision": publication.latest_map.revision,
                        "accepted_map_revision": publication.accepted_map_revision,
                        "regions_stale": publication.regions_stale,
                    })
            except BaseException as exc:
                with self._condition:
                    self._failure = f"{type(exc).__name__}: {exc}"
                    self._replay_required = True
                    self._closed = True
                    self._queue.clear()
                    self._queued_bytes = 0
                    self._mark_previous_stale()
                    self._condition.notify_all()
                self._worker._terminate_tree()
                return
            finally:
                with self._condition:
                    self._inflight_bytes = 0
                    self._condition.notify_all()

    def _validate_worker_response(self, response: dict[str, Any], metadata: dict[str, Any]):
        latest = response.get("latest_map")
        if not isinstance(latest, dict):
            raise ValueError("worker response is missing latest M3 map")
        if latest.get("source") != metadata["source"]:
            raise ValueError("worker response source frame/prefix binding mismatch")
        request_revision = response.get("request_revision")
        if type(request_revision) is not int or request_revision != self._processed_frames + 1:
            raise ValueError("worker response request revision is not the next admitted update")
        if latest.get("revision") != request_revision:
            raise ValueError("worker response map revision does not match its request")
        for name, expected in (
            ("source_hash", EXPECTED_SOURCE_TREE_SHA256),
            ("worker_sha256", EXPECTED_M23_SHA256),
            ("m4_worker_sha256", EXPECTED_M4_SHA256),
            ("config_sha256", self._worker.startup["config_sha256"]),
        ):
            if latest.get(name) != expected:
                raise ValueError(f"worker response pin mismatch: {name}")

    def _publication_from_response(self, response: dict[str, Any], admission_id: str):
        latest = response["latest_map"]
        source = latest["source"]
        arrays = {
            name: _decode_response_array(latest[name], name)
            for name in ("states", "z_floor_m", "z_ceiling_m", "floor_valid", "ceiling_valid")
        }
        if arrays["states"].ndim != 2 or arrays["states"].size > MAX_CELLS:
            raise ValueError("M3 map shape exceeds cap")
        room_map = RoomMapSnapshot(
            episode_id=self.episode_id,
            map_domain_id=f"rebuild-m3:{self.episode_id}:{latest['source_hash'][:12]}:{latest['config_sha256'][:12]}",
            revision=int(latest["revision"]),
            source=FrameKey(self.episode_id, source["sensor_id"], int(source["frame_index"])),
            capture_monotonic_ns=int(source["capture_monotonic_ns"]),
            clock_domain=source["clock_domain"], calibration_id=source["calibration_id"],
            prefix_sha256=source["prefix_sha256"],
            resolution_m=float(latest["resolution_m"]),
            origin_xy=tuple(float(v) for v in latest["origin_xy"]),
            states=arrays["states"], z_floor_m=arrays["z_floor_m"],
            z_ceiling_m=arrays["z_ceiling_m"], floor_valid=arrays["floor_valid"],
            ceiling_valid=arrays["ceiling_valid"], m2_revision=int(latest["m2_revision"]),
            m3_revision=int(latest["m3_revision"]), source_hash=latest["source_hash"],
            worker_sha256=latest["worker_sha256"], config_sha256=latest["config_sha256"],
            region_worker_sha256=latest["m4_worker_sha256"],
        )
        accepted_map_revision = response["accepted_map_revision"]
        raw_regions = response["regions"]
        regions = None
        m5_revision = response["m5_revision"]
        stale = bool(response["regions_stale"])
        accepted_revision_value = None if accepted_map_revision is None else int(accepted_map_revision)
        accepted_map = None
        if accepted_revision_value is not None:
            if accepted_revision_value == room_map.revision:
                accepted_map = room_map
            elif (self._publication is not None
                  and self._publication.accepted_map_revision == accepted_revision_value):
                accepted_map = self._publication.accepted_map
            if accepted_map is None:
                raise ValueError("worker accepted M3 revision has no retained map snapshot")
        if accepted_map_revision is not None:
            region_values = {}
            ids = {str(item["persistent_id"]) for item in raw_regions}
            for item in raw_regions:
                region_id = f"region:{self.floor_id}:{item['persistent_id']}"
                adjacency = tuple(sorted(
                    f"region:{self.floor_id}:{value}" for value in item["adjacency"]
                ))
                if not set(adjacency).issubset({f"region:{self.floor_id}:{i}" for i in ids}):
                    raise ValueError("M5 adjacency references a missing source region")
                polygon = np.asarray(item["polygon"], dtype=np.float64)
                if not valid_ring(tuple(map(tuple, polygon))):
                    raise ValueError("worker M5 polygon failed simple/nonzero validation")
                region_values[region_id] = Region(region_id, polygon, (), adjacency)
            regions = RegionSnapshot(
                self.episode_id, int(m5_revision), int(accepted_map_revision),
                self.floor_id, region_values, stale,
            )
        return RoomPipelinePublication(
            episode_id=self.episode_id, map_domain_id=room_map.map_domain_id,
            request_revision=int(response["request_revision"]), latest_map=room_map,
            accepted_map_revision=accepted_revision_value,
            regions=regions, m5_revision=None if m5_revision is None else int(m5_revision),
            regions_stale=stale, replay_required=False,
            failure_reason=response.get("m5_reason"), admission_id=admission_id,
            timings_ms=response.get("timings_ms", {}), accepted_map=accepted_map,
        )

    def _mark_previous_stale(self):
        previous = self._publication
        if previous is None:
            return
        stale_regions = None
        if previous.regions is not None:
            stale_regions = RegionSnapshot(
                previous.regions.episode_id, previous.regions.revision,
                previous.regions.source_map_revision, previous.regions.floor_id,
                dict(previous.regions.regions), True,
            )
        self._publication = RoomPipelinePublication(
            previous.episode_id, previous.map_domain_id, previous.request_revision,
            previous.latest_map, previous.accepted_map_revision, stale_regions,
            previous.m5_revision if stale_regions is not None else None,
            True, True, self._failure, previous.admission_id, previous.timings_ms,
            previous.accepted_map,
        )

    def wait_idle(self, timeout_s: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while self._queue or self._inflight_bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, timeout_s: float = 5.0) -> dict[str, Any]:
        with self._condition:
            if self._shutdown_complete:
                return dict(self._close_result or {})
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=max(0.0, timeout_s))
        clean = not self._thread.is_alive()
        if clean and self._worker.process.poll() is None:
            worker_result = self._worker.close()
            clean = bool(worker_result["clean_shutdown"]) and clean
        else:
            self._worker._terminate_tree()
        self._rss_stop.set()
        self._rss_thread.join(timeout=1.0)
        with self._condition:
            drained = not self._queue and self._inflight_bytes == 0
            recording_complete = self._admitted_frames == len(self._recorded_frames)
            runtime_complete = drained and self._failure is None and self._processed_frames == self._admitted_frames
            result = {
                "drained": not self._queue and self._inflight_bytes == 0,
                "pending": len(self._queue), "failed": self._failure is not None,
                "replay_required": self._replay_required,
                "clean_shutdown": clean and self._failure is None,
                "failure_reason": self._failure,
                "recording_complete": recording_complete,
                "runtime_complete": runtime_complete,
                "admitted_frames": self._admitted_frames,
                "recorded_frames": len(self._recorded_frames),
                "processed_frames": self._processed_frames,
                "recorded_bytes": self._recorded_bytes,
                "run_dir": str(self.run_dir),
                "process_tree_rss_samples": self._rss_samples,
                "process_tree_rss_peak_bytes": self._rss_peak_bytes,
                "process_tree_rss_last_bytes": self._rss_last_bytes,
                "process_tree_rss_cap_bytes": MAX_PROCESS_TREE_RSS_BYTES,
            }
            self._write_json_atomic(self.run_dir / "completeness.json", {
                "schema_version": 1, **result, "incomplete_reason": self._incomplete_reason,
                "frames": list(self._recorded_frames),
                "worker_stderr_tail": list(self._worker.stderr_tail),
            })
            if not self._journal_stream.closed:
                self._journal_stream.flush()
                os.fsync(self._journal_stream.fileno())
                self._journal_stream.close()
            self._shutdown_complete = True
            self._close_result = result
            return dict(result)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def replay_recording(run_dir: str | Path, session: RebuildRoomSession, *, max_frames: int | None = None) -> int:
    """Verify and replay every durably admitted RGB-D frame into a fresh session."""
    root = Path(run_dir).expanduser().resolve(strict=True)
    if session.snapshot() is not None or session.adapter._episode is not None:
        raise ValueError("replay requires a fresh room session")
    profile = json.loads((root / "run-profile.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "completeness.json").read_text(encoding="utf-8"))
    if profile.get("source_python_sha256") != EXPECTED_SOURCE_TREE_SHA256:
        raise ValueError("recorded Rebuild Python source pin differs")
    if profile.get("m23_binary_sha256") != EXPECTED_M23_SHA256 or profile.get("m4_binary_sha256") != EXPECTED_M4_SHA256:
        raise ValueError("recorded Rebuild native worker pins differ")
    if profile.get("episode_id") != session.episode_id or profile.get("floor_id") != session.floor_id:
        raise ValueError("replay episode/floor differs from the new session")
    if not manifest.get("recording_complete"):
        raise ValueError("recording is incomplete; missing admitted frame payloads")
    entries = manifest.get("frames")
    if not isinstance(entries, list) or len(entries) != manifest.get("admitted_frames"):
        raise ValueError("replay manifest frame count does not match admission count")
    if max_frames is not None:
        if type(max_frames) is not int or not 1 <= max_frames <= len(entries):
            raise ValueError("replay max_frames must select an existing positive prefix")
        entries = entries[:max_frames]
    processed = 0
    verifier = RebuildRGBDInputAdapter(session.config)
    for entry in entries:
        relative = Path(entry["payload_path"])
        payload_path = (root / relative).resolve(strict=True)
        if root not in payload_path.parents or payload_path.is_symlink():
            raise ValueError("replay payload path escapes the recording")
        raw = payload_path.read_bytes()
        if len(raw) != entry["payload_bytes"] or hashlib.sha256(raw).hexdigest() != entry["payload_sha256"]:
            raise ValueError("replay payload length or checksum mismatch")
        wire = json.loads(raw)
        if wire.get("wire_version") != 1 or not isinstance(wire.get("frame"), dict):
            raise ValueError("unsupported recorded RGB-D wire schema")
        frame = wire["frame"]
        arrays = wire.get("arrays", {})
        decoded = {name: _decode_input_array(arrays[name], name) for name in
                   ("rgb", "depth_m", "valid_depth", "K", "T_world_camera")}
        source_depth = _decode_input_array(arrays["source_depth_m"], "source_depth_m") if "source_depth_m" in arrays else decoded["depth_m"]
        source_valid = _decode_input_array(arrays["source_valid_depth"], "source_valid_depth") if "source_valid_depth" in arrays else decoded["valid_depth"]
        source_masks = frame.get("source_masks_present", {"no_return": False, "far_plane": False})
        if (not isinstance(source_masks, dict) or set(source_masks) != {"no_return", "far_plane"}
                or any(type(value) is not bool for value in source_masks.values())):
            raise ValueError("recorded optional source mask metadata is invalid")
        no_return = (_decode_input_array(arrays["no_return_mask"], "no_return_mask")
                     if source_masks["no_return"] and "no_return_mask" in arrays else None)
        far_plane = (_decode_input_array(arrays["far_plane_mask"], "far_plane_mask")
                     if source_masks["far_plane"] and "far_plane_mask" in arrays else None)
        if source_masks["no_return"] != (no_return is not None) or source_masks["far_plane"] != (far_plane is not None):
            raise ValueError("recorded optional source masks are incomplete")
        observation = Observation(
            key=FrameKey(session.episode_id, frame["sensor_id"], int(frame["frame_index"])),
            capture_monotonic_ns=int(frame["capture_monotonic_ns"]),
            clock_domain=frame["clock_domain"], sim_time_s=float(frame["timestamp_s"]),
            rgb=decoded["rgb"], depth_m=source_depth,
            valid_depth=source_valid, K=decoded["K"],
            T_world_camera=decoded["T_world_camera"],
            calibration_id=frame["calibration_id"], pose_version=int(frame["pose_version"]),
            modality="rgbd", no_return=no_return, far_plane=far_plane,
            no_return_range_m=frame.get("no_return_range_m"),
            far_plane_range_m=frame.get("far_plane_range_m"),
        )
        if observation.geometry_hash != frame["geometry_sha256"]:
            raise ValueError("reconstructed replay observation has a different geometry hash")
        adapted = verifier.adapt(observation)
        adapted_wire = adapted.to_wire()
        legacy_wire = json.loads(json.dumps(adapted_wire))
        for name in ("source_depth_m", "source_valid_depth", "no_return_mask", "far_plane_mask"):
            legacy_wire["arrays"].pop(name, None)
        for name in ("source_masks_present", "no_return_range_m", "far_plane_range_m"):
            legacy_wire["frame"].pop(name, None)
        canonical_legacy = json.dumps(legacy_wire, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if adapted.prefix_sha256 != frame["prefix_sha256"] or (adapted.wire_bytes() != raw and canonical_legacy != raw):
            raise ValueError("reconstructed replay frame/prefix differs from the recorded input")
        admission = session.submit(observation)
        if not admission.accepted:
            if admission.reason in {"pending_queue_full", "byte_queue_full"}:
                if not session.wait_idle(session.ipc_timeout_s):
                    raise TimeoutError("room replay worker did not drain bounded queue")
                admission = session.submit(observation)
            if not admission.accepted:
                raise RuntimeError(f"room replay admission failed: {admission.reason}")
        processed += 1
    if not session.wait_idle(session.ipc_timeout_s):
        raise TimeoutError("room replay did not finish within the worker deadline")
    return processed
