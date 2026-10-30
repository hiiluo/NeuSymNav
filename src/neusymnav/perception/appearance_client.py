"""Host-side adapter for the isolated appearance feature worker.

The host process validates P01 contracts and owns all feature attachment.
OpenCLIP, Torch, Pillow, and checkpoint loading stay in a separate interpreter
with an explicit local environment and bounded framed IPC.
"""
from __future__ import annotations

import base64
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np

from ..contracts.observations import (
    AppearanceBatch,
    AppearanceFeature,
    DetectionBatch,
    FrameKey,
    ObjectObservation,
    Observation,
    validate_appearance_batch,
    validate_detection_batch,
)


SUPPORTED_MODEL_NAME = "ViT-B-32"
SUPPORTED_PREPROCESSING_ID = "openclip-vit-b-32-openai-eval-224-maskbboxpad20-v1"
OPENAI_PREPROCESSING_ID = "openai-clip-vit-b-32-eval-224-maskbboxpad20-v1"
CROP_RECIPE_ID = "mask-tight-xyxy+20px-clipped+PIL-float-edge-rounding-v1"
FEATURE_DIMENSION = 512
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CLOSE_JOIN_TIMEOUT_S = 1.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_KEYS = ("python", "python_implementation", "open_clip_torch", "torch",
                 "torchvision", "Pillow", "numpy")
_OPENAI_RUNTIME_KEYS = ("python", "python_implementation", "openai_clip", "torch",
                        "torchvision", "Pillow", "numpy")


def _write_all(fd: int, payload: bytes, deadline: float) -> None:
    """Write a complete frame to a nonblocking fd before its absolute deadline."""
    os.set_blocking(fd, False)
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_WRITE)
    view = memoryview(payload)
    offset = 0
    try:
        while offset < len(view):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("IPC write exceeded its deadline")
            if not selector.select(remaining):
                raise TimeoutError("IPC write exceeded its deadline")
            try:
                count = os.write(fd, view[offset:])
            except BlockingIOError:
                continue
            except InterruptedError:
                continue
            if count <= 0:
                raise BrokenPipeError("worker closed IPC stdin")
            offset += count
    finally:
        selector.close()


def _signal_process_group(process: subprocess.Popen, sig: int) -> None:
    if process.poll() is not None and os.name != "posix":
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        pass


def _terminate_process_group(process: subprocess.Popen, grace_s: float = 0.2) -> None:
    """Boundedly stop the worker and any descendants in its isolated process group."""
    if process.poll() is None:
        _signal_process_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            pass
    # The worker may have exited while a descendant still holds one of its pipes.
    # The group remains isolated by start_new_session=True, so reap it as well.
    _signal_process_group(process, signal.SIGKILL)
    try:
        process.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        pass


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AppearanceUnavailable(RuntimeError):
    """An appearance request could not be completed by its worker."""

    def __init__(self, reason: str, source: FrameKey):
        self.reason = str(reason)
        self.source = source
        super().__init__(f"appearance unavailable for {source}: {self.reason}")


class AppearanceShutdownPending(RuntimeError):
    """Close was requested, but subprocess launch has not yet quiesced.

    The encoder is terminal after close is requested, but callers must not treat
    this exception as a completed shutdown. Retry ``close()`` after the
    synchronous OS subprocess-creation call returns. A blocked ``Popen`` call
    itself cannot be interrupted by this adapter.
    """


def attach_features(
    observations: tuple[ObjectObservation, ...],
    features: AppearanceBatch,
) -> tuple[ObjectObservation, ...]:
    """Attach only features matching the supplied projected source observations.

    The caller validates the original full DetectionBatch with
    ``validate_appearance_batch`` first, then filters its feature keys to the
    projected observation IDs before calling this helper. Missing feature keys
    leave the geometry-only observation unchanged.
    """
    if not isinstance(observations, tuple):
        raise TypeError("observations must be a tuple")
    if not isinstance(features, AppearanceBatch):
        raise TypeError("features must be an AppearanceBatch")
    if any(not isinstance(item, ObjectObservation) for item in observations):
        raise TypeError("observations must contain ObjectObservation values")

    projected_ids: set[str] = set()
    for item in observations:
        if item.source != features.source:
            raise ValueError("appearance source differs from projected observation source")
        if item.geometry_hash != features.geometry_hash:
            raise ValueError("appearance geometry_hash differs from projected observation")
        projected_ids.add(item.detection_id)
    extra_ids = set(features.features) - projected_ids
    if extra_ids:
        raise ValueError("appearance keys must be a subset of projected observation detection IDs")

    attached = []
    for item in observations:
        feature = features.features.get(item.detection_id)
        if feature is None:
            attached.append(item)
            continue
        if item.appearance is not None:
            item.appearance.require_compatible(feature)
        attached.append(replace(item, appearance=feature))
    return tuple(attached)


