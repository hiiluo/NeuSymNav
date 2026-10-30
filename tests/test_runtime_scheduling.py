"""CPU fixtures: boundedness/freshness and actual canonical-owner wiring."""
from dataclasses import replace
import threading
import time
import numpy as np
import pytest
from contract_helpers import observation
from neusymnav.contracts import FrameKey,DetectionBatch,NavSnapshot,RegionSnapshot,MotionCommand,NavigationDecision
from neusymnav.objects.store import ObjectOwner
from neusymnav.runtime import Pipeline,KeyframeScheduler
from neusymnav.runtime.scheduler import Entry,payload_bound,KeyframePolicy

DOMAIN='host_monotonic:runtime-test-boot'


def source(index=0,stamp=1_000_000_000,*,modality='rgbd',shift=0.):
    pose=np.eye(4);pose[0,3]=shift
    return observation(key=FrameKey('episode','rgbd' if modality=='rgbd' else 'nav',index),
        capture_monotonic_ns=stamp,clock_domain=DOMAIN,modality=modality,T_world_camera=pose)


def empty(obs):return DetectionBatch.from_observation(obs,(),vocabulary_id='v1')


def wait_for(predicate,timeout=3.):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.005)
    raise AssertionError('condition timed out')


class AllFrames:
    def propose(self,obs):return True,'first_view' if obs.key.frame_index==0 else None,float(obs.key.frame_index+1)
    def commit(self,obs):pass


class Detector:
    def __init__(self):self.calls=[];self.threads=[]
    def infer(self,obs):self.calls.append(obs.key.frame_index);self.threads.append(threading.get_ident());return empty(obs)
    def close(self):pass


def pipeline(root,*,clock=lambda:1_000_000_000,detector=None,**kw):
    detector=detector or Detector();owner_threads=[]
    def owner_factory():
        owner_threads.append(threading.get_ident())
        return ObjectOwner(root/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='f',
            detector_profile_id='fixture',vocabulary_id='v1',clock_domain=DOMAIN,now_ns=clock)
    p=Pipeline(root,episode_id='episode',primary_sensor_id='rgbd',floor_id='f',clock_domain=DOMAIN,
               owner_factory=kw.pop('owner_factory',owner_factory),detector_factory=lambda:detector,
               now_ns=clock,keyframe_policy=AllFrames(),**kw)
    return p,detector,owner_threads


def nav_for(obs,revision=1):
    return NavSnapshot('episode',revision,obs.key,obs.capture_monotonic_ns,obs.clock_domain,.1,(-.5,-.5),
        np.zeros((10,10),np.int8),np.ones((10,10),bool),np.full((10,10),2.,np.float32),'robot',0.,'fixture floor','a'*64)


def test_scheduler_caps_chronology_protection_and_persisted_pin():
    scheduler=KeyframeScheduler(byte_cap=1000)
    a,b,c=Entry(source(0),200,1.,'first_view'),Entry(source(2),200,2.),Entry(source(1),200,3.)
    assert scheduler.offer(a)[0];assert scheduler.offer(b)[0]
    accepted,replaced,_=scheduler.offer(c)
    assert accepted and replaced==(b,)
    assert scheduler.snapshot()['protected_pending']==1
    scheduler.accepted(a,'a');scheduler.accepted(c,'c')
    assert not scheduler.offer(Entry(source(3),200,100.))[0]
    watermarks=[]
    assert scheduler.take_next(watermarks.append) is a
    assert scheduler.take_next(watermarks.append) is None
    assert scheduler.snapshot()['payload_bytes']==400
    scheduler.complete(a);assert scheduler.take_next(watermarks.append) is c
    assert watermarks==[0,1]
    scheduler.complete(c)
    assert not scheduler.offer(Entry(source(0),200,100.))[0]
    assert not scheduler.offer(Entry(source(3),1001,100.))[0]


def test_submit_does_not_wait_for_watermark_disk_io():
    scheduler=KeyframeScheduler();a=Entry(source(),100,1.,'first_view')
    scheduler.offer(a);scheduler.accepted(a,'a');started=threading.Event();release=threading.Event()
    def fsync(index):started.set();release.wait(2)
    t=threading.Thread(target=lambda:scheduler.take_next(fsync));t.start();assert started.wait(1)
    start=time.monotonic();assert not scheduler.offer(Entry(source(1),100,2.))[0]
    assert time.monotonic()-start<.05
    release.set();t.join(1)


