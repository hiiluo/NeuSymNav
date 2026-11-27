from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np

from contract_helpers import observation
from test_rg_evidence import inputs
from neusymnav.contracts.hydra_evidence import HydraObjectKey
from neusymnav.contracts.observations import Detection, DetectionBatch
from neusymnav.reasoninggraph.producer import EvidenceProducer


def test_live_producer_uses_exact_accepted_batch_and_revokes_evidence(tmp_path):
    _, node, token = inputs()
    obs = observation()
    token = replace(token, native=replace(token.native, episode_id=obs.key.episode_id),
                    source=obs.key, source_geometry_hash=obs.geometry_hash,
                    capture_monotonic_ns=obs.capture_monotonic_ns,
                    clock_domain=obs.clock_domain, calibration_id=obs.calibration_id,
                    pose_version=obs.pose_version)
    node = replace(node, ref=replace(node.ref, token=token.native))
    current = [None]
    mask = np.ones(obs.depth_m.shape, dtype=np.bool_)
    detection = Detection('from-detector', 'chair', 'chair', .9, mask)
    batch = DetectionBatch.from_observation(obs, (detection,), vocabulary_id=token.vocabulary_id)

    class Projector:
        def project(self, observation, supplied):
            assert observation.key == obs.key
            assert supplied.detections[0].detection_id == 'from-detector'
            return (SimpleNamespace(detection_id='from-detector', points_world=np.array([[0,0,0],[1,1,1]])),)

    producer = EvidenceProducer(tmp_path, 'run', accepted=lambda: current[0],
        native_is_current=lambda native: current[0] is not None and current[0][0].native == native,
        projector=Projector())
    try:
        assert producer.stage(obs, batch)
        assert not producer.update()
        assert producer.index(token.native) is None
        current[0] = (token, (node,))
        assert producer.update()
        key = HydraObjectKey(token.native.episode_id, token.native.run_id, node.ref.native_id, 7)
        page = producer.index(token.native).resolve(key)
        assert page.status == 'available' and not page.native_confirmed
        assert page.refs[0].detection_id == 'from-detector'
        assert (producer.root / page.refs[0].asset_key).is_file()
        manifests = list(producer.root.glob('*/manifest.json'))
        assert len(manifests) == 1
        assert json.loads(manifests[0].read_text())['native']['input_prefix_sha256'] == token.native.input_prefix_sha256
        assert not producer.update()
        current[0] = None
        assert producer.index(token.native) is None
    finally:
        assert producer.close(1)['clean_shutdown']


def test_producer_never_uses_a_source_from_different_clock(tmp_path):
    _, node, token = inputs()
    obs = observation()
    token = replace(token, native=replace(token.native, episode_id=obs.key.episode_id),
                    source=obs.key, source_geometry_hash=obs.geometry_hash)
    batch = DetectionBatch.from_observation(obs, (), vocabulary_id=token.vocabulary_id)
    producer = EvidenceProducer(tmp_path, 'mismatch', accepted=lambda: (token, (node,)),
                                native_is_current=lambda native: True)
    try:
        assert producer.stage(obs, batch)
        assert not producer.update()
        assert producer.index(token.native) is None
        assert list(producer.root.iterdir()) == []
    finally:
        producer.close(1)


def test_hydra_runtime_stages_only_admitted_frames():
    from test_hydra_runtime import _calibration
    from neusymnav.backends.hydra.runtime import HydraGraphRuntime
    from neusymnav.contracts import Taxonomy

    obs = observation()
    taxonomy = Taxonomy('fixture:v1', ('chair',), {}, 'producer fixture')
    batch = DetectionBatch.from_observation(obs, (), vocabulary_id=taxonomy.vocabulary_id)
    statuses = iter(('queued', 'rejected', 'replaced'))
    calls = []
    runtime = HydraGraphRuntime(SimpleNamespace(offer=lambda _: SimpleNamespace(status=next(statuses))),
        calibration=_calibration(obs), taxonomy=taxonomy, detector_profile_id='foo')
    runtime._reasoninggraph = SimpleNamespace(stage=lambda source, value: calls.append((source.key, value)))
    assert runtime.offer(obs, batch).status == 'queued'
    assert runtime.offer(obs, batch).status == 'rejected'
    assert runtime.offer(obs, batch).status == 'replaced'
    assert calls == [(obs.key, batch), (obs.key, batch)]


def test_unexpected_producer_failure_is_reported_on_close(tmp_path):
    from threading import Event

    attempted = Event()

    def broken():
        attempted.set()
        raise ArithmeticError('numeric fixture failure')

    obs = observation()
    batch = DetectionBatch.from_observation(obs, (), vocabulary_id='fixture:v1')
    producer = EvidenceProducer(tmp_path, 'failed-lane', accepted=broken, native_is_current=lambda _: True)
    producer.stage(obs, batch)
    producer.start()
    assert attempted.wait(1.)
    report = producer.close(1.)
    assert not report['clean_shutdown']
    assert report['errors'] == 1
    assert report['terminal_error'] == 'ArithmeticError'


def test_stalled_evidence_worker_does_not_block_staging_or_publish_on_close(tmp_path):
    from threading import Event

    entered, release = Event(), Event()

    def stalled():
        entered.set()
        release.wait(3.)
        return None

    obs = observation()
    batch = DetectionBatch.from_observation(obs, (), vocabulary_id='fixture:v1')
    producer = EvidenceProducer(tmp_path, 'stalled-lane', accepted=stalled,
                                native_is_current=lambda _: True)
    producer.stage(obs, batch)
    producer.start()
    try:
        assert entered.wait(1.)
        assert producer.stage(obs, batch)
        assert not release.is_set()
        report = producer.close(.01)
        assert report['worker_pending'] and report['pending'] == 0
        assert report['published'] == 0
        assert not producer.stage(obs, batch)
    finally:
        release.set()
        assert producer.close(1.)['clean_shutdown']
    assert not list(producer.root.iterdir())


def test_startup_failure_releases_only_evidence_reservation(tmp_path, monkeypatch):
    from test_hydra_runtime import _calibration
    from neusymnav.backends.hydra.runtime import HydraGraphRuntime
    from neusymnav.contracts import Taxonomy
    from neusymnav.runtime.quota import RunQuota

    obs = observation()
    quota = RunQuota(tmp_path)
    runtime = HydraGraphRuntime(SimpleNamespace(run_id='failure', stats={'accepted': 1},
        has_detail_token=lambda _: True), calibration=_calibration(obs),
        taxonomy=Taxonomy('fixture:v1', ('chair',), {}, 'producer fixture'),
        detector_profile_id='foo', reasoninggraph_enabled=True)

    def broken_start(_):
        raise RuntimeError('injected producer startup failure')

    monkeypatch.setattr(EvidenceProducer, 'start', broken_start)
    runtime.start_reasoninggraph(tmp_path, quota)
    assert runtime.diagnostics()['accepted'] == 1
    assert runtime.diagnostics()['reasoninggraph']['startup_error'] == 'injected producer startup failure'
    assert not quota.reservations
