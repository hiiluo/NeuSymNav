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


def test_cloud_source_match_compares_frame_key_fields_not_wire_encoding():
    from neusymnav.contracts import FrameKey
    from neusymnav.runtime.ui_transport import _matches_graph_source
    key=FrameKey('episode','primary-rgbd',9)
    source=dict(episode_id='episode',sensor_id='primary-rgbd',frame_index=9)
    assert _matches_graph_source(key,source)
    assert not _matches_graph_source(key,{**source,'frame_index':10})


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
    process=UiProcess(tmp_path,python=sys.executable,script=script,clock_domain='clock',command_handler=handle,
        recording_root=tmp_path/'recording',smoke_exit_ms=700)
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


def test_ui_close_flushes_and_confirms_render_of_final_graph_publication(tmp_path,monkeypatch):
    from neusymnav.runtime.ui_transport import UiProcess,decode_publication
    from neusymnav.backends.hydra.graph_adapter import HydraGraphProjection
    from neusymnav.visualization.publisher import DisplaySources
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    publisher,hierarchy,metrics,*_=make_publisher()
    projection=HydraGraphProjection(1,'e','run',6,'a'*64,(),(),{},None,False,False,None,'available',{}, {})
    metrics={**metrics,'sources':replace(metrics['sources'],hydra_graph=projection)}
    script=Path(__file__).parents[1]/'src/neusymnav/runtime/ui_transport.py'
    ui=UiProcess(tmp_path,python=sys.executable,script=script,clock_domain='clock',command_handler=lambda c:None,
        recording_root=tmp_path/'recording')
    deadline=time.monotonic()+3
    while time.monotonic()<deadline and not (tmp_path/'ready.json').exists():time.sleep(.01)
    assert (tmp_path/'ready.json').exists()

    ui.publish(hierarchy,metrics)
    report=ui.close(4.)

    assert report['clean_shutdown']
    envelope=decode_publication((tmp_path/'publication.json').read_bytes())
    assert envelope.sources.hydra_graph.graph_revision==6
    rendered=json.loads((tmp_path/'rendered.json').read_text())
    assert rendered['publication_sequence']==envelope.publication_sequence
    assert rendered['hydra_graph_revision']==6
    assert rendered['hydra_graph_source'] is None
    assert rendered['display_cloud_revision'] is None
    assert rendered['display_cloud_graph_lag_ns'] is None
    assert rendered['hydra_cloud_reader']['shutdown']['clean_shutdown']
    assert rendered['hydra_cloud_reader']['pending']==0


def test_ui_close_stops_waiting_and_persists_logs_when_child_exits_before_render(tmp_path):
    from neusymnav.runtime.ui_transport import UiProcess
    script=tmp_path/'crash.py'
    script.write_text('print("TEST_UI_EARLY_EXIT",flush=True)\n')
    ui=UiProcess(tmp_path/'ipc',python=sys.executable,script=script,clock_domain='clock',command_handler=lambda c:None)
    publisher,hierarchy,metrics,*_=make_publisher()
    ui.publish(hierarchy,metrics)
    deadline=time.monotonic()+2
    while time.monotonic()<deadline and not (ui.root/'publication.json').exists():time.sleep(.005)
    assert (ui.root/'publication.json').exists()
    ui.process.wait(timeout=2)

    started=time.monotonic();report=ui.close(.8);elapsed=time.monotonic()-started

    assert elapsed<.3
    assert not report['clean_shutdown'] and not report['final_publication_rendered']
    assert 'TEST_UI_EARLY_EXIT' in (ui.root/'desktop.log').read_text()


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