def test_real_object_owner_one_graph_thread_one_detector_and_empty_verifier(tmp_path):
    seen=[]
    class Verifier:
        def __init__(self,owner):self.owner=owner
        def replay(self):seen.append(('replay',threading.get_ident()))
        def consume(self,result):seen.append((result.snapshot.source.frame_index,threading.get_ident()))
    p,d,threads=pipeline(tmp_path,verifier_factory=Verifier)
    for i in range(3):
        p.submit(source(i));wait_for(lambda:p.telemetry()['committed']==i+1)
    report=p.close(2.)
    assert report['clean_shutdown'] and report['pending']==0 and report['drained']==3
    assert d.calls==[0,1,2] and len(set(d.threads))==1
    assert threads==[d.threads[0]] and threads[0]!=threading.get_ident()
    assert [x[0] for x in seen]==['replay',0,1,2]
    assert all(x[1]==threads[0] for x in seen)
    assert report['metrics']['scheduler']['peak_pending']<=2
    assert report['metrics']['scheduler']['peak_bytes']<=32*1024**2


def test_historical_stream_one_infer_no_fast_and_consumer_rechecks_now(tmp_path):
    clock=[1_000_000_000]
    p,d,_=pipeline(tmp_path,clock=lambda:clock[0])
    p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    assert p.fast_semantics() is not None
    clock[0]+=751_000_000
    assert p.fast_semantics() is None
    p.submit(source(1,stamp=1_000_000_001));wait_for(lambda:p.telemetry()['committed']==2)
    assert p.fast_semantics() is None and d.calls==[0,1]
    assert p.close(2)['clean_shutdown']


def test_inference_start_250ms_enforced_for_fast_but_preserves_graph(tmp_path):
    p,d,_=pipeline(tmp_path,clock=lambda:1_300_000_000)
    p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    assert p.fast_semantics() is None
    assert p.telemetry()['health']['counts']['inference_start_stale']==1
    assert p.close(2)['clean_shutdown']


def test_control_progresses_while_detector_and_disk_blocked(tmp_path,monkeypatch):
    entered=threading.Event();release=threading.Event();clock=[1_000_000_000]
    class Slow(Detector):
        def infer(self,obs):entered.set();release.wait(3);return super().infer(obs)
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Guard:
        def bind_nav(self,nav,**pose):self.nav=nav
        def filter(self,decision,latest,now):return MotionCommand(latest.key,self.nav.revision,now,now+10_000_000,DOMAIN,.1,0.,'fixture',latest.capture_monotonic_ns)
    class Navigator:
        def step(self,nav,xy,yaw,now):return NavigationDecision(None,((0.,0.),),.1,0.,nav.revision,'fixture')
    class Actuator:
        def robot_pose(self,obs):return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=(0.,0.),yaw_rad=0.)
        def execute(self,command):return dict(executed=command.linear_mps!=0,reason=command.reason)
    p,d,_=pipeline(tmp_path,clock=lambda:clock[0],detector=Slow(),mapper=Mapper(),navigator=Navigator(),guard=Guard())
    p.submit(source());assert entered.wait(1)
    depth=source(0,modality='depth_only');p.submit(depth)
    wait_for(lambda:p._latest_nav is not None and p._latest_nav.source==depth.key
        and p._latest_nav.capture_monotonic_ns==depth.capture_monotonic_ns
        and p._latest_nav.clock_domain==depth.clock_domain)
    start=time.monotonic();assert p.control_step(Actuator())['executed'];assert time.monotonic()-start<.1
    clock[0]+=301_000_000
    assert not p.control_step(Actuator())['executed']
    release.set();assert p.close(2)['clean_shutdown']


