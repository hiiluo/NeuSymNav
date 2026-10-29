"""A dead leader's live thread reports one shared address-space RSS value."""
from pathlib import Path
import json
import os
import selectors
import subprocess
import sys
import time

import pytest

from neusymnav.runtime.resources import ProcTreeProvider
from test_resource_sampling import proc_stat, write_process


def status(pid, tid, *, state='S (sleeping)', threads=2, rss=123):
    return (f'State:\t{state}\nTgid:\t{pid}\nPid:\t{tid}\nThreads:\t{threads}\n'
            + ('' if rss is None else f'VmRSS:\t{rss} kB\n'))


def group(root, *, rss=123, tids=(11,), **provider_options):
    write_process(root,10,1,100,1)
    (root/'10/status').write_text(status(10,10,state='Z (zombie)',threads=1+len(tids),rss=None))
    (root/'10/statm').write_text('0 0 0 0 0 0 0\n')
    for tid in tids:
        path=root/'10/task'/str(tid);path.mkdir()
        (path/'children').write_text('')
        (path/'stat').write_text(proc_stat(tid,1,100+tid))
        (path/'status').write_text(status(10,tid,threads=1+len(tids),rss=rss))
    return ProcTreeProvider(root_pid=10,proc_root=root,max_attempts=1,**provider_options)


@pytest.mark.parametrize('rss',[0,123])
def test_live_tid_explicit_rss_is_counted_once_not_leader_statm_zero(tmp_path,rss):
    provider=group(tmp_path,rss=rss,tids=(11,12))
    result=provider()
    assert result.rss_bytes==rss*1024 and result.process_count==1
    assert not result.read_errors and not result.identity_changes


@pytest.mark.parametrize('field,value',[
    ('Tgid','99'),('Pid','12'),('Tgid','10\nTgid:\t10'),
    ('Pid','11\nPid:\t11'),('Threads','3'),('Threads','2\nThreads:\t2'),
    ('VmRSS','123 MB'),('VmRSS','-1 kB'),('VmRSS','123 kB\nVmRSS:\t123 kB'),
    ('State','Z (zombie)'),('State','? (unknown)'),('State','S (sleeping)\nState:\tS (sleeping)'),
])
def test_ambiguous_or_wrong_tid_metadata_remains_null(tmp_path,field,value):
    provider=group(tmp_path)
    path=tmp_path/'10/task/11/status'
    lines=path.read_text().splitlines()
    path.write_text('\n'.join(f'{field}:\t{value}' if line.startswith(field+':') else line for line in lines)+'\n')
    assert provider().rss_bytes is None


@pytest.mark.parametrize('missing',['status','stat','VmRSS','Tgid','Pid','Threads','State'])
def test_missing_live_tid_evidence_remains_null(tmp_path,missing):
    provider=group(tmp_path);path=tmp_path/'10/task/11'
    if missing in ('stat','status'):(path/missing).unlink()
    else:
        text=(path/'status').read_text()
        (path/'status').write_text('\n'.join(line for line in text.splitlines() if not line.startswith(missing+':')))
    assert provider().rss_bytes is None


@pytest.mark.parametrize('field,value',[('ppid','+1'),('starttime','+111'),('starttime','-0'),('pid','12')])
def test_malformed_or_mismatched_tid_stat_identity_remains_null(tmp_path,field,value):
    provider=group(tmp_path);path=tmp_path/'10/task/11/stat'
    text=path.read_text();prefix,tail=text.rsplit(')',1);fields=tail.split()
    if field=='ppid':fields[1]=value
    elif field=='starttime':fields[19]=value
    else:prefix=prefix.replace('11 (','12 (',1)
    path.write_text(prefix+') '+' '.join(fields))
    assert provider().rss_bytes is None


@pytest.mark.parametrize('field,value',[
    ('Tgid','20'),('Pid','20'),('Threads','3'),('Tgid','10\nTgid:\t10'),
    ('Threads','2\nThreads:\t2'),('State','S (sleeping)'),
])
def test_leader_must_identify_exact_zombie_group(tmp_path,field,value):
    provider=group(tmp_path);path=tmp_path/'10/status'
    path.write_text('\n'.join(f'{field}:\t{value}' if line.startswith(field+':') else line for line in path.read_text().splitlines()))
    assert provider().rss_bytes is None


@pytest.mark.parametrize('change',['reuse','taskset','leader_threads','disappear','root_reuse'])
def test_changes_during_live_tid_read_invalidate_trial(tmp_path,monkeypatch,change):
    provider=group(tmp_path);original=Path.open;triggered=False
    def changing(path,*args,**kwargs):
        nonlocal triggered
        handle=original(path,*args,**kwargs)
        if path==tmp_path/'10/task/11/status' and not triggered:
            triggered=True
            if change=='reuse':(tmp_path/'10/task/11/stat').write_text(proc_stat(11,1,999))
            elif change=='root_reuse':(tmp_path/'10/stat').write_text(proc_stat(10,1,999))
            elif change=='taskset':(tmp_path/'10/task/12').mkdir()
            elif change=='leader_threads':(tmp_path/'10/status').write_text(status(10,10,state='Z (zombie)',threads=3,rss=None))
            else:(tmp_path/'10/task/11/stat').unlink()
        return handle
    monkeypatch.setattr(Path,'open',changing)
    assert provider().rss_bytes is None


