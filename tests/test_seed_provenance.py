"""Seed configuration, actual launcher provenance and frozen-profile boundaries."""
from pathlib import Path
import json
import pytest
from test_launcher import config


@pytest.mark.parametrize('seed',[0,2**32-1])
def test_configuration_accepts_explicit_uint32_seed(tmp_path,seed):
    from neusymnav.runtime.configuration import load_config
    path=config(tmp_path,sensor_config=dict(seed=seed))
    assert load_config(path).data['sensor_config']['seed']==seed


@pytest.mark.parametrize('seed',[True,False,-1,2**32,1.0,'1',None])
def test_configuration_rejects_non_uint32_seed(tmp_path,seed):
    from neusymnav.runtime.configuration import load_config
    with pytest.raises(ValueError,match='seed'):load_config(config(tmp_path,sensor_config=dict(seed=seed)))


def test_old_unseeded_fixture_remains_loadable_without_seed_proof():
    from neusymnav.runtime.configuration import load_config
    fixture=Path(__file__).parent/'fixtures/package/config.yaml'
    assert 'seed' not in load_config(fixture).data.get('sensor_config',{})


def test_live_launcher_persists_start_ack_and_separate_final_decoded_sensor_metadata(tmp_path,monkeypatch):
    import hashlib,sys
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.objects.store import ObjectOwner
    from neusymnav.contracts import DetectionBatch
    from test_sensor_execution_metadata import habitat_stub,actual_worker_script
    from test_runtime_scheduling import nav_for,AllFrames
    sensor_config,_=habitat_stub(monkeypatch);sensor_config.pop('scene_id');sensor_config.pop('episode_id')
    marker=tmp_path/'scene';marker.write_bytes(b'CPU scene marker, no native scene')
    sensor_config['scene']=dict(path=str(marker),sha256=hashlib.sha256(marker.read_bytes()).hexdigest())
    path=config(tmp_path,mode='live',sensor_config=sensor_config)
    data=json.loads(path.read_text());data['episode'].update(id='episode',primary_sensor_id='rgbd');data['workers']={'sensor':{'timeout_s':3.}};path.write_text(json.dumps(data));cfg=load_config(path)
    script=actual_worker_script(tmp_path)
    monkeypatch.setattr(launcher,'_checked',lambda _: (cfg,dict(sensor=(Path(sys.executable),script),scene=marker)))
    class Detector:
        def infer(self,obs):return DetectionBatch.from_observation(obs,(),vocabulary_id='v1')
        def close(self):pass
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    def compose(config,assets,root,domain,clock,**kwargs):
        p=Pipeline(root,episode_id='episode',primary_sensor_id='rgbd',floor_id='floor-0',clock_domain=domain,
            owner_factory=lambda:ObjectOwner(root/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='floor-0',clock_domain=domain,detector_profile_id='cpu-fixture-seed',vocabulary_id='v1',now_ns=clock),
            detector_factory=Detector,mapper=Mapper(),keyframe_policy=AllFrames(),now_ns=clock,actual_profile='cpu-fixture-seed')
        p._launcher_worker_metadata={};return p
    monkeypatch.setattr(launcher,'_pipeline',compose)
    result=launcher.run(path,duration_s=.02,out=tmp_path/'out')
    assert result['attempt_id']
    start=json.loads((tmp_path/'out/attempts'/f"{result['attempt_id']}.json").read_text())['sensor_launch']
    final=result['worker_runtime']['sensor']
    assert start['runtime_metadata']['execution']['seed']==7
    assert start['runtime_metadata']['actual_resolution_hw']['navigation']['resolution_hw']==[4,5]
    assert 'primary' not in start['runtime_metadata']['actual_resolution_hw']
    assert final['actual_resolution_hw']['primary']['resolution_hw']==[2,3]
    assert final['actual_resolution_hw']['navigation']['resolution_hw']==[4,5]
    assert final['execution']==start['runtime_metadata']['execution']
    launch=start['configuration']
    assert launch['scene_id']==str(marker) and launch['seed']==7
    assert start['config_sha256']==hashlib.sha256(json.dumps(launch,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert start['config_sha256']==final['launch_config_sha256']
    assert start['runtime_metadata']['worker_script_sha256']==hashlib.sha256(script.read_bytes()).hexdigest()
    assert result['native_runtime_validated'] is False


def test_preflight_does_not_turn_requested_or_missing_seed_into_executed_proof(tmp_path):
    from neusymnav.runtime.launcher import preflight
    unseeded=preflight(config(tmp_path))
    assert unseeded['ready']
    assert unseeded['p10_seed_support']=='unavailable_unseeded_config'
    seeded=preflight(config(tmp_path,sensor_config=dict(seed=0)))
    assert seeded['p10_seed_support']=='requested_unverified_until_worker_ack'
