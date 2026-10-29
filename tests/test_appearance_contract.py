from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts.observations import (
    AppearanceBatch,
    AppearanceFeature,
    Detection,
    DetectionBatch,
    FrameKey,
    ObjectObservation,
    validate_appearance_batch,
)


FIXTURES = Path(__file__).parent / "fixtures" / "appearance"


def crop_case():
    fixture = json.loads((FIXTURES / "crops-v1.json").read_text())
    height, width = fixture["image"]["height"], fixture["image"]["width"]
    y, x = np.indices((height, width))
    rgb = np.stack(((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256), axis=-1).astype(np.uint8)
    assert hashlib.sha256(rgb.tobytes()).hexdigest() == fixture["image"]["sha256"]
    mask = np.zeros((height, width), dtype=np.bool_)
    y0, y1, x0, x1 = fixture["mask_crop"]["mask_rect_yx_exclusive"]
    mask[y0:y1, x0:x1] = True
    assert hashlib.sha256(np.packbits(mask.reshape(-1), bitorder="little").tobytes()).hexdigest() == \
        fixture["mask_crop"]["mask_packed_sha256"]
    return fixture, rgb, mask


def source_and_batch(*, count=2):
    height, width = 48, 64
    obs = observation(
        key=FrameKey("appearance-episode", "rgbd", 7),
        rgb=np.zeros((height, width, 3), dtype=np.uint8),
        depth_m=np.ones((height, width), dtype=np.float32),
        valid_depth=np.ones((height, width), dtype=np.bool_),
        K=np.array([[40.0, 0.0, 32.0], [0.0, 40.0, 24.0], [0.0, 0.0, 1.0]]),
    )
    masks = []
    for y0, y1, x0, x1 in ((14, 20, 17, 24), (29, 37, 40, 51))[:count]:
        mask = np.zeros((height, width), dtype=np.bool_)
        mask[y0:y1, x0:x1] = True
        masks.append(mask)
    detections = tuple(Detection(f"det-{i}", "chair", "chair", 0.9, mask)
                       for i, mask in enumerate(masks))
    batch = DetectionBatch.from_observation(obs, detections, vocabulary_id="taxonomy:v1")
    return obs, batch


def projected(obs, batch):
    return tuple(ObjectObservation(
        source=obs.key,
        detection_id=detection.detection_id,
        geometry_hash=obs.geometry_hash,
        points_world=np.array([[float(i), 0.0, 1.0]], dtype=np.float64),
        camera_position=tuple(obs.T_world_camera[:3, 3]),
        raw_label=detection.raw_label,
        category=detection.category,
        score=detection.score,
        evidence_kind="detected",
        appearance=None,
    ) for i, detection in enumerate(batch.detections))


def test_reference_crop_and_mask_bounds_match_independent_pixel_fixture():
    from neusymnav.perception.appearance_worker import crop_bbox_rgb, crop_mask_rgb

    fixture, rgb, mask = crop_case()
    ref = fixture["bbox_crop"]
    crop, box = crop_bbox_rgb(rgb, ref["bbox_xyxy_float"], padding_px=ref["padding_px"])
    assert list(box) == ref["crop_box_xyxy_float"]
    assert list(crop.shape) == ref["crop_shape_hwc"]
    assert hashlib.sha256(crop.tobytes()).hexdigest() == ref["crop_sha256"]

    ref = fixture["mask_crop"]
    crop, box = crop_mask_rgb(rgb, mask, padding_px=ref["padding_px"])
    assert list(box) == ref["crop_box_xyxy_float"]
    assert list(crop.shape) == ref["crop_shape_hwc"]
    assert hashlib.sha256(crop.tobytes()).hexdigest() == ref["crop_sha256"]
    # Pixels inside the crop come from the original RGB frame; the mask is not painted over them.
    np.testing.assert_array_equal(crop, rgb[:40, :44])
    with pytest.raises(ValueError, match="match the original RGB"):
        crop_mask_rgb(rgb, mask[:-1], padding_px=20)
    with pytest.raises(ValueError, match="at least one"):
        crop_mask_rgb(rgb, np.zeros_like(mask), padding_px=20)


def test_cpu_fixture_encoder_maps_ids_and_normalizes_features():
    from neusymnav.perception.appearance_worker import encode_rgb_features
    spec = importlib.util.spec_from_file_location("p05_cpu_encoder_fixture", FIXTURES / "cpu_encoder.py")
    assert spec is not None and spec.loader is not None
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    cpu_encode = fixture_module.encode

    fixture, rgb, mask = crop_case()
    other = np.zeros_like(mask)
    other[29:37, 40:51] = True
    features, status = encode_rgb_features(
        rgb,
        ({"detection_id": "det-table", "mask": mask},
         {"detection_id": "det-chair", "mask": other}),
        image_encoder=cpu_encode,
        padding_px=20,
    )
    assert status == {"det-table": {"status": "available"}, "det-chair": {"status": "available"}}
    assert set(features) == {"det-table", "det-chair"}
    assert not np.array_equal(features["det-table"], features["det-chair"])
    for vector in features.values():
        assert vector.shape == (512,)
        assert vector.dtype == np.float32
        assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-5, rtol=1e-5)
    assert np.array_equal(rgb, crop_case()[1])


