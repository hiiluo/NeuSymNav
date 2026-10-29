"""Sampled peaks have honest scope, availability and bounded shutdown semantics."""
from pathlib import Path
from threading import Event
import time
import pytest
from neusymnav.runtime.resources import ProcTreeProvider, ResourceReading, GpuReading, ResourceSampler
from neusymnav.runtime.measurements import BoundedMeasurements
from test_runtime_measurements import context, source


def reading(rss=100, **kw):
    fields = dict(sampled_at_ns=time.monotonic_ns(), rss_bytes=rss, process_count=2,
                  missing_processes=0, read_errors=0, identity_changes=0, scope_truncated=False)
    fields.update(kw)
    return ResourceReading(**fields)


def wait_samples(sampler, minimum=1):
    deadline = time.monotonic()+1
    while sampler.snapshot()['rss']['samples'] < minimum and time.monotonic() < deadline:
        time.sleep(.001)
    assert sampler.snapshot()['rss']['samples'] >= minimum


def test_sampled_peak_and_missing_gpu_are_explicit():
    sampler = ResourceSampler(provider=lambda: reading(123), interval_s=.01)
    sampler.start(); wait_samples(sampler)
    result = sampler.close(timeout_s=.2)
    assert result['rss']['sampled_peak_bytes'] == 123
    assert result['rss']['samples'] >= 1
    assert result['rss']['method'] == 'sampled_process_tree_rss_sum'
    assert result['gpu']['sampled_peak_bytes'] is None
    assert result['gpu']['support'] == 0
    assert result['gpu']['unavailable_reason'] == 'no_usable_provider'
    assert not result['worker_pending']
    assert not result['boundedness_certified']
    assert result['start_requested_monotonic_ns'] <= result['rss']['first_sample_ns']
    assert result['rss']['last_sample_ns'] <= result['stop_requested_monotonic_ns']
    assert result['stop_requested_monotonic_ns'] <= result['shutdown_observed_monotonic_ns']


def test_slow_resource_provider_cannot_block_producers_and_close_reports_pending():
    entered, release = Event(), Event()
    def slow():
        entered.set(); release.wait(2); return reading()
    sampler = ResourceSampler(provider=slow, interval_s=.01)
    sampler.start(); assert entered.wait(.5)
    try:
        meter = BoundedMeasurements(context())
        assert meter.try_record_capture(source(), width=1, height=1)
        assert meter.try_record_control(source(), now_ns=200, clock_domain='host-boot', reason='ok', map_revision=1)
        started = time.monotonic(); result = sampler.close(timeout_s=.01)
        assert time.monotonic()-started < .2
        assert result['worker_pending'] and not result['complete']
        assert result['shutdown_observed_monotonic_ns'] is None
        assert result['rss']['samples'] == 0
    finally:
        release.set()
        assert not sampler.close(timeout_s=.5)['worker_pending']


def test_hung_gpu_does_not_starve_rss_and_honors_shared_close_deadline():
    entered, release = Event(), Event()
    def gpu(deadline_ns):
        assert type(deadline_ns) is int
        entered.set(); release.wait(2); return GpuReading(None, 'timeout')
    sampler = ResourceSampler(provider=lambda: reading(), gpu_provider=gpu, interval_s=.01)
    sampler.start(); assert entered.wait(.5)
    try:
        wait_samples(sampler, 2)
        result = sampler.close(timeout_s=.01)
        assert result['worker_pending'] and result['pending_workers'] == ['gpu']
        assert result['gpu']['sampled_peak_bytes'] is None
    finally:
        release.set(); sampler.close(timeout_s=.5)


def test_cap_breach_callback_outside_lock_and_sampling_cannot_certify_bound():
    called = Event(); reports=[]
    def breached(payload):
        reports.append((payload, sampler.snapshot()))
        called.set()
    sampler = ResourceSampler(provider=lambda: reading(101), rss_cap_bytes=100,
                              on_cap_breach=breached, interval_s=.01)
    sampler.start(); assert called.wait(.5)
    result = sampler.close(timeout_s=.2)
    assert len(reports) == 1
    assert reports[0][0] == dict(resource='rss', sampled_bytes=101, cap_bytes=100)
    assert result['cap_breached'] and not result['complete']
    assert not result['boundedness_certified']


