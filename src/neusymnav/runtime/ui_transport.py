"""Versioned bounded JSON publication and command/ACK transport to a Qt process.

The UI sees a marked display projection: at most 32 history references/object,
plus references needed by displayed images, and no point cloud or embeddings.
Only one publication file is retained. Qt is imported exclusively in the child.
"""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import fields,replace
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
import numpy as np

# Direct-file child launch resolves only this bundled package root.
if __package__ in (None,''):
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from neusymnav.contracts._base import Contract
from neusymnav.contracts.serialization import _encode,_decode
from neusymnav.contracts import ObjectSnapshot
from neusymnav.visualization import publisher as dto
from neusymnav.visualization.robot_overlay import RobotSample, CameraCone, RobotTrack, RobotTrailBuffer
from neusymnav.recording.replay import _write_atomic

MAX_PUBLICATION_BYTES=64*1024**2
MAX_COMMAND_BYTES=4096
_DTO={name:getattr(dto,name) for name in ('DisplayEnvelope','DisplayImage','DisplayInstance','DisplayObservation','DisplayMetrics','DisplaySources',
    'DisplayVerificationEvidence','DisplayVerificationRecord','DisplayVerificationSnapshot','UiCommand','UiCommandAck')}
_DTO.update({c.__name__:c for c in (RobotSample,CameraCone,RobotTrack)})


def _encode_value(value):
    if type(value).__name__ in _DTO and type(value) is _DTO[type(value).__name__]:
        return {'dto':type(value).__name__,'fields':{f.name:_encode_value(getattr(value,f.name)) for f in fields(value)}}
    if isinstance(value,(Contract,np.ndarray)):return {'contract_value':_encode(value)}
    if isinstance(value,Mapping):return {'map':{k:_encode_value(v) for k,v in value.items()}}
    if isinstance(value,tuple):return {'items':[_encode_value(v) for v in value]}
    return value


def _decode_value(value,depth=0):
    if depth>32:raise ValueError('UI value depth exceeds bound')
    if not isinstance(value,dict):return value
    if set(value)=={'dto','fields'}:
        cls=_DTO.get(value['dto'])
        if cls is dto.DisplaySources and isinstance(value['fields'],dict):
            incoming=set(value['fields']); required={f.name for f in fields(cls)}-{'robot','observation'}
            if required <= incoming <= {f.name for f in fields(cls)}:
                value = dict(value,fields={'robot':None,'observation':None,**value['fields']})
        if cls is None or not isinstance(value['fields'],dict) or set(value['fields'])!={f.name for f in fields(cls)}:
            raise ValueError('unknown UI DTO/schema fields')
        return cls(**{k:_decode_value(v,depth+1) for k,v in value['fields'].items()})
    if set(value)=={'contract_value'}:return _decode(value['contract_value'])
    if set(value)=={'map'}:return {k:_decode_value(v,depth+1) for k,v in value['map'].items()}
    if set(value)=={'items'}:return tuple(_decode_value(v,depth+1) for v in value['items'])
    raise ValueError('unknown UI value type')


def _compact(envelope):
    sources=envelope.sources;objects=sources.objects;keep={}
    for image in sources.best_views:
        key=objects.resolve_id(image.object_id);keep.setdefault(key,set()).add(image.evidence_ref)
    if objects is not None:
        if len(objects.objects)>4096 or len(objects.aliases)>4096:raise ValueError('UI object/alias count cap exceeded')
        compact={}
        for key,obj in objects.objects.items():
            refs=tuple(dict.fromkeys((*obj.evidence_refs[-32:],*sorted(keep.get(key,())))))
            compact[key]=replace(obj,evidence_refs=refs,points_world=None,footprint_xy=None,covariance=None,appearance=None)
        objects=replace(objects,objects=compact)
    nodes={}
    for key,node in envelope.hierarchy.nodes.items():
        attrs=dict(node.attributes)
        if 'evidence_refs' in attrs:
            attrs['evidence_refs']=objects.objects[key].evidence_refs if objects is not None and key in objects.objects else tuple(attrs['evidence_refs'][-32:])
            attrs['evidence_refs_scope']='display_projection_last32_plus_displayed_evidence'
        nodes[key]=replace(node,attributes=attrs)
    return replace(envelope,hierarchy=replace(envelope.hierarchy,nodes=nodes),sources=replace(sources,objects=objects))


