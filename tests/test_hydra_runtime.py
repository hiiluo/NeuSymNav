import json
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import Detection, DetectionBatch, Taxonomy
from neusymnav.contracts.hydra_graph import HydraCalibration
from neusymnav.backends.hydra.runtime import HydraGraphRuntime
from neusymnav.runtime.configuration import load_config
from test_launcher import config


def _calibration(obs):
    return HydraCalibration(obs.calibration_id, 'camera-cal-v1', obs.key.sensor_id,
        'primary_rgbd', obs.K, np.eye(4), obs.pose_version, 'canonical_z_up_v1',
        'optical_x_right_y_down_z_forward_v1', 'metric_axial_v1', 'simulator:test')


def _hydra_profile(tmp_path, *, workers=None):
    root = Path(__file__).resolve().parents[1] / 'configs' / 'hydra' / 'config'
    dataset = root / 'datasets' / 'neusymnav.yaml'
    labelspace = root / 'label_spaces' / 'neusymnav_label_space.yaml'
    entry = Path(__file__).resolve().parents[1] / 'src' / 'neusymnav' / 'backends' / 'hydra' / 'entry.py'
    child = entry.with_name('child.sh')
    setup = Path(__file__).resolve().parents[1] / '.runtime' / 'hydra_ws' / 'install' / 'setup.bash'
    calibration = dict(calibration_id='hydra-cal-v1', version='calibration-v1', sensor_id='rgbd',
        camera_name='primary_rgbd', K=[[1.,0.,1.],[0.,1.,1.],[0.,0.,1.]],
        body_T_camera=np.eye(4).tolist(), pose_version=0, coordinate_convention='canonical_z_up_v1',
        camera_convention='optical_x_right_y_down_z_forward_v1', depth_convention='metric_axial_v1',
        provenance='test fixture')
    worker = workers or {'python': {'path': sys.executable,
        'sha256': hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()},
        'script': {'path': str(entry), 'sha256': hashlib.sha256(entry.read_bytes()).hexdigest()},
        'setup_script': {'path': str(setup), 'sha256': hashlib.sha256(setup.read_bytes()).hexdigest()}}
    path = config(tmp_path, scene_graph={'backend': 'hydra', 'hydra': {
        'config_root': str(root), 'dataset_sha256': hashlib.sha256(dataset.read_bytes()).hexdigest(),
        'labelspace_sha256': hashlib.sha256(labelspace.read_bytes()).hexdigest(),
        'detector_profile_id': 'yoloe:test', 'calibration': calibration}}, workers={'hydra': worker})
    value = json.loads(path.read_text());value['mode'] = 'live';path.write_text(json.dumps(value))
    return path


class _Session:
    def __init__(self):
        self.frames = []
        self.closed = False

    def offer(self, frame):
        self.frames.append(frame)
        return type('Admission', (), {'status': 'queued', 'source_key': frame.source_key})()

    def snapshot(self):
        return 'cached-graph-snapshot'

    def close(self, timeout_s):
        self.closed = True
        return {'complete': True}


def test_runtime_rasterizes_existing_detector_output_then_nonblocking_offers_frame():
    obs = observation()
    taxonomy = Taxonomy('taxonomy:v1', ('chair',), {}, 'test taxonomy')
    detection = Detection('chair-1', 'chair', 'chair', .9, np.array([[1, 0, 0], [0, 1, 0]], bool))
    batch = DetectionBatch.from_observation(obs, (detection,), vocabulary_id=taxonomy.vocabulary_id)
    session = _Session()
    runtime = HydraGraphRuntime(session, calibration=_calibration(obs), taxonomy=taxonomy,
        detector_profile_id='yoloe:test')

    admission = runtime.offer(obs, batch)

    assert admission.status == 'queued'
    assert len(session.frames) == 1
    np.testing.assert_array_equal(session.frames[0].labels, [[2, 0, 0], [0, 2, 0]])
    assert runtime.snapshot() == 'cached-graph-snapshot'