def test_read_errors_and_gpu_unavailable_never_become_zero_usage():
    sampler = ResourceSampler(provider=lambda: reading(None, read_errors=1),
                              gpu_provider=lambda deadline_ns: GpuReading(None, 'no_permission'), interval_s=.01)
    sampler.start(); wait_samples(sampler)
    result = sampler.close(timeout_s=.2)
    assert result['rss']['sampled_peak_bytes'] is None
    assert result['rss']['read_errors'] >= 1
    assert result['gpu']['sampled_peak_bytes'] is None and result['gpu']['support'] == 0
    assert result['gpu']['unavailable_reason'] == 'no_permission'
    assert not result['complete']


def proc_stat(pid, ppid, start):
    # Linux stat fields 3..22: state, ppid, ..., starttime.
    return f'{pid} (command name) S {ppid} ' + ' '.join(['0']*17+[str(start)])


def write_process(root, pid, ppid, start, rss_kib):
    directory = root/str(pid); directory.mkdir(exist_ok=True)
    (directory/'stat').write_text(proc_stat(pid,ppid,start))
    (directory/'status').write_text(f'Name:\tfixture\nVmRSS:\t{rss_kib} kB\n')
    task=directory/'task'/str(pid);task.mkdir(parents=True,exist_ok=True)
    children=[]
    for candidate in root.iterdir():
        if candidate.name.isdecimal() and (candidate/'stat').exists():
            if (candidate/'stat').read_text().split(')')[-1].split()[1]==str(pid):
                children.append(candidate.name)
    (task/'children').write_text(' '.join(children))
    if ppid!=pid and (root/str(ppid)/'task'/str(ppid)).exists():
        parent_children=root/str(ppid)/'task'/str(ppid)/'children'
        previous=parent_children.read_text().split() if parent_children.exists() else []
        parent_children.write_text(' '.join(dict.fromkeys([*previous,str(pid)])))


def test_proc_tree_excludes_unrelated_processes_and_detects_root_pid_reuse(tmp_path):
    write_process(tmp_path, 10, 1, 100, 2)
    write_process(tmp_path, 11, 10, 200, 3)
    write_process(tmp_path, 12, 11, 300, 4)
    write_process(tmp_path, 13, 1, 400, 1000)
    provider = ProcTreeProvider(root_pid=10, proc_root=tmp_path, max_attempts=1)
    first = provider()
    assert first.rss_bytes == 9*1024 and first.process_count == 3
    write_process(tmp_path, 10, 1, 101, 2000)
    churn = provider()
    assert churn.rss_bytes is None and churn.identity_changes >= 1


def test_proc_tree_rechecks_child_identity_around_rss_read(tmp_path, monkeypatch):
    write_process(tmp_path, 10, 1, 100, 2)
    write_process(tmp_path, 11, 10, 200, 3000)
    provider = ProcTreeProvider(root_pid=10, proc_root=tmp_path, max_attempts=1)
    original = provider._rss
    def churn(pid):
        value = original(pid)
        if pid == 11:
            (tmp_path/'11'/'stat').write_text(proc_stat(11,10,201))
        return value
    monkeypatch.setattr(provider, '_rss', churn)
    sample = provider()
    assert sample.rss_bytes is None
    assert sample.identity_changes == 1


def test_proc_scope_cap_and_worker_lifecycle_are_truthful(tmp_path):
    write_process(tmp_path, 10, 1, 100, 2)
    write_process(tmp_path, 11, 10, 200, 3)
    provider = ProcTreeProvider(root_pid=10, proc_root=tmp_path, max_processes=1)
    result = provider()
    assert result.scope_truncated and result.rss_bytes is None
    sampler = ResourceSampler(provider=lambda: reading())
    assert not sampler.close(timeout_s=0)['complete']
    with pytest.raises(RuntimeError): sampler.start()


