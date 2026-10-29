"""Declared idle-lane sampling retains raw sources and strict actual offers."""
import threading
from dataclasses import replace
import pytest
from neusymnav.contracts import MotionCommand,NavigationDecision
from neusymnav.runtime.scheduler import KeyframeScheduler,Entry,KeyframePolicy
from neusymnav.objects.store import ObjectOwner
from neusymnav.runtime import Pipeline
from neusymnav.runtime.workers import Journal
from test_runtime_scheduling import source,wait_for,Detector,DOMAIN,AllFrames,nav_for


def make_pipeline(root,*,mode='capacity_deferred',policy=None,**kw):
    detector=kw.pop('detector',Detector())
    owner=kw.pop('owner_factory',lambda:ObjectOwner(root/'objects',episode_id='episode',
        primary_sensor_id='rgbd',floor_id='f',detector_profile_id='fixture',vocabulary_id='v1',
        clock_domain=DOMAIN,now_ns=lambda:1_000_000_000))
    return Pipeline(root,episode_id='episode',primary_sensor_id='rgbd',floor_id='f',clock_domain=DOMAIN,
        owner_factory=owner,detector_factory=lambda:detector,now_ns=lambda:1_000_000_000,
        keyframe_policy=policy or AllFrames(),keyframe_sampling=mode,**kw)


def test_recording_capacity_defers_before_policy_and_processes_only_current_next_source(tmp_path,monkeypatch):
    # Without the preselection gate, the blocked durable recorder causes actual
    # rejected/missing offers and mutates policy on captures that were deferred.
    entered=threading.Event();release=threading.Event();original=Journal.accept
    class Policy(AllFrames):
        def __init__(self):self.proposed=[];self.committed=[]
        def propose(self,obs):self.proposed.append(obs.key.frame_index);return super().propose(obs)
        def commit(self,obs):self.committed.append(obs.key.frame_index)
    policy=Policy()
    def blocked(self,obs):entered.set();assert release.wait(2);return original(self,obs)
    monkeypatch.setattr(Journal,'accept',blocked)
    p=make_pipeline(tmp_path,policy=policy)
    try:
        p.submit(source());assert entered.wait(1)
        for index in range(1,6):p.submit(source(index))
        assert policy.proposed==[0] and policy.committed==[0]
        assert p.semantic_sampling_snapshot()==dict(schema_version=1,mode='capacity_deferred',
            policy_version='idle-semantic-v1',seen=6,deferred_capacity=5,policy_evaluated=1,
            policy_unselected=0,offered=1,counter_saturated=False)
        assert p.telemetry()['missing']==0
        release.set();wait_for(lambda:p.telemetry()['committed']==1)
        wait_for(lambda:not p.scheduler.semantic_busy())
        p.submit(source(6));wait_for(lambda:p.telemetry()['committed']==2)
        assert policy.proposed==[0,6]
    finally:
        release.set();report=p.close(2)
    assert report['recorder_certificate']['complete']
    assert report['semantic_sampling']['seen']==7
    assert report['semantic_sampling']['offered']==2


