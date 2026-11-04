from dataclasses import replace
import hashlib
import json
import sys
import time

import numpy as np
from contract_helpers import observation
from neusymnav.regions.rebuild_room_session import RebuildRoomSession, replay_recording


_FAKE_WORKER = r'''
import base64, hashlib, json, sys, time
import numpy as np
source_hash, m23_hash, m4_hash, mode = sys.argv[1:5]
def emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
config_hash = __import__("os").environ["NEUSYMNAV_EXPECTED_ROOM_CONFIG_SHA256"]
emit({"status":"ready", "source_sha256":source_hash, "m23_sha256":m23_hash,
      "m4_sha256":m4_hash, "config_sha256":config_hash})
revision = 0
def enc(array):
    dtype = array.dtype.newbyteorder("<")
    array = array.astype(dtype, copy=False)
    raw = array.tobytes()
    return {"dtype":dtype.str, "shape":list(array.shape), "sha256":hashlib.sha256(raw).hexdigest(),
            "data":base64.b64encode(raw).decode("ascii")}
for line in sys.stdin:
    request = json.loads(line)
    if request == {"op":"close"}:
        emit({"status":"closed", "clean_shutdown":True})
        break
    frame = request["frame"]["frame"]
    if mode == "fatal" or (mode == "pairfatal" and revision == 1):
        emit({"status":"error", "fatal":True, "replay_required":True, "error":"injected native mutation failure"})
        break
    if mode in ("delay", "pair"):
        time.sleep(0.35)
    revision += 1
    states = np.full((2,2), -1, dtype=np.int8)
    height = np.full((2,2), np.nan, dtype=np.float64)
    invalid = np.zeros((2,2), dtype=bool)
    accepted_revision = revision if revision == 1 else 1
    stale = revision > 1
    regions = []
    m5_revision = None
    if mode in ("pair", "pairfatal"):
        regions = [{"persistent_id":"7", "source_map_revision":accepted_revision,
                    "polygon":[[0.,0.],[1.,0.],[1.,1.]], "adjacency":[], "timestamp_s":float(revision)}]
        m5_revision = 1
    emit({
        "status":"ok", "request_revision":revision,
        "latest_map":{"revision":revision, "m2_revision":revision, "m3_revision":revision,
            "resolution_m":0.05, "origin_xy":[-0.05,0.1], "states":enc(states),
            "z_floor_m":enc(height), "z_ceiling_m":enc(height), "floor_valid":enc(invalid),
            "ceiling_valid":enc(invalid),
            "source":({**frame,"prefix_sha256":"f"*64} if mode == "badsource" else frame),
            "source_hash":("e"*64 if mode == "badpin" else source_hash),
            "worker_sha256":m23_hash, "m4_worker_sha256":m4_hash, "config_sha256":config_hash},
        "accepted_map_revision":accepted_revision if mode in ("pair", "pairfatal") else None,
        "regions":regions, "m5_revision":m5_revision,
        "regions_stale":stale if mode in ("pair", "pairfatal") else True,
        "m4_status":"success", "m4_branch":"accept_incremental",
        "m5_accepted":not stale, "m5_reason":None, "timings_ms":{"m1_runtime_ms":1.0}
    })
'''


def _session(tmp_path, mode, *, timeout=5., monkeypatch):
    from neusymnav.regions import rebuild_room_session as session_module
    source = tmp_path / "Rebuild_3DScene_OccuSG"
    package = source / "src" / "standalone_sg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# fake pinned source for IPC test\n")
    m23 = source / "build" / "native-m3" / "occupancy" / "standalone_sg_octomap_fixture_runner"
    m4 = source / "build" / "native-m4-dude" / "occusg_dude_worker"
    m23.parent.mkdir(parents=True)
    m4.parent.mkdir(parents=True)
    m23.write_bytes(b"fake m23 worker")
    m4.write_bytes(b"fake m4 worker")
    m23.chmod(0o755)
    m4.chmod(0o755)
    constants = ("d" * 64, hashlib.sha256(m23.read_bytes()).hexdigest(),
                 hashlib.sha256(m4.read_bytes()).hexdigest())
    monkeypatch.setattr(session_module, "EXPECTED_SOURCE_TREE_SHA256", constants[0])
    monkeypatch.setattr(session_module, "EXPECTED_M23_SHA256", constants[1])
    monkeypatch.setattr(session_module, "EXPECTED_M4_SHA256", constants[2])
    command = (sys.executable, "-u", "-c", _FAKE_WORKER, *constants, mode)
    return RebuildRoomSession(
        source_root=source, m23_binary=m23, m4_binary=m4,
        episode_id="episode", floor_id="floor-0", ipc_timeout_s=timeout,
        run_dir=tmp_path / mode,
        worker_command=command,
    )


def test_empty_episode_closes_cleanly_without_fabricating_a_map(tmp_path, monkeypatch):
    session = _session(tmp_path, "pair", monkeypatch=monkeypatch)
    assert session.snapshot() is None
    result = session.close()
    assert result["clean_shutdown"]
    assert result["recording_complete"] and result["runtime_complete"]
    assert result["admitted_frames"] == result["recorded_frames"] == result["processed_frames"] == 0
    assert session.snapshot() is None