def test_nonblocking_recorder_counts_inflight_bytes_and_incomplete_drops(tmp_path,monkeypatch):
    from neusymnav.runtime.workers import Journal
    started=threading.Event();release=threading.Event();original=Journal.accept
    def slow(self,obs):started.set();release.wait(3);return original(self,obs)
    monkeypatch.setattr(Journal,'accept',slow)
    p,_,_=pipeline(tmp_path)
    p.submit(source());assert started.wait(1)
    start=time.monotonic()
    for i in range(1,50):p.submit(source(i))
    assert time.monotonic()-start<.15
    status=p.telemetry();assert status['scheduler']['pending']<=2 and status['scheduler']['payload_bytes']<=32*1024**2
    release.set();report=p.close(2)
    assert report['clean_shutdown'] and not report['recorder_certificate']['complete']
    assert report['recorder_certificate']['missing_count']>0


def test_region_worker_pins_accepted_map_and_latest_navigation_independent(tmp_path):
    entered=threading.Event();release=threading.Event()
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Regions:
        def __init__(self):self.calls=0
        def update(self,nav):
            self.calls+=1
            if self.calls==1:entered.set();release.wait(3)
            return RegionSnapshot('episode',self.calls,nav.revision,'f',{},False)
        def close(self):pass
    p,_,_=pipeline(tmp_path,mapper=Mapper(),region_factory=Regions)
    p.submit(source());assert entered.wait(1)
    for i in range(1,5):
        p.submit(source(i));wait_for(lambda:p._latest_nav is not None and p._latest_nav.revision==i+1)
    assert p.snapshot() is None
    release.set();wait_for(lambda:p.snapshot() is not None)
    wait_for(lambda:p.snapshot().latest_nav_revision==5)
    h=p.snapshot();assert h.map_revision<=h.latest_nav_revision and p.telemetry()['health']['counts']['publication_mismatch']==0
    assert p.close(2)['clean_shutdown']


def test_ui_ack_applies_pause_stop_and_rejects_wrong_domain(tmp_path):
    from neusymnav.visualization.publisher import UiCommand
    from uuid import uuid4
    p,_,_=pipeline(tmp_path)
    command=UiCommand(str(uuid4()),'pause','fixture',1_000_000_000,DOMAIN)
    ack=p.handle_ui_command(command);assert ack.status=='accepted' and p.telemetry()['paused']
    p.submit(source());assert p.telemetry()['offered']==0
    ack=p.handle_ui_command(replace(command,request_uuid=str(uuid4()),clock_domain='other'))
    assert ack.status=='rejected'
    assert p.handle_ui_command(replace(command,request_uuid=str(uuid4()),action='stop')).status=='accepted'
    assert p.telemetry()['stop_requested'];assert p.close(2)['clean_shutdown']


def test_wrong_clock_future_order_and_secondary_graph_rejected(tmp_path):
    p,_,_=pipeline(tmp_path)
    with pytest.raises(ValueError,match='clock'):p.submit(replace(source(),clock_domain='host_monotonic:otherboot'))
    with pytest.raises(ValueError,match='future'):p.submit(source(stamp=1_000_000_001))
    p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    with pytest.raises(ValueError,match='order'):p.submit(source())
    with pytest.raises(ValueError,match='primary'):p.submit(replace(source(1),key=FrameKey('episode','other',1)))
    assert p.close(2)['clean_shutdown']


def test_keyframe_policy_translation_oracle():
    policy=KeyframePolicy();obs=source()
    assert policy.propose(obs)==(True,'first_view',1.)
    policy.commit(obs)
    assert not policy.propose(source(1,shift=.24))[0]
    assert policy.propose(source(2,shift=.25))[0]


def test_telemetry_waiting_for_quota_does_not_hold_submit_lock(tmp_path,monkeypatch):
    # A slow filesystem scan owns quota.lock; telemetry must not transfer that
    # wait to the sensor-facing submit lock.
    entered=threading.Event();release=threading.Event();submitted=threading.Event()
    p,_,_=pipeline(tmp_path)
    original=p.quota.snapshot
    def stalled():entered.set();release.wait(2);return original()
    monkeypatch.setattr(p.quota,'snapshot',stalled)
    telemetry=threading.Thread(target=p.telemetry);telemetry.start();assert entered.wait(1)
    submit=threading.Thread(target=lambda:(p.submit(source()),submitted.set()));submit.start()
    try:assert submitted.wait(.15),'submit blocked behind telemetry/quota'
    finally:
        release.set();telemetry.join(1);submit.join(1);p.close(2)


