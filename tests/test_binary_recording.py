"""Versioned binary replay, bounded decoding, and actual durable-byte quotas."""
from dataclasses import replace
import io
import json
from pathlib import Path
import threading
import zipfile

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import FrameKey
from neusymnav.recording import ReplayReader, ReplayWriter
from neusymnav.recording.replay import _digest, _manifest_bytes


def source(index=0, **changes):
    return observation(key=FrameKey('episode', 'rgbd', index),
                       capture_monotonic_ns=100 + index, **changes)


def rewrite_payload(path, edit):
    manifest_path = path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.pop('manifest_sha256')
    record = manifest['records'][0]
    target = path / record['file']
    target.write_bytes(edit(target.read_bytes()))
    record['size_bytes'] = target.stat().st_size
    record['sha256'] = _digest(target.read_bytes())
    manifest_path.write_bytes(_manifest_bytes(manifest))


def zip_edit(payload, name, value):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as old, zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as new:
        for info in old.infolist():
            new.writestr(info.filename, value if info.filename == name else old.read(info))
    return output.getvalue()


def test_binary_roundtrip_preserves_all_sample_bytes_metadata_and_provenance(tmp_path):
    depth = np.array([0x7fc00001, 0x7fa12345, 0xffc00002, 0x3f800000, 0, 0x7f800000], np.uint32).view(np.float32).reshape(2, 3)
    obs = source(depth_m=depth, valid_depth=np.array([[False, False, False], [True, False, False]]),
                 no_return=np.array([[True, False, False], [False, False, False]]),
                 far_plane=np.array([[False, True, False], [False, False, False]]),
                 no_return_range_m=8., far_plane_range_m=10., calibration_id='calibration:測定:v1')
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2', source_provenance={'sensor': 'actual-K:v2'})
    assert writer.append(obs)
    cert = writer.close()
    assert cert['complete']
    reader = ReplayReader(writer.path)
    record = reader.manifest['records'][0]
    assert reader.manifest['format_version'] == 2
    assert record['file'].endswith('.npz')
    with zipfile.ZipFile(writer.path / record['file']) as zf:
        assert 'metadata.json' in zf.namelist()
        assert 'depth_m.npy' in zf.namelist()
    result, = reader.source_frames()
    assert result.to_json() == obs.to_json()
    assert result.geometry_hash == obs.geometry_hash
    for name in ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera', 'no_return', 'far_plane'):
        assert getattr(result, name).dtype == getattr(obs, name).dtype
        assert getattr(result, name).tobytes() == getattr(obs, name).tobytes()
    assert reader.manifest['source_provenance']['sensor'] == 'actual-K:v2'
    assert cert['pending_bytes'] == 0
    assert cert['durable_bytes'] == sum(p.stat().st_size for p in writer.path.iterdir())
    assert cert['reserved_bytes'] == cert['durable_bytes']


def test_legacy_reader_and_writer_default_remain_compatible(tmp_path):
    fixture = Path(__file__).parent / 'fixtures/launcher/recording'
    assert len(list(ReplayReader(fixture).source_frames())) == 1
    writer = ReplayWriter(tmp_path / 'legacy')
    assert writer.append(source())
    assert writer.close()['complete']
    assert list(writer.path.glob('frame-*.json'))
    assert list(ReplayReader(writer.path).source_frames())[0].to_json() == source().to_json()


@pytest.mark.parametrize('name,value', [
    ('depth_m.npy', b'not-npy'),
    ('depth_m.npy', b'\x93NUMPY\x01\x00' + (70).to_bytes(2, 'little') + b"{'descr': '<f4', 'fortran_order': False, 'shape': (1000000000,)}\n"),
    ('metadata.json', b'{}'),
    ('metadata.json', b'x' * (65536 + 1)),
    ('rgb.npy', b'x' * (64 * 1024**2 + 1)),
], ids=['invalid-npy', 'oversized-shape', 'invalid-metadata', 'oversized-metadata', 'oversized-member'])
def test_binary_reader_rejects_malformed_or_oversized_decoded_members(tmp_path, name, value):
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2')
    assert writer.append(source())
    assert writer.close()['complete']
    rewrite_payload(writer.path, lambda payload: zip_edit(payload, name, value))
    reader = ReplayReader(writer.path)
    with pytest.raises(ValueError, match='payload|bound|metadata|NPY'):
        list(reader.source_frames())
    assert not reader.certificate['complete']


def test_binary_reader_rejects_corruption_with_unchanged_digest(tmp_path):
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2')
    assert writer.append(source())
    assert writer.close()['complete']
    reader = ReplayReader(writer.path)
    target = writer.path / reader.manifest['records'][0]['file']
    target.write_bytes(bytes([target.read_bytes()[0] ^ 1]) + target.read_bytes()[1:])
    with pytest.raises(ValueError, match='checksum'):
        list(reader.source_frames())


def test_compressed_durable_bytes_replace_admission_upper_bound(tmp_path):
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2', max_bytes=240_000, max_pending_bytes=200_000)
    for index in range(30):
        obs = source(index, rgb=np.zeros((96, 96, 3), np.uint8), depth_m=np.ones((96, 96), np.float32), valid_depth=np.ones((96, 96), bool))
        assert writer.append(obs), index
        writer._queue.join()
    cert = writer.close()
    assert cert['complete']
    assert cert['written_count'] == 30
    assert cert['durable_bytes'] < 240_000
    assert cert['durable_bytes'] == sum(p.stat().st_size for p in writer.path.iterdir())


