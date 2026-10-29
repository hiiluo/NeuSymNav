"""Paired capture publication pins exact depth without an intermediate dequeue."""
from dataclasses import replace
import threading

import pytest

from neusymnav.contracts import FrameKey
from test_runtime_scheduling import pipeline, source, wait_for, nav_for
from test_runtime_places import pose


class Mapper:
    def __init__(self):self.sources=[]
    def update(self,obs):
        self.sources.append(obs.key)
        return nav_for(obs,len(self.sources))


class Observer:
    def __init__(self):
        self.stop_requested=threading.Event();self.captures=[];self.poses=[]
    def capture(self,obs):self.captures.append(obs.key)
    def pose(self,obs,proof):self.poses.append((obs.key,proof))
    def admission(self,*args):pass
    def __getattr__(self,name):return lambda *a,**kw:None


def test_pair_cannot_dequeue_primary_between_offers(tmp_path,monkeypatch):
    mapper=Mapper();observer=Observer();p,detector,_=pipeline(tmp_path,mapper=mapper,measurements=observer)
    primary=source();depth=source(7,modality='depth_only')
    producer_paused=threading.Event();release=threading.Event();attempted=threading.Event()
    errors=[];original=p.submit
    # Instrument the already agreed queue-selection lock, without replacing
    # mapper/recorder/graph workers. An observed acquisition attempt is a barrier.
    original_lock=p._lock
    class TracedLock:
        def __enter__(self):
            if threading.current_thread() is p._threads['navigation'] and producer_paused.is_set():attempted.set()
            original_lock.acquire();return self
        def __exit__(self,*args):original_lock.release()
    p._lock=TracedLock()
    def submit(obs):
        original(obs)
        if obs is primary:
            producer_paused.set();p._nav_wake.set();assert release.wait(2)
    monkeypatch.setattr(p,'submit',submit)
    def publish():
        try:p.submit_sensor_pair(primary,depth,pose(depth))
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=publish)
    try:
        thread.start()
        assert producer_paused.wait(1),errors
        assert attempted.wait(1)
        assert mapper.sources==[]
        release.set();thread.join(1);assert not thread.is_alive() and not errors
        wait_for(lambda:p._latest_nav is not None)
        assert mapper.sources==[depth.key]
        assert p._latest_nav.source==depth.key
        assert observer.captures==[primary.key,depth.key]
        assert observer.poses==[(depth.key,pose(depth))]
        wait_for(lambda:p.telemetry()['committed']==1)
        assert detector.calls==[primary.key.frame_index]
        assert p.telemetry()['health']['counts']['nav_replaced']==1
    finally:
        release.set();thread.join(1);assert p.close(2)['clean_shutdown']