def test_failed_individual_crop_is_marked_missing_without_fabricating_vector():
    from neusymnav.perception.appearance_worker import encode_rgb_features

    fixture, rgb, mask = crop_case()
    missing = np.zeros_like(mask)
    missing[29:37, 40:51] = True

    def fail_second(crop):
        if float(crop[0, 0, 0]) > 0:
            raise RuntimeError("fixture inference failure")
        return np.ones(512, dtype=np.float32)

    features, status = encode_rgb_features(
        rgb,
        ({"detection_id": "first", "mask": mask}, {"detection_id": "second", "mask": missing}),
        image_encoder=fail_second,
        padding_px=20,
    )
    assert set(features) == {"first"}
    assert status["first"] == {"status": "available"}
    assert status["second"]["status"] == "missing"
    assert "fixture inference failure" in status["second"]["reason"]


def test_attach_features_checks_source_hash_and_projected_detection_keys():
    from neusymnav.perception.appearance_client import attach_features

    obs, batch = source_and_batch()
    observations = projected(obs, batch)
    feature = AppearanceFeature("space:fixture", np.array([1.0, 0.0], dtype=np.float32))
    result = attach_features(observations, AppearanceBatch(obs.key, obs.geometry_hash, {"det-0": feature}))
    assert result[0].appearance is feature
    assert result[1] is observations[1]
    assert np.linalg.norm(result[0].appearance.vector) == 1.0
    with pytest.raises(ValueError, match="source"):
        attach_features(observations, AppearanceBatch(FrameKey("other", "rgbd", 7), obs.geometry_hash,
                                                       {"det-0": feature}))
    with pytest.raises(ValueError, match="geometry_hash"):
        attach_features(observations, AppearanceBatch(obs.key, "0" * 64, {"det-0": feature}))
    with pytest.raises(ValueError, match="projected"):
        attach_features(observations, AppearanceBatch(obs.key, obs.geometry_hash,
                                                       {"unprojected": feature}))


def test_attach_features_rejects_space_or_dimension_mismatch_and_preserves_missing():
    from neusymnav.perception.appearance_client import attach_features

    obs, batch = source_and_batch()
    observations = projected(obs, batch)
    old = replace(observations[0], appearance=AppearanceFeature("space:old", np.array([1.0, 0.0])))
    features = AppearanceBatch(obs.key, obs.geometry_hash,
                               {"det-0": AppearanceFeature("space:new", np.array([1.0, 0.0]))})
    with pytest.raises(ValueError, match="space/dimension"):
        attach_features((old, observations[1]), features)
    baseline = attach_features(observations, AppearanceBatch(obs.key, obs.geometry_hash, {}))
    assert baseline[0] is observations[0] and baseline[1] is observations[1]


def encoder_for_mode(tmp_path, mode, *, timeout_s=0.5, max_request_bytes=32 * 1024 * 1024,
                     checkpoint_bytes=b"explicit fixture checkpoint; stub worker does not load it",
                     startup_timeout_s=1.0, worker_args=()):
    from neusymnav.perception.appearance_client import AppearanceWorkerEncoder

    tmp_path.mkdir(parents=True, exist_ok=True)
    checkpoint = tmp_path / "fixture.safetensors"
    checkpoint.write_bytes(checkpoint_bytes)
    python = Path(sys.executable).resolve()
    stub = (FIXTURES / "worker_stub.py").resolve()
    return AppearanceWorkerEncoder(
        worker_python=python,
        checkpoint_path=checkpoint.resolve(),
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        model_name="ViT-B-32",
        preprocessing_id="openclip-vit-b-32-openai-eval-224-maskbboxpad20-v1",
        timeout_s=timeout_s,
        startup_timeout_s=startup_timeout_s,
        max_request_bytes=max_request_bytes,
        _worker_command=(str(python), str(stub), "--mode", mode, *map(str, worker_args)),
    )


