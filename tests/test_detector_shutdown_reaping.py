"""A killed native process may take longer than the signal helper's grace to reap."""
import subprocess,time
from neusymnav.perception.detector_client import _BoundedProcess


def test_close_uses_remaining_budget_to_observe_native_process_exit(monkeypatch):
    from neusymnav.perception import detector_client
    wire=_BoundedProcess(['unused'],timeout_s=1.,response_limit=1024)
    class Process:
        stdin=stdout=stderr=None
        def __init__(self):self.reaped=False;self.waits=[]
        def poll(self):return 0 if self.reaped else None
        def wait(self,timeout):
            self.waits.append(timeout)
            if timeout<.01:raise subprocess.TimeoutExpired('unused',timeout)
            self.reaped=True;return 0
    wire.process=Process();wire.launch_done.set()
    monkeypatch.setattr(detector_client,'_terminate_process_group',lambda *a,**k:None)
    report=wire.close(.2)
    assert report['clean_shutdown'] and report['process_reaped']
    assert len(wire.process.waits)==1 and .01<=wire.process.waits[0]<=.2


def test_close_keeps_truthful_pending_when_exit_exceeds_shared_deadline(monkeypatch):
    from neusymnav.perception import detector_client
    wire=_BoundedProcess(['unused'],timeout_s=1.,response_limit=1024)
    class Process:
        stdin=stdout=stderr=None
        def poll(self):return None
        def wait(self,timeout):raise subprocess.TimeoutExpired('unused',timeout)
    wire.process=Process();wire.launch_done.set()
    monkeypatch.setattr(detector_client,'_terminate_process_group',lambda *a,**k:None)
    start=time.monotonic();report=wire.close(.02)
    assert not report['clean_shutdown'] and not report['process_reaped']
    assert time.monotonic()-start<.1