def test_hydra_backend_configuration_is_explicit_and_excludes_legacy_room_workers(tmp_path):
    value = load_config(_hydra_profile(tmp_path))
    assert value.data['scene_graph']['backend'] == 'hydra'

    data = json.loads(value.path.read_text())
    data['workers'] = {'room_pipeline': {'source_root': '/unused', 'm23_binary': {}, 'm4_binary': {}}}
    value.path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Hydra.*legacy|legacy.*Hydra'):
        load_config(value.path)


@pytest.mark.parametrize('backend', ['automatic', 'm5', None])
def test_scene_graph_backend_rejects_undefined_fallbacks(tmp_path, backend):
    path = config(tmp_path, scene_graph={'backend': backend})
    with pytest.raises(ValueError, match='scene_graph.backend'):
        load_config(path)


def test_hydra_pipeline_never_constructs_legacy_owner_and_failure_is_graph_local(tmp_path):
    from neusymnav.runtime import Pipeline
    from neusymnav.contracts import DetectionBatch, FrameKey
    import time

    domain = 'host_monotonic:hydra-runtime-test'
    now = 10_000_000_000
    obs = observation(key=FrameKey('episode', 'rgbd', 0), capture_monotonic_ns=now,
        clock_domain=domain)

    class Detector:
        def infer(self, value):
            return DetectionBatch.from_observation(value, (), vocabulary_id='taxonomy:v1')
        def close(self): pass

    class Runtime:
        def offer(self, value, batch): raise RuntimeError('native worker crashed')
        def snapshot(self): return {'stale': True, 'failure_reason': 'native worker crashed'}
        def close(self, timeout_s): return {'clean_shutdown': False}

    def forbidden(): raise AssertionError('legacy owner must not start in Hydra profile')
    pipeline = Pipeline(tmp_path, episode_id='episode', primary_sensor_id='rgbd',
        clock_domain=domain, floor_id='floor', owner_factory=forbidden,
        detector_factory=Detector, now_ns=lambda: now, scene_graph_backend='hydra',
        hydra_runtime_factory=Runtime)
    report = None
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not pipeline.telemetry()['ready']:
            time.sleep(.005)
        pipeline.submit(obs)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and pipeline.telemetry()['committed'] == 0:
            time.sleep(.005)
        telemetry = pipeline.telemetry()
        assert telemetry['health']['failed'] == {}
        assert telemetry['detector_calls'] == 1, {k:telemetry[k] for k in ('health','semantic_sampling','scheduler','hydra','missing','offered','durable_accepted','committed')}
        assert telemetry['hydra']['failure'] == 'native worker crashed'
    finally:
        report=pipeline.close(2.)
    assert report['cleanup_pending']['hydra']['clean_shutdown'] is False


def test_hydra_native_export_close_result_is_retained_in_runtime_metrics(tmp_path):
    from neusymnav.runtime import Pipeline

    domain='host_monotonic:hydra-export-metrics-test';now=10_000_000_000
    export=dict(complete=True,manifest_path=str(tmp_path/'hydra-export-manifest.json'),
        manifest_sha256='a'*64,graph_asset_verified=True,failure_reason=None)
    class Detector:
        def close(self):pass
    class Runtime:
        def snapshot(self):return {'failure_reason':None,'stale':False}
        def close(self,timeout_s):return export
    pipeline=Pipeline(tmp_path,episode_id='episode',primary_sensor_id='rgbd',
        clock_domain=domain,floor_id='floor',owner_factory=lambda:pytest.fail('legacy owner started'),
        detector_factory=Detector,now_ns=lambda:now,scene_graph_backend='hydra',
        hydra_runtime_factory=Runtime)

    report=pipeline.close(2.)

    assert report['metrics']['hydra']['native_export']==export


