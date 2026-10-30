"""GPU IPC never grants authority to mismatched, oversized or stale replies."""
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pytest

from neusymnav.mapping.gpu_raycast_client import GpuRaycastClient
from neusymnav.mapping._raycast_kernel import collect_ray_votes


def geometry():
    return dict(resolution_m=.1,origin_x_m=0.,origin_z_m=0.,floor_y_m=0.,
                robot_height_m=1.5,height_bin_m=.1,ray_step_m=.05)


@pytest.fixture
def fake_worker(monkeypatch):
    import neusymnav.mapping.gpu_raycast_client as module
    from neusymnav.perception.detector_client import _BoundedProcess
    class Wire:
        corruption=None
        def __init__(self,command,**kw):
            import threading
            self.lock=threading.Lock();self.root=Path(command[-1]);self.ready=False
            self.diagnostics=[];self.request=None;self.closed=False
        def start(self):pass
        def send(self,request,*a,**kw):self.request=request
        def receive(self,deadline):
            if not self.ready:
                self.ready=True
                return dict(protocol=module.PROTOCOL,status='ready',backend='triton_cuda',
                            limits=module.LIMITS,execution=dict(torch_version='fixture',triton_version='fixture',
                            device_name='fixture',device_uuid='GPU-fixture',capability=[8,6],numeric_policy='fp64_ieee_fma_off'))
            r=self.request;n=r['n'];g=r['geometry'].copy();origin=np.asarray(g.pop('camera_origin_world'))
            data=(self.root/'request.bin').read_bytes()
            e=np.frombuffer(data[:n*24],dtype='<f8').reshape(n,3)
            mask=np.frombuffer(data[n*24:],dtype=np.uint8).astype(bool)
            v=collect_ray_votes(e,origin,has_return=mask,backend='python',**g)
            arrays=[getattr(v,k) for k in ['planar_free','planar_hit','floor_hit','height_free','height_hit']]
            payload=b''.join(a.astype(np.uint8).tobytes() for a in arrays)
            (self.root/'response.bin').write_bytes(payload)
            out=dict(protocol=module.PROTOCOL,id=r['id'],status='ok',request_sha256=r['request_sha256'],
                     response_sha256=hashlib.sha256(payload).hexdigest(),min_row=v.min_row,min_col=v.min_col,
                     rows=v.planar_free.shape[0],cols=v.planar_free.shape[1],height_bins=v.height_free.shape[2],
                     response_bytes=len(payload),timings_ms=dict(validation=0.,kernel=0.,total=0.))
            if self.corruption=='id':out['id']='old-response'
            if self.corruption=='shape':out['rows']+=1
            if self.corruption=='hash':out['response_sha256']='0'*64
            if self.corruption=='binary':(self.root/'response.bin').write_bytes(bytes([2])+payload[1:])
            if self.corruption in ('mask2','mask255'):
                payload=bytes([2 if self.corruption=='mask2' else 255])+payload[1:]
                (self.root/'response.bin').write_bytes(payload)
                out['response_sha256']=hashlib.sha256(payload).hexdigest()
            if self.corruption=='error':return dict(protocol=module.PROTOCOL,id=r['id'],status='error',error='GPU unavailable')
            if self.corruption=='fifo':
                import os
                (self.root/'response.bin').unlink();os.mkfifo(self.root/'response.bin')
            return out
        def close(self,*a,**kw):self.closed=True;return dict(clean_shutdown=True)
    monkeypatch.setattr(module,'_BoundedProcess',Wire)
    return Wire


def client(tmp_path):
    return GpuRaycastClient(python=Path(sys.executable).absolute(),worker_script=Path(__file__).absolute(),root=tmp_path/'ipc')


