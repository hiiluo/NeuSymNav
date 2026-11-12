"""The ObjectNav read seam uses one accepted canonical Hydra generation."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from contract_helpers import observation
from test_hydra_runtime import _calibration
from test_hydra_session import frame, worker
from neusymnav.backends.hydra.labels import HydraLabelRasterizer
from neusymnav.backends.hydra.runtime import HydraGraphRuntime
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.backends.hydra.worker import _graph_summary
from neusymnav.contracts import Taxonomy
from neusymnav.contracts.hydra_evidence import HydraObjectKey


def test_worker_exports_numeric_semantic_label_separate_from_display_name():
    node = SimpleNamespace(id='O(0)', attributes=SimpleNamespace(
        name='misleading chair display', position=np.array([1., 2., 3.]),
        semantic_label=np.uint32(3)), get_parent=lambda: None)
    graph = SimpleNamespace(layers=[SimpleNamespace(id=2, nodes=[node], edges=[])],
                            interlayer_edges=[])
    summary = _graph_summary(graph, graph_revision=1, input_prefix_sha256='a'*64)
    assert summary['nodes'][0]['semantic_label'] == 3
    assert summary['nodes'][0]['name'] == 'misleading chair display'


def test_session_semantics_come_from_last_accepted_not_later_offered_frame(tmp_path):
    first = frame()
    body = '''
for line in sys.stdin:
 msg=json.loads(line)
 if msg["type"] == "close": break
 print(json.dumps({"type":"result","request_id":msg["request_id"],
                   "accepted":msg["frame_index"] == 0}),flush=True)
'''
    session = HydraSession('ep', command=worker(tmp_path, body),
                           journal_path=tmp_path/'journal.jsonl')
    try:
        assert session.offer(first).status == 'queued'
        assert session.wait_for_revision(1, 2.)
        snapshot = session.snapshot()
        assert snapshot.last_semantics == {
            'vocabulary_id': first.vocabulary_id,
            'labelspace_id': first.labelspace_id,
            'labelspace_hash': first.labelspace_hash,
            'source_geometry_hash': first.source_geometry_hash,
        }
        session.offer(replace(frame(1), vocabulary_id='different:vocabulary'))
        assert snapshot.last_semantics['vocabulary_id'] == first.vocabulary_id
    finally:
        session.close(2.)


def test_runtime_query_uses_one_snapshot_and_never_reads_ui_or_native():
    obs = observation()
    taxonomy = Taxonomy('fixture:query:v1', ('chair', 'table'), {}, 'test query')
    labels = HydraLabelRasterizer(taxonomy)
    calibration = _calibration(obs)
    summary = dict(schema_version=1, graph_revision=4, input_prefix_sha256='a'*64,
        layer_counts={'2': 1}, edges=[], nodes=[dict(native_id='O(0)', layer_id=2,
            name='chair display', semantic_label=3, position=[1., 2., .5],
            parent_native_id=None)])
    snapshot = SimpleNamespace(graph_summary=summary, last_source_key=obs.key,
        last_capture_monotonic_ns=obs.capture_monotonic_ns,
        last_clock_domain=obs.clock_domain, stale=False, replay_required=False,
        failure_reason=None, last_semantics=dict(vocabulary_id=taxonomy.vocabulary_id,
            labelspace_id=labels.LABELSPACE_ID, labelspace_hash=labels.labelspace_hash,
            source_geometry_hash=obs.geometry_hash),
        last_transform=dict(calibration_id=calibration.calibration_id,
            calibration_hash=calibration.calibration_hash,
            coordinate_convention='canonical_z_up_v1'))
    for name in ('config_sha256', 'source_sha256', 'build_sha256', 'graph_asset_path',
                 'graph_asset_sha256', 'graph_asset_bytes', 'node_counts', 'edge_count'):
        setattr(snapshot, name, None)

    class Session:
        episode_id = obs.key.episode_id
        run_id = 'run-query'
        calls = 0
        def snapshot(self):
            self.calls += 1
            assert self.calls == 1, 'query must not join two graph generations'
            return snapshot

    session = Session()
    runtime = HydraGraphRuntime(session, calibration=calibration, taxonomy=taxonomy,
                               detector_profile_id='detector:test')
    query = runtime.scene_graph_query()
    candidates = query.objects('table')
    assert session.calls == 1
    assert len(candidates) == 1
    assert candidates[0].category == 'table'
    assert candidates[0].graph_revision == 4
    assert candidates[0].navigability == 'unvalidated'
    object_key = HydraObjectKey(obs.key.episode_id, session.run_id, 'O(0)', 4)
    assert query.evidence(object_key).status == 'not_recorded'
    assert query.evidence(HydraObjectKey(obs.key.episode_id, session.run_id, 'O(0)', 3)).status == 'unavailable'


def test_coordinator_exposes_query_without_holding_pipeline_lock():
    import threading
    from neusymnav.runtime.coordinator import Pipeline
    pipeline = object.__new__(Pipeline)
    pipeline._lock = threading.Lock()
    expected = object()
    def read():
        assert pipeline._lock.acquire(blocking=False)
        pipeline._lock.release()
        return expected
    pipeline._hydra_runtime = SimpleNamespace(scene_graph_query=read)
    assert pipeline.scene_graph_query() is expected
    pipeline._hydra_runtime = None
    assert pipeline.scene_graph_query() is None


def test_session_snapshot_detaches_mutable_graph_and_transform(tmp_path):
    session = HydraSession('ep',command=worker(tmp_path,''),journal_path=tmp_path/'j.jsonl')
    try:
        with session._condition:
            session._graph_summary = {'nodes':[{'semantic_label':3}]}
            session._last_transform = {'K':[[1.,0.,0.]]}
        first = session.snapshot()
        first.graph_summary['nodes'][0]['semantic_label'] = 99
        first.last_transform['K'][0][0] = 99.
        second = session.snapshot()
        assert second.graph_summary['nodes'][0]['semantic_label'] == 3
        assert second.last_transform['K'][0][0] == 1.
    finally:session.close(2.)


def test_rejected_native_step_reports_last_accepted_source():
    from neusymnav.backends.hydra.worker import _PipelineOwner
    first, second = frame(0), frame(1)
    owner = object.__new__(_PipelineOwner)
    decisions=iter((True,False))
    owner.pipeline=SimpleNamespace(step=lambda *args: next(decisions),
                                   graph=SimpleNamespace(layers=[],interlayer_edges=[]))
    owner.labelspace_id=first.labelspace_id;owner.labelspace_hash=first.labelspace_hash
    owner.sensor_id=first.source_key.sensor_id;owner.calibration_hash=first.calibration_hash
    owner.capture_clock_domain=first.clock_domain;owner.last_source=None
    owner.graph_revision=0;owner.input_prefix=None
    accepted=owner.process_frame(first)
    rejected=owner.process_frame(second)
    assert rejected['accepted'] is False
    assert rejected['last_source'] == accepted['last_source']
    assert rejected['input_prefix_sha256'] == accepted['input_prefix_sha256']
    assert rejected['graph_revision'] == 1
