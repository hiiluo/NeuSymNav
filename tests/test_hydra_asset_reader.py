from dataclasses import replace
import hashlib
import time

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
from neusymnav.recording.codec import encode
from neusymnav.visualization.hydra_assets import AsyncHydraAssetReader, HydraAssetReader


def graph_for(obs):
    source = dict(episode_id=obs.key.episode_id, sensor_id=obs.key.sensor_id,
        frame_index=obs.key.frame_index, capture_monotonic_ns=obs.capture_monotonic_ns,
        clock_domain=obs.clock_domain)
    return HydraGraphAdapter.project({
        'schema_version': 1, 'graph_revision': 1, 'input_prefix_sha256': 'a' * 64,
        'layer_counts': {'2': 1},
        'nodes': [{'native_id': 'o1', 'layer_id': 2, 'name': 'chair',
                   'position': [0., 0., 0.], 'parent_native_id': None}],
        'edges': [],
    }, episode_id=obs.key.episode_id, run_id='run', stale=False,
       replay_required=False, failure_reason=None, last_source=source)


def test_hydra_asset_reader_projects_exact_recorded_source_to_bounded_cloud(tmp_path):
    obs = observation(key=__import__('neusymnav.contracts', fromlist=['FrameKey']).FrameKey('episode','rgbd',4),
        clock_domain='clock', capture_monotonic_ns=123, rgb=np.full((2,3,3),[10,20,30],np.uint8))
    recording = tmp_path / 'recording'
    recording.mkdir()
    payload = encode(obs)
    digest = hashlib.sha256(payload).hexdigest()
    (recording / 'frame-000000000004.npz').write_bytes(payload)

    cloud = HydraAssetReader(recording).read(graph_for(obs))

    assert cloud.last_source == obs.key
    assert cloud.last_capture_ns == 123 and cloud.clock_domain == 'clock'
    assert cloud.sources[0]['asset_sha256'] == digest
    assert np.array_equal(cloud.colors, np.tile([10,20,30], (6,1)))
    assert not cloud.points.flags.writeable and not cloud.colors.flags.writeable


def test_hydra_asset_reader_rejects_wrong_recorded_source_and_keeps_last_good(tmp_path):
    from neusymnav.contracts import FrameKey
    first = observation(key=FrameKey('episode','rgbd',0), clock_domain='clock', capture_monotonic_ns=100)
    second = replace(first, key=FrameKey('episode','rgbd',1), capture_monotonic_ns=200)
    recording = tmp_path / 'recording'; recording.mkdir()
    (recording / 'frame-000000000000.npz').write_bytes(encode(first))
    (recording / 'frame-000000000001.npz').write_bytes(encode(second))
    reader = HydraAssetReader(recording)
    good = reader.read(graph_for(first))
    (recording / 'frame-000000000001.npz').write_bytes(encode(replace(second, clock_domain='other')))

    with pytest.raises(ValueError, match='source|clock'):
        reader.read(graph_for(second))
    assert reader.latest is good


def test_hydra_asset_reader_rejects_corrupt_or_oversized_recording(tmp_path, monkeypatch):
    from neusymnav.visualization import hydra_assets
    from neusymnav.contracts import FrameKey
    obs = observation(key=FrameKey('episode','rgbd',2), clock_domain='clock', capture_monotonic_ns=123)
    recording = tmp_path / 'recording'; recording.mkdir()
    path = recording / 'frame-000000000002.npz'
    path.write_bytes(encode(obs))
    monkeypatch.setattr(hydra_assets, 'MAX_PAYLOAD_BYTES', 1)
    with pytest.raises(ValueError, match='bound'):
        HydraAssetReader(recording).read(graph_for(obs))
    monkeypatch.setattr(hydra_assets, 'MAX_PAYLOAD_BYTES', 64 * 1024**2)
    path.write_bytes(b'not-an-npz')
    with pytest.raises(ValueError, match='exact Hydra RGB-D source'):
        HydraAssetReader(recording).read(graph_for(obs))


def test_hydra_asset_reader_indexes_each_recording_payload_once(tmp_path, monkeypatch):
    from neusymnav.contracts import FrameKey
    from neusymnav.visualization import hydra_assets
    recording=tmp_path/'recording';recording.mkdir()
    frames=[]
    for index in range(8):
        obs=observation(key=FrameKey('episode','rgbd',index),clock_domain='clock',
            capture_monotonic_ns=100+index,rgb=np.full((2,3,3),index,np.uint8))
        frames.append(obs)
        (recording/f'frame-{index:012d}.npz').write_bytes(encode(obs))
    original=hydra_assets.decode;calls=[]
    def counted(payload):
        calls.append(payload)
        return original(payload)
    monkeypatch.setattr(hydra_assets,'decode',counted)
    reader=HydraAssetReader(recording)
    reader.read(graph_for(frames[0]))
    before=len(calls)
    reader.read(graph_for(frames[1]))
    # The initial bounded scan decodes candidates once; each selected source is
    # re-read and verified, but older candidates are never decoded again.
    assert before==9 and len(calls)==10


def test_async_hydra_asset_reader_has_one_pending_snapshot_and_closes(tmp_path):
    reader = AsyncHydraAssetReader(tmp_path / 'recording')
    try:
        envelope = type('Envelope', (), {'sources': type('Sources', (), {'hydra_graph':
            graph_for(observation())})()})()
        for _ in range(50):
            reader.offer(envelope)
            assert reader.pending.qsize() <= 1
    finally:
        result = reader.close()
    assert result['clean_shutdown'] and result['pending'] <= 1


def test_async_hydra_asset_reader_flushes_final_graph_source(tmp_path):
    from neusymnav.contracts import FrameKey
    obs=observation(key=FrameKey('episode','rgbd',4),clock_domain='clock',capture_monotonic_ns=123)
    recording=tmp_path/'recording';recording.mkdir()
    (recording/'frame-000000000000.npz').write_bytes(encode(obs))
    reader=AsyncHydraAssetReader(recording)
    envelope=type('Envelope',(),{'sources':type('Sources',(),{'hydra_graph':graph_for(obs)})()})()
    try:
        assert reader.flush(envelope,2.)
        assert reader.latest.last_source==obs.key
        assert reader.report()['completed_source']==envelope.sources.hydra_graph.last_source
    finally:
        result=reader.close()
    assert result['clean_shutdown'] and result['pending']==0