def test_consumed_ui_acks_remain_in_bounded_persistent_audit(tmp_path):
    """Removing ACK mailboxes must not erase the actor and pause evidence."""
    from uuid import uuid4
    from neusymnav.runtime.ui_transport import UiProcess,UiEndpoint
    from neusymnav.visualization.publisher import UiCommand,UiCommandAck
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    def handle(command):
        rejected=command.action=='stop'
        return UiCommandAck(command.request_uuid,'rejected' if rejected else 'accepted',
            'test rejection' if rejected else None,time.monotonic_ns(),'clock')
    ui=UiProcess(tmp_path/'ipc',python=sys.executable,script=script,clock_domain='clock',command_handler=handle)
    endpoint=UiEndpoint(tmp_path/'ipc',clock_domain='clock');commands=[]
    try:
        for index in range(66):
            command=UiCommand(str(uuid4()),'pause' if index%2==0 else 'stop','desktop',time.monotonic_ns(),'clock')
            commands.append(command);endpoint.submit(command)
            deadline=time.monotonic()+2;acks=[]
            while not acks and time.monotonic()<deadline:
                acks=endpoint.read_acks();time.sleep(.001)
            assert acks and acks[0].request_uuid==command.request_uuid
        assert not list((tmp_path/'ipc'/'acks').glob('*.json'))
        assert not (tmp_path/'ipc'/'diagnostics.json').exists(),'disk persistence belongs to finalizer'
    finally:assert ui.close(2)['clean_shutdown']
    audit=json.loads((tmp_path/'ipc'/'diagnostics.json').read_text())
    assert audit['commands_seen']==66
    assert len(audit['command_history'])==64
    first,last=audit['command_history'][0],audit['command_history'][-1]
    assert first['command']['request_uuid']==commands[2].request_uuid
    assert first['command']['action']=='pause' and first['command']['source']=='desktop'
    assert first['command']['requested_monotonic_ns']==commands[2].requested_monotonic_ns
    assert first['ack']['status']=='accepted' and first['ack']['reason'] is None
    assert last['command']['request_uuid']==commands[-1].request_uuid
    assert last['ack']['status']=='rejected' and last['ack']['reason']=='test rejection'
    assert last['ack']['handled_monotonic_ns']>=last['command']['requested_monotonic_ns']
    assert last['ack_published'] and last['error'] is None
    assert (tmp_path/'ipc'/'diagnostics.json').stat().st_size<=128*1024


@pytest.mark.parametrize('failure',['malformed','handler','ack_write'])
def test_ui_audit_retains_transport_failures(tmp_path,monkeypatch,failure):
    from uuid import uuid4
    from neusymnav.runtime import ui_transport
    from neusymnav.visualization.publisher import UiCommand,UiCommandAck
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    def handle(command):
        if failure=='handler':raise RuntimeError('handler failed')
        return UiCommandAck(command.request_uuid,'accepted',None,time.monotonic_ns(),'clock')
    ui=ui_transport.UiProcess(tmp_path/'ipc',python=sys.executable,script=script,clock_domain='clock',command_handler=handle)
    original=ui_transport._write_atomic
    def write(path,payload):
        if failure=='ack_write' and path.parent.name=='acks':raise OSError('ACK disk failed')
        return original(path,payload)
    monkeypatch.setattr(ui_transport,'_write_atomic',write)
    command=UiCommand(str(uuid4()),'pause','desktop',time.monotonic_ns(),'clock')
    path=ui.root/'commands'/(command.request_uuid+'.json')
    try:
        if failure=='malformed':original(path,b'{not JSON')
        else:ui.endpoint.submit(command)
        deadline=time.monotonic()+2
        while path.exists() and time.monotonic()<deadline:time.sleep(.001)
        assert not path.exists()
    finally:assert ui.close(2)['clean_shutdown']
    record=json.loads((ui.root/'diagnostics.json').read_text())['command_history'][0]
    assert not record['ack_published'] and record['error']
    assert (record['command'] is None)==(failure=='malformed')
    assert (record['ack'] is not None)==(failure=='ack_write')
    if failure=='ack_write':assert record['ack']['status']=='accepted'


@pytest.mark.parametrize('character',['\x01','"'])
def test_ui_audit_bounds_escaped_fields_and_marks_modified_evidence(tmp_path,monkeypatch,character):
    from uuid import uuid4
    from neusymnav.runtime.ui_transport import UiProcess
    from neusymnav.visualization.publisher import UiCommand,UiCommandAck
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    def handle(command):
        return UiCommandAck(command.request_uuid,'rejected',character*(100000 if character=='\x01' else 256),time.monotonic_ns(),command.clock_domain)
    ui=UiProcess(tmp_path/'ipc',python=sys.executable,script=script,clock_domain='clock',command_handler=handle)
    from neusymnav.runtime import ui_transport
    original=ui_transport._write_atomic
    def write(path,payload):
        if path.parent.name=='acks':raise OSError(character*1000)
        return original(path,payload)
    monkeypatch.setattr(ui_transport,'_write_atomic',write)
    try:
        for _ in range(64):
            command=UiCommand(str(uuid4()),'pause',character*128,time.monotonic_ns(),character*128)
            ui.endpoint.submit(command)
            path=ui.root/'commands'/(command.request_uuid+'.json')
            deadline=time.monotonic()+2
            while path.exists() and time.monotonic()<deadline:time.sleep(.001)
            assert not path.exists()
    finally:assert ui.close(2)['clean_shutdown']
    payload=(ui.root/'diagnostics.json').read_bytes()
    assert len(payload)<=128*1024
    record=json.loads(payload)['command_history'][-1]
    assert 'reason' in record['ack']['modified_fields']
    assert record['ack']['status']=='rejected'
    assert not record['ack_published'] and record['error']
