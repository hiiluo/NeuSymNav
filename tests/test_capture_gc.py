"""Cyclic maintenance belongs before sensor capture, with state restored."""
import pytest
from neusymnav.runtime.capture_gc import CaptureGCWindow

class Collector:
    def __init__(self,enabled=True):self.enabled=enabled;self.events=[]
    def isenabled(self):return self.enabled
    def disable(self):self.enabled=False;self.events.append('disable')
    def enable(self):self.enabled=True;self.events.append('enable')
    def collect(self,generation):
        assert self.enabled
        self.events.append(('collect',generation));return 0


def test_collection_before_capture_and_none_inside_control_window():
    gc=Collector();now=[1_000_000_000]
    window=CaptureGCWindow(True,collector=gc,now_ns=lambda:now[0])
    with window:
        gc.events.append('capture')
        assert not gc.isenabled()
        gc.events.append('actuate_and_finish')
    assert gc.events==[('collect',2),'disable','capture','actuate_and_finish','enable']
    assert window.snapshot()['windows']==1


def test_periodic_collection_and_bounded_diagnostics():
    gc=Collector();now=[1_000_000_000];w=CaptureGCWindow(True,collector=gc,now_ns=lambda:now[0])
    for _ in range(1100):
        with w:assert not gc.isenabled()
        now[0]+=1_000_000_000
    assert w.snapshot()['collections']==1100
    assert len(w.snapshot()['events'])==1024
    assert w.snapshot()['events_dropped']==76


def test_exception_restores_original_state():
    gc=Collector();w=CaptureGCWindow(True,collector=gc,now_ns=lambda:1)
    with pytest.raises(RuntimeError,match='sensor'):
        with w:raise RuntimeError('sensor')
    assert gc.isenabled()


def test_preexisting_disabled_gc_not_enabled_or_collected():
    gc=Collector(False);w=CaptureGCWindow(True,collector=gc,now_ns=lambda:1)
    with w:assert not gc.isenabled()
    assert gc.events==[] and not gc.isenabled()


def test_disabled_profile_does_not_touch_process_gc():
    gc=Collector();w=CaptureGCWindow(False,collector=gc,now_ns=lambda:1)
    with w:assert gc.isenabled()
    assert gc.events==[] and w.snapshot()['collections']==0


def test_collection_failure_cannot_leave_gc_disabled():
    gc=Collector()
    def fail(_):raise RuntimeError('collector')
    gc.collect=fail
    with pytest.raises(RuntimeError,match='collector'):
        with CaptureGCWindow(True,collector=gc,now_ns=lambda:1):pass
    assert gc.isenabled()

@pytest.mark.parametrize('value',[True,False])
def test_hydra_profile_accepts_explicit_gc_window(tmp_path,value):
    import json
    from pathlib import Path
    from neusymnav.runtime.configuration import load_config
    data=json.loads(Path('configs/demo-00805.hydra-rolling.local.json').read_text())
    data['runtime']['defer_capture_gc']=value
    p=tmp_path/'gc.json';p.write_text(json.dumps(data))
    assert load_config(p).data['runtime']['defer_capture_gc'] is value

@pytest.mark.parametrize('value',[1,None,'true'])
def test_gc_window_configuration_rejects_non_boolean(tmp_path,value):
    import json
    from pathlib import Path
    from neusymnav.runtime.configuration import load_config
    data=json.loads(Path('configs/demo-00805.hydra-rolling.local.json').read_text())
    data['runtime']['defer_capture_gc']=value
    p=tmp_path/'gc.json';p.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_config(p)


def test_gc_window_covers_current_local_map_guard_and_synchronous_actuation(tmp_path):
    from test_local_control_lane import local_pipeline
    p, body, _ = local_pipeline(tmp_path)
    collector = Collector()
    window = CaptureGCWindow(True, collector=collector, now_ns=lambda: 1_000_000_000)
    build = p._local_map.snapshot
    execute = body.execute
    def measured(*args, **kwargs):
        assert not collector.isenabled()
        return build(*args, **kwargs)
    def actuate(command):
        assert not collector.isenabled()
        assert command.source_capture_monotonic_ns == p._latest_depth.capture_monotonic_ns
        return execute(command)
    p._local_map.snapshot = measured
    body.execute = actuate
    with window:
        assert p.control_step(body)['executed']
    assert collector.isenabled()
    assert collector.events == [('collect', 2), 'disable', 'enable']
    assert window.snapshot()['windows'] == 1
