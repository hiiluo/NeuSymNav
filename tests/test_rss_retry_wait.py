"""One fixed provider deadline covers full fresh trials and explicit waits."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from neusymnav.runtime.resources import ProcTreeProvider,ResourceSampler
from test_resource_sampling import write_process


def fake_clock(monkeypatch,*,start=1_000_000_000):
    import neusymnav.runtime.resources as resources
    import neusymnav.runtime.proc_scope as scope
    now=[start];waits=[]
    def sleep(seconds):waits.append(seconds);now[0]+=int(round(seconds*1e9))
    clock=SimpleNamespace(monotonic_ns=lambda:now[0],sleep=sleep)
    monkeypatch.setattr(resources,'time',clock);monkeypatch.setattr(scope,'time',clock)
    return now,waits


def test_later_full_fresh_trial_can_measure_after_exit_settles_without_repairing_prior_null(tmp_path,monkeypatch):
    write_process(tmp_path,10,1,100,2)
    clock,waits=fake_clock(monkeypatch)
    # The real scoped read is transiently unavailable until the declared exit
    # settles150ms later; original rapid three trials necessarily stay null.
    settled_at=clock[0]+150_000_000;reads=[];censuses=[]
    original_rss=ProcTreeProvider._rss;original_census=ProcTreeProvider._census
    def rss(self,pid):
        reads.append((id(self),clock[0]))
        if clock[0]<settled_at:raise ValueError('exit transition still lacks VmRSS')
        return original_rss(self,pid)
    def census(self,deadline):censuses.append((id(self),clock[0]));return original_census(self,deadline)
    monkeypatch.setattr(ProcTreeProvider,'_rss',rss);monkeypatch.setattr(ProcTreeProvider,'_census',census)
    before=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.5)
    failed=before();assert failed.rss_bytes is None and before.diagnostics()['attempts']==3
    new=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.5,retry_wait_s=.2)
    supported=new()
    assert supported.rss_bytes==2048 and supported.sampled_at_ns>=settled_at
    assert failed.rss_bytes is None
    assert new.diagnostics()['attempts']==2 and new.diagnostics()['failed_attempts']==1
    assert new.diagnostics()['retries']==1
    assert [stamp for ident,stamp in reads if ident==id(new)]==[1_010_000_000,1_210_000_000]
    assert len([x for x in censuses if x[0]==id(new)])==3
    assert waits==[.005,.005,.2]


@pytest.mark.parametrize('value',[True,False,None,'0.2',[],{},-.001,.250001,float('inf'),float('-inf'),float('nan'),10**1000,-10**1000])
def test_invalid_wait_rejects_before_any_proc_read(tmp_path,monkeypatch,value):
    reads=[]
    def stat(self,pid):reads.append(pid);raise AssertionError('invalid option reached proc')
    monkeypatch.setattr(ProcTreeProvider,'_stat',stat)
    with pytest.raises(ValueError,match='retry_wait_s'):
        ProcTreeProvider(root_pid=10,proc_root=tmp_path,retry_wait_s=value)
    assert reads==[]


@pytest.mark.parametrize('wait,want',[(0,[]),(.25,[.25,.25])])
def test_wait_endpoints_keep_three_attempts_bounded(tmp_path,monkeypatch,wait,want):
    write_process(tmp_path,10,1,100,2);clock,waits=fake_clock(monkeypatch)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=1,retry_wait_s=wait)
    def fail(pid):raise FileNotFoundError('persistent scoped failure')
    monkeypatch.setattr(p,'_rss',fail)
    r=p();d=p.diagnostics()
    assert r.rss_bytes is None and r.missing_processes==1
    assert waits==want and d['attempts']==3 and d['failed_attempts']==3
    assert d['attempt_limit_exhaustions']==1


def test_third_trial_uses_one_deadline_and_never_reuses_partial_sum(tmp_path,monkeypatch):
    write_process(tmp_path,10,1,100,100);write_process(tmp_path,11,10,200,3)
    clock,waits=fake_clock(monkeypatch);p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.5,retry_wait_s=.2)
    original=p._rss;root_reads=[];deadlines=[];census=p._census
    def scoped(deadline):deadlines.append(deadline);return census(deadline)
    def read(pid):
        if pid==10:root_reads.append(clock[0])
        if pid==11 and clock[0]<1_350_000_000:raise ValueError('last thread still exiting')
        return original(pid)
    monkeypatch.setattr(p,'_census',scoped);monkeypatch.setattr(p,'_rss',read)
    r=p();d=p.diagnostics()
    assert r.rss_bytes==103*1024 and r.sampled_at_ns==1_400_000_000
    assert root_reads==[1_000_000_000,1_200_000_000,1_400_000_000]
    assert waits==[.2,.2] and set(deadlines)=={1_500_000_000}
    assert d['attempts']==3 and d['failed_attempts']==2 and d['read_errors']==2


def test_wait_clips_to_remaining_budget_and_cannot_begin_late_third_trial(tmp_path,monkeypatch):
    write_process(tmp_path,10,1,100,2);clock,waits=fake_clock(monkeypatch)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.3,retry_wait_s=.2)
    calls=[]
    def fail(pid):calls.append(clock[0]);raise FileNotFoundError('not yet reaped')
    monkeypatch.setattr(p,'_rss',fail)
    r=p();d=p.diagnostics()
    assert r.rss_bytes is None and r.scope_truncated
    assert calls==[1_000_000_000,1_200_000_000] and waits==[.2,.1]
    assert d['attempts']==2 and d['failed_attempts']==2 and d['deadline_exhaustions']==1


def test_elapsed_budget_before_retry_skips_sleep_and_new_trial(tmp_path,monkeypatch):
    write_process(tmp_path,10,1,100,2);clock,waits=fake_clock(monkeypatch)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.1,retry_wait_s=.2)
    def fail(pid):clock[0]+=101_000_000;raise FileNotFoundError('gone after budget')
    monkeypatch.setattr(p,'_rss',fail)
    r=p();assert r.rss_bytes is None and r.scope_truncated and waits==[]
    assert p.diagnostics()['attempts']==1 and p.diagnostics()['deadline_exhaustions']==1


def test_scheduler_oversleep_cannot_credit_new_trial(tmp_path,monkeypatch):
    import neusymnav.runtime.resources as resources
    write_process(tmp_path,10,1,100,2);clock,waits=fake_clock(monkeypatch)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.5,retry_wait_s=.2)
    calls=[]
    def fail(pid):calls.append(1);raise ValueError('not yet reaped')
    def oversleep(seconds):waits.append(seconds);clock[0]+=600_000_000
    monkeypatch.setattr(p,'_rss',fail);monkeypatch.setattr(resources.time,'sleep',oversleep)
    r=p();assert r.rss_bytes is None and r.scope_truncated
    assert len(calls)==1 and waits==[.2] and p.diagnostics()['deadline_exhaustions']==1


def test_pending_close_during_provider_wait_is_not_clean_then_reaps(tmp_path,monkeypatch):
    import threading,time
    import neusymnav.runtime.resources as resources
    write_process(tmp_path,10,1,100,2)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.5,retry_wait_s=.2)
    entered=threading.Event();release=threading.Event()
    def sleep(seconds):entered.set();assert release.wait(2)
    def fail(pid):raise ValueError('persistent no VmRSS')
    # Isolate the provider module's clock rather than replacing time.sleep on
    # the shared Python module used by Event/Thread internals.
    monkeypatch.setattr(resources,'time',SimpleNamespace(monotonic_ns=time.monotonic_ns,monotonic=time.monotonic,sleep=sleep))
    monkeypatch.setattr(p,'_rss',fail)
    s=ResourceSampler(provider=p)
    s.start()
    try:
        assert entered.wait(1);r=s.close(timeout_s=.01)
        assert r['worker_pending'] and not r['complete'] and r['rss']['samples']==0
    finally:release.set();r=s.close(timeout_s=1)
    assert not r['worker_pending'] and r['rss']['samples']==0


def test_supported_later_cap_breach_still_triggers_callback_and_incomplete(tmp_path,monkeypatch):
    import threading
    write_process(tmp_path,10,1,100,2)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.5,retry_wait_s=.02)
    original=p._rss;calls=[];breach=threading.Event();payloads=[]
    def transient(pid):
        calls.append(pid)
        if len(calls)==1:raise ValueError('exit transition')
        return original(pid)
    def callback(payload):payloads.append(payload);breach.set()
    monkeypatch.setattr(p,'_rss',transient)
    s=ResourceSampler(provider=p,rss_cap_bytes=1024,on_cap_breach=callback)
    s.start()
    try:assert breach.wait(1)
    finally:r=s.close(timeout_s=.5)
    assert payloads==[dict(resource='rss',sampled_bytes=2048,cap_bytes=1024)]
    assert r['cap_breached'] and not r['complete'] and p.diagnostics()['failed_attempts']>=1


def test_all_exiting_r_tasks_without_vmrss_remain_null(tmp_path):
    from test_thread_rss_fallback import group,status
    p=group(tmp_path,rss=None)
    p.retry_wait_s=0
    assert p().rss_bytes is None
    assert p.diagnostics()['read_errors']==1