def test_rejected_primary_source_does_not_reach_navigation(tmp_path):
    called=threading.Event()
    class Mapper:
        def update(self,obs):called.set();return nav_for(obs)
    p,_,_=pipeline(tmp_path,mapper=Mapper())
    try:
        with pytest.raises(ValueError,match='primary'):
            p.submit(replace(source(),key=FrameKey('episode','unauthorized',0)))
        assert not called.wait(.1),'rejected graph source contaminated navigation'
    finally:p.close(2)


def test_publication_age_is_for_pinned_map_during_navigation_race(tmp_path,monkeypatch):
    from neusymnav.hierarchy.composer import HierarchyComposer
    from neusymnav.visualization.publisher import DisplayPublisher
    entered=threading.Event();release=threading.Event();published=threading.Event();envelopes=[]
    original=HierarchyComposer.compose;clock=[2_000_000_000]
    def slow(self,*args,**kwargs):
        if not entered.is_set():entered.set();release.wait(2)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(HierarchyComposer,'compose',slow)
    class Publisher(DisplayPublisher):
        def publish(self,*args,**kwargs):
            result=super().publish(*args,**kwargs);envelopes.append(self.read_latest());published.set();return result
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    p,_,_=pipeline(tmp_path,clock=lambda:clock[0],mapper=Mapper(),publisher=Publisher(clock_domain=DOMAIN,now_ns=lambda:clock[0]))
    try:
        p.submit(source(stamp=1_000_000_000));assert entered.wait(1)
        p.submit(source(1,stamp=2_000_000_000));wait_for(lambda:p._latest_nav.revision==2)
        release.set();assert published.wait(1)
        first=envelopes[0]
        assert first.sources.nav.revision==1
        assert first.metrics.source_age_ns['map']==1_000_000_000
    finally:release.set();p.close(2)