def test_slow_hydra_offer_runs_after_submit_on_graph_thread(tmp_path):
    from neusymnav.runtime import Pipeline
    from neusymnav.contracts import DetectionBatch, FrameKey
    import threading
    import time

    domain = 'host_monotonic:hydra-slow-test';now = 10_000_000_000
    obs = observation(key=FrameKey('episode','rgbd',0),capture_monotonic_ns=now,clock_domain=domain)
    entered = threading.Event();release = threading.Event();worker_threads=[]
    class Detector:
        def infer(self,value):return DetectionBatch.from_observation(value,(),vocabulary_id='taxonomy:v1')
        def close(self):pass
    class Runtime:
        def offer(self,value,batch):
            worker_threads.append(threading.get_ident());entered.set();release.wait(1)
            return type('Admission',(),{'status':'queued'})()
        def snapshot(self):return None
        def close(self,timeout_s):release.set();return {'clean_shutdown':True}
    main_thread=threading.get_ident()
    pipeline=Pipeline(tmp_path,episode_id='episode',primary_sensor_id='rgbd',clock_domain=domain,
        floor_id='floor',owner_factory=lambda:pytest.fail('legacy owner started'),detector_factory=Detector,
        now_ns=lambda:now,scene_graph_backend='hydra',hydra_runtime_factory=Runtime)
    try:
        started=time.perf_counter();pipeline.submit(obs);elapsed=time.perf_counter()-started
        assert elapsed<.1
        assert entered.wait(2)
        assert worker_threads and worker_threads[0]!=main_thread
    finally:
        release.set();pipeline.close(2.)


def test_hydra_close_writes_native_graph_and_exact_selected_input_manifest(tmp_path):
    artifact=tmp_path/'native'/'graph.sparkdsg';artifact.parent.mkdir();artifact.write_bytes(b'native Spark-DSG graph+mesh')
    journal=tmp_path/'journal.jsonl';selected='{"frame":"exact-selected-input"}'
    journal.write_text('\n'.join([
        json.dumps({'run_id':'run-1','event':'started','source':{'frame_index':2},'selected_frame':selected}),
        json.dumps({'run_id':'run-1','event':'accepted','source':{'frame_index':2},'accepted':True,'graph_revision':1,'input_prefix_sha256':'c'*64}),
        json.dumps({'run_id':'run-1','event':'started','source':{'frame_index':3},'selected_frame':'discarded'}),
        json.dumps({'run_id':'run-1','event':'step_rejected','source':{'frame_index':3},'accepted':False}),
    ])+'\n')
    class ExportSession(_Session):
        run_id='run-1';episode_id='episode-1';journal_path=journal
        def close(self,timeout_s):return {'complete':True,'worker_result':{
            'asset_path':str(artifact),'asset_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
            'asset_bytes':artifact.stat().st_size,'graph_revision':1,'input_prefix_sha256':'c'*64,
            'config_sha256':'d'*64,'source_sha256':'e'*64,'build_sha256':'f'*64}}
    runtime=HydraGraphRuntime(ExportSession(),calibration=_calibration(observation()),
        taxonomy=Taxonomy('taxonomy:v1',('chair',),{},'test taxonomy'),detector_profile_id='yoloe:test')
    result=runtime.close(2.)
    manifest=json.loads(Path(result['manifest_path']).read_text())
    assert result['complete'] is True
    assert manifest['graph_sha256']==hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert manifest['input_prefix_sha256']=='c'*64
    assert [item['source']['frame_index'] for item in manifest['selected_inputs']]==[2]
    assert manifest['selected_inputs'][0]['payload_sha256']==hashlib.sha256(selected.encode()).hexdigest()
    assert manifest['selected_inputs'][0]['payload_bytes']==len(selected.encode())


def test_hydra_close_marks_unverified_native_export_incomplete(tmp_path):
    journal=tmp_path/'journal.jsonl';journal.write_text('')
    class FailedExportSession(_Session):
        run_id='run-failed';episode_id='episode-1';journal_path=journal
        def close(self,timeout_s):return {'complete':True,'worker_result':{
            'asset_path':str(tmp_path/'missing.sparkdsg'),'asset_sha256':'0'*64,
            'asset_bytes':10,'graph_revision':0,'input_prefix_sha256':None}}
    runtime=HydraGraphRuntime(FailedExportSession(),calibration=_calibration(observation()),
        taxonomy=Taxonomy('taxonomy:v1',('chair',),{},'test taxonomy'),detector_profile_id='yoloe:test')
    result=runtime.close(2.)
    manifest=json.loads(Path(result['manifest_path']).read_text())
    assert result['complete'] is False
    assert result['graph_asset_verified'] is False
    assert manifest['complete'] is False
    assert manifest['selected_inputs']==[]