def test_pending_reservation_bounds_concurrent_admission_and_releases_after_failure(tmp_path, monkeypatch):
    import neusymnav.recording.writer as module
    entered, release = threading.Event(), threading.Event()
    real_write = module._write_atomic
    def failure(path, payload):
        if path.name.startswith('frame-'):
            entered.set()
            assert release.wait(5)
            raise OSError('injected recording failure')
        return real_write(path, payload)
    monkeypatch.setattr(module, '_write_atomic', failure)
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2', max_pending_bytes=150_000, max_bytes=160_000)
    obs = source(rgb=np.zeros((96, 96, 3), np.uint8), depth_m=np.ones((96, 96), np.float32), valid_depth=np.ones((96, 96), bool))
    try:
        assert writer.append(obs)
        assert entered.wait(2)
        assert not writer.append(replace(obs, key=FrameKey('episode', 'rgbd', 1), capture_monotonic_ns=101))
        assert writer._reserved_bytes <= 160_000
    finally:
        release.set()
    cert = writer.close()
    assert not cert['complete']
    assert cert['pending_bytes'] == 0
    assert 'injected recording failure' in cert['error']
    assert not list(writer.path.glob('*.tmp'))
    assert cert['durable_bytes'] == sum(p.stat().st_size for p in writer.path.iterdir())


@pytest.mark.parametrize('stage', ['frame', 'manifest'])
def test_failure_after_atomic_replace_never_leaves_complete_certificate(tmp_path, monkeypatch, stage):
    import neusymnav.recording.writer as module
    real_write = module._write_atomic
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2')
    def fail_after_replace(path, payload):
        real_write(path, payload)
        if (stage == 'frame' and path.name.startswith('frame-')) or (stage == 'manifest' and path.name == 'manifest.json'):
            raise OSError('directory fsync failed after rename')
    monkeypatch.setattr(module, '_write_atomic', fail_after_replace)
    assert writer.append(source())
    cert = writer.close()
    assert not cert['complete']
    assert cert['pending_bytes'] == 0
    assert cert['durable_bytes'] == sum(p.stat().st_size for p in writer.path.iterdir())
    if (writer.path / 'manifest.json').exists():
        assert not json.loads((writer.path / 'manifest.json').read_text())['certificate']['complete']
    assert not list(writer.path.glob('*.tmp'))


def test_admission_reservation_bounds_escaped_manifest_and_atomic_peak(tmp_path, monkeypatch):
    import neusymnav.recording.writer as module
    real_write = module._write_atomic
    peak = []
    cap = 120_000
    def track_peak(path, payload):
        peak.append(sum(p.stat().st_size for p in path.parent.iterdir()) + len(payload))
        return real_write(path, payload)
    monkeypatch.setattr(module, '_write_atomic', track_peak)
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2', max_bytes=cap)
    obs = replace(source(), key=FrameKey('\x00' * 500, '\x01' * 500, 0), calibration_id='\x02' * 500, clock_domain='\x03' * 500)
    for index in range(20):
        accepted = writer.append(replace(obs, key=FrameKey(obs.key.episode_id, obs.key.sensor_id, index), capture_monotonic_ns=100 + index))
        writer._queue.join()
        assert writer._reserved_bytes <= cap
        if not accepted:
            break
    cert = writer.close()
    assert max(peak) <= cap
    assert cert['durable_bytes'] == sum(p.stat().st_size for p in writer.path.iterdir())


def test_binary_reader_rejects_duplicate_members(tmp_path):
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2')
    assert writer.append(source())
    assert writer.close()['complete']
    def duplicate(payload):
        output = io.BytesIO(payload)
        with pytest.warns(UserWarning, match='Duplicate'), zipfile.ZipFile(output, 'a') as archive:
            archive.writestr('metadata.json', b'{}')
        return output.getvalue()
    rewrite_payload(writer.path, duplicate)
    with pytest.raises(ValueError, match='binary|payload|members'):
        list(ReplayReader(writer.path).source_frames())


def test_reader_rejects_oversized_manifest_before_reading(tmp_path):
    path = tmp_path / 'run'
    path.mkdir()
    with (path / 'manifest.json').open('wb') as stream:
        stream.truncate(64 * 1024**2 + 1)
    with pytest.raises(ValueError, match='bound|size'):
        ReplayReader(path)


def test_binary_records_source_gaps_and_independent_sensor_lanes(tmp_path):
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2')
    assert writer.append(source())
    nav = replace(source(), key=FrameKey('episode', 'nav', 0), modality='depth_only')
    assert writer.append(nav)
    assert writer.append(source(2))
    cert = writer.close()
    assert cert['source_gap_count'] == 1
    assert not cert['complete']
    with pytest.raises(ValueError, match='incomplete'):
        list(ReplayReader(writer.path).source_frames())
    assert [o.key.sensor_id for o in ReplayReader(writer.path, allow_incomplete=True).source_frames()] == ['rgbd', 'nav', 'rgbd']


def test_nested_binary_metadata_invalidates_complete_reader_certificate(tmp_path):
    writer = ReplayWriter(tmp_path / 'run', payload_format='npz_v2')
    assert writer.append(source())
    assert writer.close()['complete']
    nested = b'[' * 10000 + b'0' + b']' * 10000
    rewrite_payload(writer.path, lambda payload: zip_edit(payload, 'metadata.json', nested))
    reader = ReplayReader(writer.path)
    with pytest.raises(ValueError, match='payload'):
        list(reader.source_frames())
    assert reader.certificate['complete'] is False
