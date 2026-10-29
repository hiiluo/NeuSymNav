"""P02 losslessness, completeness, and historical-clock regression cases."""
from dataclasses import replace
import json
import threading
import time

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import FrameKey
from neusymnav.recording.writer import ReplayWriter
from neusymnav.recording.replay import ReplayReader


def frame(index=0, sensor='rgbd', **changes):
    return observation(key=FrameKey('episode', sensor, index),
                       capture_monotonic_ns=100 + index * 50, **changes)


def test_lossless_source_bytes_and_replay_clock(tmp_path):
    depth = np.array([[1., np.nan, 0.], [2., 3., np.inf]], dtype=np.float32)
    source = frame(depth_m=depth, valid_depth=np.isfinite(depth) & (depth > 0),
                   rgb=np.arange(18, dtype=np.uint8).reshape(2, 3, 3),
                   no_return=np.array([[False, True, False], [False, False, False]]),
                   no_return_range_m=7.)
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(source)
    assert writer.close()['complete']
    reader = ReplayReader(tmp_path / 'run', start_ns=9000)
    raw = list(reader.source_frames())[0]
    replayed = list(reader.frames())[0]
    for name in ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera', 'no_return'):
        assert getattr(raw, name).tobytes() == getattr(source, name).tobytes()
        assert getattr(replayed, name).tobytes() == getattr(source, name).tobytes()
    assert raw.to_json() == source.to_json()
    assert replayed.key == source.key
    assert replayed.clock_domain.startswith('replay:')
    assert replayed.clock_domain != source.clock_domain
    assert replayed.capture_monotonic_ns == 9000
    assert reader.manifest['source_provenance']['pose_source'] == 'simulator_ground_truth'
    assert reader.manifest['records'][0]['source_clock_domain'] == 'host:boot1'
    assert reader.manifest['records'][0]['source_capture_monotonic_ns'] == 100


def test_replay_retains_source_intervals_and_distinct_sessions(tmp_path):
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame())
    assert writer.append(frame(1))
    assert writer.close()['complete']
    first = ReplayReader(tmp_path / 'run', start_ns=1000)
    second = ReplayReader(tmp_path / 'run', start_ns=1000)
    assert [x.capture_monotonic_ns for x in first.frames()] == [1000, 1050]
    assert first.clock_domain != second.clock_domain


@pytest.mark.parametrize('damage', ['corrupt', 'missing'])
def test_reader_fails_before_yielding_damaged_record(tmp_path, damage):
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame())
    writer.close()
    reader = ReplayReader(tmp_path / 'run')
    path = reader.path / reader.manifest['records'][0]['file']
    if damage == 'corrupt':
        path.write_bytes(path.read_bytes() + b'!')
    else:
        path.unlink()
    with pytest.raises(ValueError, match='checksum|payload'):
        next(reader.frames())
    assert not reader.certificate['complete']


def test_missing_index_produces_incomplete_certificate(tmp_path):
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame(0))
    assert writer.append(frame(2))
    certificate = writer.close()
    assert not certificate['complete']
    assert certificate['source_gap_count'] == 1
    with pytest.raises(ValueError, match='incomplete'):
        list(ReplayReader(tmp_path / 'run').frames())
    assert len(list(ReplayReader(tmp_path / 'run', allow_incomplete=True).frames())) == 2


def test_episode_restart_uses_new_directory_and_key(tmp_path):
    writer = ReplayWriter(tmp_path / 'a')
    assert writer.append(frame())
    with pytest.raises(ValueError, match='episode'):
        writer.append(replace(frame(), key=FrameKey('next', 'rgbd', 0)))
    assert not writer.close()['complete']
    other = ReplayWriter(tmp_path / 'b')
    assert other.append(replace(frame(), key=FrameKey('next', 'rgbd', 0)))
    assert other.close()['complete']
    assert list(ReplayReader(tmp_path / 'b').source_frames())[0].key.episode_id == 'next'
    with pytest.raises(FileExistsError):
        ReplayWriter(tmp_path / 'b')


def test_secondary_sensor_sequence_is_independent(tmp_path):
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame())
    assert writer.append(frame(sensor='nav', modality='depth_only'))
    assert writer.append(frame(1))
    assert writer.close()['complete']
    assert [x.key.sensor_id for x in ReplayReader(tmp_path / 'run').frames()] == ['rgbd', 'nav', 'rgbd']