def test_complete_task_enumeration_is_bounded(tmp_path):
    provider=group(tmp_path,tids=(11,12),max_directory_entries=2)
    result=provider()
    assert result.rss_bytes is None and result.scope_truncated


@pytest.mark.parametrize('kind',['duplicate','noncanonical','oversized_status','oversized_stat'])
def test_ambiguous_or_oversized_task_scope_remains_null(tmp_path,monkeypatch,kind):
    provider=group(tmp_path)
    if kind=='oversized_status':(tmp_path/'10/task/11/status').write_text('x'*65537)
    elif kind=='oversized_stat':(tmp_path/'10/task/11/stat').write_text('x'*8193)
    elif kind=='noncanonical':(tmp_path/'10/task/011').mkdir()
    else:
        original=os.scandir
        class Duplicated:
            def __enter__(self):
                self.entries=original(tmp_path/'10/task');self.items=list(self.entries)
                return iter(self.items+[self.items[-1]])
            def __exit__(self,*args):self.entries.close()
        monkeypatch.setattr(os,'scandir',lambda path:Duplicated() if Path(path)==tmp_path/'10/task' else original(path))
    assert provider().rss_bytes is None


def test_late_thread_status_cannot_extend_original_sample_deadline(tmp_path,monkeypatch):
    import neusymnav.runtime.resources as resources
    provider=group(tmp_path);clock=[1_000_000_000]
    monkeypatch.setattr(resources.time,'monotonic_ns',lambda:clock[0])
    original=Path.open
    def late(path,*args,**kwargs):
        handle=original(path,*args,**kwargs)
        if path==tmp_path/'10/task/11/status':clock[0]+=101_000_000
        return handle
    monkeypatch.setattr(Path,'open',late)
    result=provider()
    assert result.rss_bytes is None and result.scope_truncated


def test_failed_thread_evidence_requires_wholly_fresh_retry(tmp_path,monkeypatch):
    provider=group(tmp_path)
    provider.max_attempts=2
    path=tmp_path/'10/task/11/status';valid=path.read_text();path.write_text(valid.replace('Tgid:\t10','Tgid:\t99'))
    original=provider._rss;calls=[]
    def repair_after_first(pid):
        calls.append(pid)
        try:return original(pid)
        finally:path.write_text(valid)
    monkeypatch.setattr(provider,'_rss',repair_after_first)
    result=provider()
    assert result.rss_bytes==123*1024 and calls==[10,10]
    diagnostics=provider.diagnostics()
    assert diagnostics['failed_attempts']==1 and diagnostics['retries']==1


def test_real_pthread_exit_leader_uses_positive_shared_mm_once(tmp_path):
    code='''import ctypes,os,threading
ready=threading.Event()
def survivor():
 print(threading.get_native_id(),flush=True);ready.set();os.read(0,1)
threading.Thread(target=survivor).start();ready.wait()
ctypes.CDLL(None).pthread_exit(None)
'''
    child=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout,selectors.EVENT_READ)
            assert selector.select(2),'child did not become ready'
        tid=int(child.stdout.readline());deadline=time.monotonic()+2
        while True:
            leader=Path(f'/proc/{child.pid}/status').read_text()
            if '\nState:\tZ ' in '\n'+leader:break
            assert time.monotonic()<deadline
            time.sleep(.001)
        thread_path=Path(f'/proc/{child.pid}/task/{tid}')
        before=(thread_path/'status').read_text();statm=(thread_path/'statm').read_text()
        assert 'VmRSS:' not in leader and 'Threads:\t2' in leader
        assert Path(f'/proc/{child.pid}/statm').read_text().split()==['0']*7
        assert int(statm.split()[1])>0
        provider=ProcTreeProvider(root_pid=child.pid,max_attempts=1)
        result=provider();after=(thread_path/'status').read_text()
        rss=lambda text:int(next(line.split()[1] for line in text.splitlines() if line.startswith('VmRSS:')))*1024
        assert result.process_count==1 and result.rss_bytes is not None and result.rss_bytes>0
        assert min(rss(before),rss(after))-16384<=result.rss_bytes<=max(rss(before),rss(after))+16384
        evidence=dict(pid=child.pid,tid=tid,leader_status=leader,live_status_before=before,live_status_after=after,live_statm=statm,rss_bytes=result.rss_bytes,process_count=result.process_count)
        (tmp_path/'evidence.json').write_text(json.dumps(evidence,indent=2))
    finally:
        child.kill();child.wait(timeout=2);child.stdin.close();child.stdout.close()
    assert not Path(f'/proc/{child.pid}').exists()