def test_session_bounds_pending_queue_and_publishes_exact_accepted_map_pair(tmp_path, monkeypatch):
    session = _session(tmp_path, "pair", monkeypatch=monkeypatch)
    try:
        first = session.submit(observation())
        assert first.accepted
        deadline = time.monotonic() + 2.
        while not session.health["inflight_bytes"] and time.monotonic() < deadline:
            time.sleep(.005)
        second = session.submit(observation(
            key=observation().key.__class__("episode", "rgbd", 1),
            capture_monotonic_ns=101, sim_time_s=1.))
        third = session.submit(observation(
            key=observation().key.__class__("episode", "rgbd", 2),
            capture_monotonic_ns=102, sim_time_s=2.))
        fourth = session.submit(observation(
            key=observation().key.__class__("episode", "rgbd", 3),
            capture_monotonic_ns=103, sim_time_s=3.))
        assert second.accepted and third.accepted
        assert not fourth.accepted and fourth.reason == "pending_queue_full"
        assert session.health["queued_frames"] <= 2
        assert session.health["queue_bytes"] <= 32 * 1024 * 1024
        assert session.wait_idle(5.)
        publication = session.snapshot()
        assert publication.latest_map.revision == 3
        assert publication.accepted_map_revision == 1
        assert publication.accepted_map.revision == 1
        assert publication.regions.source_map_revision == 1
        assert publication.regions_stale and publication.regions.stale
        assert publication.regions.regions["region:floor-0:7"].polygon.shape == (3, 2)
    finally:
        result = session.close()
    assert result["clean_shutdown"]
    assert result["recording_complete"] and result["runtime_complete"]
    assert result["admitted_frames"] == result["recorded_frames"] == result["processed_frames"] == 3
    run_dir = session.run_dir
    manifest = json.loads((run_dir / "completeness.json").read_text())
    assert manifest["runtime_complete"]
    frame_entries = manifest["frames"]
    assert len(frame_entries) == 3
    first_entry = frame_entries[0]
    saved = (run_dir / first_entry["payload_path"]).read_bytes()
    assert hashlib.sha256(saved).hexdigest() == first_entry["payload_sha256"]
    assert (run_dir / "admission-journal.jsonl").is_file()


def test_native_failure_poison_requires_new_session_and_stales_publication(tmp_path, monkeypatch):
    session = _session(tmp_path, "fatal", monkeypatch=monkeypatch)
    try:
        assert session.submit(observation()).accepted
        assert session.wait_idle(5.)
        health = session.health
        assert health["failed"] and health["replay_required"]
        refused = session.submit(observation(
            key=observation().key.__class__("episode", "rgbd", 1),
            capture_monotonic_ns=101, sim_time_s=1.))
        assert not refused.accepted and refused.reason == "replay_required"
        assert session.snapshot() is None
    finally:
        result = session.close()
    assert session.health["replay_required"]
    assert result["recording_complete"] and not result["runtime_complete"]


def test_worker_response_must_bind_to_admitted_frame_prefix(tmp_path, monkeypatch):
    session = _session(tmp_path, "badsource", monkeypatch=monkeypatch)
    try:
        assert session.submit(observation()).accepted
        assert session.wait_idle(5.)
        health = session.health
        assert health["failed"] and health["replay_required"]
        assert "source frame/prefix binding mismatch" in health["failure_reason"]
        assert session.snapshot() is None
    finally:
        result = session.close()
    assert result["recording_complete"] and not result["runtime_complete"]


def test_worker_response_must_match_startup_resource_pins(tmp_path, monkeypatch):
    session = _session(tmp_path, "badpin", monkeypatch=monkeypatch)
    try:
        assert session.submit(observation()).accepted
        assert session.wait_idle(5.)
        health = session.health
        assert health["failed"] and health["replay_required"]
        assert "pin mismatch: source_hash" in health["failure_reason"]
        assert session.snapshot() is None
    finally:
        result = session.close()
    assert result["recording_complete"] and not result["runtime_complete"]


def test_failure_after_accepted_publication_keeps_old_pair_stale(tmp_path, monkeypatch):
    session = _session(tmp_path, "pairfatal", monkeypatch=monkeypatch)
    try:
        assert session.submit(observation()).accepted
        assert session.wait_idle(5.)
        accepted = session.snapshot()
        assert accepted.accepted_map_revision == 1 and not accepted.regions_stale
        assert session.submit(observation(
            key=observation().key.__class__("episode", "rgbd", 1),
            capture_monotonic_ns=101, sim_time_s=1.,
        )).accepted
        assert session.wait_idle(5.)
        stale = session.snapshot()
        assert session.health["replay_required"]
        assert stale.latest_map.revision == 1
        assert stale.accepted_map_revision == 1
        assert stale.regions_stale and stale.regions.stale
        assert stale.replay_required
    finally:
        session.close()


def test_complete_recording_replays_in_order_with_the_same_prefixes(tmp_path, monkeypatch):
    original = _session(tmp_path, "pair", monkeypatch=monkeypatch)
    for index in range(3):
        base = observation()
        depth = base.depth_m.copy()
        valid = base.valid_depth.copy()
        depth.flat[0] = 0.0  # Invalid raw sensor values must survive exact replay.
        valid.flat[0] = False
        empty_no_return = np.zeros_like(valid)
        source = replace(base, key=base.key.__class__("episode", "rgbd", index),
            capture_monotonic_ns=100 + index, sim_time_s=float(index),
            depth_m=depth, valid_depth=valid, no_return=empty_no_return,
            no_return_range_m=8.)
        assert original.submit(source).accepted
        assert original.wait_idle(5.)
    recording_dir = original.run_dir
    original_result = original.close()
    assert original_result["recording_complete"]

    replay = _session(tmp_path / "replay", "pair", monkeypatch=monkeypatch)
    try:
        assert replay_recording(recording_dir, replay) == 3
        assert replay.snapshot().latest_map.revision == 3
        assert replay.snapshot().latest_map.prefix_sha256 == original.snapshot().latest_map.prefix_sha256
    finally:
        result = replay.close()
    assert result["recording_complete"] and result["runtime_complete"]
