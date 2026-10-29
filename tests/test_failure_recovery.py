"""CPU fault injection and real subprocess kill/recovery; no native claims."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import pytest
from test_runtime_scheduling import pipeline,source,wait_for,Detector,DOMAIN,empty
from neusymnav.runtime.workers import Journal
from neusymnav.runtime import RunQuota,QuotaExceeded


def test_graph_failure_keeps_durable_input_and_poison_no_retry(tmp_path):
    class Fails(Detector):
        def infer(self,obs):self.calls.append(obs.key.frame_index);raise RuntimeError('injected detector crash')
    p,d,_=pipeline(tmp_path,detector=Fails())
    p.submit(source());wait_for(lambda:bool(p.telemetry()['health']['failed']))
    p.submit(source(1));report=p.close(1)
    assert not report['clean_shutdown'] and report['pending']==1 and report['replay_required']
    assert d.calls==[0]
    p2,d2,_=pipeline(tmp_path)
    assert p2.telemetry()['recovered']==1 and d2.calls==[0]
    p2.submit(source(1));wait_for(lambda:p2.telemetry()['committed']==2)
    assert p2.close(2)['clean_shutdown']


def test_recovery_uses_durable_detector_result_after_commit_failure(tmp_path):
    from neusymnav.objects.store import ObjectOwner
    class FailsOwner(ObjectOwner):
        def commit(self,*args):raise RuntimeError('injected commit fault')
    def factory():return FailsOwner(tmp_path/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='f',
        detector_profile_id='fixture',vocabulary_id='v1',clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p,d,_=pipeline(tmp_path,owner_factory=factory)
    p.submit(source());wait_for(lambda:bool(p.telemetry()['health']['failed']));assert not p.close(1)['clean_shutdown']
    p2,d2,_=pipeline(tmp_path)
    assert p2.telemetry()['recovered']==1 and d.calls==[0] and d2.calls==[]
    assert p2.close(2)['clean_shutdown']


def test_close_deadline_reports_pending_and_later_reaps(tmp_path):
    started=threading.Event();release=threading.Event()
    class Slow(Detector):
        def infer(self,obs):started.set();release.wait(4);return empty(obs)
    p,_,_=pipeline(tmp_path,detector=Slow());p.submit(source());assert started.wait(1)
    start=time.monotonic();report=p.close(.03)
    assert time.monotonic()-start<.15
    assert not report['clean_shutdown'] and report['workers_pending'] and report['replay_required']
    release.set();assert p.close(2)['clean_shutdown']


def test_appearance_pending_is_not_clean_even_is_alive_false(tmp_path):
    from neusymnav.perception.appearance_client import AppearanceShutdownPending
    class Encoder:
        is_alive=False
        def close(self):raise AppearanceShutdownPending('Popen has not returned')
    p,_,_=pipeline(tmp_path,encoder_factory=Encoder)
    report=p.close(1)
    assert not report['clean_shutdown'] and 'encoder' in report['workers_pending']
    assert 'AppearanceShutdownPending' in report['cleanup_pending']['encoder']


def test_constructor_factory_failure_rejects_ui_and_admission(tmp_path):
    def fail():raise RuntimeError('missing native detector/model')
    p,_,_=pipeline(tmp_path,owner_factory=fail)
    assert not p.telemetry()['ready'];p.submit(source())
    assert p.telemetry()['durable_accepted']==0
    assert not p.close(1)['clean_shutdown']


def test_raw_total_quota_accounts_staging_wal_tiles_and_reservations(tmp_path):
    for name in ('keyframes/a.tmp','objects/store.sqlite-wal','tiles/archive','pending/refs'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*100)
    q=RunQuota(tmp_path,raw_cap=250,total_cap=600)
    q.reserve('recorder',100,100)
    with pytest.raises(QuotaExceeded):q.reserve('commit',101)
    with pytest.raises(QuotaExceeded):q.reserve('raw',51,51)
    assert all(p.stat().st_size==100 for p in tmp_path.rglob('*') if p.is_file())


def test_corrupt_accepted_source_fails_recovery_and_retains_evidence(tmp_path):
    class Fails(Detector):
        def infer(self,obs):raise RuntimeError('leave accepted input')
    p,_,_=pipeline(tmp_path,detector=Fails());p.submit(source());wait_for(lambda:bool(p.telemetry()['health']['failed']));p.close(1)
    path=tmp_path/'keyframes/frame-000000000000.json';data=path.read_bytes();path.write_bytes(b'X'+data[1:])
    p2,_,_=pipeline(tmp_path)
    assert 'checksum' in p2.close(1)['failed']['graph'] and path.exists()


def test_real_process_kill_recovers_source_identity_and_pending(tmp_path):
    # Producer is a separate OS process with live worker threads. SIGKILL after
    # durable acceptance, before detector completion, is stronger than an
    # exception fixture and exercises SQLite/source fsync recovery.
    root=Path(__file__).resolve().parents[1]
    program='''
import sys,time
from pathlib import Path
from test_runtime_scheduling import pipeline,source,Detector
class Blocks(Detector):
    def infer(self,obs):
        (Path(sys.argv[1])/'detector-entered').write_text('accepted source durable')
        time.sleep(60)
p,_,_=pipeline(Path(sys.argv[1]),detector=Blocks())
p.submit(source())
while True:time.sleep(1)
'''
    env=dict(os.environ,PYTHONPATH=str(root/'tests')+os.pathsep+str(root/'src'))
    proc=subprocess.Popen([sys.executable,'-c',program,str(tmp_path)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        wait_for(lambda:(tmp_path/'detector-entered').exists(),timeout=5)
        proc.kill();assert proc.wait(timeout=3)==-signal.SIGKILL
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        proc.stdout.close();proc.stderr.close()
    p,d,_=pipeline(tmp_path)
    assert p.telemetry()['recovered']==1 and d.calls==[0]
    journal=Journal(tmp_path,p._config)
    recovered=journal.load(0);assert recovered.key==source().key and recovered.geometry_hash==source().geometry_hash
    assert recovered.clock_domain==DOMAIN and recovered.capture_monotonic_ns==1_000_000_000
    assert journal.next_pending() is None;journal.close()
    assert p.close(2)['clean_shutdown']


def test_reboot_clock_mismatch_cannot_resume_old_ledger(tmp_path):
    from neusymnav.runtime import Pipeline
    p,_,_=pipeline(tmp_path);p.submit(source());wait_for(lambda:p.telemetry()['committed']==1);p.close(1)
    p2=Pipeline(tmp_path,episode_id='episode',primary_sensor_id='rgbd',floor_id='f',clock_domain='host_monotonic:newboot',
                owner_factory=lambda:None,detector_factory=Detector)
    assert not p2.telemetry()['ready']
    assert 'mismatch' in p2.close(1)['failed']['graph']


@pytest.mark.parametrize('after_consume',[False,True])
def test_real_verifier_ack_failure_recovers_once_without_detector_retry(tmp_path,after_consume):
    from dataclasses import replace
    from test_projection import scene,batch
    from neusymnav.verification import VerificationOwner
    class Views(Detector):
        def infer(self,obs):self.calls.append(obs.key.frame_index);return batch(obs)
    class Interrupted(VerificationOwner):
        def consume(self,result):
            if after_consume:super().consume(result)
            raise RuntimeError('crash between graph commit and verifier ACK')
    def factory(cls):return lambda owner:cls(owner,clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p,d,_=pipeline(tmp_path,detector=Views(),verifier_factory=factory(Interrupted))
    p.submit(replace(scene(stamp=1_000_000_000),clock_domain=DOMAIN))
    wait_for(lambda:bool(p.telemetry()['health']['failed']))
    report=p.close(1)
    assert report['pending']==1 and report['replay_required'] and not report['clean_shutdown']
    p2,d2,_=pipeline(tmp_path,detector=Views(),verifier_factory=factory(VerificationOwner))
    try:
        state=next(iter(p2._verification.objects.values()))
        assert (state.detected_count,state.independent_views)==(1,1)
        assert p2._verification.batch_count==p2._verification.view_count==1
        assert not p2._verification.replay_required
        assert d.calls==[0] and d2.calls==[] and p2.telemetry()['recovered']==1
    finally:assert p2.close(2)['clean_shutdown']


def test_verifier_ledger_must_be_under_the_run_root(tmp_path):
    from neusymnav.verification import VerificationOwner
    outside=tmp_path.parent/(tmp_path.name+'-external-verification')
    p,_,_=pipeline(tmp_path,verifier_factory=lambda owner:VerificationOwner(owner,clock_domain=DOMAIN,root=outside))
    report=p.close(1)
    assert not report['clean_shutdown']
    assert 'VerificationOwner root must be inside' in report['failed']['graph']


def test_replay_reserves_verifier_growth_before_constructing_it(tmp_path):
    p,_,_=pipeline(tmp_path);p.submit(source());wait_for(lambda:p.telemetry()['committed']==1);assert p.close(2)['clean_shutdown']
    used=RunQuota.tree_bytes(tmp_path);called=[]
    from neusymnav.verification import VerificationOwner
    def factory(owner):called.append(True);return VerificationOwner(owner,clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p2,_,_=pipeline(tmp_path,total_cap=used+3*1024**2+1,raw_cap=1024**2,verifier_factory=factory)
    report=p2.close(1)
    assert not called,'verifier grew its ledger without reserved replay capacity'
    assert not report['clean_shutdown'] and 'QuotaExceeded' in report['failed']['graph']


def test_close_deadline_does_not_wait_for_quota_filesystem_scan(tmp_path,monkeypatch):
    entered=threading.Event();release=threading.Event()
    p,_,_=pipeline(tmp_path)
    original=RunQuota.tree_bytes
    def stalled(root):entered.set();release.wait(2);return original(root)
    monkeypatch.setattr(RunQuota,'tree_bytes',staticmethod(stalled))
    p.submit(source());assert entered.wait(1)
    try:
        start=time.monotonic();report=p.close(.03)
        assert time.monotonic()-start<.15,'close waited past deadline for quota telemetry'
        assert not report['clean_shutdown'] and report['workers_pending']
    finally:release.set();p.close(2)


def test_owner_floor_identity_must_match_runtime_before_admission(tmp_path):
    from neusymnav.objects.store import ObjectOwner
    def factory():return ObjectOwner(tmp_path/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='another-floor',
        detector_profile_id='fixture',vocabulary_id='v1',clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    p,_,_=pipeline(tmp_path,owner_factory=factory)
    report=p.close(1)
    assert not report['clean_shutdown'] and not report['metrics']['ready']
    assert 'owner floor_id mismatch' in report['failed']['graph']


@pytest.mark.parametrize('durable_before_dispatch',[False,True])
def test_restart_restores_index_and_capture_admission_watermarks(tmp_path,durable_before_dispatch):
    p,_,_=pipeline(tmp_path)
    if not durable_before_dispatch:
        p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    assert p.close(2)['clean_shutdown']
    if durable_before_dispatch:
        journal=Journal(tmp_path,p._config);journal.accept(source());journal.close()
    p2,_,_=pipeline(tmp_path)
    try:
        with pytest.raises(ValueError,match='order'):p2.submit(source())
        with pytest.raises(ValueError,match='order'):p2.submit(source(1,stamp=999_999_999))
    finally:assert p2.close(2)['clean_shutdown']


def test_recovered_pending_source_never_creates_current_negative(tmp_path):
    from dataclasses import replace
    from test_projection import scene, batch
    from neusymnav.verification import VerificationOwner
    class Views(Detector):
        def infer(self, obs):
            return batch(obs, ((12,12,20,20),) if obs.key.frame_index == 0 else ())
    vf = lambda o: VerificationOwner(o, clock_domain=DOMAIN,
                                    now_ns=lambda: 1_000_000_000)
    p, _, _ = pipeline(tmp_path, detector=Views(), verifier_factory=vf)
    p.submit(replace(scene(stamp=1_000_000_000), clock_domain=DOMAIN))
    wait_for(lambda: p.telemetry()['committed'] == 1)
    assert p.close(2)['clean_shutdown']
    # Exact durable crash boundary: source fsynced + admission row committed,
    # before detector/owner commit. Original capture is within live TTL.
    j = Journal(tmp_path, p._config)
    pending = replace(scene(1, depth=3., stamp=1_000_000_000), clock_domain=DOMAIN)
    j.accept(pending)
    j.close()
    p2, _, _ = pipeline(tmp_path, detector=Views(), verifier_factory=vf)
    try:
        assert p2.telemetry()['recovered'] == 1
        assert p2.fast_semantics() is None
        state = next(iter(p2._verification.objects.values()))
        assert state.negative_views == 0, (
            'recovery-only source was credited as a current negative')
    finally:
        p2.close(2)



def test_recovery_requires_historical_verifier_ack(tmp_path):
    class LegacyVerifier:
        def __init__(self, owner):
            self.calls = []
        def replay(self):
            pass
        def consume(self, result):
            self.calls.append(result)
    p, _, _ = pipeline(tmp_path)
    assert p.close(2)['clean_shutdown']
    journal = Journal(tmp_path, p._config)
    journal.accept(source())
    journal.close()
    p2, _, _ = pipeline(tmp_path, verifier_factory=LegacyVerifier)
    try:
        report = p2.close(2)
        assert not report['clean_shutdown'] and report['replay_required']
        assert report['pending'] == 1
        assert 'historical' in str(report['failed'])
    finally:
        p2.close(2)
