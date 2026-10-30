import json
import pytest
from test_launcher import config
from neusymnav.runtime.configuration import load_config


@pytest.mark.parametrize('mode',['novelty','capacity_deferred'])
def test_live_sampling_profile_is_explicit(tmp_path,mode):
    path=config(tmp_path,mode='live',keyframe_sampling=mode)
    assert load_config(path).data['keyframe_sampling']==mode


@pytest.mark.parametrize('mode',[None,True,0,[],{},'latest'])
def test_sampling_enum_rejects_invalid_values(tmp_path,mode):
    with pytest.raises(ValueError):load_config(config(tmp_path,keyframe_sampling=mode))


def test_recorded_fixture_cannot_resample_by_live_capacity(tmp_path):
    with pytest.raises(ValueError,match='live'):load_config(config(tmp_path,keyframe_sampling='capacity_deferred'))


@pytest.mark.parametrize('value',[.1,.5,1,.001])
def test_rss_acquisition_budget_is_explicit(tmp_path,value):
    assert load_config(config(tmp_path,measurements=dict(rss_sample_timeout_s=value))).data['measurements']['rss_sample_timeout_s']==value


@pytest.mark.parametrize('value',[True,False,None,0,-1,1.001,float('inf'),float('nan'),10**1000,'0.5',[],{}])
def test_rss_acquisition_budget_rejects_invalid_values(tmp_path,value):
    with pytest.raises(ValueError):load_config(config(tmp_path,measurements=dict(rss_sample_timeout_s=value)))


@pytest.mark.parametrize('explicit',[None,.5])
@pytest.mark.parametrize('retry',[None,.2])
def test_actual_launcher_passes_rss_budget_only_to_provider(tmp_path,monkeypatch,explicit,retry):
    from pathlib import Path
    import sys
    from neusymnav.runtime import launcher,resources
    from neusymnav.runtime.configuration import Configuration
    from neusymnav.sensors import client
    options=dict(enabled=True)
    if explicit is not None:options['rss_sample_timeout_s']=explicit
    if retry is not None:options['rss_retry_wait_s']=retry
    path=config(tmp_path,mode='live',measurements=options,sensor_config=dict(seed=0,primary=dict(sensor_id='rgbd'),navigation=dict(sensor_id='nav')),
                workers=dict(sensor=dict(timeout_s=.2)))
    cfg=Configuration(path,json.loads(path.read_text()));marker=tmp_path/'scene';marker.write_text('stub')
    monkeypatch.setattr(launcher,'_checked',lambda _:(cfg,dict(sensor=(Path(sys.executable),marker),scene=marker)))
    monkeypatch.setattr(launcher,'load_config',lambda _:cfg)
    observed=[];observed_wait=[]
    original=resources.ProcTreeProvider.__init__
    def record(self,*args,**kwargs):
        observed.append(kwargs.get('sample_timeout_s',.1));observed_wait.append(kwargs.get('retry_wait_s',.005));original(self,*args,**kwargs)
    monkeypatch.setattr(resources.ProcTreeProvider,'__init__',record)
    class Broken:
        def __init__(self,**kwargs):raise RuntimeError('intentional early sensor failure')
    monkeypatch.setattr(client,'HabitatPoseSource',Broken)
    result=launcher.run(path,duration_s=.01,out=tmp_path/'out')
    assert result['outcome']=='failed'
    assert observed==[.1 if explicit is None else explicit]
    acquisition=result['resource_acquisition']
    assert acquisition['rss_sample_timeout_s']==observed[0]
    assert acquisition['rss_interval_s']==.1
    assert acquisition['schema_version']==1
    assert acquisition['rss_retry_wait_s']==observed_wait[0]==(.005 if retry is None else retry)
    assert 'sampled' in acquisition['limitation']


@pytest.mark.parametrize('mode',['novelty','capacity_deferred'])
@pytest.mark.parametrize('adapter',['strict_3d','planar_fixed_y_v1'])
def test_real_pipeline_builder_binds_sampling_profile_and_constructor(tmp_path,monkeypatch,mode,adapter):
    from types import SimpleNamespace
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import Configuration
    from neusymnav.perception import detector_client
    from neusymnav.navigation import controller,safety
    from neusymnav.contracts import Taxonomy
    asset=tmp_path/'asset';asset.write_bytes(b'fixture')
    data=dict(profile='baseline',mode='live',keyframe_sampling=mode,sensor_config=dict(motion_adapter=adapter),episode=dict(id='episode',primary_sensor_id='rgbd',floor_id='floor'),
              detector={},workers=dict(detector={}))
    cfg=Configuration(tmp_path/'config',data)
    monkeypatch.setattr(launcher,'_mapper',lambda *args,**kwargs:SimpleNamespace(robot=object()))
    monkeypatch.setattr(detector_client,'validate_recipe',lambda value:value)
    monkeypatch.setattr(Taxonomy,'load',lambda path:SimpleNamespace(vocabulary_id='v1'))
    monkeypatch.setattr(controller,'Navigator',lambda *args,**kwargs:SimpleNamespace())
    monkeypatch.setattr(safety,'MotionGuard',lambda *args,**kwargs:SimpleNamespace())
    observed=[]
    def build(*args,**kwargs):observed.append(kwargs);return SimpleNamespace()
    monkeypatch.setattr(launcher,'Pipeline',build)
    assets=dict(checkpoint=asset,encoder=asset,taxonomy=asset,detector=(asset,asset),region=asset)
    launcher._pipeline(cfg,assets,tmp_path/'out','host_monotonic:fixture',lambda:1)
    kwargs=observed[0]
    suffix='' if adapter=='strict_3d' else ':motion-planar_fixed_y_v1'
    if mode=='novelty':
        assert 'keyframe_sampling' not in kwargs
        assert kwargs['actual_profile']=='baseline:yoloe:appearance-off'+suffix
    else:
        assert kwargs['keyframe_sampling']==mode
        assert kwargs['actual_profile']=='baseline:yoloe:appearance-off:sampling-capacity_deferred'+suffix