@pytest.mark.parametrize('kw', [{'interval_s':0}, {'rss_cap_bytes':True}, {'gpu_timeout_s':float('inf')}])
def test_invalid_resource_limits_rejected(kw):
    with pytest.raises((TypeError, ValueError)): ResourceSampler(provider=lambda: reading(), **kw)


def test_backward_sample_clock_and_provider_exception_are_missing_coverage():
    values = iter((reading(100,sampled_at_ns=200), reading(1000,sampled_at_ns=199)))
    def provider():
        return next(values)
    sampler = ResourceSampler(provider=provider, interval_s=.01)
    sampler.start(); wait_samples(sampler,3)
    result = sampler.close(timeout_s=.2)
    assert result['rss']['sampled_peak_bytes'] == 100
    assert result['rss']['support'] == 1
    assert result['rss']['read_errors'] >= 2
    assert not result['complete']


def test_gpu_reply_after_deadline_is_not_a_supported_peak():
    def gpu(deadline_ns):
        time.sleep(.02)
        return GpuReading(9999)
    sampler = ResourceSampler(provider=lambda: reading(), gpu_provider=gpu,
                              gpu_timeout_s=.001, interval_s=.01)
    sampler.start()
    deadline = time.monotonic()+1
    while sampler.snapshot()['gpu']['samples'] < 1 and time.monotonic() < deadline:
        time.sleep(.001)
    result = sampler.close(timeout_s=.2)
    assert result['gpu']['samples'] == 1
    assert result['gpu']['sampled_peak_bytes'] is None
    assert result['gpu']['timeouts'] == 1
    assert result['gpu']['unavailable_reason'] == 'provider_timeout'
    assert not result['complete']


def test_sampler_reports_scope_proof_and_counter_saturation():
    from neusymnav.runtime.resources import MAX_COUNTER
    sampler = ResourceSampler(provider=lambda: reading(None,read_errors=MAX_COUNTER), interval_s=.01)
    sampler.start(); wait_samples(sampler,2)
    result = sampler.close(timeout_s=.2)
    assert result['rss']['read_errors'] == MAX_COUNTER
    assert result['counter_saturated'] and not result['complete']
    assert result['scope_proof']['method'] == 'injected_provider_unverified'