def test_hydra_preflight_probe_sources_child_setup_before_imports(tmp_path):
    import shlex
    from neusymnav.runtime.launcher import _probe_interpreter
    module='neusymnav_probe_setup_only'
    (tmp_path/(module+'.py')).write_text('VALUE=1\n')
    setup=tmp_path/'setup.bash'
    setup.write_text('export PYTHONPATH='+shlex.quote(str(tmp_path))+'\n')
    result=_probe_interpreter(sys.executable,[module],'hydra',setup_script=setup)
    assert result['missing']==[]
    with pytest.raises(ValueError,match='environment missing'):
        _probe_interpreter(sys.executable,[module],'hydra')


def test_hydra_publication_advances_hierarchy_revision_when_nav_source_advances():
    from threading import RLock
    from types import SimpleNamespace
    from neusymnav.contracts import FrameKey,NavSnapshot
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.visualization.publisher import DisplayPublisher

    def nav(revision):
        return NavSnapshot('episode-1',revision,FrameKey('episode-1','downward-depth',revision),
            100+revision,'host:boot1',.1,(0.,0.),np.zeros((1,1),np.int8),
            np.zeros((1,1),bool),np.zeros((1,1),np.float32),'robot:v1',0.,'test-floor','a'*64)

    coordinator=object.__new__(Pipeline)
    coordinator.publisher=DisplayPublisher(clock_domain='host:boot1',now_ns=lambda:200)
    coordinator._lock=RLock();coordinator._hydra_projection=None;coordinator._hydra_failure=None
    coordinator._captured=None;coordinator._processed=None;coordinator._hydra_publication_key=None
    coordinator._hydra_publication_ns=0;coordinator._hydra_display_revision=0;coordinator._latest_nav=nav(0)
    coordinator.now_ns=lambda:200;coordinator.clock_domain='host:boot1';coordinator.episode_id='episode-1'
    coordinator._counts={'missing':0};coordinator.scheduler=SimpleNamespace(counts={'replaced':0})
    coordinator.health=SimpleNamespace(profile='hydra')

    coordinator._publish_hydra(force=True)
    coordinator._latest_nav=nav(1)
    coordinator._publish_hydra(force=True)

    latest=coordinator.publisher.read_latest()
    assert latest.hierarchy.map_revision==1
    assert latest.hierarchy.revision==2


def test_hydra_close_publishes_projection_after_runtime_drains_pending_frames():
    from threading import RLock
    from types import SimpleNamespace
    from neusymnav.backends.hydra.graph_adapter import HydraGraphProjection
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.visualization.publisher import DisplayPublisher

    final_projection=HydraGraphProjection(1,'episode-1','run-1',6,'a'*64,(),(),{},None,
        False,False,None,'available',{}, {})
    class Runtime:
        def snapshot(self):return {'graph_revision':6,'failure_reason':None}
        def projection(self):return final_projection
    coordinator=object.__new__(Pipeline)
    coordinator._lock=RLock();coordinator._hydra_snapshot=None;coordinator._hydra_projection=None
    coordinator._hydra_runtime=Runtime()
    coordinator.publisher=DisplayPublisher(clock_domain='host:boot1',now_ns=lambda:200)
    coordinator._hydra_failure=None;coordinator._captured=None;coordinator._processed=None
    coordinator._hydra_publication_key=None;coordinator._hydra_publication_ns=0
    coordinator._hydra_display_revision=0;coordinator._latest_nav=None
    coordinator.now_ns=lambda:200;coordinator.clock_domain='host:boot1';coordinator.episode_id='episode-1'
    coordinator._counts={'missing':0};coordinator.scheduler=SimpleNamespace(counts={'replaced':0})
    coordinator.health=SimpleNamespace(profile='hydra')

    coordinator._publish_hydra_after_close(coordinator._hydra_runtime)

    latest=coordinator.publisher.read_latest()
    assert latest.sources.hydra_graph is final_projection
    assert latest.sources.hydra_graph.graph_revision==6