@pytest.mark.parametrize('stage',['reserved','durable','dispatch','detector','commit'])
def test_every_semantic_stage_defers_without_transferring_worker_wait_to_submit(tmp_path,monkeypatch,stage):
    # Dropping reserved, durable, dispatch or inflight from the predicate would
    # permit policy evaluation while one selected event is still outstanding.
    entered=threading.Event();release=threading.Event()
    def block():entered.set();assert release.wait(3)
    if stage=='reserved':
        original=KeyframeScheduler.next_to_record
        def next_to_record(self):
            with self.lock:ready=any(e.state=='reserved' for e in self.pending)
            if ready:block()
            return original(self)
        monkeypatch.setattr(KeyframeScheduler,'next_to_record',next_to_record)
    elif stage=='durable':
        original=KeyframeScheduler.take_next
        def take_next(self,persist):
            with self.lock:ready=bool(self.pending and self.pending[0].state=='durable')
            if ready:block()
            return original(self,persist)
        monkeypatch.setattr(KeyframeScheduler,'take_next',take_next)
    elif stage=='dispatch':
        original=Journal.watermark
        def watermark(self,index=None):
            if index is not None:block()
            return original(self,index)
        monkeypatch.setattr(Journal,'watermark',watermark)
    class Slow(Detector):
        def infer(self,obs):
            if stage=='detector':block()
            return super().infer(obs)
    class Owner(ObjectOwner):
        def commit(self,*a,**kw):
            if stage=='commit':block()
            return super().commit(*a,**kw)
    def owner():return Owner(tmp_path/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='f',
        detector_profile_id='fixture',vocabulary_id='v1',clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p=make_pipeline(tmp_path,detector=Slow(),owner_factory=owner)
    try:
        p.submit(source());assert entered.wait(1)
        # Run submit on another thread so an accidental long lock is observed
        # through a bounded event, instead of hanging the entire test harness.
        done=threading.Event();errors=[]
        def submit():
            try:
                for i in range(1,4):p.submit(source(i))
            except Exception as exc:errors.append(exc)
            finally:done.set()
        producer=threading.Thread(target=submit);producer.start()
        assert done.wait(.3),'submit waited for semantic worker'
        producer.join(1);assert not errors
        s=p.semantic_sampling_snapshot()
        assert s['seen']==4 and s['deferred_capacity']==3 and s['offered']==1
        assert p.telemetry()['missing']==0
    finally:release.set();report=p.close(3)
    assert report['clean_shutdown'] and report['recorder_certificate']['complete']


def test_scheduler_busy_covers_standalone_dispatch_and_every_pending_state():
    s=KeyframeScheduler();assert not s.semantic_busy()
    e=Entry(source(),100,1.)
    assert s.offer(e)[0] and s.semantic_busy()
    assert s.next_to_record() is e and s.semantic_busy()
    s.accepted(e,'source');assert s.semantic_busy()
    assert s.take_next(lambda i:None) is e and s.semantic_busy()
    s.complete(e);assert not s.semantic_busy()
    s.dispatch_pending=True
    assert s.semantic_busy()


def test_two_concurrent_submissions_select_once_when_first_policy_evaluation_is_paused(tmp_path):
    entered=threading.Event();release=threading.Event();detector_entered=threading.Event();release_detector=threading.Event()
    class Policy(AllFrames):
        def __init__(self):self.calls=[]
        def propose(self,obs):
            self.calls.append(obs.key.frame_index)
            if obs.key.frame_index==0:entered.set();assert release.wait(2)
            return super().propose(obs)
    class Slow(Detector):
        def infer(self,obs):detector_entered.set();assert release_detector.wait(3);return super().infer(obs)
    policy=Policy();p=make_pipeline(tmp_path,policy=policy,detector=Slow());errors=[]
    def submit(obs):
        try:p.submit(obs)
        except Exception as exc:errors.append(exc)
    a=threading.Thread(target=submit,args=(source(),));b=threading.Thread(target=submit,args=(source(1),))
    try:
        a.start();assert entered.wait(1);b.start();release.set();a.join(1);b.join(1)
        assert not a.is_alive() and not b.is_alive() and not errors
        assert detector_entered.wait(1)
        assert policy.calls==[0]
        s=p.semantic_sampling_snapshot();assert s['seen']==2 and s['deferred_capacity']==1 and s['offered']==1
    finally:
        release.set();release_detector.set();a.join(1);b.join(1);p.close(3)


def test_deferred_primary_does_not_mutate_real_novelty_policy_and_keeps_capture_nav_sources(tmp_path):
    entered=threading.Event();release=threading.Event();mapped=[];captures=[]
    class Slow(Detector):
        def infer(self,obs):entered.set();assert release.wait(3);return super().infer(obs)
    class Mapper:
        def update(self,obs):mapped.append(obs.key);return nav_for(obs,obs.key.frame_index+1)
    from neusymnav.runtime.observability import RunMeasurements
    from neusymnav.runtime.measurements import MeasurementContext
    class Observer(RunMeasurements):
        def capture(self,obs):captures.append(obs.key);return super().capture(obs)
    observer=Observer(MeasurementContext('sampling-attempt','episode',DOMAIN,'a'*64,'b'*64,None,('rgbd','nav')))
    class Guard:
        def bind_nav(self,nav,**pose):self.nav=nav
        def filter(self,decision,latest,now):return MotionCommand(latest.key,self.nav.revision,now,now+10_000_000,DOMAIN,.1,0.,'sampling-test',latest.capture_monotonic_ns)
    class Navigator:
        def step(self,nav,xy,yaw,now):return NavigationDecision(None,((0.,0.),),.1,0.,nav.revision,'sampling-test')
    class Actuator:
        def robot_pose(self,obs):return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=DOMAIN,pose_version=obs.pose_version,robot_xy=(0.,0.),yaw_rad=0.)
        def execute(self,command):return dict(executed=command.linear_mps!=0,reason=command.reason)
    policy=KeyframePolicy();p=make_pipeline(tmp_path,policy=policy,detector=Slow(),mapper=Mapper(),measurements=observer,guard=Guard(),navigator=Navigator())
    try:
        p.submit(source());assert entered.wait(1)
        previous=(policy.previous_yaw,policy.rotation,policy.last)
        p.submit(source(1,shift=1.))
        wait_for(lambda:source(1).key in mapped)
        assert (policy.previous_yaw,policy.rotation,policy.last)==previous
        depth=source(0,modality='depth_only');p.submit(depth)
        wait_for(lambda:p.telemetry()['source_age_ns']['depth']==0 and p._latest_nav is not None and p._latest_nav.source==depth.key)
        assert p.control_step(Actuator())['executed']
        assert not release.is_set()
        assert captures==[source().key,source(1).key,depth.key]
        with pytest.raises(ValueError,match='order'):p.submit(source(1))
        assert p.semantic_sampling_snapshot()['seen']==2
    finally:release.set();p.close(3)