def test_proc_scan_discovers_child_spawned_by_non_main_thread():
    import subprocess
    import sys
    from threading import Thread
    ready = Event(); children=[]
    def spawn():
        child = subprocess.Popen([sys.executable,'-c',
                                  "import time; print('ready',flush=True); time.sleep(10)"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        children.append(child)
        if child.stdout.readline().strip() == 'ready':
            ready.set()
    thread = Thread(target=spawn, daemon=True)
    thread.start()
    try:
        assert ready.wait(2)
        provider = ProcTreeProvider()
        sample = provider()
        # This pytest process owns exactly the one explicitly created child.
        assert sample.process_count == 2
    finally:
        for child in children:
            child.kill(); child.wait(timeout=1)
            child.stdout.close()
        thread.join(1)


def test_unrelated_proc_churn_does_not_invalidate_rooted_sample(tmp_path):
    write_process(tmp_path,10,1,100,2)
    (tmp_path/'99').mkdir()
    result=ProcTreeProvider(root_pid=10,proc_root=tmp_path)()
    assert result.rss_bytes==2*1024,result


def test_unrelated_pids_do_not_exhaust_selected_process_cap(tmp_path):
    write_process(tmp_path,10,1,100,2)
    for pid in range(100,110):write_process(tmp_path,pid,1,pid,1)
    result=ProcTreeProvider(root_pid=10,proc_root=tmp_path,max_processes=2)()
    assert result.rss_bytes==2*1024,result


def test_retry_reaps_missing_child_with_fresh_sample_and_retained_diagnostics(tmp_path,monkeypatch):
    import shutil
    write_process(tmp_path,10,1,100,2);write_process(tmp_path,11,10,200,3)
    provider=ProcTreeProvider(root_pid=10,proc_root=tmp_path)
    original=provider._rss;exited=[]
    def reap(pid):
        value=original(pid)
        if pid==10 and not exited:
            shutil.rmtree(tmp_path/'11');(tmp_path/'10/task/10/children').write_text('')
            exited.append(time.monotonic_ns())
        return value
    monkeypatch.setattr(provider,'_rss',reap)
    result=provider()
    assert result.rss_bytes==2*1024 and result.sampled_at_ns>exited[0]
    diagnostics=provider.diagnostics()
    assert diagnostics['attempts']==2 and diagnostics['failed_attempts']==1
    assert diagnostics['missing_processes']==1
    assert result.missing_processes==0


def test_persistent_missing_selected_child_stays_null_with_bounded_retries(tmp_path):
    write_process(tmp_path,10,1,100,2)
    (tmp_path/'10/task/10/children').write_text('11')
    provider=ProcTreeProvider(root_pid=10,proc_root=tmp_path)
    assert provider().rss_bytes is None
    d=provider.diagnostics()
    assert d['attempts']==3 and d['attempt_limit_exhaustions']==1
    assert d['missing_processes']==3


def test_rooted_census_includes_nonleader_children_and_rejects_unreadable_task(tmp_path):
    write_process(tmp_path,10,1,100,2);write_process(tmp_path,11,10,200,3)
    (tmp_path/'10/task/10/children').write_text('')
    t=tmp_path/'10/task/12';t.mkdir();(t/'children').write_text('11')
    provider=ProcTreeProvider(root_pid=10,proc_root=tmp_path)
    assert provider().rss_bytes==5*1024
    (t/'children').unlink()
    assert provider().rss_bytes is None


def test_retry_budget_is_one_absolute_deadline(tmp_path,monkeypatch):
    write_process(tmp_path,10,1,100,2)
    provider=ProcTreeProvider(root_pid=10,proc_root=tmp_path,sample_timeout_s=.001)
    original=provider._rss
    def late(pid):time.sleep(.01);return original(pid)
    monkeypatch.setattr(provider,'_rss',late)
    assert provider().rss_bytes is None
    d=provider.diagnostics()
    assert d['attempts']==1 and d['deadline_exhaustions']==1


def test_provider_diagnostics_are_separate_and_injected_readings_stay_strict():
    sampler=ResourceSampler(provider=lambda:reading(None,missing_processes=1),interval_s=.01)
    sampler.start();wait_samples(sampler)
    result=sampler.close(timeout_s=.2)
    d=sampler.provider_diagnostics()
    assert d=={'schema_version':1,'rss':None,'gpu':None}
    assert not result['complete'] and result['rss']['support']==0
    assert 'provider_diagnostics' not in result


@pytest.mark.parametrize('kwargs',[{'max_attempts':True},{'max_attempts':0},{'max_attempts':4},
                                    {'sample_timeout_s':0},{'sample_timeout_s':float('inf')}])
def test_invalid_rooted_retry_limits_reject(kwargs):
    with pytest.raises(ValueError):ProcTreeProvider(**kwargs)


def test_live_nonleader_thread_children_remain_in_scope_until_thread_exits():
    import os,subprocess,sys
    from threading import Thread,get_native_id
    ready=Event();release=Event();children=[];tids=[]
    def spawn():
        tids.append(get_native_id())
        children.append(subprocess.Popen([sys.executable,'-c','import time;time.sleep(3)']))
        ready.set();release.wait(2)
    thread=Thread(target=spawn);thread.start()
    try:
        assert ready.wait(1)
        assert str(children[0].pid) in Path(f'/proc/self/task/{tids[0]}/children').read_text().split()
        assert str(children[0].pid) not in Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()
        result=ProcTreeProvider()()
        assert result.rss_bytes is not None and result.process_count==2,result
    finally:
        release.set()
        for child in children:child.kill();child.wait(timeout=1)
        thread.join(1)


@pytest.mark.parametrize('kind',['children-size','directory-entries','duplicate-child','bad-child','short-stat','wrong-parent'])
def test_reachable_scope_boundaries_fail_closed(tmp_path,kind):
    write_process(tmp_path,10,1,100,2);write_process(tmp_path,11,10,200,3)
    kwargs={}
    if kind=='children-size':(tmp_path/'10/task/10/children').write_text('11 '*30000)
    elif kind=='directory-entries':
        extra=tmp_path/'10/task/12';extra.mkdir();(extra/'children').write_text('')
        kwargs['max_directory_entries']=1
    elif kind=='duplicate-child':(tmp_path/'10/task/10/children').write_text('11 11')
    elif kind=='bad-child':(tmp_path/'10/task/10/children').write_text('-11')
    elif kind=='short-stat':(tmp_path/'11/stat').write_text('11 (short) S 10')
    elif kind=='wrong-parent':(tmp_path/'11/stat').write_text(proc_stat(11,99,200))
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path,**kwargs)
    assert p().rss_bytes is None


def test_default_retry_never_repins_reused_root_and_diagnostics_saturate(tmp_path):
    from neusymnav.runtime.resources import MAX_COUNTER
    write_process(tmp_path,10,1,100,2)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path)
    write_process(tmp_path,10,1,101,2)
    p._diagnostics.add(attempts=MAX_COUNTER)
    assert p().rss_bytes is None
    d=p.diagnostics()
    assert d['identity_changes']==3 and d['counter_saturated']
    assert d['attempts']==MAX_COUNTER
    d['identity_changes']=0
    assert p.diagnostics()['identity_changes']==3