@pytest.mark.parametrize('case',[
    'primary_type','nav_type','primary_modality','nav_modality','primary_id','same_lane',
    'primary_episode','nav_episode','primary_clock','nav_clock','future_primary','future_nav',
    'reverse_capture','body_moved','pose_missing','pose_extra','pose_source','pose_stamp',
    'pose_domain','pose_version','pose_bool_version','pose_nan','pose_bool_xy','pose_bad_yaw','pose_stale',
])
def test_invalid_pair_has_no_capture_admission_or_counter_side_effect(tmp_path,case):
    observer=Observer();mapper=Mapper();clock=[1_000_000_000]
    p,detector,_=pipeline(tmp_path,mapper=mapper,measurements=observer,clock=lambda:clock[0])
    primary=source();depth=source(7,modality='depth_only');proof=pose(depth)
    if case=='primary_type':primary=None
    elif case=='nav_type':depth={}
    elif case=='primary_modality':primary=source(modality='depth_only')
    elif case=='nav_modality':depth=source(7)
    elif case=='primary_id':primary=replace(primary,key=FrameKey('episode','wrong-primary',0))
    elif case=='same_lane':depth=replace(depth,key=FrameKey('episode','rgbd',7));proof=pose(depth)
    elif case.endswith('_episode'):
        if case.startswith('primary'):primary=replace(primary,key=FrameKey('other','rgbd',0))
        else:depth=replace(depth,key=FrameKey('other','nav',7));proof=pose(depth)
    elif case.endswith('_clock'):
        if case.startswith('primary'):primary=replace(primary,clock_domain='replay:wrong')
        else:depth=replace(depth,clock_domain='replay:wrong');proof=pose(depth)
    elif case=='future_primary':primary=replace(primary,capture_monotonic_ns=1_000_000_001)
    elif case=='future_nav':depth=replace(depth,capture_monotonic_ns=1_000_000_001);proof=pose(depth)
    elif case=='reverse_capture':primary=replace(primary,capture_monotonic_ns=999_999_999);depth=replace(depth,capture_monotonic_ns=999_999_998);proof=pose(depth)
    elif case=='body_moved':depth=replace(depth,pose_version=depth.pose_version+1);proof=pose(depth)
    elif case=='pose_missing':proof.pop('source')
    elif case=='pose_extra':proof['inferred']=False
    elif case=='pose_source':proof['source']=primary.key
    elif case=='pose_stamp':proof['capture_monotonic_ns']-=1
    elif case=='pose_domain':proof['clock_domain']='replay:wrong'
    elif case=='pose_version':proof['pose_version']+=1
    elif case=='pose_bool_version':proof['pose_version']=bool(depth.pose_version)
    elif case=='pose_nan':proof['robot_xy']=(float('nan'),0.)
    elif case=='pose_bool_xy':proof['robot_xy']=(True,0.)
    elif case=='pose_bad_yaw':proof['yaw_rad']=None
    elif case=='pose_stale':clock[0]+=300_000_001
    before=p.telemetry()
    try:
        with pytest.raises((TypeError,ValueError)):p.submit_sensor_pair(primary,depth,proof)
        after=p.telemetry()
        for name in ('submitted','offered','missing','semantic_sampling','places'):
            assert after[name]==before[name]
        assert observer.captures==[] and observer.poses==[]
        assert mapper.sources==[] and detector.calls==[]
        assert p._captured is None and p._nav_input is None
    finally:assert p.close(2)['clean_shutdown']


@pytest.mark.parametrize('baseline,case',[
    ('primary','index'),('primary','stamp'),('depth','index'),('depth','stamp'),('depth','sensor'),
    ('pose','index'),('pose','stamp'),('pose','sensor'),
])
def test_pair_checks_all_existing_lane_watermarks_before_primary_admission(tmp_path,baseline,case):
    observer=Observer();mapper=Mapper();p,_,_=pipeline(tmp_path,mapper=mapper,measurements=observer)
    old=source(10,stamp=999_999_999,modality='rgbd' if baseline=='primary' else 'depth_only')
    try:
        if baseline=='pose':p.submit_robot_pose(old,pose(old))
        else:p.submit(old);wait_for(lambda:p._latest_nav is not None)
        primary=source(11);depth=source(11,modality='depth_only')
        target=primary if baseline=='primary' else depth
        if case=='index':target=replace(target,key=replace(target.key,frame_index=10))
        elif case=='stamp':target=replace(target,capture_monotonic_ns=999_999_998)
        else:target=replace(target,key=replace(target.key,sensor_id='different-nav'))
        if baseline=='primary':primary=target
        else:depth=target;primary=replace(primary,capture_monotonic_ns=depth.capture_monotonic_ns)
        before=p.telemetry();captures=list(observer.captures);poses=list(observer.poses)
        with pytest.raises(ValueError):p.submit_sensor_pair(primary,depth,pose(depth))
        after=p.telemetry()
        for name in ('submitted','offered','missing','semantic_sampling','places'):assert after[name]==before[name]
        assert observer.captures==captures and observer.poses==poses
    finally:assert p.close(2)['clean_shutdown']