def large_source_and_batch():
    height = width = 256
    obs = observation(
        key=FrameKey("appearance-large", "rgbd", 11),
        rgb=np.full((height, width, 3), 127, dtype=np.uint8),
        depth_m=np.ones((height, width), dtype=np.float32),
        valid_depth=np.ones((height, width), dtype=np.bool_),
        K=np.array([[200.0, 0.0, 128.0], [0.0, 200.0, 128.0], [0.0, 0.0, 1.0]]),
    )
    mask = np.zeros((height, width), dtype=np.bool_)
    mask[32:220, 40:211] = True
    batch = DetectionBatch.from_observation(
        obs, (Detection("det-large", "chair", "chair", 0.9, mask),), vocabulary_id="taxonomy:v1"
    )
    return obs, batch


def test_worker_encoder_returns_readonly_features_and_partial_status(tmp_path):
    from neusymnav.perception.appearance_client import attach_features

    obs, batch = source_and_batch()
    encoder = encoder_for_mode(tmp_path, "partial")
    try:
        result = encoder.encode(obs, batch)
        validate_appearance_batch(obs, batch, result)
        assert set(result.features) == {"det-0"}
        assert result.features["det-0"].space_id == encoder.space_id
        assert not result.features["det-0"].vector.flags.writeable
        assert encoder.last_status["status"] == "partial"
        assert encoder.last_status["missing_detection_ids"] == ("det-1",)
        attached = attach_features(projected(obs, batch), result)
        assert attached[0].appearance is not None and attached[1].appearance is None
    finally:
        encoder.close()


@pytest.mark.parametrize("mode", ["timeout", "crash"])
def test_worker_timeout_or_crash_is_explicit_and_process_is_cleaned(tmp_path, mode):
    from neusymnav.perception.appearance_client import AppearanceUnavailable

    obs, batch = source_and_batch(count=1)
    encoder = encoder_for_mode(tmp_path, mode, timeout_s=0.15)
    start = time.monotonic()
    try:
        with pytest.raises(AppearanceUnavailable) as captured:
            encoder.encode(obs, batch)
        assert captured.value.source == obs.key
        assert captured.value.reason
        assert time.monotonic() - start < 2.0
        assert not encoder.is_alive
    finally:
        encoder.close()


@pytest.mark.parametrize(("mode", "field"), [("spoof", "source"), ("spoof_hash", "geometry_hash")])
def test_worker_rejects_spoofed_source_or_geometry_even_when_detection_ids_match(tmp_path, mode, field):
    from neusymnav.perception.appearance_client import AppearanceUnavailable

    obs, batch = source_and_batch(count=1)
    encoder = encoder_for_mode(tmp_path, mode)
    try:
        with pytest.raises(AppearanceUnavailable, match=field) as captured:
            encoder.encode(obs, batch)
        assert captured.value.source == obs.key
        assert not encoder.is_alive
    finally:
        encoder.close()


def test_oversized_request_fails_before_worker_launch_with_source_context(tmp_path):
    from neusymnav.perception.appearance_client import AppearanceUnavailable

    obs, batch = source_and_batch(count=1)
    encoder = encoder_for_mode(tmp_path, "success", max_request_bytes=1024)
    try:
        with pytest.raises(AppearanceUnavailable, match="IPC request") as captured:
            encoder.encode(obs, batch)
        assert captured.value.source == obs.key
        assert not encoder.is_alive
    finally:
        encoder.close()


def test_space_id_changes_with_local_checkpoint_content(tmp_path):
    first = encoder_for_mode(tmp_path / "first", "success", checkpoint_bytes=b"checkpoint one")
    second = encoder_for_mode(tmp_path / "second", "success", checkpoint_bytes=b"checkpoint two")
    obs, batch = source_and_batch(count=1)
    try:
        first_result = first.encode(obs, batch)
        second_result = second.encode(obs, batch)
        assert first.space_id != second.space_id
        assert first_result.features["det-0"].space_id != second_result.features["det-0"].space_id
    finally:
        first.close()
        second.close()


def test_space_id_changes_with_actual_worker_transform_fingerprint(tmp_path):
    first = encoder_for_mode(tmp_path / "first", "success")
    second = encoder_for_mode(tmp_path / "second", "transform")
    obs, batch = source_and_batch(count=1)
    try:
        first.encode(obs, batch)
        second.encode(obs, batch)
        assert first.space_id != second.space_id
    finally:
        first.close()
        second.close()


def test_client_import_keeps_openclip_and_torch_out_of_host_process():
    import neusymnav.perception.appearance_client  # noqa: F401

    assert "open_clip" not in sys.modules
    assert "torch" not in sys.modules


