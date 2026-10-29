from pathlib import Path
import pytest
from test_resource_sampling import write_process
from neusymnav.runtime.resources import ProcTreeProvider


def zombie(root,*,state='Z (zombie)',threads=1,statm='0 0 0 0 0 0 0\n'):
    write_process(root,10,1,100,1)
    (root/'10/status').write_text(f'State:\t{state}\nThreads:\t{threads}\n')
    (root/'10/statm').write_text(statm)
    return ProcTreeProvider(root_pid=10,proc_root=root,max_attempts=1)


def test_explicit_single_task_zombie_zero_statm_is_supported(tmp_path):
    p=zombie(tmp_path);r=p()
    assert r.rss_bytes==0 and r.process_count==1 and not r.read_errors


@pytest.mark.parametrize('state,threads,statm',[
    ('S (sleeping)',1,'0 0 0 0 0 0 0'),('Z (zombie)',2,'0 0 0 0 0 0 0'),
    ('Z (zombie)',1,'1 0 0 0 0 0 0'),('Z (zombie)',1,'0 1 0 0 0 0 0'),
    ('Z (zombie)',1,'0 0'),('Z (zombie)',1,'0 0 0 0 0 0 bad')])
def test_missing_rss_without_complete_zero_proof_remains_null(tmp_path,state,threads,statm):
    assert zombie(tmp_path,state=state,threads=threads,statm=statm)().rss_bytes is None


def test_zombie_leader_with_live_task_cannot_report_zero(tmp_path):
    p=zombie(tmp_path)
    task=tmp_path/'10/task/11';task.mkdir();(task/'children').write_text('')
    (task/'status').write_text('State:\tS (sleeping)\nVmRSS:\t123 kB\n')
    assert p().rss_bytes is None


def test_missing_statm_is_not_zero(tmp_path):
    p=zombie(tmp_path);(tmp_path/'10/statm').unlink()
    assert p().rss_bytes is None


def test_actual_zombie_leader_with_verified_live_thread_has_positive_rss():
    import subprocess,sys,time
    code='''import ctypes,threading,time
ready=threading.Event()
def survivor():
 print(threading.get_native_id(),flush=True);ready.set();time.sleep(5)
threading.Thread(target=survivor).start();ready.wait()
ctypes.CDLL(None).pthread_exit(None)
'''
    child=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,text=True)
    try:
        tid=int(child.stdout.readline());deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            status=Path(f'/proc/{child.pid}/status').read_text()
            if '\nState:\tZ ' in '\n'+status:break
            time.sleep(.001)
        assert '\nState:\tZ ' in '\n'+status and 'Threads:\t2' in status
        assert 'VmRSS:' in Path(f'/proc/{tid}/status').read_text()
        result=ProcTreeProvider(root_pid=child.pid,max_attempts=1)()
        assert result.process_count==1 and result.rss_bytes is not None and result.rss_bytes>0
    finally:
        child.kill();child.wait(timeout=2);child.stdout.close()