def test_old_inflight_map_and_detector_do_not_block_pair_latest_wins(tmp_path):
    entered=threading.Event();release=threading.Event();detector_entered=threading.Event();detector_release=threading.Event()
    class SlowMap(Mapper):
        def update(self,obs):
            if obs.key.frame_index==0:entered.set();assert release.wait(2)
            return super().update(obs)
    from test_runtime_scheduling import Detector
    class SlowDetector(Detector):
        def infer(self,obs):detector_entered.set();assert detector_release.wait(2);return super().infer(obs)
    mapper=SlowMap();observer=Observer();detector=SlowDetector()
    p,_,_=pipeline(tmp_path,mapper=mapper,measurements=observer,detector=detector,keyframe_sampling='capacity_deferred')
    old=source(modality='depth_only');primary1=source(1);nav1=source(7,modality='depth_only')
    primary2=source(2);nav2=source(8,modality='depth_only')
    try:
        p.submit(old);assert entered.wait(1)
        p.submit_sensor_pair(primary1,nav1,pose(nav1))
        assert detector_entered.wait(1)
        done=threading.Event();errors=[]
        def publish():
            try:p.submit_sensor_pair(primary2,nav2,pose(nav2))
            except BaseException as exc:errors.append(exc)
            finally:done.set()
        thread=threading.Thread(target=publish);thread.start();assert done.wait(.5);thread.join(1);assert not errors
        assert mapper.sources==[] and not release.is_set() and not detector_release.is_set()
        assert p.telemetry()['health']['counts']['nav_replaced']==3
        sampling=p.semantic_sampling_snapshot()
        assert (sampling['seen'],sampling['offered'],sampling['deferred_capacity'])==(2,1,1)
        assert observer.captures==[old.key,primary1.key,nav1.key,primary2.key,nav2.key]
        assert observer.poses==[(nav1.key,pose(nav1)),(nav2.key,pose(nav2))]
        release.set();wait_for(lambda:p._latest_nav is not None and p._latest_nav.source==nav2.key)
        assert mapper.sources==[old.key,nav2.key]
        detector_release.set();wait_for(lambda:p.telemetry()['committed']==1)
        assert detector.calls==[primary1.key.frame_index]
    finally:release.set();detector_release.set();assert p.close(2)['clean_shutdown']


def test_pair_preserves_distinct_frame_indices_calibration_and_single_source_mapping(tmp_path):
    mapper=Mapper();observer=Observer();p,detector,_=pipeline(tmp_path,mapper=mapper,measurements=observer)
    primary=replace(source(),calibration_id='primary-calibration')
    depth=replace(source(17,modality='depth_only'),calibration_id='nav-calibration')
    try:
        p.submit_sensor_pair(primary,depth,pose(depth))
        wait_for(lambda:p._latest_nav is not None and p._latest_nav.source==depth.key)
        p.submit(source(1));wait_for(lambda:p._latest_nav.source==source(1).key)
        assert mapper.sources==[depth.key,source(1).key]
        assert observer.captures==[primary.key,depth.key,source(1).key]
        wait_for(lambda:p.telemetry()['committed']==2)
        assert detector.calls==[0,1]
    finally:assert p.close(2)['clean_shutdown']


def test_clock_change_after_primary_is_honest_partial_failure(tmp_path,monkeypatch):
    clock=[1_000_000_000];observer=Observer();p,_,_=pipeline(tmp_path,clock=lambda:clock[0],measurements=observer)
    primary=source();depth=source(7,modality='depth_only');original=p.submit
    def submit(obs):
        original(obs)
        if obs is primary:clock[0]+=300_000_001
    monkeypatch.setattr(p,'submit',submit)
    try:
        with pytest.raises(ValueError,match='stale'):p.submit_sensor_pair(primary,depth,pose(depth))
        assert observer.captures==[primary.key] and observer.poses==[]
        assert p.telemetry()['submitted']==1 and p.telemetry()['offered']==1
        assert p.telemetry()['places']['offered']==0
    finally:assert p.close(2)['clean_shutdown']


