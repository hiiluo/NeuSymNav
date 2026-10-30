"""Bounded optional GPU worker; core imports neither Torch nor Triton."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import threading
import time
import uuid
import numpy as np
from ..perception.detector_client import _BoundedProcess
from ._raycast_kernel import RaycastVotes

PROTOCOL='neusymnav.gpu_raycast.v1'
LIMITS=dict(max_rays=100000,max_grid_cells=1000000,max_height_bins=256,
            max_output_bytes=128*1024**2,max_device_bytes=512*1024**2,
            max_samples_per_ray=100000,max_total_samples=50000000,max_json_bytes=65536)
MASKS=('planar_free','planar_hit','floor_hit','height_free','height_hit')


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _layout(endpoints,camera,geometry):
    """Independent host bounds, including exact CPU raster guard cells."""
    if (endpoints.ndim!=2 or endpoints.shape[1:]!=(3,) or len(endpoints)>LIMITS['max_rays']
            or camera.shape!=(3,) or not np.isfinite(endpoints).all() or not np.isfinite(camera).all()):
        raise ValueError('GPU ray shape/finite/ray count bound')
    required={'resolution_m','origin_x_m','origin_z_m','floor_y_m','robot_height_m','height_bin_m','ray_step_m'}
    if set(geometry)!=required or not all(math.isfinite(v) for v in geometry.values()):
        raise ValueError('GPU closed finite geometry required')
    res=geometry['resolution_m'];bin_m=geometry['height_bin_m'];step=geometry['ray_step_m']
    if res<=0 or bin_m<=0 or step<=0 or geometry['robot_height_m']<=bin_m:
        raise ValueError('GPU invalid positive geometry')
    bins=math.ceil(geometry['robot_height_m']/bin_m)
    if not 1<=bins<=LIMITS['max_height_bins']:raise ValueError('GPU height bin bound')
    if not len(endpoints):return (0,0,0,0,bins,0)
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
        delta=endpoints-camera
        distances=np.sqrt(delta[:,0]*delta[:,0]+delta[:,1]*delta[:,1]+delta[:,2]*delta[:,2])
        samples=np.maximum(1,np.ceil(distances/step))
    if (not np.isfinite(samples).all() or np.any(samples>LIMITS['max_samples_per_ray'])
            or float(samples.sum()+len(samples))>LIMITS['max_total_samples']):
        raise ValueError('GPU ray work bound')
    min_row=math.floor((min(float(endpoints[:,2].min()),float(camera[2]))-geometry['origin_z_m'])/res)-1
    max_row=math.floor((max(float(endpoints[:,2].max()),float(camera[2]))-geometry['origin_z_m'])/res)+1
    min_col=math.floor((min(float(endpoints[:,0].min()),float(camera[0]))-geometry['origin_x_m'])/res)-1
    max_col=math.floor((max(float(endpoints[:,0].max()),float(camera[0]))-geometry['origin_x_m'])/res)+1
    rows,cols=max_row-min_row+1,max_col-min_col+1
    size=rows*cols*(3+2*bins)
    if (rows*cols>LIMITS['max_grid_cells'] or size>LIMITS['max_output_bytes']
            or 4*size+len(endpoints)*25+1024>LIMITS['max_device_bytes']
            or max(abs(min_row),abs(max_row),abs(min_col),abs(max_col))>2**30):
        raise ValueError('GPU raster/device byte/index bound')
    return min_row,min_col,rows,cols,bins,size


class GpuRaycastClient:
    def __init__(self,*,python,worker_script,root,timeout_s=.25,startup_timeout_s=30.):
        self.root=Path(root).absolute();self.timeout_s=timeout_s;self._closed=False;self.calls=0
        self._state_lock=threading.Lock()
        self._root_fd=None;self._wire=None
        if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=60 for v in (timeout_s,startup_timeout_s)):
            raise ValueError('GPU timeouts must be positive, finite and bounded')
        if any(p.is_symlink() for p in (self.root,*self.root.parents)):
            raise ValueError('GPU IPC root must not contain symlinks')
        self.root.mkdir(parents=True,exist_ok=False,mode=0o700)
        try:
            self._root_fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            self._wire=_BoundedProcess([str(python),str(worker_script),'--root',str(self.root)],
                timeout_s=timeout_s,response_limit=LIMITS['max_json_bytes'])
            self._wire.start();ready=self._wire.receive(time.monotonic()+startup_timeout_s)
            if (set(ready)!={'protocol','status','backend','limits','execution'} or ready['protocol']!=PROTOCOL
                    or ready['status']!='ready' or ready['backend']!='triton_cuda' or ready['limits']!=LIMITS):
                raise RuntimeError('GPU worker qualification/limits mismatch')
            execution=ready['execution']
            if (not isinstance(execution,dict) or set(execution)!={'torch_version','triton_version','device_name','device_uuid','capability','numeric_policy'}
                    or execution['numeric_policy']!='fp64_ieee_fma_off'):
                raise ValueError('GPU worker numeric execution metadata mismatch')
            self.runtime_metadata=json.loads(json.dumps(ready))
        except BaseException:
            self.close();raise

    def collect(self,endpoints_world,camera_origin_world,*,has_return=None,workers=1,**geometry):
        with self._state_lock:
            if self._closed:raise RuntimeError('GPU raycaster closed')
        if not self._wire.lock.acquire(blocking=False):raise RuntimeError('GPU request already in flight')
        failed=False
        try:
            with self._state_lock:
                if self._closed:raise RuntimeError('GPU raycaster closed before request admission')
            deadline=time.monotonic()+self.timeout_s
            if type(workers) is not int or not 1<=workers<=4:raise ValueError('invalid workers')
            e=np.ascontiguousarray(endpoints_world,dtype='<f8');camera=np.asarray(camera_origin_world,dtype=np.float64)
            geometry={k:float(v) for k,v in geometry.items()}
            layout=_layout(e,camera,geometry)
            returns=np.ones(len(e),bool) if has_return is None else np.asarray(has_return)
            if returns.dtype!=np.bool_ or returns.shape!=(len(e),):raise ValueError('GPU has_return must be bool[N]')
            payload=e.tobytes()+returns.astype(np.uint8).tobytes()
            g=dict(geometry,camera_origin_world=camera.tolist());identifier=str(uuid.uuid4())
            request=dict(protocol=PROTOCOL,id=identifier,n=len(e),geometry=g,
                request_sha256=hashlib.sha256(_canonical(dict(n=len(e),geometry=g))+b'\0'+payload).hexdigest())
            self._write_request(payload,deadline)
            self._wire.send(request,deadline,limit=LIMITS['max_json_bytes'])
            response=self._wire.receive(deadline)
            expected={'protocol','id','status','request_sha256','response_sha256','min_row','min_col',
                      'rows','cols','height_bins','response_bytes','timings_ms'}
            if (response.get('status')=='error'):raise RuntimeError('GPU raycasting failed: '+str(response.get('error','unknown'))[:256])
            if (set(response)!=expected or response['protocol']!=PROTOCOL or response['id']!=identifier
                    or response['status']!='ok' or response['request_sha256']!=request['request_sha256']):
                raise ValueError('GPU response context/schema mismatch')
            actual=tuple(response[k] for k in ['min_row','min_col','rows','cols','height_bins','response_bytes'])
            if any(type(v) is not int for v in actual) or actual!=layout:
                raise ValueError('GPU response raster shape/bounds mismatch')
            timings=response['timings_ms']
            if (not isinstance(timings,dict) or set(timings)!={'validation','kernel','total'}
                    or not all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in timings.values())):
                raise ValueError('GPU timing metadata invalid')
            size=layout[-1]
            data=self._read_response(size)
            if len(data)!=size or hashlib.sha256(data).hexdigest()!=response['response_sha256']:
                raise ValueError('GPU binary response checksum mismatch')
            raw=np.frombuffer(data,np.uint8)
            # The view is uint8: its lower bound is already zero. A single
            # comparison enforces the exact {0,1} domain without np.isin's
            # integer lookup/index temporaries on every dense vote buffer.
            if np.any(raw>1):raise ValueError('GPU masks must contain only bool values')
            min_row,min_col,rows,cols,bins,_=layout;at=0;arrays=[]
            for shape in [(rows,cols)]*3+[(rows,cols,bins)]*2:
                count=math.prod(shape);arrays.append(raw[at:at+count].astype(bool).reshape(shape));at+=count
            arrays[0]&=~arrays[1];arrays[3]&=~arrays[4]
            if time.monotonic()>=deadline:raise TimeoutError('GPU whole-operation deadline exceeded')
            self.calls+=1
            self.runtime_metadata['requests_completed']=self.calls
            self.runtime_metadata['last_timings_ms']=dict(timings)
            return RaycastVotes(min_row,min_col,*arrays)
        except BaseException:
            failed=True;raise
        finally:
            self._wire.lock.release()
            if failed:self.close()

    def close(self,timeout_s=1.):
        with self._state_lock:self._closed=True
        report=dict(clean_shutdown=True) if self._wire is None else self._wire.close(timeout_s)
        fd=None
        if report.get('operation_quiesced',report['clean_shutdown']):
            with self._state_lock:
                fd,self._root_fd=self._root_fd,None
        if fd is not None:os.close(fd)
        return report

    def _write_request(self,payload,deadline):
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NONBLOCK|os.O_NOFOLLOW
        fd=os.open('request.bin.tmp',flags,0o600,dir_fd=self._root_fd)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1:
                raise ValueError('GPU request must be an owned regular file')
            view=memoryview(payload)
            while view:
                if time.monotonic()>=deadline:raise TimeoutError('GPU input write deadline')
                written=os.write(fd,view)
                if not written:raise OSError('GPU short request write')
                view=view[written:]
        finally:os.close(fd)
        os.replace('request.bin.tmp','request.bin',src_dir_fd=self._root_fd,dst_dir_fd=self._root_fd)

    def _read_response(self,size):
        fd=os.open('response.bin',os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW,dir_fd=self._root_fd)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1
                    or info.st_size!=size):
                raise ValueError('GPU response must be an owned regular file of the exact bounded size')
            with os.fdopen(fd,'rb',closefd=False) as stream:return stream.read(size+1)
        finally:os.close(fd)