def test_sampler_exposes_builtin_diagnostics_without_changing_v1_snapshot(tmp_path):
    write_process(tmp_path,10,1,100,2)
    p=ProcTreeProvider(root_pid=10,proc_root=tmp_path)
    sampler=ResourceSampler(provider=p,interval_s=.01)
    sampler.start();wait_samples(sampler)
    result=sampler.close(timeout_s=.2)
    d=sampler.provider_diagnostics()
    assert d['schema_version']==1 and d['rss']['calls']>=1 and d['gpu'] is None
    assert result['complete'] and result['rss']['support']==result['rss']['samples']
    assert result['schema_version']=='runtime_resource_samples_v1'
    assert 'provider_diagnostics' not in result


def test_fresh_retry_allows_parent_thread_to_reap_exited_child():
    """A transient unreadable child requires a wholly fresh supported census."""
    import os,subprocess,sys
    from threading import Thread
    child=subprocess.Popen([sys.executable,'-c','pass']);trigger=Event();reaped=Event()
    def reap():
        trigger.wait(1)
        time.sleep(.002)
        child.wait(timeout=1);reaped.set()
    thread=Thread(target=reap);thread.start()
    try:
        deadline=time.monotonic()+1
        while ' Z ' not in Path(f'/proc/{child.pid}/stat').read_text() and time.monotonic()<deadline:time.sleep(.001)
        assert ' Z ' in Path(f'/proc/{child.pid}/stat').read_text()
        provider=ProcTreeProvider();original=provider._rss
        def read(pid):
            if pid==child.pid:
                trigger.set()
                raise ValueError('injected unavailable child RSS before reap')
            return original(pid)
        provider._rss=read
        result=provider()
        assert result.rss_bytes is not None and result.process_count==1,result
        diagnostics=provider.diagnostics()
        assert diagnostics['failed_attempts']>=1 and diagnostics['retries']>=1
        assert diagnostics['read_errors']>=1
    finally:
        trigger.set();thread.join(2)
        if not reaped.is_set():child.kill();child.wait(timeout=1)