def test_real_verification_and_display_bundle_keep_committed_multiview_identity(tmp_path):
    from test_projection import scene,batch
    from neusymnav.verification import VerificationOwner
    from neusymnav.visualization.publisher import DisplayPublisher
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Views(Detector):
        def infer(self,obs):
            self.calls.append(obs.key.frame_index)
            offset=round(20*float(obs.T_world_camera[0,3]))
            return batch(obs,((12-offset,12,20-offset,20),))
    publisher=DisplayPublisher(clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p,d,_=pipeline(tmp_path,detector=Views(),mapper=Mapper(),publisher=publisher,
        verifier_factory=lambda owner:VerificationOwner(owner,clock_domain=DOMAIN,now_ns=lambda:1_000_000_000))
    try:
        for index,x in enumerate((-.3,0.,.3,0.,.3)):
            obs=replace(scene(index,stamp=1_000_000_000,shift=x),clock_domain=DOMAIN)
            p.submit(obs);wait_for(lambda:p.telemetry()['committed']==index+1)
            for _ in range(3):assert p.fast_semantics()[0].key==obs.key
        wait_for(lambda:publisher.read_latest() is not None and publisher.read_latest().hierarchy.object_revision==5)
        envelope=publisher.read_latest();verification=p._verification
        state=next(iter(verification.objects.values()));oid=state.object_id
        assert (verification.batch_count,verification.view_count)==(5,5)
        assert (state.detected_count,state.independent_views,state.status,state.graph_lifecycle)==(5,3,'verified','active')
        assert d.calls==[0,1,2,3,4]
        assert envelope.sources.verification.object_revision==envelope.sources.objects.revision==5
        record=envelope.sources.verification.objects[oid]
        assert record.status=='verified' and record.object_revision==envelope.sources.objects.objects[oid].revision
        assert len(record.evidence)==3
        assert {e.evidence_ref for e in record.evidence} <= set(envelope.sources.objects.objects[oid].evidence_refs)
        assert envelope.hierarchy.nodes[oid].attributes['lifecycle']=='active'
        assert not verification.replay_required
    finally:assert p.close(2)['clean_shutdown']


def test_integrated_complete_empty_event_reaches_verifier_and_historical_never_votes(tmp_path):
    from test_projection import scene,batch
    from neusymnav.verification import VerificationOwner
    clock=[1_000_000_000]
    class Views(Detector):
        def infer(self,obs):return batch(obs,((12,12,20,20),) if obs.key.frame_index==0 else ())
    p,_,_=pipeline(tmp_path,clock=lambda:clock[0],detector=Views(),
        verifier_factory=lambda owner:VerificationOwner(owner,clock_domain=DOMAIN,now_ns=lambda:clock[0]))
    try:
        for index,depth,stamp in ((0,2.,1_000_000_000),(1,3.,1_000_000_000),(2,3.,1_000_000_000)):
            if index==2:clock[0]=1_750_000_001
            p.submit(replace(scene(index,depth=depth,stamp=stamp),clock_domain=DOMAIN))
            wait_for(lambda:p.telemetry()['committed']==index+1)
            if index==1:
                state=next(iter(p._verification.objects.values()))
                assert (state.negative_views,state.negative_history_count)==(1,1)
        snapshot=p._verification;state=next(iter(snapshot.objects.values()))
        assert snapshot.batch_count==3 and snapshot.complete_empty_batch_count==2
        assert state.detected_count==1 and state.negative_views==0 and state.negative_history_count==1
        assert p.fast_semantics() is None
    finally:assert p.close(2)['clean_shutdown']


def test_ui_pause_ack_waits_for_active_pulse_and_prevents_the_next(tmp_path):
    from neusymnav.visualization.publisher import UiControlClient
    started=threading.Event();release=threading.Event();acknowledged=threading.Event()
    class Mapper:
        def update(self,obs):return nav_for(obs)
    class Navigator:
        def step(self,nav,xy,yaw,now):return NavigationDecision(None,((0.,0.),),.1,0.,nav.revision,'fixture')
    class Guard:
        def bind_nav(self,nav,**kw):self.nav=nav
        def filter(self,decision,latest,now):return MotionCommand(latest.key,self.nav.revision,now,now+10_000_000,DOMAIN,.1,0.,'fixture',latest.capture_monotonic_ns)
    class Actuator:
        def __init__(self):self.moving=[]
        def robot_pose(self,obs):return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=DOMAIN,pose_version=obs.pose_version,robot_xy=(0.,0.),yaw_rad=0.)
        def execute(self,command):
            self.moving.append(command.linear_mps!=0)
            if command.linear_mps:started.set();release.wait(2)
            return dict(executed=command.linear_mps!=0)
    p,_,_=pipeline(tmp_path,mapper=Mapper(),navigator=Navigator(),guard=Guard());actuator=Actuator()
    client=UiControlClient(command_source='fixture',submit=p.handle_ui_command,clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    statuses=[]
    try:
        p.submit(source(modality='depth_only'));wait_for(lambda:p._latest_nav is not None)
        control=threading.Thread(target=lambda:p.control_step(actuator));control.start();assert started.wait(1)
        ui=threading.Thread(target=lambda:(statuses.append(client.request('pause')),acknowledged.set()));ui.start()
        assert not acknowledged.wait(.05)
        release.set();control.join(1);ui.join(1)
        assert acknowledged.is_set() and statuses[0].state=='acknowledged'
        assert p.control_step(actuator)==dict(executed=False,reason='runtime_paused')
        assert actuator.moving==[True]  # ACK followed completion; no further actuator call.
    finally:release.set();p.close(2)


def test_graph_composition_and_display_stalls_leave_submit_and_control_live(tmp_path,monkeypatch):
    from neusymnav.hierarchy.composer import HierarchyComposer
    entered=threading.Event();release=threading.Event();display_entered=threading.Event();display_release=threading.Event()
    original=HierarchyComposer.compose
    def stalled(self,*args,**kwargs):entered.set();release.wait(2);return original(self,*args,**kwargs)
    monkeypatch.setattr(HierarchyComposer,'compose',stalled)
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Publisher:
        def publish(self,*args,**kwargs):display_entered.set();display_release.wait(2)
    p,_,_=pipeline(tmp_path,mapper=Mapper(),publisher=Publisher())
    try:
        p.submit(source());assert entered.wait(1)
        start=time.monotonic();p.submit(source(1));assert p.control_step(None)['reason']=='navigation_unavailable'
        assert time.monotonic()-start<.1
        release.set();assert display_entered.wait(1)
        start=time.monotonic();p.submit(source(2));assert p.control_step(None)['reason']=='navigation_unavailable'
        assert time.monotonic()-start<.1
    finally:release.set();display_release.set();assert p.close(2)['clean_shutdown']


def test_periodic_publication_rechecks_verifier_and_increases_original_source_ages(tmp_path):
    from test_projection import scene,batch
    from neusymnav.verification import VerificationOwner
    from neusymnav.visualization.publisher import DisplayPublisher
    clock=[1_000_000_000]
    class PendingVerifier(VerificationOwner):
        def consume(self,commit):
            super().consume(commit)
            self.request(next(iter(commit.snapshot.objects)))
    class Views(Detector):
        def infer(self,obs):return batch(obs)
    class Mapper:
        def update(self,obs):return nav_for(obs)
    publisher=DisplayPublisher(clock_domain=DOMAIN,now_ns=lambda:clock[0])
    p,_,_=pipeline(tmp_path,clock=lambda:clock[0],detector=Views(),mapper=Mapper(),publisher=publisher,
        verifier_factory=lambda owner:PendingVerifier(owner,clock_domain=DOMAIN,now_ns=lambda:clock[0]))
    try:
        p.submit(replace(scene(stamp=1_000_000_000),clock_domain=DOMAIN))
        wait_for(lambda:publisher.read_latest() is not None and publisher.read_latest().hierarchy.object_revision==1)
        first=publisher.read_latest();oid=next(iter(first.sources.verification.objects))
        assert first.sources.verification.objects[oid].status=='unverified'
        clock[0]=11_000_000_001
        wait_for(lambda:publisher.read_latest().publication_sequence>first.publication_sequence)
        second=publisher.read_latest()
        assert second.hierarchy.object_revision==first.hierarchy.object_revision==1
        assert second.sources.nav.source==first.sources.nav.source
        assert second.sources.nav.capture_monotonic_ns==1_000_000_000
        assert second.metrics.source_age_ns['map']==second.metrics.source_age_ns['objects']==10_000_000_001
        assert second.metrics.source_age_ns['verification']==10_000_000_001
        assert second.sources.verification.objects[oid].status=='unknown'
        assert p.fast_semantics() is None
    finally:assert p.close(2)['clean_shutdown']


def test_verified_display_dto_rejects_missing_committed_gallery():
    from types import SimpleNamespace
    bad=SimpleNamespace(episode_id='episode',object_revision=1,
        objects={'id':SimpleNamespace(status='verified',object_revision=1,best_views=())})
    with pytest.raises(ValueError,match='verified.*committed'):
        Pipeline._display_verification(bad)


@pytest.mark.parametrize('payload',[-1,0,True,1.5])
def test_scheduler_rejects_invalid_accounting_bytes(payload):
    scheduler=KeyframeScheduler()
    with pytest.raises(ValueError,match='payload'):
        scheduler.offer(Entry(source(),payload,1.))
    assert scheduler.snapshot()['payload_bytes']==0


def test_region_failure_during_composition_aborts_dependent_publication(tmp_path,monkeypatch):
    from neusymnav.hierarchy.composer import HierarchyComposer
    from neusymnav.visualization.publisher import DisplayPublisher
    entered=threading.Event();release=threading.Event();original=HierarchyComposer.compose
    def slow(self,*args,**kwargs):entered.set();release.wait(2);return original(self,*args,**kwargs)
    monkeypatch.setattr(HierarchyComposer,'compose',slow)
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Regions:
        def update(self,nav):
            if nav.revision>1:raise RuntimeError('region failed during composition')
            return RegionSnapshot('episode',1,nav.revision,'f',{},False)
    publisher=DisplayPublisher(clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p,_,_=pipeline(tmp_path,mapper=Mapper(),region_factory=Regions,publisher=publisher)
    try:
        p.submit(source());assert entered.wait(1)
        p.submit(source(1));wait_for(lambda:bool(p.telemetry()['health']['failed']))
        release.set();report=p.close(2)
        assert not report['clean_shutdown']
        assert publisher.read_latest() is None,'failed dependency published as complete'
    finally:release.set();p.close(2)
