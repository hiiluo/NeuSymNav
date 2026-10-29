from pathlib import Path
import sys,time
import pytest
from neusymnav.runtime.gpu_provider import NvidiaSmiProvider


def proc(tmp_path,pid,parent,start):
    d=tmp_path/str(pid);d.mkdir(exist_ok=True)
    fields=['S',str(parent)]+['0']*17+[str(start)]+['0']*4
    (d/'stat').write_text(f'{pid} (fixture) '+ ' '.join(fields))
    t=d/'task'/str(pid);t.mkdir(parents=True,exist_ok=True)
    children=[]
    for candidate in tmp_path.iterdir():
        if candidate.name.isdecimal() and (candidate/'stat').exists():
            if (candidate/'stat').read_text().split(')')[-1].split()[1]==str(pid):children.append(candidate.name)
    (t/'children').write_text(' '.join(children))
    parent_task=tmp_path/str(parent)/'task'/str(parent)
    if parent_task.exists():
        f=parent_task/'children';previous=f.read_text().split() if f.exists() else []
        f.write_text(' '.join(dict.fromkeys([*previous,str(pid)])))


def tool(tmp_path,rows,*,delay=0,uuid='GPU-fixture'):
    p=tmp_path/'nvidia-smi'
    p.write_text('#!'+sys.executable+'\nimport sys,time\ntime.sleep('+str(delay)+')\nprint('+repr(uuid)+' if "--query-gpu=uuid" in sys.argv else '+repr(rows)+')\n')
    p.chmod(0o700);return p


def provider(tmp_path,rows,**kw):
    root=tmp_path/'proc';root.mkdir();proc(root,10,1,100);proc(root,11,10,200);proc(root,99,1,300)
    return NvidiaSmiProvider(executable=tool(tmp_path,rows,**kw),gpu_uuid='GPU-fixture',root_pid=10,proc_root=root),root


def test_only_process_tree_selected_gpu_memory_counted(tmp_path):
    p,_=provider(tmp_path,'10, GPU-fixture, 2\n11, GPU-fixture, 3\n99, GPU-fixture, 50\n11, GPU-other, 99')
    r=p(time.monotonic_ns()+1_000_000_000)
    assert r.used_bytes==5*1024**2 and r.unavailable_reason is None


@pytest.mark.parametrize('rows',['10, GPU-fixture, N/A','10, GPU-fixture, 2\n10, GPU-fixture, 3','broken'])
def test_ambiguous_gpu_output_null(tmp_path,rows):
    p,_=provider(tmp_path,rows);r=p(time.monotonic_ns()+1_000_000_000)
    assert r.used_bytes is None and r.unavailable_reason


def test_absent_device_and_deadline_are_unsupported(tmp_path):
    p,_=provider(tmp_path,'',uuid='GPU-other');assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None
    other=tmp_path/'other';other.mkdir();p,_=provider(other,'10, GPU-fixture, 2',delay=.3)
    before=time.monotonic();r=p(time.monotonic_ns()+50_000_000)
    assert time.monotonic()-before<.25 and r.used_bytes is None


def test_pid_reuse_during_query_is_not_attributed(tmp_path):
    p,root=provider(tmp_path,'10, GPU-fixture, 2')
    original=p._query;calls=[]
    def query(*a,**kw):
        result=original(*a,**kw);calls.append(1)
        if len(calls)%2==0:proc(root,11,10,999+len(calls))
        return result
    p._query=query
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None


def test_output_bound_and_no_compute_rows_explicit_zero(tmp_path):
    p,_=provider(tmp_path,'');assert p(time.monotonic_ns()+1_000_000_000).used_bytes==0
    other=tmp_path/'other';other.mkdir();p,_=provider(other,'x'*70000)
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None


def test_oversized_deadline_never_attempts_subprocess(tmp_path):
    p,_=provider(tmp_path,'')
    assert p(10**10000).used_bytes is None


def test_read_only_gpu_query_does_not_leave_descendant_on_output_overflow(tmp_path):
    import os
    p,root=provider(tmp_path,'')
    pidfile=tmp_path/'descendant.pid'
    script=p.executable
    script.write_text('#!'+sys.executable+'\nimport sys,subprocess,time\n'+
        'if "--query-gpu=uuid" in sys.argv:print("GPU-fixture")\n'+
        'else:\n child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(20)"])\n'+f' open({str(pidfile)!r},"w").write(str(child.pid))\n'+
        ' print("x"*70000,flush=True)\n time.sleep(20)\n')
    assert p(time.monotonic_ns()+500_000_000).used_bytes is None
    pid=int(pidfile.read_text())
    deadline=time.monotonic()+.5
    def alive():
        try:
            state=Path(f'/proc/{pid}/stat').read_text().split(')')[1].split()[0]
            return state!='Z'
        except FileNotFoundError:return False
    while alive() and time.monotonic()<deadline:time.sleep(.005)
    try:assert not alive()
    finally:
        if alive():os.kill(pid,9)


def test_provider_obeys_existing_sampler_nanosecond_deadline_seam(tmp_path):
    p,_=provider(tmp_path,'10, GPU-fixture, 3')
    from neusymnav.runtime.resources import ResourceSampler,ResourceReading
    sampler=ResourceSampler(provider=lambda:ResourceReading(time.monotonic_ns(),1,1),
                            gpu_provider=p,interval_s=.01,gpu_interval_s=.01)
    sampler.start()
    try:
        deadline=time.monotonic()+1
        while sampler.snapshot()['gpu']['samples']==0 and time.monotonic()<deadline:
            time.sleep(.001)
    finally:
        result=sampler.close(timeout_s=.5)
    assert result['gpu']['samples']>0
    assert result['gpu']['support']>0, result['gpu']
    assert result['gpu']['sampled_peak_bytes']==3*1024**2