def test_bounded_queue_rejects_without_waiting_for_disk(tmp_path, monkeypatch):
    import neusymnav.recording.writer as module
    entered, release = threading.Event(), threading.Event()
    original = module._write_atomic
    def slow_write(path, payload):
        if path.name.startswith('frame-'):
            entered.set()
            assert release.wait(5)
        return original(path, payload)
    monkeypatch.setattr(module, '_write_atomic', slow_write)
    writer = ReplayWriter(tmp_path / 'run', queue_capacity=1)
    try:
        assert writer.append(frame())
        assert entered.wait(2)
        assert writer.append(frame(1))
        start = time.monotonic()
        assert not writer.append(frame(2))
        assert time.monotonic() - start < .1
    finally:
        release.set()
    certificate = writer.close()
    assert not certificate['complete']
    assert certificate['rejection_counts']['queue_full'] == 1
    assert certificate['written_count'] == 2


def test_disk_quota_and_write_errors_never_claim_complete(tmp_path, monkeypatch):
    quota = ReplayWriter(tmp_path / 'quota', max_bytes=9000)
    assert quota.append(frame(rgb=np.zeros((100, 100, 3), np.uint8),
                              depth_m=np.ones((100, 100), np.float32),
                              valid_depth=np.ones((100, 100), bool))) is False
    assert not quota.close()['complete']
    import neusymnav.recording.writer as module
    original = module._write_atomic
    def failed_write(path, data):
        if path.name.startswith('frame-'):
            raise OSError('disk failed')
        return original(path, data)
    monkeypatch.setattr(module, '_write_atomic', failed_write)
    writer = ReplayWriter(tmp_path / 'failed')
    assert writer.append(frame())
    certificate = writer.close()
    assert not certificate['complete']
    assert certificate['written_count'] == 0
    assert 'disk failed' in certificate['error']


def test_close_detects_deleted_accepted_payload(tmp_path):
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame())
    # close's verification must protect against corruption after a successful write.
    writer._queue.join()
    next((tmp_path / 'run').glob('frame-*.json')).unlink()
    assert not writer.close()['complete']


def test_metadata_tampering_rejected(tmp_path):
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame())
    writer.close()
    path = tmp_path / 'run' / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['records'][0]['source_capture_monotonic_ns'] += 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='manifest|checksum'):
        list(ReplayReader(tmp_path / 'run').frames())


def test_escaped_metadata_and_atomic_manifest_temporary_respect_cap(tmp_path):
    # Regression: escaped source identity appears in both frame and manifest.
    source = frame()
    source = replace(source, key=FrameKey('\x00' * 500, '\x01' * 500, 0),
                     calibration_id='\x02' * 500, clock_domain='\x03' * 500)
    cap = 120_000
    writer = ReplayWriter(tmp_path / 'run', max_bytes=cap)
    assert writer.append(source)
    assert writer.close()['complete']
    assert sum(x.stat().st_size for x in writer.path.iterdir()) <= cap
    assert list(ReplayReader(writer.path).source_frames())[0].key == source.key


def test_reader_rejects_forged_completed_certificate_and_gap(tmp_path):
    from neusymnav.recording.replay import _manifest_bytes
    writer = ReplayWriter(tmp_path / 'run')
    assert writer.append(frame(1))
    assert not writer.close()['complete']
    path = writer.path / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest.pop('manifest_sha256')
    manifest['certificate']['complete'] = True
    path.write_bytes(_manifest_bytes(manifest))
    with pytest.raises(ValueError, match='certificate|gap'):
        list(ReplayReader(writer.path).frames())


def test_empty_recording_and_bounded_frame_count_are_incomplete(tmp_path):
    empty = ReplayWriter(tmp_path / 'empty')
    assert not empty.close()['complete']
    capped = ReplayWriter(tmp_path / 'cap', max_frames=1)
    assert capped.append(frame())
    assert not capped.append(frame(1))
    cert = capped.close()
    assert cert['written_count'] == 1
    assert cert['missing_count'] == 1
    assert cert['rejection_counts']['frame_quota'] == 1


def test_pending_byte_quota_rejects_before_retaining_payload(tmp_path):
    writer = ReplayWriter(tmp_path / 'run', max_pending_bytes=1)
    assert not writer.append(frame())
    assert writer.close()['rejection_counts']['pending_byte_quota'] == 1


def test_manifest_write_failure_has_no_completed_artifact(tmp_path, monkeypatch):
    import neusymnav.recording.writer as module
    writer = ReplayWriter(tmp_path / 'run')
    original = module._write_atomic
    def fail_manifest(path, payload):
        if path.name == 'manifest.json':
            raise OSError('certificate volume unavailable')
        return original(path, payload)
    monkeypatch.setattr(module, '_write_atomic', fail_manifest)
    assert writer.append(frame())
    cert = writer.close()
    assert not cert['complete']
    assert 'certificate write failed' in cert['error']
    assert json.loads((writer.path / 'manifest.json').read_text())['certificate']['complete'] is False