def test_actual_payload_rejection_stays_offered_missing_and_incomplete(tmp_path):
    p=make_pipeline(tmp_path,byte_cap=100)
    try:p.submit(source())
    finally:r=p.close(2)
    assert r['semantic_sampling']['offered']==1 and r['semantic_sampling']['deferred_capacity']==0
    assert r['recorder_certificate']['missing_count']==1 and not r['recorder_certificate']['complete']
    assert r['metrics']['scheduler']['counts']['rejected']==1


def test_default_mode_keeps_real_rejections_and_old_journal_identity(tmp_path,monkeypatch):
    entered=threading.Event();release=threading.Event();original=Journal.accept
    def block(self,obs):entered.set();assert release.wait(3);return original(self,obs)
    monkeypatch.setattr(Journal,'accept',block)
    # Omitted keyword uses the exact historical identity and selection path.
    from test_runtime_scheduling import pipeline
    p,_,_=pipeline(tmp_path)
    try:
        p.submit(source());assert entered.wait(1)
        for i in range(1,4):p.submit(source(i))
    finally:release.set();r=p.close(3)
    assert not r['recorder_certificate']['complete'] and r['recorder_certificate']['missing_count']>0
    s=r['semantic_sampling'];assert s['mode']=='novelty' and s['policy_version']=='all-primary-novelty-v1'
    assert s['seen']==s['policy_evaluated']==s['offered']==4 and s['deferred_capacity']==0
    p2,_,_=pipeline(tmp_path)
    try:assert 'keyframe_sampling' not in p2.telemetry()['configuration']
    finally:assert not p2.close(2)['recorder_certificate']['complete']


def test_capacity_mode_is_journal_identity_and_profile_is_not_changed_by_pipeline(tmp_path):
    profile='fixture:sampling-capacity_deferred'
    p=make_pipeline(tmp_path,actual_profile=profile)
    p.submit(source());wait_for(lambda:p.telemetry()['committed']==1);r=p.close(2)
    assert r['actual_profile']==profile and r['metrics']['configuration']['keyframe_sampling']=='capacity_deferred'
    resumed=make_pipeline(tmp_path,actual_profile=profile)
    try:assert resumed.telemetry()['journal']['committed']==1
    finally:assert resumed.close(2)['clean_shutdown']
    mismatched=make_pipeline(tmp_path,mode='novelty',actual_profile=profile)
    assert not mismatched.close(2)['clean_shutdown']


@pytest.mark.parametrize('mode',[None,True,1,'','capacity','CAPACITY_DEFERRED',[],{}])
def test_sampling_mode_rejected_before_worker_or_run_creation(tmp_path,mode):
    path=tmp_path/'not-created'
    with pytest.raises(ValueError,match='keyframe_sampling'):make_pipeline(path,mode=mode)
    assert not path.exists()


def test_policy_unselected_and_invalid_lifecycle_populations_are_distinct(tmp_path):
    class Never:
        def propose(self,obs):return False,None,0.
        def commit(self,obs):raise AssertionError('never selected')
    p=make_pipeline(tmp_path,policy=Never())
    try:
        p.submit(source());p.submit(source(0,modality='depth_only'))
        with pytest.raises(ValueError):p.submit(replace(source(1),clock_domain='wrong'))
        with p._lock:p._paused=True
        p.submit(source(1))
        s=p.semantic_sampling_snapshot()
        assert s['seen']==1 and s['policy_evaluated']==1 and s['policy_unselected']==1 and s['offered']==0
        assert p.telemetry()['missing']==2
        s['seen']=999;assert p.semantic_sampling_snapshot()['seen']==1
    finally:p.close(2)