class AppearanceWorkerEncoder:
    """AppearanceEncoder implementation backed by a persistent local worker.

    ``worker_python`` and ``checkpoint_path`` must be absolute local paths.
    Only the pinned ViT-B-32 eval transform and mask-bounds crop recipe are
    accepted until another checkpoint/format/preprocessing profile is reviewed.
    The private ``_worker_command`` hook is used only by protocol failure tests.
    """

    def __init__(
        self,
        worker_python: str | Path,
        checkpoint_path: str | Path,
        *,
        checkpoint_sha256: str,
        model_name: str,
        preprocessing_id: str,
        checkpoint_format: str = "safetensors",
        timeout_s: float = 2.0,
        startup_timeout_s: float = 30.0,
        max_request_bytes: int = MAX_REQUEST_BYTES,
        _worker_command: Sequence[str] | None = None,
    ) -> None:
        python_path = Path(worker_python).expanduser()
        checkpoint = Path(checkpoint_path).expanduser()
        if not python_path.is_absolute() or not python_path.is_file() or not os.access(python_path, os.X_OK):
            raise ValueError("worker_python must be an absolute executable interpreter path")
        if checkpoint_format not in ("safetensors", "openai_jit"):
            raise ValueError("unsupported checkpoint_format; expected safetensors or openai_jit")
        suffix = ".pt" if checkpoint_format == "openai_jit" else ".safetensors"
        if not checkpoint.is_absolute() or not checkpoint.is_file() or checkpoint.suffix.lower() != suffix:
            raise ValueError(f"checkpoint_path must be an existing absolute {suffix} file")
        if not isinstance(checkpoint_sha256, str) or _SHA256.fullmatch(checkpoint_sha256) is None:
            raise ValueError("checkpoint_sha256 must be a lowercase SHA-256 digest")
        if model_name != SUPPORTED_MODEL_NAME:
            raise ValueError(f"model_name must be {SUPPORTED_MODEL_NAME!r} until another model is reviewed")
        expected_preprocessing = OPENAI_PREPROCESSING_ID if checkpoint_format == "openai_jit" else SUPPORTED_PREPROCESSING_ID
        if preprocessing_id != expected_preprocessing:
            raise ValueError("preprocessing_id does not name the supported pinned eval/crop recipe")
        for name, value in (("timeout_s", timeout_s), ("startup_timeout_s", startup_timeout_s)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if type(max_request_bytes) is not int or not 1024 <= max_request_bytes <= MAX_REQUEST_BYTES:
            raise ValueError(f"max_request_bytes must be between 1024 and {MAX_REQUEST_BYTES}")
        if _worker_command is not None:
            command = tuple(str(part) for part in _worker_command)
            if not command or any(not part for part in command):
                raise ValueError("_worker_command must be a nonempty argument sequence")
        else:
            worker_file = Path(__file__).with_name("appearance_worker.py").resolve(strict=True)
            command = (str(python_path.resolve(strict=True)), str(worker_file), "--worker")

        self.worker_python = python_path.resolve(strict=True)
        self.checkpoint_path = checkpoint.resolve(strict=True)
        self.checkpoint_sha256 = checkpoint_sha256
        self.model_name = model_name
        self.preprocessing_id = preprocessing_id
        self.checkpoint_format = checkpoint_format
        self.timeout_s = float(timeout_s)
        self.startup_timeout_s = float(startup_timeout_s)
        self.max_request_bytes = max_request_bytes
        self._command = command
        self._lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._close_requested = threading.Event()
        self._process: subprocess.Popen | None = None
        self._stdout_buffer = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._stderr_done = threading.Event()
        self._stderr_done.set()
        self._stderr_data = bytearray()
        self._stderr_lock = threading.Lock()
        self._space_metadata: dict[str, Any] | None = None
        self._space_id: str | None = None
        self._last_status: dict[str, Any] = {"status": "not_started", "missing_detection_ids": ()}

    @property
    def space_id(self) -> str | None:
        return self._space_id

    @property
    def space_metadata(self) -> Mapping[str, Any] | None:
        if self._space_metadata is None:
            return None
        return MappingProxyType(dict(self._space_metadata))

    @property
    def last_status(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self._last_status))

    @property
    def is_alive(self) -> bool:
        with self._process_lock:
            process = self._process
        return process is not None and process.poll() is None

    def _stderr_tail(self) -> str:
        with self._stderr_lock:
            return bytes(self._stderr_data).decode("utf-8", errors="replace")[-4096:]

    def _stderr_loop(self, process: subprocess.Popen) -> None:
        assert process.stderr is not None
        stream = process.stderr
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr_data.extend(chunk)
                    if len(self._stderr_data) > 32 * 1024:
                        del self._stderr_data[:-32 * 1024]
        except (OSError, ValueError):
            pass
        finally:
            self._stderr_done.set()

    @staticmethod
    def _frame(payload: Mapping[str, Any], limit: int) -> bytes:
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError(f"worker request is not JSON-safe: {error}") from error
        if len(encoded) > limit:
            raise ValueError(f"IPC request is {len(encoded)} bytes; limit is {limit}")
        return len(encoded).to_bytes(4, "big") + encoded

    def _send(self, payload: Mapping[str, Any], deadline: float) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("appearance worker is not running")
        frame = self._frame(payload, self.max_request_bytes)
        _write_all(process.stdin.fileno(), frame, deadline)

    def _read_response(self, deadline: float) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("appearance worker stdout is unavailable")
        fd = process.stdout.fileno()
        os.set_blocking(fd, False)
        selector = selectors.DefaultSelector()
        selector.register(fd, selectors.EVENT_READ)
        try:
            while True:
                if len(self._stdout_buffer) >= 4:
                    size = int.from_bytes(self._stdout_buffer[:4], "big", signed=False)
                    if size > MAX_RESPONSE_BYTES:
                        raise ValueError("worker response exceeds the IPC byte limit")
                    frame_size = size + 4
                    if len(self._stdout_buffer) >= frame_size:
                        encoded = bytes(self._stdout_buffer[4:frame_size])
                        del self._stdout_buffer[:frame_size]
                        response = json.loads(encoded.decode("utf-8"))
                        if not isinstance(response, dict):
                            raise ValueError("worker response must be a JSON object")
                        return response
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("appearance worker exceeded the whole-operation deadline")
                if not selector.select(remaining):
                    raise TimeoutError("appearance worker exceeded the whole-operation deadline")
                try:
                    chunk = os.read(fd, min(65536, MAX_RESPONSE_BYTES + 4 - len(self._stdout_buffer)))
                except BlockingIOError:
                    continue
                except InterruptedError:
                    continue
                if not chunk:
                    code = process.poll()
                    raise EOFError(f"worker stdout closed (exit={code})")
                self._stdout_buffer.extend(chunk)
                if len(self._stdout_buffer) > MAX_RESPONSE_BYTES + 4:
                    raise ValueError("worker response exceeds the IPC byte limit")
        finally:
            selector.close()

    def _validate_metadata(self, metadata: Any) -> tuple[dict[str, Any], str]:
        if not isinstance(metadata, dict):
            raise ValueError("worker ready response omitted model/preprocessing metadata")
        expected = {
            "model_name": self.model_name,
            "checkpoint_sha256": self.checkpoint_sha256,
            "pretrained": None,
            "state_dict_strict": True,
            "preprocessing_id": self.preprocessing_id,
            "crop_recipe_id": CROP_RECIPE_ID,
            "feature_dimension": FEATURE_DIMENSION,
        }
        if self.checkpoint_format == "openai_jit":
            expected.update(checkpoint_format="openai_jit", backend="openai_clip", model_package="clip",
                            architecture={"input_resolution": 224, "patch_size": 32, "width": 768,
                                          "layers": 12, "embedding_dimension": 512})
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(f"worker actual {key} differs from configured metadata")
        transform_digest = metadata.get("transform_repr_sha256")
        if not isinstance(transform_digest, str) or _SHA256.fullmatch(transform_digest) is None:
            raise ValueError("worker did not report a valid actual transform fingerprint")
        runtime = metadata.get("runtime")
        runtime_keys = _OPENAI_RUNTIME_KEYS if self.checkpoint_format == "openai_jit" else _RUNTIME_KEYS
        if not isinstance(runtime, dict) or any(
            not isinstance(runtime.get(key), str) or not runtime[key].strip() for key in runtime_keys
        ):
            raise ValueError("worker did not report complete backend/runtime versions")
        if self.checkpoint_format == "openai_jit":
            for key in ("model_implementation_sha256", "preprocessing_implementation_sha256"):
                if not isinstance(metadata.get(key), str) or _SHA256.fullmatch(metadata[key]) is None:
                    raise ValueError(f"worker did not report valid actual {key}")
        normalized = dict(metadata)
        normalized["runtime"] = {key: runtime[key] for key in runtime_keys}
        model_identity = {
            "model_name": normalized["model_name"],
            "checkpoint_sha256": normalized["checkpoint_sha256"],
            "pretrained": normalized["pretrained"],
            "state_dict_strict": normalized["state_dict_strict"],
        }
        prefix = "neusymnav-openclip-model-v1:"
        if self.checkpoint_format == "openai_jit":
            prefix = "neusymnav-openai-clip-model-v1:"
            model_identity.update(checkpoint_format="openai_jit", backend="openai_clip",
                                  model_implementation_sha256=normalized["model_implementation_sha256"])
        model_fingerprint = prefix + _canonical_hash(model_identity)
        normalized["model_fingerprint"] = model_fingerprint
        space_id = "neusymnav-appearance-space-v1:" + _canonical_hash(normalized)
        return normalized, space_id

    def _start(self, source: FrameKey) -> None:
        if self._close_requested.is_set():
            raise AppearanceUnavailable("encoder is closed", source)
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            return
        self._stop_worker(graceful=False)
        startup_deadline = time.monotonic() + self.startup_timeout_s
        self._stdout_buffer.clear()
        self._stderr_data = bytearray()
        environment = os.environ.copy()
        environment.update({
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "PYTHONNOUSERSITE": "1",
        })
        try:
            process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                close_fds=True,
                start_new_session=True,
                env=environment,
            )
        except Exception as error:
            if self._close_requested.is_set():
                raise AppearanceUnavailable("encoder was closed during worker startup", source) from error
            raise AppearanceUnavailable(f"could not start isolated worker: {error}", source) from error
        with self._process_lock:
            self._process = process
            cancelled = self._close_requested.is_set()
        if cancelled:
            _terminate_process_group(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            with self._process_lock:
                if self._process is process:
                    self._process = None
            raise AppearanceUnavailable("worker startup cancelled because encoder is closed", source)
        self._stderr_done.clear()
        self._stderr_thread = threading.Thread(target=self._stderr_loop, args=(process,),
                                               name="appearance-worker-stderr", daemon=True)
        self._stderr_thread.start()
        config = {
            "checkpoint_path": str(self.checkpoint_path),
            "checkpoint_sha256": self.checkpoint_sha256,
            "model_name": self.model_name,
            "pretrained": None,
            "state_dict_strict": True,
            "preprocessing_id": self.preprocessing_id,
            "crop_recipe_id": CROP_RECIPE_ID,
            "feature_dimension": FEATURE_DIMENSION,
        }
        if self.checkpoint_format == "openai_jit":
            config["checkpoint_format"] = self.checkpoint_format
        try:
            self._send({"op": "initialize", "config": config}, startup_deadline)
            response = self._read_response(startup_deadline)
            if response.get("op") == "error":
                raise RuntimeError(f"worker initialization failed: {response.get('reason', 'unknown reason')}")
            if response.get("op") != "ready":
                raise ValueError("worker did not return a ready response")
            metadata, space_id = self._validate_metadata(response.get("metadata"))
            self._space_metadata = metadata
            self._space_id = space_id
        except Exception as error:
            detail = str(error)
            tail = self._stderr_tail()
            if tail:
                detail = f"{detail}; worker stderr: {tail}"
            self._stop_worker(graceful=False)
            raise AppearanceUnavailable(f"worker startup failed: {detail}", source) from error

    @staticmethod
    def _source_dict(source: FrameKey) -> dict[str, Any]:
        return {"episode_id": source.episode_id, "sensor_id": source.sensor_id,
                "frame_index": int(source.frame_index)}

    def _request(self, observation: Observation, batch: DetectionBatch) -> dict[str, Any]:
        rgb = np.ascontiguousarray(observation.rgb, dtype=np.uint8)
        detections = []
        for detection in batch.detections:
            packed = np.packbits(detection.mask.reshape(-1), bitorder="little").tobytes()
            detections.append({
                "detection_id": detection.detection_id,
                "mask_shape": list(detection.mask.shape),
                "mask_bits_b64": base64.b64encode(packed).decode("ascii"),
            })
        return {
            "op": "encode",
            "source": self._source_dict(observation.key),
            "geometry_hash": observation.geometry_hash,
            "rgb_shape": list(rgb.shape),
            "rgb_b64": base64.b64encode(rgb.tobytes(order="C")).decode("ascii"),
            "detections": detections,
        }

    def _check_request_budget(self, observation: Observation, batch: DetectionBatch) -> None:
        pixels = int(observation.rgb.shape[0]) * int(observation.rgb.shape[1])
        raw_rgb_bytes = pixels * 3
        raw_mask_bytes = sum((pixels + 7) // 8 for _ in batch.detections)
        b64_bytes = 4 * ((raw_rgb_bytes + 2) // 3) + 4 * ((raw_mask_bytes + 2) // 3)
        # IDs are JSON escaped; six bytes per UTF-8 byte is a conservative
        # upper bound for quoted/control-character content.
        id_bytes = sum(6 * len(d.detection_id.encode("utf-8")) + 256 for d in batch.detections)
        source_bytes = sum(6 * len(value.encode("utf-8")) for value in
                           (observation.key.episode_id, observation.key.sensor_id))
        estimated = b64_bytes + id_bytes + source_bytes + len(observation.geometry_hash) + 512
        if estimated > self.max_request_bytes:
            raise AppearanceUnavailable(
                f"IPC request would exceed the byte limit ({estimated} > {self.max_request_bytes})",
                observation.key,
            )

    @staticmethod
    def _read_features(response: Mapping[str, Any], expected_ids: set[str], *, space_id: str):
        feature_payload = response.get("features")
        status_payload = response.get("status")
        if not isinstance(feature_payload, dict) or not isinstance(status_payload, dict):
            raise ValueError("worker response omitted per-detection features/status")
        if set(status_payload) != expected_ids or not set(feature_payload).issubset(expected_ids):
            raise ValueError("worker response detection IDs differ from request")
        available_ids = set()
        missing_ids = []
        for detection_id, status in status_payload.items():
            if not isinstance(status, dict):
                raise ValueError("worker feature status must be an object")
            state = status.get("status")
            if state == "available":
                available_ids.add(detection_id)
                if detection_id not in feature_payload:
                    raise ValueError("worker marked a detection available without a feature")
            elif state == "missing":
                reason = status.get("reason")
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
                    raise ValueError("worker missing-feature status needs a bounded reason")
                missing_ids.append(detection_id)
                if detection_id in feature_payload:
                    raise ValueError("worker attached a feature to a missing detection")
            else:
                raise ValueError("worker returned an unknown feature status")
        if set(feature_payload) != available_ids:
            raise ValueError("worker feature payload does not match available status IDs")
        features: dict[str, AppearanceFeature] = {}
        for detection_id, encoded in feature_payload.items():
            if not isinstance(encoded, str):
                raise ValueError("feature vector payload must be base64 text")
            vector_bytes = base64.b64decode(encoded, validate=True)
            if len(vector_bytes) != FEATURE_DIMENSION * np.dtype("<f4").itemsize:
                raise ValueError("worker feature vector has the wrong byte length")
            vector = np.frombuffer(vector_bytes, dtype="<f4").astype(np.float32, copy=True)
            if not np.isfinite(vector).all():
                raise ValueError("worker feature vector contains non-finite values")
            norm = float(np.linalg.norm(vector.astype(np.float64)))
            if not math.isfinite(norm) or not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
                raise ValueError("worker feature vector is not L2-normalized")
            features[detection_id] = AppearanceFeature(space_id, vector)
        return features, tuple(sorted(missing_ids)), status_payload

    def encode(self, observation: Observation, batch: DetectionBatch) -> AppearanceBatch:
        validate_detection_batch(observation, batch)
        if self._close_requested.is_set():
            self._last_status = {"status": "unavailable", "missing_detection_ids": ()}
            raise AppearanceUnavailable("encoder is closed", observation.key)
        if not batch.detections:
            self._last_status = {"status": "empty", "missing_detection_ids": ()}
            return AppearanceBatch(observation.key, observation.geometry_hash, {})
        try:
            self._check_request_budget(observation, batch)
        except AppearanceUnavailable:
            self._last_status = {"status": "unavailable", "missing_detection_ids": ()}
            raise
        with self._lock:
            try:
                self._start(observation.key)
                process = self._process
                if process is None or process.stdin is None:
                    raise RuntimeError("appearance worker was not started")
                request_deadline = time.monotonic() + self.timeout_s
                request = self._request(observation, batch)
                frame = self._frame(request, self.max_request_bytes)
                _write_all(process.stdin.fileno(), frame, request_deadline)
                response = self._read_response(request_deadline)
                if response.get("op") == "error":
                    raise RuntimeError(f"worker encode failed: {response.get('reason', 'unknown reason')}")
                if response.get("op") != "features":
                    raise ValueError("worker returned an unexpected response operation")
                if response.get("source") != self._source_dict(observation.key):
                    raise ValueError("worker response source differs from request")
                if response.get("geometry_hash") != observation.geometry_hash:
                    raise ValueError("worker response geometry_hash differs from request")
                if self._space_id is None:
                    raise RuntimeError("appearance worker has no verified feature space")
                features, missing_ids, status_payload = self._read_features(
                    response, {d.detection_id for d in batch.detections}, space_id=self._space_id
                )
                result = AppearanceBatch(observation.key, observation.geometry_hash, features)
                validate_appearance_batch(observation, batch, result)
                self._last_status = {
                    "status": "partial" if missing_ids else "available",
                    "missing_detection_ids": missing_ids,
                    "detections": MappingProxyType({key: MappingProxyType(dict(value))
                                                     for key, value in status_payload.items()}),
                }
                return result
            except AppearanceUnavailable:
                self._last_status = {"status": "unavailable", "missing_detection_ids": ()}
                raise
            except Exception as error:
                detail = str(error)
                tail = self._stderr_tail()
                if tail:
                    detail = f"{detail}; worker stderr: {tail}"
                self._last_status = {"status": "unavailable", "missing_detection_ids": ()}
                self._stop_worker(graceful=False)
                raise AppearanceUnavailable(detail, observation.key) from error

    def _stop_worker(self, *, graceful: bool) -> None:
        with self._process_lock:
            process = self._process
        if process is None:
            return
        if graceful and process.poll() is None:
            try:
                if process.stdin is not None:
                    _write_all(process.stdin.fileno(), self._frame({"op": "close"}, 1024),
                               time.monotonic() + min(0.2, self.timeout_s))
            except (BrokenPipeError, OSError, ValueError, TimeoutError):
                pass
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            _terminate_process_group(process)
        else:
            # Also clean up descendants that may have inherited the worker pipes.
            _signal_process_group(process, signal.SIGKILL)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for thread in (self._stderr_thread,):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=0.5)
        with self._process_lock:
            if self._process is process:
                self._process = None
        self._stderr_thread = None
        self._stdout_buffer.clear()

    def close(self) -> None:
        """Stop this encoder permanently and reap its worker.

        Raises ``AppearanceShutdownPending`` if synchronous process creation
        has not returned within the bounded wait. The close request remains
        terminal, and a subsequently published worker is cancelled by startup.
        """
        self._close_requested.set()
        with self._process_lock:
            process = self._process
        if process is not None:
            _terminate_process_group(process)
        if not self._lock.acquire(timeout=CLOSE_JOIN_TIMEOUT_S):
            # A process may have appeared after the first snapshot while Popen
            # returned to _start. Re-read it after requesting cancellation.
            with self._process_lock:
                process = self._process
            if process is not None:
                _terminate_process_group(process)
            if not self._lock.acquire(timeout=0.25):
                raise AppearanceShutdownPending(
                    "close was requested, but worker startup has not quiesced; "
                    "cleanup is pending until subprocess creation returns"
                )
        try:
            self._stop_worker(graceful=False)
        finally:
            self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()