def encode_publication(envelope,*,max_bytes=MAX_PUBLICATION_BYTES):
    if not isinstance(envelope,dto.DisplayEnvelope):raise ValueError('typed DisplayEnvelope required')
    if type(max_bytes) is not int or not 0<max_bytes<=MAX_PUBLICATION_BYTES:raise ValueError('UI wire cap must be <=64 MiB')
    packet=dict(wire_version=1,projection=dict(object_history='last32_plus_displayed_evidence',
        object_geometry='centroid_bounds_only',complete_object_history=False),payload=_encode_value(_compact(envelope)))
    # iterencode stops at the byte cap, without constructing an unbounded JSON string.
    encoded=bytearray()
    for chunk in json.JSONEncoder(separators=(',',':'),allow_nan=False).iterencode(packet):
        data=chunk.encode()
        if len(encoded)+len(data)>max_bytes:raise ValueError('UI publication byte cap exceeded; publication dropped')
        encoded.extend(data)
    return bytes(encoded)


def decode_publication(payload):
    value=_read_json_bytes(payload,MAX_PUBLICATION_BYTES)
    if set(value)!={'wire_version','projection','payload'} or type(value['wire_version']) is not int or value['wire_version']!=1:
        raise ValueError('invalid UI wire version/schema')
    if value['projection']!={'object_history':'last32_plus_displayed_evidence','object_geometry':'centroid_bounds_only','complete_object_history':False}:
        raise ValueError('unsupported UI projection')
    result=_decode_value(value['payload'])
    if not isinstance(result,dto.DisplayEnvelope):raise ValueError('UI publication must be DisplayEnvelope')
    return result


def _read_json_bytes(payload,cap):
    if len(payload)>cap:raise ValueError('UI payload exceeds byte bound')
    return json.loads(payload,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('invalid JSON '+x)))


def _read(path,cap):
    if path.is_symlink() or path.stat().st_size>cap:raise ValueError('UI file symlink/byte bound')
    return path.read_bytes()


def _command_bytes(value):
    payload=json.dumps(dict(wire_version=1,payload=_encode_value(value)),separators=(',',':'),allow_nan=False).encode()
    if len(payload)>MAX_COMMAND_BYTES:raise ValueError('UI command exceeds byte bound')
    return payload


def _command_read(path,cls):
    value=_read_json_bytes(_read(path,MAX_COMMAND_BYTES),MAX_COMMAND_BYTES)
    if set(value)!={'wire_version','payload'} or type(value['wire_version']) is not int or value['wire_version']!=1:raise ValueError('UI command version/schema mismatch')
    result=_decode_value(value['payload'])
    if not isinstance(result,cls):raise ValueError('wrong UI command DTO')
    return result


class UiEndpoint:
    """Child-side latest-publication reader and bounded pending command mailbox."""
    def __init__(self,root,*,clock_domain):
        self.root=Path(root);self.domain=clock_domain;self.sequence=None;self.latest=None
        self.root.mkdir(parents=True,exist_ok=True)
        for name in ('commands','acks'):(self.root/name).mkdir(exist_ok=True)
        self.client=dto.UiControlClient(command_source='desktop',submit=self.submit,clock_domain=clock_domain)

    def submit(self,command):
        if not isinstance(command,dto.UiCommand):raise ValueError('UiCommand required')
        if len(list((self.root/'commands').glob('*.json')))>=8:raise RuntimeError('UI command queue full')
        _write_atomic(self.root/'commands'/(command.request_uuid+'.json'),_command_bytes(command))
        return None

    def read_acks(self):
        result=[]
        for path in list((self.root/'acks').glob('*.json'))[:64]:
            try:result.append(_command_read(path,dto.UiCommandAck))
            finally:path.unlink(missing_ok=True)
        return result

    def read_latest(self):
        for ack in self.read_acks():
            try:self.client.accept_ack(ack)
            except ValueError:pass # late/unknown ACK is never accepted as success
        path=self.root/'publication.json'
        if not path.exists():return self.latest
        stamp=path.stat().st_mtime_ns
        if stamp==self.sequence:return self.latest
        try:
            result=decode_publication(_read(path,MAX_PUBLICATION_BYTES))
            if result.clock_domain!=self.domain:raise ValueError('UI publication clock mismatch')
            self.latest=result;self.sequence=stamp
        except (ValueError,OSError,TypeError,KeyError):return self.latest
        return self.latest


