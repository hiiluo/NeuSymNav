"""P07 external detector process transport and closed local recipe tests."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import numpy as np
import pytest

from neusymnav.contracts import FrameKey, Observation
from neusymnav.perception.detector_client import DetectorClient, _BoundedProcess


def observation(size=3,index=0):
    return Observation(FrameKey('episode','primary',index),time.monotonic_ns(),'host_monotonic:test',0.,
        np.zeros((size,size,3),np.uint8),np.ones((size,size),np.float32),np.ones((size,size),bool),
        np.eye(3),np.eye(4),'test',0,'rgbd')


def recipe(tmp_path):
    result={}
    for name,filename in [('checkpoint','yoloe-11s-seg.pt'),('encoder','mobileclip_blt.ts'),('taxonomy','taxonomy.json')]:
        p=tmp_path/filename
        if name=='taxonomy':
            p.write_text(json.dumps(dict(schema_version=1,vocabulary_id='test-v1',categories=['chair'],aliases={},provenance='test')))
        else:p.write_bytes(b'explicit-test-fixture')
        result[name+'_path']=str(p)
        result[name+'_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    result.update(checkpoint_license='test fixture only',imgsz=480,max_detections=30,confidence_threshold=.25,device='cpu')
    return result


def client(tmp_path,monkeypatch,mode='success',timeout=.5):
    monkeypatch.setenv('NEUSYMNAV_DETECTOR_STUB_MODE',mode)
    return DetectorClient(python=sys.executable,recipe=recipe(tmp_path),timeout_s=timeout,startup_timeout_s=3.,
                          worker_script=Path(__file__).parent/'fixtures/detector_worker/worker.py')


@pytest.mark.parametrize('mode',['success','partial'])
def test_real_external_process_original_source_empty_complete_batch_and_bounded_close(tmp_path,monkeypatch,mode):
    c=client(tmp_path,monkeypatch,mode)
    obs=observation()
    result=c.infer(obs)
    assert result.source==obs.key and result.geometry_hash==obs.geometry_hash
    assert result.completion=='complete' and not result.cap_reached and result.detections==()
    assert c.is_alive and c.runtime_metadata['python']=='3.12.test'
    report=c.close()
    assert report['clean_shutdown'] and report['process_reaped'] and report['readers_stopped']
    with pytest.raises(RuntimeError,match='closed'):c.infer(replace(obs,key=FrameKey('episode','primary',1)))


@pytest.mark.parametrize('mode',['wrong_source','wrong_geometry','wrong_vocab','bool_version','gt_field','huge_header','truncated'])
def test_malformed_source_geometry_envelope_and_headers_are_terminal(tmp_path,monkeypatch,mode):
    c=client(tmp_path,monkeypatch,mode)
    with pytest.raises((ValueError,EOFError)):c.infer(observation())
    assert not c.is_alive and c.close()['clean_shutdown']


def test_duplicate_source_does_not_infer_twice(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    obs=observation()
    c.infer(obs)
    with pytest.raises(ValueError,match='replay'):c.infer(obs)
    assert not c.is_alive and c.close()['clean_shutdown']


def test_future_capture_and_depth_only_are_rejected_before_launch(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    obs=observation()
    with pytest.raises(ValueError,match='future'):
        c.infer(replace(obs,capture_monotonic_ns=time.monotonic_ns()+10**10))
    with pytest.raises(ValueError,match='rgbd'):c.infer(replace(obs,modality='depth_only'))
    assert not c.is_alive
    assert c.close()['clean_shutdown']


@pytest.mark.parametrize('mode,size',[('timeout',3),('no_read',512)])
def test_whole_operation_deadline_includes_pipe_backpressure(tmp_path,monkeypatch,mode,size):
    c=client(tmp_path,monkeypatch,mode,timeout=.05)
    started=time.monotonic()
    with pytest.raises(TimeoutError):c.infer(observation(size))
    assert time.monotonic()-started<2.
    assert not c.is_alive and c.close()['clean_shutdown']


def test_single_flight_busy_reject_and_concurrent_close_wakes_infer(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch,'timeout',timeout=10.)
    errors=[]
    def infer():
        try:c.infer(observation())
        except Exception as error:errors.append(error)
    t=threading.Thread(target=infer)
    t.start()
    until=time.monotonic()+3.
    while not c.is_alive and time.monotonic()<until:time.sleep(.005)
    with pytest.raises(RuntimeError,match='in flight'):c.infer(observation(index=1))
    report=c.close(timeout_s=1.)
    t.join(1.)
    assert not t.is_alive() and errors
    assert c.close()['clean_shutdown']


def test_timeout_kills_term_ignoring_descendant_and_reaps_group(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch,'child',timeout=.15)
    with pytest.raises(TimeoutError):c.infer(observation())
    text=''.join(c.diagnostics)
    assert 'CHILD_PID=' in text
    pid=int(text.split('CHILD_PID=')[1].splitlines()[0])
    status=Path('/proc')/str(pid)/'stat'
    until=time.monotonic()+1.
    while status.exists() and status.read_text().split()[2]!='Z' and time.monotonic()<until:time.sleep(.01)
    assert not status.exists() or status.read_text().split()[2]=='Z'
    assert c.close()['clean_shutdown']


def test_close_during_os_launch_cannot_claim_completed_shutdown(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    import neusymnav.perception.detector_client as module
    real=module.subprocess.Popen
    entered,release=threading.Event(),threading.Event()
    def delayed(*args,**kwargs):
        entered.set();release.wait(3.);return real(*args,**kwargs)
    monkeypatch.setattr(module.subprocess,'Popen',delayed)
    errors=[]
    def run():
        try:c.infer(observation())
        except Exception as e:errors.append(e)
    t=threading.Thread(target=run);t.start();assert entered.wait(1.)
    assert not c.close(timeout_s=.01)['clean_shutdown']
    release.set();t.join(2.)
    assert not t.is_alive() and errors and c.close()['clean_shutdown']
    assert not c.is_alive


def test_real_worker_loads_actual_recipe_and_reports_missing_dependency_no_fallback(tmp_path):
    c=DetectorClient(python=sys.executable,recipe=recipe(tmp_path),timeout_s=.5,startup_timeout_s=3.)
    with pytest.raises(RuntimeError,match='unavailable') as exc:c.infer(observation())
    # This host has no Ultralytics/CLIP stack. No mocked detector is substituted.
    assert 'error' in str(exc.value) or 'tokenizer' in str(exc.value)
    assert c.close()['clean_shutdown']


def test_recipe_is_hash_pinned_closed_and_requires_absolute_python(tmp_path):
    r=recipe(tmp_path)
    with pytest.raises(ValueError,match='absolute'):DetectorClient(python='python',recipe=r)
    with pytest.raises(ValueError,match='closed'):DetectorClient(python=sys.executable,recipe=dict(r,semantic_scene='forbidden'))
    Path(r['encoder_path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):DetectorClient(python=sys.executable,recipe=r)


def test_nonempty_original_size_mask_roundtrip(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch,'detection')
    obs=observation(size=7)
    batch=c.infer(obs)
    assert len(batch.detections)==1
    d=batch.detections[0]
    assert d.mask.shape==obs.depth_m.shape and d.mask.all() and not d.mask.flags.writeable
    assert (d.raw_label,d.category,d.score)==('chair','chair',.9)
    assert c.close()['clean_shutdown']


def test_wrong_original_mask_shape_is_terminal(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch,'wrong_mask')
    with pytest.raises(ValueError,match='original source'):c.infer(observation(size=7))
    assert c.close()['clean_shutdown']


@pytest.mark.parametrize('lines', [False, True])
def test_json_decode_cannot_return_success_after_receive_deadline(monkeypatch, lines):
    import neusymnav.perception.detector_client as module
    from types import SimpleNamespace
    wire=_BoundedProcess([sys.executable,'-u','-c','import time; time.sleep(60)'],
                         timeout_s=1.,response_limit=1024,lines=lines)
    wire.start()
    clock=[time.monotonic()]
    real_json=module._json
    def slow_decode(data):
        result=real_json(data)
        clock[0] += .02
        return result
    data=b'{"ok":true}'
    wire.buffer.extend(data+b'\n' if lines else len(data).to_bytes(4,'big')+data)
    try:
        monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
        monkeypatch.setattr(module,'_json',slow_decode)
        with pytest.raises(TimeoutError,match='deadline'):
            wire.receive(clock[0]+.01)
    finally:
        assert wire.close()['clean_shutdown']
