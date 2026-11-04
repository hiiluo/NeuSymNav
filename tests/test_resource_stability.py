import os

from neusymnav.runtime.resources import ProcTreeProvider


def test_failed_rss_attempt_keeps_bounded_diagnostic_context(monkeypatch):
    provider = ProcTreeProvider(max_attempts=1)
    def fail(pid):
        raise ValueError('diagnostic evidence')
    monkeypatch.setattr(provider, '_rss', fail)
    reading = provider()
    assert reading.rss_bytes is None and reading.read_errors == 1
    failure = provider.diagnostics()['last_failure']
    assert failure == {'stage': 'rss', 'pid': os.getpid(),
                       'exception': 'ValueError', 'reason': 'diagnostic evidence'}


def test_real_proc_process_and_thread_churn():
    import subprocess
    import sys
    import threading
    import time

    stop = threading.Event()
    def churn():
        while not stop.is_set():
            worker = threading.Thread(target=lambda: None)
            worker.start()
            worker.join()
            child = subprocess.Popen([sys.executable, '-c', 'pass'])
            child.wait()
    worker = threading.Thread(target=churn)
    worker.start()
    provider = ProcTreeProvider()
    readings = []
    try:
        end = time.monotonic() + 2
        while time.monotonic() < end and len(readings) < 250:
            reading = provider()
            assert (reading.rss_bytes is not None or reading.read_errors or
                    reading.missing_processes or reading.identity_changes or
                    reading.scope_truncated)
            readings.append(reading)
    finally:
        stop.set()
        worker.join(timeout=5)
    assert not worker.is_alive() and len(readings) >= 10
    print('samples', len(readings), 'unsupported', sum(r.rss_bytes is None for r in readings),
          'diagnostics', provider.diagnostics())


def test_failed_sample_context_survives_later_recovered_attempt(monkeypatch):
    provider = ProcTreeProvider(max_attempts=2, retry_wait_s=0)
    real_rss = provider._rss
    calls = 0
    def fail_three_times(pid):
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise ValueError('permanent' if calls <= 2 else 'transient')
        return real_rss(pid)
    monkeypatch.setattr(provider, '_rss', fail_three_times)
    assert provider().rss_bytes is None
    assert provider().rss_bytes is not None
    diagnostics = provider.diagnostics()
    assert diagnostics['last_failure']['reason'] == 'transient'
    assert diagnostics['last_failed_sample']['reason'] == 'permanent'


def test_mm_less_thread_error_includes_bounded_identity_context(tmp_path):
    from test_thread_rss_fallback import group, status
    provider = group(tmp_path)
    path = tmp_path/'10/task/11/status'
    path.write_text('Name:\tworker\n' + status(10, 11, state='R (running)', threads=2, rss=None))
    reading = provider()
    assert reading.rss_bytes is None and reading.read_errors == 1
    reason = provider.diagnostics()['last_failed_sample']['reason']
    for expected in ('live thread RSS unavailable', 'tid=11', 'state=R',
                     'threads=2', 'leader=Z', 'start=100', 'comm=worker'):
        assert expected in reason
    assert len(reason) <= 160


def test_mm_less_thread_does_not_hide_other_shared_mm(tmp_path):
    from test_thread_rss_fallback import group, status
    provider = group(tmp_path, tids=(11, 12), rss=123)
    (tmp_path/'10/task/11/status').write_text(status(10, 11, state='R (running)', threads=3, rss=None))
    reading = provider()
    assert reading.rss_bytes == 123 * 1024 and reading.process_count == 1
    assert not reading.read_errors


def test_no_live_thread_rss_remains_unknown(tmp_path):
    from test_thread_rss_fallback import group, status
    provider = group(tmp_path, tids=(11, 12), rss=None)
    for tid in (11, 12):
        (tmp_path/f'10/task/{tid}/status').write_text(status(10, tid, threads=3, rss=None))
    reading = provider()
    assert reading.rss_bytes is None and reading.read_errors == 1


def test_other_thread_malformed_identity_invalidates_shared_mm(tmp_path):
    from test_thread_rss_fallback import group, status
    provider = group(tmp_path, tids=(11, 12), rss=123)
    (tmp_path/'10/task/12/status').write_text(status(10, 99, threads=3, rss=None))
    reading = provider()
    assert reading.rss_bytes is None and reading.identity_changes == 1


def test_missing_child_leader_children_remains_unknown_and_reports_path(tmp_path):
    from test_resource_sampling import write_process
    write_process(tmp_path, 10, 1, 100, 2)
    write_process(tmp_path, 11, 10, 200, 3)
    (tmp_path/'10/task/10/children').write_text('11')
    missing = tmp_path/'11/task/11/children'
    missing.unlink()
    provider = ProcTreeProvider(root_pid=10, proc_root=tmp_path, retry_wait_s=0)
    reading = provider()
    assert reading.rss_bytes is None and reading.missing_processes == 1
    diagnostics = provider.diagnostics()
    assert diagnostics['attempts'] == 3 and diagnostics['attempt_limit_exhaustions'] == 1
    assert diagnostics['last_failed_sample']['stage'] == 'census_before'
    assert str(missing) in diagnostics['last_failed_sample']['reason']
    missing.write_text('')
    later = provider()
    assert later.rss_bytes == 5 * 1024
    assert reading.rss_bytes is None