@pytest.mark.parametrize('failure',[None,'navigation','pose','raw_nav'])
def test_launcher_real_pair_and_raw_writer_keep_captures_once(tmp_path,failure):
    from types import SimpleNamespace
    from neusymnav.runtime import launcher
    from neusymnav.recording.writer import ReplayWriter
    from neusymnav.recording.replay import ReplayReader
    from test_runtime_measurement_wiring import session
    measurements=session();mapper=Mapper()
    p,detector,_=pipeline(tmp_path/'pipeline',mapper=mapper,measurements=measurements)
    primary=source();depth=source(modality='depth_only');events=[]
    writer=ReplayWriter(tmp_path/'raw')
    def capture():events.append('rgb');return primary
    def navigation():
        events.append('nav')
        if failure=='navigation':raise RuntimeError('capture failed')
        return depth
    def body(obs):
        assert obs is depth;events.append('pose')
        if failure=='pose':raise RuntimeError('pose failed')
        return pose(obs)
    def append(obs):
        events.append('raw_rgb' if obs is primary else 'raw_nav')
        if failure=='raw_nav' and obs is depth:raise RuntimeError('raw failed')
        launcher._append_raw(writer,obs)
    sensor=SimpleNamespace(capture=capture,capture_navigation=navigation,robot_pose=body)
    try:
        if failure is None:
            assert launcher._capture_sensor_pair(sensor,p,append)==(primary,depth)
            wait_for(lambda:p._latest_nav is not None)
            wait_for(lambda:p.telemetry()['committed']==1)
            assert mapper.sources==[depth.key] and detector.calls==[0]
            assert events==['rgb','raw_rgb','nav','raw_nav','pose']
        else:
            with pytest.raises(RuntimeError):launcher._capture_sensor_pair(sensor,p,append)
            assert p.telemetry()['submitted']==0 and detector.calls==[] and mapper.sources==[]
        raw_report=writer.close();assert raw_report['complete']
        raw=list(ReplayReader(tmp_path/'raw').source_frames())
        expected_raw=[primary] if failure in ('navigation','raw_nav') else [primary,depth]
        assert [obs.to_json() for obs in raw]==[obs.to_json() for obs in expected_raw]
        report=p.close(2);assert report['clean_shutdown']
        result=measurements.finalize(runtime_report=report,resources=None)
        registry=result['collector']['capture_registry']
        assert registry['retained']==(1 if failure=='navigation' else 2)
        assert result['collector']['rejected_records']==0
        assert len(result['actuation']['body_pose_records'])==(1 if failure is None else 0)
    finally:writer.close();p.close(2)


@pytest.mark.parametrize('state',['paused','closing','failed','resource_stop'])
def test_pair_preserves_terminal_and_capacity_rejection_accounting(tmp_path,state):
    observer=Observer();mapper=Mapper();p,_,_=pipeline(tmp_path,mapper=mapper,measurements=observer)
    primary=source();depth=source(modality='depth_only')
    if state=='paused':p._paused=True
    elif state=='closing':p._closing=True
    elif state=='failed':p.health.fail('fixture',RuntimeError('terminal'))
    else:observer.stop_requested.set()
    try:
        p.submit_sensor_pair(primary,depth,pose(depth))
        assert observer.captures==[primary.key,depth.key]
        telemetry=p.telemetry()
        assert telemetry['submitted']==2 and telemetry['missing']==2 and telemetry['offered']==0
        assert p._nav_input is None and mapper.sources==[]
        assert telemetry['semantic_sampling']['seen']==0
    finally:
        report=p.close(2)
        assert not report['workers_pending']
        assert report['clean_shutdown'] is (state!='failed')
