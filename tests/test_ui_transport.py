from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
import pytest
from test_display_snapshot import make_publisher


def test_transport_roundtrip_preserves_images_and_source_revision():
    from neusymnav.runtime.ui_transport import encode_publication,decode_publication
    envelope=make_publisher()[0].read_latest()
    payload=encode_publication(envelope)
    decoded=decode_publication(payload)
    assert decoded.hierarchy.map_revision==envelope.hierarchy.map_revision
    assert decoded.sources.rgb.source==envelope.sources.rgb.source
    assert np.array_equal(decoded.sources.rgb.pixels,envelope.sources.rgb.pixels)
    assert decoded.sources.best_views[0].evidence_ref==envelope.sources.best_views[0].evidence_ref
    assert decoded.sources.verification.objects.keys()==envelope.sources.verification.objects.keys()


def test_transport_bounds_history_and_wire_bytes():
    from neusymnav.runtime.ui_transport import encode_publication,decode_publication
    envelope=make_publisher()[0].read_latest()
    objects=envelope.sources.objects
    key=next(iter(objects.objects));obj=objects.objects[key]
    updated=replace(obj,evidence_refs=tuple(str(i) for i in range(100000)))
    objects=replace(objects,objects={**objects.objects,key:updated})
    sources=replace(envelope.sources,objects=objects,best_views=())
    envelope=replace(envelope,sources=sources)
    payload=encode_publication(envelope)
    decoded=decode_publication(payload)
    assert len(decoded.sources.objects.objects[key].evidence_refs)<=32
    assert json.loads(payload)['projection']['object_history']=='last32_plus_displayed_evidence'
    with pytest.raises(ValueError,match='bound|cap'):encode_publication(envelope,max_bytes=100)


def test_actual_ui_subprocess_and_ack(tmp_path,monkeypatch):
    from neusymnav.runtime.ui_transport import UiProcess,UiEndpoint
    from neusymnav.visualization.publisher import UiCommand,UiCommandAck
    from uuid import uuid4
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    root=Path(__file__).parents[1]
    script=root/'src'/'neusymnav'/'runtime'/'ui_transport.py'
    now=time.monotonic_ns()
    def handle(command):return UiCommandAck(command.request_uuid,'accepted',None,time.monotonic_ns(),'clock')
    process=UiProcess(tmp_path,python=sys.executable,script=script,clock_domain='clock',command_handler=handle,smoke_exit_ms=700)
    try:
        endpoint=UiEndpoint(tmp_path,clock_domain='clock')
        command=UiCommand(str(uuid4()),'pause','test',now,'clock')
        endpoint.submit(command)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            acks=endpoint.read_acks()
            if acks:break
            time.sleep(.01)
        assert acks[0].request_uuid==command.request_uuid
        assert acks[0].status=='accepted'
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not (tmp_path/'ready.json').exists():time.sleep(.01)
        ready=json.loads((tmp_path/'ready.json').read_text())
        assert ready['pid']!=os.getpid()
        assert ready['desktop']=='run_desktop'
    finally:assert process.close(2.)['clean_shutdown']


def test_ui_diagnostics_remain_bounded_after_noisy_child(tmp_path):
    from neusymnav.runtime.ui_transport import UiProcess
    script=tmp_path/'noisy.py';script.write_text('import sys,time\nsys.stdout.write("x"*4000000);sys.stdout.flush();time.sleep(5)\n')
    process=UiProcess(tmp_path/'ipc',python=sys.executable,script=script,clock_domain='clock',command_handler=lambda c:None)
    try:
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if (tmp_path/'ipc'/'desktop.log').exists() and (tmp_path/'ipc'/'desktop.log').stat().st_size>65536:break
            time.sleep(.01)
    finally:assert process.close(2)['clean_shutdown']
    assert (tmp_path/'ipc'/'desktop.log').stat().st_size<=65536


def test_pending_ui_handler_is_not_reported_clean(tmp_path,monkeypatch):
    import threading
    from uuid import uuid4
    from neusymnav.runtime.ui_transport import UiProcess,UiEndpoint
    from neusymnav.visualization.publisher import UiCommand,UiCommandAck
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    entered=threading.Event();release=threading.Event()
    def handler(command):
        entered.set();release.wait(2)
        return UiCommandAck(command.request_uuid,'accepted',None,time.monotonic_ns(),'clock')
    script=Path(__file__).parents[1]/'src/neusymnav/runtime/ui_transport.py'
    process=UiProcess(tmp_path,python=sys.executable,script=script,clock_domain='clock',command_handler=handler)
    endpoint=UiEndpoint(tmp_path,clock_domain='clock')
    endpoint.submit(UiCommand(str(uuid4()),'pause','test',time.monotonic_ns(),'clock'))
    try:
        assert entered.wait(1)
        start=time.monotonic();report=process.close(.1)
        assert time.monotonic()-start<.4
        assert not report['clean_shutdown'] and report['command_thread_pending']
    finally:release.set();assert process.close(2)['clean_shutdown']


def test_ui_close_does_not_wait_for_diagnostic_disk_fsync(tmp_path,monkeypatch):
    import threading
    from neusymnav.runtime import ui_transport
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    ui=ui_transport.UiProcess(tmp_path/'ipc',python=sys.executable,script=script,
        clock_domain='clock',command_handler=lambda c:None)
    entered=threading.Event();release=threading.Event();finished=threading.Event();reports=[]
    original=ui_transport._write_atomic
    def stalled(path,payload):
        if path.name=='desktop.log':entered.set();release.wait(2)
        return original(path,payload)
    monkeypatch.setattr(ui_transport,'_write_atomic',stalled)
    thread=threading.Thread(target=lambda:(reports.append(ui.close(.05)),finished.set()))
    thread.start()
    try:
        assert entered.wait(1)
        assert finished.wait(.15),'close(.05) is blocked in diagnostic filesystem IO after its deadline'
        assert reports[0]['diagnostics_pending']
        assert not reports[0]['clean_shutdown']
    finally:
        release.set();thread.join(3)
        assert ui.close(1)['clean_shutdown']


def test_ui_log_failure_never_claims_clean_shutdown(tmp_path,monkeypatch):
    from neusymnav.runtime import ui_transport
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    ui=ui_transport.UiProcess(tmp_path/'ipc',python=sys.executable,script=script,
        clock_domain='clock',command_handler=lambda c:None)
    original=ui_transport._write_atomic
    def broken(path,payload):
        if path.name=='desktop.log':raise OSError('injected diagnostic IO failure')
        return original(path,payload)
    monkeypatch.setattr(ui_transport,'_write_atomic',broken)
    result=ui.close(1)
    assert not result['clean_shutdown'] and not result['diagnostics_pending']
    assert 'injected diagnostic IO failure' in result['diagnostics_error']
    assert not ui.close(.1)['clean_shutdown']



def test_ui_close_quota_release_stays_in_pending_finalizer(tmp_path):
    import threading
    from neusymnav.runtime import ui_transport
    entered=threading.Event();release=threading.Event()
    class Quota:
        def reserve(self,*args):pass
        def release(self,*args):entered.set();release.wait(2)
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    ui=ui_transport.UiProcess(tmp_path/'ipc',python=sys.executable,script=script,
        clock_domain='clock',command_handler=lambda c:None,quota=Quota())
    try:
        start=time.monotonic();result=ui.close(.1)
        assert time.monotonic()-start<.3
        assert entered.is_set()
        assert not result['clean_shutdown'] and result['diagnostics_pending']
    finally:
        release.set()
        assert ui.close(1)['clean_shutdown']