def test_recorded_replay_cannot_reselect_capacity_profile(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import Configuration
    monkeypatch.setattr(launcher,'_mapper',lambda *args,**kwargs:None)
    cfg=Configuration(tmp_path/'config',dict(profile='baseline',mode='live',keyframe_sampling='capacity_deferred',episode=dict(id='episode',primary_sensor_id='rgbd',floor_id='floor')))
    with pytest.raises(ValueError,match='exact semantic input'):
        launcher._pipeline(cfg,{},tmp_path,'replay:fixture',lambda:1,recorded=SimpleNamespace(vocabulary_id='v1'))


def test_live_mode_replay_rejects_capacity_sampling_before_output_or_workers(tmp_path,monkeypatch):
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import Configuration
    path=config(tmp_path,mode='live',keyframe_sampling='capacity_deferred')
    cfg=Configuration(path,json.loads(path.read_text()))
    monkeypatch.setattr(launcher,'_checked',lambda _: (cfg,{}))
    def forbidden(*args,**kwargs):raise AssertionError('replay side effect before sampling rejection')
    monkeypatch.setattr(launcher,'_root',forbidden)
    monkeypatch.setattr(launcher,'_pipeline',forbidden)
    with pytest.raises(ValueError,match='exact selected semantic'):
        launcher.replay(tmp_path/'unused-input',path,out=tmp_path/'unused-output')
    assert not (tmp_path/'unused-output').exists()


@pytest.mark.parametrize('value',[0,.005,.2,.25])
def test_rss_retry_wait_is_explicit(tmp_path,value):
    cfg=load_config(config(tmp_path,measurements=dict(rss_retry_wait_s=value)))
    assert cfg.data['measurements']['rss_retry_wait_s']==value


@pytest.mark.parametrize('value',[True,False,None,-1,.251,float('inf'),float('nan'),10**1000,'0.2',[],{}])
def test_rss_retry_wait_rejects_invalid_values(tmp_path,value):
    with pytest.raises(ValueError):load_config(config(tmp_path,measurements=dict(rss_retry_wait_s=value)))


@pytest.mark.parametrize('mode',['strict_3d','planar_fixed_y_v1'])
def test_motion_adapter_mode_is_explicit(tmp_path,mode):
    cfg=load_config(config(tmp_path,sensor_config=dict(motion_adapter=mode)))
    assert cfg.data['sensor_config']['motion_adapter']==mode


@pytest.mark.parametrize('value',[True,False,None,'planar','strict',0,[],{}])
def test_motion_adapter_rejects_unknown_modes(tmp_path,value):
    with pytest.raises(ValueError):load_config(config(tmp_path,sensor_config=dict(motion_adapter=value)))


def test_real_worker_ack_binds_opt_in_adapter_and_rejects_silent_default(tmp_path,monkeypatch):
    import hashlib,sys
    from pathlib import Path
    from neusymnav.sensors.client import HabitatPoseSource
    from test_sensor_execution_metadata import habitat_stub,actual_worker_script
    cfg,_=habitat_stub(monkeypatch);cfg['motion_adapter']='planar_fixed_y_v1'
    script=actual_worker_script(tmp_path)
    source=HabitatPoseSource(python=sys.executable,worker_script=script,config=cfg,timeout_s=3.)
    try:
        expected=hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        assert source.runtime_metadata['execution']['config_sha256']==expected
        source.capture_navigation()
    finally:assert source.close()['clean_shutdown']
    tests=Path(__file__).resolve().parent
    dropped=tmp_path/'drop-adapter.py'
    dropped.write_text('import sys\n'+f'sys.path.insert(0,{str(tests)!r})\n'+
        'import pytest\nfrom test_sensor_execution_metadata import habitat_stub\nhabitat_stub(pytest.MonkeyPatch())\n'+
        'from neusymnav.sensors import habitat_worker as worker\noriginal=worker.HabitatCapture\n'+
        "worker.HabitatCapture=lambda cfg:original({k:v for k,v in cfg.items() if k!='motion_adapter'})\nraise SystemExit(worker.main())\n")
    with pytest.raises((ValueError,RuntimeError),match='ACK|config|configuration'):
        HabitatPoseSource(python=sys.executable,worker_script=dropped,config=cfg,timeout_s=3.)