def test_binary_ipc_exact_votes_and_request_geometry_binding(tmp_path,fake_worker):
    c=client(tmp_path);e=np.array([[-.2,0.,.2],[.2,.3,-.2]])
    try:
        actual=c.collect(e,np.array([0.,1.5,0.]),**geometry())
        expected=collect_ray_votes(e,np.array([0.,1.5,0.]),backend='python',**geometry())
        assert actual.min_row==expected.min_row and actual.min_col==expected.min_col
        for name in ['planar_free','planar_hit','floor_hit','height_free','height_hit']:
            assert np.array_equal(getattr(actual,name),getattr(expected,name))
        r=c._wire.request
        canonical=json.dumps(dict(n=r['n'],geometry=r['geometry']),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        assert r['request_sha256']==hashlib.sha256(canonical+b'\0'+(c.root/'request.bin').read_bytes()).hexdigest()
    finally:assert c.close()['clean_shutdown']


@pytest.mark.parametrize('corruption',['id','shape','hash','binary','mask2','mask255','error'])
def test_bad_gpu_reply_is_terminal_and_never_falls_back(tmp_path,fake_worker,corruption):
    c=client(tmp_path);c._wire.corruption=corruption
    with pytest.raises((ValueError,RuntimeError)):
        c.collect(np.array([[.1,0.,.1]]),np.array([0.,1.5,0.]),**geometry())
    assert c._wire.closed
    c.close()


def test_payload_bound_before_writing_and_single_flight(tmp_path,fake_worker):
    c=client(tmp_path)
    try:
        with pytest.raises(ValueError):c.collect(np.zeros((100001,3)),np.zeros(3),**geometry())
        assert not (c.root/'request.bin').exists()
    finally:c.close()


def test_ipc_root_must_be_fresh_without_symlink(tmp_path,fake_worker):
    c=client(tmp_path)
    try:
        with pytest.raises((ValueError,FileExistsError)):client(tmp_path)
    finally:c.close()


def test_empty_fifo_response_is_rejected_without_blocking(tmp_path,fake_worker):
    import threading
    c=client(tmp_path);c._wire.corruption='fifo';errors=[]
    def call():
        try:c.collect(np.empty((0,3)),np.array([0.,1.5,0.]),**geometry())
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=call,daemon=True);thread.start();thread.join(.5)
    try:
        assert not thread.is_alive(),'FIFO response blocked beyond the operation deadline'
        assert errors and isinstance(errors[0],ValueError)
    finally:
        # Release the RED implementation's blocked open, then remove fixture.
        if thread.is_alive():
            import os
            fd=os.open(c.root/'response.bin',os.O_WRONLY|os.O_NONBLOCK);os.close(fd);thread.join(1.)
        c.close()


def test_concurrent_close_detaches_directory_descriptor_only_once(tmp_path,fake_worker,monkeypatch):
    import os,threading
    import neusymnav.mapping.gpu_raycast_client as module
    c=client(tmp_path);target=c._root_fd;real_close=os.close
    first_closed=threading.Event();release=threading.Event();calls=[];replacement=[]
    unrelated=tmp_path/'unrelated';unrelated.write_bytes(b'preserve')
    def observed(fd):
        if fd!=target:return real_close(fd)
        calls.append(fd)
        if len(calls)==1:
            real_close(fd);replacement.append(os.open(unrelated,os.O_RDONLY))
            first_closed.set();release.wait(1.)
        else:real_close(fd)
    monkeypatch.setattr(module.os,'close',observed)
    one=threading.Thread(target=c.close);two=threading.Thread(target=c.close)
    try:
        one.start();assert first_closed.wait(1.);two.start();two.join(.2)
        release.set();one.join(1.);two.join(1.)
        assert len(calls)==1,'concurrent close reused another descriptor'
        assert os.read(replacement[0],8)==b'preserve'
    finally:
        release.set();one.join(1.)
        if two.ident is not None:two.join(1.)
        for fd in replacement:
            try:real_close(fd)
            except OSError:pass


def test_collect_admitted_after_close_cannot_write_relative_to_cwd(tmp_path,fake_worker,monkeypatch):
    import threading
    c=client(tmp_path);entered=threading.Event();release=threading.Event();errors=[]
    class LateLock:
        def __init__(self):self.lock=threading.Lock()
        def acquire(self,blocking=True,**kw):
            entered.set();assert release.wait(1.);return self.lock.acquire(blocking=blocking)
        def release(self):self.lock.release()
    c._wire.lock=LateLock();cwd=tmp_path/'cwd';cwd.mkdir();monkeypatch.chdir(cwd)
    def call():
        try:c.collect(np.array([[.1,0.,.1]]),np.array([0.,1.5,0.]),**geometry())
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=call)
    try:
        thread.start();assert entered.wait(1.);c.close();release.set();thread.join(1.)
        assert errors and isinstance(errors[0],RuntimeError)
        assert not list(cwd.iterdir()),'late admission wrote outside private IPC root'
    finally:release.set();thread.join(1.);c.close()
