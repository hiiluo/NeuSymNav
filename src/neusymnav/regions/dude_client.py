"""Bounded persistent DuDe wire. The caller supplies the executable explicitly.

Ported from Fusion standalone_sg/regions/dude_client.py; transport/schema failure
poisons and reaps this process. A fully decoded but invalid geometry candidate
rejects only that update; a later independent response must pass every check.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time
import numpy as np
from ..contracts import RegionGrid
from ._types import Polygon2D, RegionObservation
from .geometry import valid_ring,MAX_RING_VERTICES,normalize_room_ring

class CandidateGeometryRejected(ValueError):
    """Well-formed native candidate violates the unchanged polygon contract."""

@dataclass(frozen=True)
class DuDeConfig:
    decomp_threshold_m: float = 1.5
    safety_distance_m: float = .5
    timeout_s: float = 30.
    preprocessing_policy: str = 'extended_unknown_boundary'
    max_request_bytes: int = 16*1024*1024
    max_response_bytes: int = 16*1024*1024
    max_regions: int = 4096
    max_vertices: int = 100000

    def __post_init__(self):
        for name in ('decomp_threshold_m','safety_distance_m','timeout_s'):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError(name+' must be finite')
        if self.decomp_threshold_m<=0 or self.safety_distance_m<0 or self.timeout_s<=0:
            raise ValueError('threshold/timeout positive; safety distance nonnegative')
        if self.preprocessing_policy!='extended_unknown_boundary':raise ValueError('unsupported preprocessing policy')
        for name in ('max_request_bytes','max_response_bytes','max_regions','max_vertices'):
            if type(getattr(self,name)) is not int or getattr(self,name)<=0:raise ValueError(name+' must be a positive integer')

class DuDeWorkerClient:
    protocol_version=1
    def __init__(self,binary: str|Path,config: DuDeConfig|None=None):
        self.binary=str(Path(binary).resolve())
        if not Path(self.binary).is_file():raise ValueError('DuDe binary must be provided explicitly and exist')
        self.config=config or DuDeConfig()
        self._lock=threading.Lock();self._stderr=deque(maxlen=256);self._closed=False;self._failed=None
        self._proc=subprocess.Popen([self.binary],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,start_new_session=True)
        self._drain_stop=threading.Event();self._terminated=False
        self._stderr_thread=threading.Thread(target=self._drain_stderr,daemon=True);self._stderr_thread.start()

    @property
    def stderr_tail(self):return tuple(self._stderr)

    def _drain_stderr(self):
        # Poll a nonblocking pipe so inherited/escaped writers cannot leave the
        # drain thread blocked forever after this client terminates its group.
        selector=selectors.DefaultSelector()
        try:
            fd=self._proc.stderr.fileno()
            os.set_blocking(fd,False)
            selector.register(fd,selectors.EVENT_READ)
            while not self._drain_stop.is_set():
                if not selector.select(.05):continue
                try:chunk=os.read(fd,1024)
                except BlockingIOError:continue
                if not chunk:return
                self._stderr.append(chunk.decode('utf8',errors='replace'))
        except (OSError,ValueError):
            return
        finally:
            selector.close()

    def _terminate(self):
        if self._terminated:return
        # start_new_session makes the leader PID our process-group ID. The
        # leader may exit before its children; always signal the whole group.
        try:os.killpg(self._proc.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:self._proc.wait(timeout=.5)
        except subprocess.TimeoutExpired:pass
        # TERM-ignoring descendants still need KILL even after leader exit.
        try:os.killpg(self._proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        self._proc.wait(timeout=1.)
        self._drain_stop.set()
        self._stderr_thread.join(timeout=.5)
        for stream in (self._proc.stdin,self._proc.stdout,self._proc.stderr):stream.close()
        self._terminated=True

    def _fail(self,reason):
        self._failed=reason;self._terminate()

    def _exchange(self,payload):
        if self._closed:raise ValueError('DuDe worker is closed')
        if self._failed:raise ValueError('DuDe worker is in error state: '+self._failed)
        data=(json.dumps(payload,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(data)>self.config.max_request_bytes:raise ValueError('request exceeds byte cap')
        if self._proc.poll() is not None:
            self._fail('worker died before request');raise ValueError(self._failed)
        fdin,fdout=self._proc.stdin.fileno(),self._proc.stdout.fileno()
        os.set_blocking(fdin,False);os.set_blocking(fdout,False)
        selector=selectors.DefaultSelector();selector.register(fdin,selectors.EVENT_WRITE,'write')
        offset=0;response=bytearray();deadline=time.monotonic()+self.config.timeout_s
        try:
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('whole request deadline exceeded')
                events=selector.select(remaining)
                if not events:raise TimeoutError('whole request deadline exceeded')
                for key,_ in events:
                    if key.data=='write':
                        try:offset+=os.write(fdin,data[offset:])
                        except BlockingIOError:continue
                        if offset==len(data):
                            selector.unregister(fdin);selector.register(fdout,selectors.EVENT_READ,'read')
                    else:
                        try:chunk=os.read(fdout,65536)
                        except BlockingIOError:continue
                        if not chunk:raise BrokenPipeError('worker closed stdout')
                        response.extend(chunk)
                        if len(response)>self.config.max_response_bytes:raise ValueError('response exceeds byte cap')
                        if b'\n' not in response:continue
                        line,_,tail=response.partition(b'\n')
                        if tail.strip():raise ValueError('unsolicited response tail')
                        parsed=json.loads(line)
                        if not isinstance(parsed,dict) or type(parsed.get('protocol_version')) is not int or parsed['protocol_version']!=1:raise ValueError('protocol mismatch')
                        if parsed.get('status')=='error':raise ValueError('worker error: '+str(parsed.get('message')))
                        return parsed
        except Exception as exc:
            self._fail(str(exc));raise ValueError('DuDe request failed: '+str(exc)) from exc
        finally:selector.close()

    def integrate(self,grid: RegionGrid,*,timestamp_s:float|None=None,capture_preprocessed_mask=False):
        if not isinstance(grid,RegionGrid):raise ValueError('expected narrow RegionGrid')
        if type(capture_preprocessed_mask) is not bool:raise ValueError('capture flag must be bool')
        timestamp=float(grid.source_map_revision if timestamp_s is None else timestamp_s)
        if not math.isfinite(timestamp):raise ValueError('timestamp must be finite')
        height,width=grid.values.shape
        # Reject size before materializing Python integers/JSON (four bytes per value minimum cap).
        if grid.values.size>self.config.max_request_bytes//4:raise ValueError('request raster exceeds byte cap')
        frame_id='canonical_world_z_up:'+grid.episode_id
        request_id='revision-'+str(grid.source_map_revision)
        req={'protocol_version':1,'op':'integrate','request_id':request_id,'revision':grid.source_map_revision,'frame_id':frame_id,
             'grid':{'width':width,'height':height,'resolution_m':grid.resolution_m,'origin_xy':list(grid.origin_xy),'values':grid.values.ravel().tolist()},
             'config':{'decomp_threshold_m':self.config.decomp_threshold_m,'safety_distance_m':self.config.safety_distance_m,'preprocessing_policy':grid.preprocessing_policy},
             'debug_capture_preprocessing':capture_preprocessed_mask}
        with self._lock:
            response=self._exchange(req)
            try:
                if (response.get('protocol_status')!='ok' or response.get('status') not in ('success','fallback','rejected') or
                    type(response.get('input_revision')) is not int or response['input_revision']!=grid.source_map_revision or
                    response.get('request_id')!=request_id or response.get('frame_id')!=frame_id or response.get('units')!='meters' or
                    response.get('coordinate_convention')!='world_x=origin_x+col*resolution; world_y=origin_y+row*resolution'):
                    raise ValueError('malformed or wrong-revision response')
                diagnostics=response.get('diagnostics',{})
                if diagnostics.get('preprocessing_policy')!=grid.preprocessing_policy:raise ValueError('preprocessing policy mismatch')
                if response['status']=='rejected':return response,()
                raw=response.get('regions')
                if not isinstance(raw,list) or len(raw)>self.config.max_regions:raise ValueError('invalid regions count')
                expected=set(range(len(raw)));observations=[];vertices=0
                for i,r in enumerate(raw):
                    if not isinstance(r,dict) or type(r.get('raw_id')) is not int or r['raw_id']!=i:raise ValueError('invalid raw IDs')
                    outer=r.get('outer');adj=r.get('adjacent_raw_ids')
                    if not isinstance(outer,list) or not 3<=len(outer)<=MAX_RING_VERTICES:raise ValueError('invalid outer polygon or per-ring vertex cap exceeded')
                    vertices+=len(outer)
                    if vertices>self.config.max_vertices:raise ValueError('vertex cap exceeded')
                    if not isinstance(adj,list) or any(type(v) is not int or v not in expected or v==i for v in adj):raise ValueError('invalid adjacency')
                    if r.get('holes_supported') is not False or r.get('holes'):raise ValueError('unsupported holes')
                    polygon=Polygon2D(tuple(map(tuple,outer)))
                    normalized,removed=normalize_room_ring(polygon.outer)
                    polygon=Polygon2D(normalized)
                    observations.append(RegionObservation(i,polygon,timestamp,grid.source_map_revision,tuple(r.get('centroid_xy',())),r.get('area_m2'),adjacent_raw_ids=tuple(adj),metadata={'backend':'dude_incremental_cpp','preprocessing_policy':grid.preprocessing_policy,'branch':response.get('branch'),'ring_normalization':'exact_collinear_zero_area_v1','removed_vertices':removed}))
            except Exception as exc:
                self._fail(str(exc));raise ValueError('DuDe response invalid: '+str(exc)) from exc
            # Finish schema/type/finite/cap validation for the entire response
            # before classifying geometry. A malformed later region must still
            # poison IPC even when an earlier polygon is non-simple.
            if any(not valid_ring(o.polygon.outer) for o in observations):
                raise CandidateGeometryRejected('region polygon must be simple and nonzero')
            return response,tuple(observations)

    def reset(self):
        with self._lock:return self._exchange({'protocol_version':1,'op':'reset'})

    def close(self):
        with self._lock:
            if self._closed:return
            self._closed=True;self._terminate()
            for stream in (self._proc.stdin,self._proc.stdout,self._proc.stderr):stream.close()
            self._stderr_thread.join(timeout=.5)

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