@pytest.mark.parametrize('stage',['initialize','register'])
def test_selector_failure_after_spawn_always_reaps_private_query(tmp_path,monkeypatch,stage):
    import neusymnav.runtime.gpu_provider as module
    p,_=provider(tmp_path,'',delay=.3)
    launched=[];original_popen=module.subprocess.Popen;original_selector=module.selectors.DefaultSelector
    def tracked(*a,**kw):
        child=original_popen(*a,**kw);launched.append(child);return child
    def broken_selector():
        if stage=='initialize':raise OSError('fixture selector unavailable')
        selector=original_selector()
        def fail(*a,**kw):raise OSError('fixture registration unavailable')
        selector.register=fail;return selector
    monkeypatch.setattr(module.subprocess,'Popen',tracked)
    monkeypatch.setattr(module.selectors,'DefaultSelector',broken_selector)
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None
    assert launched and all(child.poll() is not None for child in launched)


def test_malformed_stat_and_device_row_cap_do_not_escape_or_support(tmp_path):
    p,root=provider(tmp_path,'')
    (root/'11/stat').write_text('11 (short) S 10')
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None
    other=tmp_path/'other';other.mkdir();p,_=provider(other,'',uuid='GPU-fixture\n'+'GPU-other\n'*4096)
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None


def test_seconds_float_deadline_is_rejected_as_wrong_api_unit(tmp_path):
    p,_=provider(tmp_path,'')
    assert p(time.monotonic()+1).used_bytes is None


def test_unrelated_missing_proc_does_not_invalidate_gpu_scope(tmp_path):
    p,root=provider(tmp_path,'10, GPU-fixture, 2')
    (root/'98').mkdir()
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes==2*1024**2


def test_gpu_scope_retry_uses_fresh_queries_and_retains_diagnostics(tmp_path):
    p,root=provider(tmp_path,'10, GPU-fixture, 2');original=p._query;calls=[]
    def changing(arg,deadline):
        value=original(arg,deadline);calls.append(arg)
        if len(calls)==2:proc(root,12,10,400)
        return value
    p._query=changing
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes==2*1024**2
    assert len(calls)==4
    d=p.diagnostics()
    assert d['attempts']==2 and d['scope_changes']==1 and d['failed_attempts']==1


def test_gpu_persistent_selected_missing_scope_stays_null(tmp_path):
    p,root=provider(tmp_path,'10, GPU-fixture, 2')
    (root/'10/task/10/children').write_text('11 12')
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None
    assert p.diagnostics()['attempts']==3
    assert p.diagnostics()['missing_processes']==3


def test_missing_query_executable_is_query_error_not_scope_missing_process(tmp_path):
    p,_=provider(tmp_path,'10, GPU-fixture, 2')
    p.executable.unlink()
    assert p(time.monotonic_ns()+1_000_000_000).used_bytes is None
    d=p.diagnostics()
    assert d['query_errors']==1 and d['missing_processes']==0 and d['attempts']==1


@pytest.mark.parametrize('value',[True,0,4,10**1000])
def test_gpu_retry_limit_is_bounded_before_work(tmp_path,value):
    root=tmp_path/'proc';root.mkdir();proc(root,10,1,100)
    with pytest.raises(ValueError):
        NvidiaSmiProvider(executable=tool(tmp_path,''),gpu_uuid='GPU-fixture',root_pid=10,proc_root=root,max_attempts=value)


def test_gpu_retries_share_one_absolute_deadline(tmp_path):
    p,_=provider(tmp_path,'10, GPU-fixture, 2')
    calls=[]
    def late(arg,deadline):
        calls.append(arg);time.sleep(.02);return 'GPU-fixture'
    p._query=late
    assert p(time.monotonic_ns()+5_000_000).used_bytes is None
    d=p.diagnostics()
    assert d['attempts']==1 and d['deadline_exhaustions']==1


def test_sampler_exposes_builtin_gpu_diagnostics_in_separate_sidecar(tmp_path):
    from neusymnav.runtime.resources import ResourceSampler,ResourceReading
    p,_=provider(tmp_path,'10, GPU-fixture, 2')
    sampler=ResourceSampler(provider=lambda:ResourceReading(time.monotonic_ns(),1,1),gpu_provider=p)
    sampler.start()
    try:
        deadline=time.monotonic()+1
        while sampler.snapshot()['gpu']['samples']==0 and time.monotonic()<deadline:time.sleep(.001)
    finally:result=sampler.close(timeout_s=.5)
    d=sampler.provider_diagnostics()
    assert d['rss'] is None and d['gpu']['attempts']>=1
    assert result['gpu']['support']>=1
    assert 'provider_diagnostics' not in result


@pytest.mark.parametrize('error',[ValueError('late parse'),OSError('late read'),__import__('subprocess').TimeoutExpired('fake',.01)])
def test_late_query_exception_is_deadline_exhaustion(tmp_path,monkeypatch,error):
    from types import SimpleNamespace
    from neusymnav.runtime import gpu_provider as module
    p,_=provider(tmp_path,'10, GPU-fixture, 2');clock=[1_000_000_000]
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic_ns=lambda:clock[0],monotonic=lambda:clock[0]/1e9))
    monkeypatch.setattr(p,'_tree',lambda deadline:{10:(1,100)})
    calls=[]
    def late(arg,deadline):
        calls.append(arg)
        clock[0]+=60_000_000
        raise error
    p._query=late
    result=p(1_050_000_000)
    assert result.used_bytes is None and result.unavailable_reason=='provider_timeout'
    assert p.diagnostics()['deadline_exhaustions']==1
    assert p.diagnostics()['query_errors']==0
    assert len(calls)==1