class UiProcess:
    """Optional process. Failure is reported locally and never raises into control."""
    def __init__(self,root,*,python,script,clock_domain,command_handler,assets_root=None,smoke_exit_ms=None,quota=None,publish_hz=None):
        if publish_hz is not None and (type(publish_hz) not in (int,float) or not 0<publish_hz<=20):
            raise ValueError('publish_hz must be finite, positive and at most 20')
        self._publish_hz=publish_hz;self._last_publication_ns=None
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.endpoint=UiEndpoint(self.root,clock_domain=clock_domain)
        self.publisher=dto.DisplayPublisher(clock_domain=clock_domain)
        self.command_handler=command_handler;self.domain=clock_domain;self.assets_root=None if assets_root is None else Path(assets_root)
        self._robot_trail=RobotTrailBuffer()
        from neusymnav.visualization.detector_observation import CommittedObservationReader
        self._observation_reader=None if self.assets_root is None else CommittedObservationReader(self.assets_root,clock_domain=clock_domain)
        self._rgb=None;self._stop=threading.Event();self._lock=threading.Lock();self.status=dict(failed=None,dropped_publications=0,coalesced_publications=0)
        command=[str(python),str(script),'--root',str(self.root),'--clock-domain',clock_domain]
        if smoke_exit_ms is not None:command+=['--smoke-exit-ms',str(smoke_exit_ms)]
        self._diagnostics=bytearray();self._reader=None;self._quota=quota
        self._finalizer=None;self._finalizer_error=None;self._finalize_lock=threading.Lock()
        if quota is not None:quota.reserve('ui-transport',2*MAX_PUBLICATION_BYTES+512*1024)
        self.process=None
        try:self.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        except OSError as exc:self.status['failed']=str(exc)
        if self.process is not None:
            self._reader=threading.Thread(target=self._drain,name='neusymnav-ui-log',daemon=True);self._reader.start()
        self.thread=threading.Thread(target=self._commands,name='neusymnav-ui-commands',daemon=True);self.thread.start()

    def _drain(self):
        try:
            while True:
                data=self.process.stdout.read(8192)
                if not data:return
                with self._lock:
                    self._diagnostics.extend(data)
                    if len(self._diagnostics)>65536:del self._diagnostics[:-65536]
        except (OSError,ValueError):return


    def observe_robot(self,rgb,nav,pose):
        try:self._robot_trail.observe(rgb,nav,pose)
        except Exception as exc:
            self.status['robot_overlay_error']=f'{type(exc).__name__}: {exc}'[:256]

    def set_rgb(self,observation):
        # Assign immutable source pointer only. Pixels are copied on graph lane.
        with self._lock:self._rgb=observation

    def _images(self,sources):
        best=[]
        if self.assets_root is None or sources.verification is None or sources.objects is None:return best
        database=self.assets_root.parent/'objects.sqlite3'
        if not database.exists():return best
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True,timeout=.05) as connection:
            for object_id,record in sources.verification.objects.items():
                for proof in record.evidence:
                    if len(best)>=3:return best
                    row=connection.execute('SELECT crop_asset,data FROM views WHERE event_id=?',(proof.evidence_ref,)).fetchone()
                    if row is None:continue
                    ref,data=row;data=json.loads(data)
                    if not isinstance(ref,str) or len(ref)!=64 or any(c not in '0123456789abcdef' for c in ref):continue
                    path=self.assets_root/ref
                    payload=_read(path,8*1024**2+65536)
                    if hashlib.sha256(payload).hexdigest()!=ref:continue
                    pixels=np.load(io.BytesIO(payload),allow_pickle=False)
                    best.append(dto.DisplayImage('best_view',proof.source,proof.capture_monotonic_ns,
                        proof.clock_domain,pixels,object_id,sources.objects.revision,proof.evidence_ref))
        return best

    def publish(self,snapshot,metrics):
        # The graph lane remains the sole publication writer. Do not retain
        # skipped bundles: the next eligible call supplies current graph/source
        # metadata and reads the latest immutable RGB pointer. Gate before image
        # copies, committed-observation reads, serialization or filesystem work.
        if self._publish_hz is not None:
            now=time.monotonic_ns()
            if self._last_publication_ns is not None and (now-self._last_publication_ns)*self._publish_hz<1_000_000_000:
                self.status['coalesced_publications']+=1
                return
            self._last_publication_ns=now
        try:
            metrics=dict(metrics);sources=metrics['sources'];ages=dict(metrics['source_age_ns'])
            with self._lock:obs=self._rgb
            if obs is not None:
                rgb=dto.DisplayImage('rgb',obs.key,obs.capture_monotonic_ns,obs.clock_domain,obs.rgb)
                ages['rgb']=max(0,time.monotonic_ns()-obs.capture_monotonic_ns)
                sources=replace(sources,rgb=rgb)
            observation=None
            try:
                if self._observation_reader is not None:
                    observation=self._observation_reader.read(metrics['processed_frame_id'])
                    self.status.pop('observation_error',None)
            except Exception as exc:
                self.status['observation_error']=f'{type(exc).__name__}: {exc}'[:256]
            sources=replace(sources,best_views=tuple(self._images(sources)),robot=self._robot_trail.for_nav(sources.nav),observation=observation)
            metrics.update(sources=sources,source_age_ns=ages)
            self.publisher.publish(snapshot,metrics)
            payload=encode_publication(self.publisher.read_latest())
            _write_atomic(self.root/'publication.json',payload)
        except Exception as exc:
            self.status['dropped_publications']+=1;self.status['failed']=f'{type(exc).__name__}: {exc}'

    def _commands(self):
        while not self._stop.wait(.02):
            if self.process is not None and self.process.poll() is not None:
                self.status['failed']='UI exited with code '+str(self.process.returncode)
            for path in list((self.root/'commands').glob('*.json'))[:8]:
                try:
                    command=_command_read(path,dto.UiCommand)
                    if path.name!=command.request_uuid+'.json':raise ValueError('UI command filename mismatch')
                    ack=self.command_handler(command)
                    acks=list((self.root/'acks').glob('*.json'))
                    if len(acks)>=64:
                        for old in sorted(acks,key=lambda p:p.stat().st_mtime_ns)[:len(acks)-63]:old.unlink(missing_ok=True)
                    _write_atomic(self.root/'acks'/(ack.request_uuid+'.json'),_command_bytes(ack))
                except Exception as exc:self.status['failed']=f'UI command: {exc}'
                finally:path.unlink(missing_ok=True)

    def _persist_diagnostics(self):
        try:
            with self._lock:payload=bytes(self._diagnostics)
            _write_atomic(self.root/'desktop.log',payload)
            # Quota release can wait on another worker's filesystem scan.
            # It belongs to the same boundedly joined finalizer, not close().
            if self._quota is not None:self._quota.release('ui-transport')
        except Exception as exc:
            self._finalizer_error=f'{type(exc).__name__}: {exc}'

    def close(self,timeout_s=1.):
        if type(timeout_s) not in (int,float) or not np.isfinite(timeout_s) or timeout_s<0:
            raise ValueError('UI shutdown timeout must be finite and nonnegative')
        deadline=time.monotonic()+timeout_s;self._stop.set()
        from neusymnav.perception.appearance_client import _terminate_process_group
        if self.process is not None:
            # Existing bounded group cleanup handles descendants after leader exit.
            _terminate_process_group(self.process,grace_s=max(0.,deadline-time.monotonic())/2)
        self.thread.join(max(0.,deadline-time.monotonic()))
        if self._reader is not None:self._reader.join(max(0.,deadline-time.monotonic()))
        reader_pending=self._reader is not None and self._reader.is_alive()
        clean=not self.thread.is_alive() and not reader_pending and (self.process is None or self.process.poll() is not None)
        if clean:
            if self.process is not None:self.process.stdout.close()
            with self._finalize_lock:
                if self._finalizer is None:
                    self._finalizer=threading.Thread(target=self._persist_diagnostics,
                        name='neusymnav-ui-finalize',daemon=True)
                    self._finalizer.start()
            self._finalizer.join(max(0.,deadline-time.monotonic()))
            clean=not self._finalizer.is_alive() and self._finalizer_error is None
        return dict(clean_shutdown=clean,process_reaped=self.process is None or self.process.poll() is not None,
            command_thread_pending=self.thread.is_alive(),reader_pending=reader_pending,
            diagnostics_pending=self._finalizer is not None and self._finalizer.is_alive(),
            diagnostics_error=self._finalizer_error,status=dict(self.status))


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--clock-domain',required=True)
    parser.add_argument('--smoke-exit-ms',type=int);args=parser.parse_args()
    endpoint=UiEndpoint(args.root,clock_domain=args.clock_domain)
    from PyQt5 import QtCore,QtWidgets
    from neusymnav.visualization.desktop import run_desktop
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QtCore.QTimer.singleShot(0,lambda:_write_atomic(Path(args.root)/'ready.json',json.dumps(dict(pid=os.getpid(),desktop='run_desktop')).encode()))
    return run_desktop(endpoint.read_latest,endpoint.client,clock_domain=args.clock_domain,smoke_exit_ms=args.smoke_exit_ms)


if __name__=='__main__':raise SystemExit(main())