def test_nonblocking_writer_handles_partial_os_writes(monkeypatch):
    import neusymnav.perception.appearance_client as client

    read_fd, write_fd = os.pipe()
    payload = bytes(range(256)) * 1024
    received = bytearray()
    reader = threading.Thread(target=lambda: received.extend(iter_pipe(read_fd, len(payload))))
    original_write = os.write

    def short_write(fd, data):
        return original_write(fd, data[:7])

    try:
        os.set_blocking(read_fd, True)
        os.set_blocking(write_fd, False)
        monkeypatch.setattr(client.os, "write", short_write)
        reader.start()
        client._write_all(write_fd, payload, time.monotonic() + 2.0)
        os.close(write_fd)
        write_fd = -1
        reader.join(timeout=2.0)
        assert not reader.is_alive()
        assert bytes(received) == payload
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)
        if reader.is_alive():
            reader.join(timeout=0.2)


def iter_pipe(fd, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def test_large_request_and_concurrent_close_obey_whole_request_deadline(tmp_path):
    from neusymnav.perception.appearance_client import AppearanceUnavailable

    obs, batch = large_source_and_batch()
    child_pid_file = tmp_path / "stalled-child.pid"
    encoder = encoder_for_mode(tmp_path, "write_stall_child", timeout_s=0.2,
                               worker_args=("--child-pid-file", child_pid_file))
    outcome = []

    def invoke():
        try:
            encoder.encode(obs, batch)
        except BaseException as error:
            outcome.append(error)

    request_thread = threading.Thread(target=invoke, daemon=True)
    request_thread.start()
    try:
        ready_deadline = time.monotonic() + 2.0
        while encoder.space_id is None and time.monotonic() < ready_deadline:
            time.sleep(0.005)
        assert encoder.space_id is not None, "stub worker did not finish initialization"
        child_deadline = time.monotonic() + 1.0
        while (not child_pid_file.exists() or child_pid_file.stat().st_size == 0) and \
                time.monotonic() < child_deadline:
            time.sleep(0.005)
        assert child_pid_file.exists() and child_pid_file.stat().st_size > 0, \
            "stub worker did not publish its cleanup probe PID"
        child_pid = int(child_pid_file.read_text())
        request_thread.join(timeout=0.05)
        assert request_thread.is_alive(), "large payload did not exercise pipe backpressure"

        close_thread = threading.Thread(target=encoder.close, daemon=True)
        close_thread.start()
        close_thread.join(timeout=1.0)
        assert not close_thread.is_alive(), "close waited indefinitely behind a stalled request"
        request_thread.join(timeout=1.0)
        assert not request_thread.is_alive(), "request exceeded its whole-request deadline"
        assert len(outcome) == 1 and isinstance(outcome[0], AppearanceUnavailable)
        assert outcome[0].source == obs.key
        assert not encoder.is_alive
        assert encoder._stderr_thread is None
        assert encoder._stderr_done.is_set()
        for _ in range(100):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            pytest.fail("close left the worker's child process running")
    finally:
        process = encoder._process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=1.0)
        request_thread.join(timeout=1.0)


def test_nonreading_worker_write_hits_whole_request_deadline(tmp_path):
    from neusymnav.perception.appearance_client import AppearanceUnavailable

    obs, batch = large_source_and_batch()
    encoder = encoder_for_mode(tmp_path, "write_stall", timeout_s=0.2)
    start = time.monotonic()
    try:
        with pytest.raises(AppearanceUnavailable, match="deadline") as captured:
            encoder.encode(obs, batch)
        elapsed = time.monotonic() - start
        assert captured.value.source == obs.key
        assert 0.15 <= elapsed < 1.0
        assert not encoder.is_alive
        assert encoder._stderr_thread is None
        assert encoder._stderr_done.is_set()
    finally:
        encoder.close()


def test_startup_deadline_covers_init_exchange_and_reaps_worker(tmp_path):
    from neusymnav.perception.appearance_client import AppearanceUnavailable

    obs, batch = source_and_batch(count=1)
    encoder = encoder_for_mode(tmp_path, "startup_stall", startup_timeout_s=0.15)
    start = time.monotonic()
    try:
        with pytest.raises(AppearanceUnavailable, match="deadline") as captured:
            encoder.encode(obs, batch)
        assert captured.value.source == obs.key
        assert time.monotonic() - start < 1.0
        assert not encoder.is_alive
        assert encoder._stderr_thread is None
        assert encoder._stderr_done.is_set()
    finally:
        encoder.close()