def test_sampling_counter_capacity_fails_closed_without_broken_conservation(tmp_path):
    class Never:
        def propose(self,obs):return False,None,0.
        def commit(self,obs):raise AssertionError('not selected')
    p=make_pipeline(tmp_path,policy=Never())
    # Boundary setup represents 2**63-1 prior unselected captures; executing
    # that many public calls cannot be a finite regression fixture.
    maximum=(1<<63)-1
    with p._lock:p._semantic_sampling.update(seen=maximum,policy_evaluated=maximum,policy_unselected=maximum)
    try:
        p.submit(source());s=p.semantic_sampling_snapshot()
        assert s['counter_saturated'] and s['seen']==maximum
        assert s['seen']==s['deferred_capacity']+s['policy_evaluated']
        assert s['policy_evaluated']==s['policy_unselected']+s['offered']
    finally:r=p.close(2)
    assert not r['clean_shutdown'] and not r['recorder_certificate']['complete']
    assert 'semantic_sampling' in r['failed']


def test_accepted_capacity_event_recovers_without_recounting_deferred_or_loss(tmp_path):
    class Fails(Detector):
        def infer(self,obs):raise RuntimeError('accepted input retained for recovery')
    p=make_pipeline(tmp_path,detector=Fails())
    p.submit(source());wait_for(lambda:bool(p.telemetry()['health']['failed']))
    r=p.close(2);assert r['pending']==1 and not r['recorder_certificate']['complete']
    recovered=make_pipeline(tmp_path)
    try:
        assert recovered.telemetry()['recovered']==1
        assert recovered.semantic_sampling_snapshot()['seen']==0
        recovered.submit(source(1));wait_for(lambda:recovered.telemetry()['committed']==2)
    finally:rr=recovered.close(2)
    assert rr['clean_shutdown'] and not rr['recorder_certificate']['complete']


def test_full_raw_archive_and_capture_trace_keep_deferred_primary_population(tmp_path):
    from neusymnav.recording.writer import ReplayWriter
    from test_runtime_measurement_wiring import session
    entered=threading.Event();release=threading.Event();m=session()
    class Slow(Detector):
        def infer(self,obs):entered.set();assert release.wait(3);return super().infer(obs)
    p=make_pipeline(tmp_path/'run',detector=Slow(),measurements=m)
    raw=ReplayWriter(tmp_path/'raw')
    try:
        first=source();assert raw.append(first);p.submit(first);assert entered.wait(1)
        for index in range(1,5):
            obs=source(index);assert raw.append(obs);p.submit(obs)
        assert p.semantic_sampling_snapshot()['deferred_capacity']==4
    finally:
        release.set();report=p.close(3);certificate=raw.close(2)
    assert certificate['complete'] and certificate['written_count']==5 and certificate['missing_count']==0
    artifact=m.finalize(runtime_report=report,resources=None)
    assert artifact['collector']['capture_registry']['retained']==5
    assert artifact['collector']['admission_counts']['offered']==1
    assert artifact['collector']['admission_counts']['rejected']==0


def test_pending_close_cannot_claim_selected_event_was_processed(tmp_path):
    entered=threading.Event();release=threading.Event()
    class Slow(Detector):
        def infer(self,obs):entered.set();assert release.wait(3);return super().infer(obs)
    p=make_pipeline(tmp_path,detector=Slow())
    try:
        p.submit(source());assert entered.wait(1);p.submit(source(1))
        report=p.close(.01)
        assert report['workers_pending'] and report['pending']==1
        assert not report['clean_shutdown'] and not report['recorder_certificate']['complete']
        assert report['semantic_sampling']['deferred_capacity']==1
        assert report['semantic_sampling']['offered']==1
    finally:release.set();final=p.close(3)
    assert final['clean_shutdown'] and final['recorder_certificate']['complete']


def test_recording_failure_is_not_relabeled_capacity_deferral(tmp_path,monkeypatch):
    from neusymnav.runtime.quota import QuotaExceeded
    def failed(self,obs):raise QuotaExceeded('actual admission storage failure')
    monkeypatch.setattr(Journal,'accept',failed)
    p=make_pipeline(tmp_path)
    try:
        p.submit(source());wait_for(lambda:bool(p.telemetry()['health']['failed']))
    finally:report=p.close(2)
    assert 'recorder' in report['failed'] and not report['recorder_certificate']['complete']
    assert report['recorder_certificate']['offered_count']==1 and report['recorder_certificate']['durable_accepted_count']==0
    assert report['semantic_sampling']['offered']==1 and report['semantic_sampling']['deferred_capacity']==0
