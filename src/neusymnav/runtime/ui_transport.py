"""Versioned bounded JSON publication and command/ACK transport to a Qt process.

The UI sees a marked display projection: at most 32 history references/object,
plus references needed by displayed images, and no point cloud or embeddings.
Only one publication file is retained. Qt is imported exclusively in the child.
"""
from __future__ import annotations
from collections.abc import Mapping
from collections import deque
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
from neusymnav.contracts import ObjectSnapshot,NavSnapshot,HierarchySnapshot,age_ns
from neusymnav.visualization import publisher as dto
from neusymnav.visualization.robot_overlay import RobotSample, CameraCone, CameraProjection, RobotTrack, RobotTrailBuffer
from neusymnav.visualization.navigation_overlay import NavigationOverlay
from neusymnav.mapping.overview import MapOverview, build_overview
from neusymnav.backends.hydra.graph_adapter import HydraDisplayNode,HydraDisplayEdge,HydraGraphProjection
from neusymnav.recording.replay import _write_atomic

MAX_PUBLICATION_BYTES=64*1024**2
MAX_COMMAND_BYTES=4096
MAX_COMMAND_HISTORY=64
MAX_COMMAND_DIAGNOSTICS_BYTES=128*1024
_DTO={name:getattr(dto,name) for name in ('DisplayEnvelope','DisplayImage','DisplayInstance','DisplayObservation','DisplayMetrics','DisplaySources',
    'DisplayVerificationEvidence','DisplayVerificationRecord','DisplayVerificationSnapshot','UiCommand','UiCommandAck')}
_DTO.update({c.__name__:c for c in (RobotSample,CameraCone,CameraProjection,RobotTrack,NavigationOverlay)})
_DTO['MapOverview']=MapOverview
_DTO.update({c.__name__:c for c in (HydraDisplayNode,HydraDisplayEdge,HydraGraphProjection)})


def _matches_graph_source(frame_key,source):
    return (frame_key is not None and isinstance(source,dict)
        and frame_key.episode_id==source.get('episode_id')
        and frame_key.sensor_id==source.get('sensor_id')
        and frame_key.frame_index==source.get('frame_index'))


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
            incoming=set(value['fields']); required={f.name for f in fields(cls)}-{'robot','observation','navigation','live_nav','overview','hydra_graph'}
            if required <= incoming <= {f.name for f in fields(cls)}:
                value = dict(value,fields={'robot':None,'observation':None,'navigation':None,'live_nav':None,'overview':None,'hydra_graph':None,**value['fields']})
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
    # Keep all gallery references, not all pixels: selected-object lazy reads
    # must still bind an older best view to the pinned compact object history.
    if sources.verification is not None and objects is not None:
        for object_id,record in sources.verification.objects.items():
            key=objects.resolve_id(object_id)
            history=set(objects.objects[key].evidence_refs)
            keep.setdefault(key,set()).update(p.evidence_ref for p in record.evidence if p.evidence_ref in history)
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


def _json_ascii_upper_bound(value, max_bytes, *, _seen=None, _depth=0):
    """Return a conservative ASCII JSON size, or None for unknown values.

    String bounds require no escaped copy; the encoder handles escaping once.
    Unknown, cyclic, and
    unusually deep values use the original streaming encoder.
    """
    if _depth > 100:
        return None
    if value is None:
        return 4
    if type(value) is bool:
        return 4 if value else 5
    if type(value) is int:
        bits = value.bit_length()
        digits = 1 if bits == 0 else (bits * 30103 + 99999) // 100000
        return digits + (1 if value < 0 else 0)
    if type(value) is float:
        # JSONEncoder's finite float representation is repr(value). Non-finite
        # values still reach the serializer and are rejected by allow_nan=False.
        return len(repr(value))
    if type(value) is str:
        factor = 6 if value.isascii() else 12
        return min(len(value) * factor + 2, max_bytes + 1)
    if type(value) not in (list, tuple, dict):
        return None

    if _seen is None:
        _seen = set()
    identity = id(value)
    if identity in _seen:
        return None
    _seen.add(identity)
    try:
        if type(value) is dict:
            count = len(value)
            used = 2 + max(0, count - 1)
            if used > max_bytes:
                return max_bytes + 1
            for key, item in value.items():
                if type(key) is not str:
                    return None
                remaining = max_bytes - used
                key_size = _json_ascii_upper_bound(
                    key, remaining, _seen=_seen, _depth=_depth + 1)
                if key_size is None:
                    return None
                used += key_size + 1  # quoted key and colon
                if used > max_bytes:
                    return max_bytes + 1
                item_size = _json_ascii_upper_bound(
                    item, max_bytes - used, _seen=_seen, _depth=_depth + 1)
                if item_size is None:
                    return None
                used += item_size
                if used > max_bytes:
                    return max_bytes + 1
            return used

        count = len(value)
        used = 2 + max(0, count - 1)
        if used > max_bytes:
            return max_bytes + 1
        for item in value:
            item_size = _json_ascii_upper_bound(
                item, max_bytes - used, _seen=_seen, _depth=_depth + 1)
            if item_size is None:
                return None
            used += item_size
            if used > max_bytes:
                return max_bytes + 1
        return used
    finally:
        _seen.remove(identity)


def encode_publication(envelope,*,max_bytes=MAX_PUBLICATION_BYTES):
    if not isinstance(envelope,dto.DisplayEnvelope):raise ValueError('typed DisplayEnvelope required')
    if type(max_bytes) is not int or not 0<max_bytes<=MAX_PUBLICATION_BYTES:raise ValueError('UI wire cap must be <=64 MiB')
    packet=dict(wire_version=1,projection=dict(object_history='last32_plus_displayed_evidence',
        object_geometry='centroid_bounds_only',complete_object_history=False),payload=_encode_value(_compact(envelope)))
    upper_bound = _json_ascii_upper_bound(packet, max_bytes)
    if upper_bound is not None and upper_bound <= max_bytes:
        payload = json.dumps(packet, separators=(',', ':'), allow_nan=False).encode()
        if len(payload) > max_bytes:
            raise ValueError('UI publication byte cap exceeded; publication dropped')
        return payload
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


def _audit_text(value,cap):
    """Bound retained UTF-8 bytes even for handler errors/ACKs outside wire caps."""
    if value is None:return None
    text=str(value)[:cap].encode('utf-8',errors='replace')[:cap].decode('utf-8',errors='ignore')
    # Control characters otherwise expand sixfold in JSON, breaking byte quotas.
    return ''.join(char if ord(char)>=32 else '?' for char in text)


def _audit_dto(value):
    if value is None:return None
    result={};modified=[]
    for field in fields(value):
        item=getattr(value,field.name)
        if type(item) is int:
            # DTO timestamps have no magnitude cap; never retain huge integers.
            result[field.name]=item if 0<=item<2**64 else 'outside_uint64'
        else:
            result[field.name]=_audit_text(item,192 if field.name=='reason' else 64)
        if result[field.name]!=item:modified.append(field.name)
    result['modified_fields']=modified
    return result


class UiEndpoint:
    """Child-side latest-publication reader and bounded pending command mailbox."""
    def __init__(self,root,*,clock_domain):
        self.root=Path(root);self.domain=clock_domain;self.sequence=None;self.latest=None
        self._last_live_nav=None
        self._last_overview_nav=None
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
            if self.latest is not None and (result.publication_sequence<=self.latest.publication_sequence
                or result.hierarchy.episode_id!=self.latest.hierarchy.episode_id
                or result.hierarchy.revision<self.latest.hierarchy.revision):
                raise ValueError('UI publication stream moved backward')
            if result.sources.live_nav is not None:
                dto.DisplayPublisher._validate_live_stream(self._last_live_nav,result.sources.live_nav)
            if result.sources.overview is not None:
                dto.DisplayPublisher._validate_live_stream(self._last_overview_nav,result.sources.overview.source_nav)
            if result.sources.live_nav is not None:self._last_live_nav=result.sources.live_nav
            if result.sources.overview is not None:self._last_overview_nav=result.sources.overview.source_nav
            self.latest=result;self.sequence=stamp
        except (ValueError,OSError,TypeError,KeyError):return self.latest
        return self.latest


class UiProcess:
    """Optional process. Failure is reported locally and never raises into control."""
    def __init__(self,root,*,python,script,clock_domain,command_handler,assets_root=None,recording_root=None,smoke_exit_ms=None,quota=None,publish_hz=None,navigation_provider=None,live_nav_provider=None,overview_provider=None):
        if navigation_provider is not None and not callable(navigation_provider):raise ValueError('navigation provider must be callable')
        if live_nav_provider is not None and not callable(live_nav_provider):raise ValueError('live navigation provider must be callable')
        self._navigation_provider=navigation_provider
        self._live_nav_provider=live_nav_provider
        if overview_provider is not None and not callable(overview_provider):raise ValueError('overview provider must be callable')
        self._overview_provider=overview_provider
        self._display_overview=None;self._overview_tiles=None
        if publish_hz is not None and (type(publish_hz) not in (int,float) or not 0<publish_hz<=20):
            raise ValueError('publish_hz must be finite, positive and at most 20')
        self._publish_hz=min(5.,publish_hz or 5.);self._last_publication_ns=None
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.endpoint=UiEndpoint(self.root,clock_domain=clock_domain)
        self.publisher=dto.DisplayPublisher(clock_domain=clock_domain)
        self.command_handler=command_handler;self.domain=clock_domain;self.assets_root=None if assets_root is None else Path(assets_root)
        self.recording_root=None if recording_root is None else Path(recording_root)
        self._robot_trail=RobotTrailBuffer()
        from neusymnav.visualization.detector_observation import CommittedObservationReader
        self._observation_reader=None if self.assets_root is None else CommittedObservationReader(self.assets_root,clock_domain=clock_domain)
        self._rgb=None;self._stop=threading.Event();self._lock=threading.Lock();self.status=dict(failed=None,dropped_publications=0,coalesced_publications=0)
        self._publication_wake=threading.Event();self._pending_bundle=None;self._display_bundle=None;self._display_live_nav=None
        self._closing=False
        command=[str(python),str(script),'--root',str(self.root),'--clock-domain',clock_domain]
        if self.assets_root is not None:command+=['--assets-root',str(self.assets_root)]
        if self.recording_root is not None:command+=['--recording-root',str(self.recording_root)]
        if smoke_exit_ms is not None:command+=['--smoke-exit-ms',str(smoke_exit_ms)]
        self._diagnostics=bytearray();self._reader=None;self._quota=quota
        self._command_history=deque(maxlen=MAX_COMMAND_HISTORY);self._commands_seen=0
        self._finalizer=None;self._finalizer_error=None;self._finalize_lock=threading.Lock()
        if quota is not None:quota.reserve('ui-transport',2*MAX_PUBLICATION_BYTES+512*1024)
        self.process=None
        # Honor the desktop's Qt scale without multiplying it again. An extra
        # zoom compounds per-screen DPI and can push panels outside the screen.
        ui_env=os.environ.copy()
        try:self.process=subprocess.Popen(command,env=ui_env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        except OSError as exc:self.status['failed']=str(exc)
        if self.process is not None:
            self._reader=threading.Thread(target=self._drain,name='neusymnav-ui-log',daemon=True);self._reader.start()
        self.thread=threading.Thread(target=self._commands,name='neusymnav-ui-commands',daemon=True);self.thread.start()
        self.publication_thread=threading.Thread(target=self._publications,name='neusymnav-ui-publication',daemon=True)
        self.publication_thread.start()

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
        # Assign immutable source pointer only. Pixels are copied on UI lane.
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
        """Offer one immutable graph/source bundle without doing display work."""
        with self._lock:
            if self._stop.is_set():return
            if self._pending_bundle is not None:self.status['coalesced_publications']+=1
            self._pending_bundle=(snapshot,metrics,time.monotonic_ns())
        self._publication_wake.set()

    def _publications(self):
        """Single bounded display writer independent of graph/model workers."""
        while not self._stop.is_set():
            self._publication_wake.wait(.02);self._publication_wake.clear()
            if self._stop.is_set():break
            with self._lock:
                if self._closing and self._pending_bundle is None:break
            now=time.monotonic_ns()
            if self._last_publication_ns is not None and (now-self._last_publication_ns)*self._publish_hz<1_000_000_000:
                continue
            with self._lock:
                if self._pending_bundle is not None:
                    self._display_bundle=self._pending_bundle;self._pending_bundle=None
                bundle=self._display_bundle
            live=self._display_live_nav
            # Read global history before the local map so a navigation update
            # racing these reads can only make the overview older, never future.
            try:
                if self._overview_provider is not None:
                    tiles=self._overview_provider()
                    if tiles is not None and tiles is not self._overview_tiles:
                        overview=build_overview(tiles)
                        age_ns(overview.source_nav.capture_monotonic_ns,overview.source_nav.clock_domain,now,self.domain)
                        dto.DisplayPublisher._validate_live_stream(
                            None if self._display_overview is None else self._display_overview.source_nav,overview.source_nav)
                        self._display_overview=overview;self._overview_tiles=tiles
                    self.status.pop('overview_error',None)
            except Exception as exc:
                self.status['overview_error']=f'{type(exc).__name__}: {exc}'[:256]
            now=time.monotonic_ns()
            try:
                if self._live_nav_provider is not None:
                    candidate=self._live_nav_provider()
                    if candidate is not None:
                        if not isinstance(candidate,NavSnapshot):raise ValueError('typed live NavSnapshot required')
                        age_ns(candidate.capture_monotonic_ns,candidate.clock_domain,now,self.domain)
                        self.publisher._validate_live_stream(live,candidate)
                        if bundle is not None:
                            if candidate.episode_id!=bundle[0].episode_id:raise ValueError('live map episode mismatch')
                            pinned=bundle[1]['sources'].nav
                            if pinned is not None:
                                self.publisher._validate_live_stream(pinned,candidate)
                        live=candidate;self._display_live_nav=candidate
                    self.status.pop('live_nav_error',None)
            except Exception as exc:
                self.status['live_nav_error']=f'{type(exc).__name__}: {exc}'[:256]
            if bundle is None:
                if live is None:continue
                # Display-only startup surface, never a canonical graph commit.
                snapshot=HierarchySnapshot(live.episode_id,0,0,0,0,{},(),
                    {'display':'awaiting_canonical_hierarchy'},0,0)
                metrics=dict(captured_frame_id=None,processed_frame_id=None,published_frame_id=None,
                    source_age_ns={},dropped_count=0,replaced_count=0,actual_profile=None,sources=dto.DisplaySources())
                bundle=(snapshot,metrics,now)
            self._last_publication_ns=now
            self._publish_bundle(*bundle,live_nav=live,overview=self._display_overview)
        with self._lock:
            self._pending_bundle=None;self._display_bundle=None;self._rgb=None

    def _publish_bundle(self,snapshot,metrics,bundle_ns,*,live_nav,overview=None):
        try:
            metrics=dict(metrics);sources=metrics['sources'];ages=dict(metrics['source_age_ns'])
            now=time.monotonic_ns()
            elapsed=max(0,now-bundle_ns)
            ages={key:None if value is None else value+elapsed for key,value in ages.items()}
            if sources.nav is not None:
                ages['map']=age_ns(sources.nav.capture_monotonic_ns,sources.nav.clock_domain,now,self.domain)
            if live_nav is not None:
                if (live_nav.episode_id!=snapshot.episode_id or
                    (sources.nav is not None and live_nav.revision<sources.nav.revision)):
                    live_nav=None
                else:
                    if sources.nav is not None:self.publisher._validate_map_geometry(sources.nav,live_nav)
                    ages['live_map']=age_ns(live_nav.capture_monotonic_ns,live_nav.clock_domain,now,self.domain)
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
            navigation=None
            try:
                provider=getattr(self,'_navigation_provider',None)
                if provider is not None:navigation=provider()
                if navigation is not None:
                    ages['navigation_plan']=age_ns(navigation.capture_monotonic_ns,navigation.clock_domain,time.monotonic_ns(),self.domain)
                self.status.pop('navigation_error',None)
            except Exception as exc:
                navigation=None;self.status['navigation_error']=f'{type(exc).__name__}: {exc}'[:256]
            displayed_nav=live_nav if live_nav is not None else sources.nav
            if overview is not None:
                if live_nav is None or overview.source_nav.revision>live_nav.revision:
                    overview=None
                else:
                    ages['overview']=age_ns(overview.source_nav.capture_monotonic_ns,overview.source_nav.clock_domain,now,self.domain)
            sources=replace(sources,live_nav=live_nav,overview=overview,best_views=tuple(self._images(sources)),robot=self._robot_trail.for_nav(displayed_nav),observation=observation,navigation=navigation)
            metrics.update(sources=sources,source_age_ns=ages)
            self.publisher.publish(snapshot,metrics)
            payload=encode_publication(self.publisher.read_latest())
            if not self._stop.is_set():_write_atomic(self.root/'publication.json',payload)
        except Exception as exc:
            self.status['dropped_publications']+=1;self.status['failed']=f'{type(exc).__name__}: {exc}'

    def _commands(self):
        while not self._stop.wait(.02):
            if self.process is not None and self.process.poll() is not None:
                self.status['failed']='UI exited with code '+str(self.process.returncode)
            for path in list((self.root/'commands').glob('*.json'))[:8]:
                command=None;ack=None;published=False;error=None
                received=time.monotonic_ns()
                try:
                    command=_command_read(path,dto.UiCommand)
                    if path.name!=command.request_uuid+'.json':raise ValueError('UI command filename mismatch')
                    ack=self.command_handler(command)
                    if not isinstance(ack,dto.UiCommandAck):raise ValueError('UiCommandAck required from handler')
                    acks=list((self.root/'acks').glob('*.json'))
                    if len(acks)>=64:
                        for old in sorted(acks,key=lambda p:p.stat().st_mtime_ns)[:len(acks)-63]:old.unlink(missing_ok=True)
                    _write_atomic(self.root/'acks'/(ack.request_uuid+'.json'),_command_bytes(ack))
                    published=True
                except Exception as exc:
                    error=_audit_text(f'{type(exc).__name__}: {exc}',128)
                    self.status['failed']=f'UI command: {error}'
                finally:
                    try:path.unlink(missing_ok=True)
                    except OSError as exc:
                        error=_audit_text(f'{error or ""}; unlink: {exc}',128)
                        self.status['failed']=f'UI command: {error}'
                    # Command lane only; keep evidence independently of consumed ACKs.
                    with self._lock:
                        self._commands_seen=min(self._commands_seen+1,2**64-1)
                        self._command_history.append(dict(command=_audit_dto(command),
                            ack=_audit_dto(ack) if isinstance(ack,dto.UiCommandAck) else None,
                            mailbox=_audit_text(path.name,80),received_monotonic_ns=received,
                            completed_monotonic_ns=time.monotonic_ns(),ack_published=published,error=error))

    def _persist_diagnostics(self):
        try:
            with self._lock:
                payload=bytes(self._diagnostics)
                audit=dict(schema_version=1,history_limit=MAX_COMMAND_HISTORY,commands_seen=self._commands_seen,
                    command_history=list(self._command_history))
            diagnostics=json.dumps(audit,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
            if len(diagnostics)>MAX_COMMAND_DIAGNOSTICS_BYTES:raise ValueError('UI command diagnostics byte bound exceeded')
            _write_atomic(self.root/'diagnostics.json',diagnostics)
            _write_atomic(self.root/'desktop.log',payload)
            # Quota release can wait on another worker's filesystem scan.
            # It belongs to the same boundedly joined finalizer, not close().
            if self._quota is not None:self._quota.release('ui-transport')
        except Exception as exc:
            self._finalizer_error=f'{type(exc).__name__}: {exc}'

    def close(self,timeout_s=1.):
        if type(timeout_s) not in (int,float) or not np.isfinite(timeout_s) or timeout_s<0:
            raise ValueError('UI shutdown timeout must be finite and nonnegative')
        deadline=time.monotonic()+timeout_s
        with self._lock:self._closing=True
        self._publication_wake.set()
        self.publication_thread.join(max(0.,deadline-time.monotonic()))
        target_sequence=None;rendered=False
        publication_path=self.root/'publication.json'
        try:
            latest=self.publisher.read_latest()
            target_sequence=None if latest is None else latest.publication_sequence
            if publication_path.exists():
                envelope=decode_publication(_read(publication_path,MAX_PUBLICATION_BYTES))
                if target_sequence is not None and envelope.publication_sequence<target_sequence:
                    self.status['failed']='final UI publication was not written'
                elif target_sequence is None:
                    target_sequence=envelope.publication_sequence
        except (OSError,ValueError,TypeError):
            self.status['failed']='final UI publication could not be read'
        rendered_path=self.root/'rendered.json'
        while target_sequence is not None and time.monotonic()<deadline:
            if self.process is not None and self.process.poll() is not None:
                break
            try:
                record=_read_json_bytes(_read(rendered_path,4096),4096)
                rendered=(type(record.get('publication_sequence')) is int and
                    record['publication_sequence']>=target_sequence)
            except (OSError,ValueError,TypeError):pass
            if rendered:break
            time.sleep(min(.01,max(0.,deadline-time.monotonic())))
        self._stop.set();self._publication_wake.set()
        if self.process is not None:
            ready=False
            try:
                ready_record=_read_json_bytes(_read(self.root/'ready.json',4096),4096)
                ready=ready_record.get('desktop')=='run_desktop'
            except (OSError,ValueError,TypeError):pass
            if ready:
                # Ask the Qt child to exit through its event loop so display
                # readers flush final source/age telemetry before escalation.
                try:_write_atomic(self.root/'shutdown.json',b'{"schema_version":1,"action":"quit"}')
                except OSError as exc:self.status['shutdown_request_error']=str(exc)[:160]
                try:self.process.wait(timeout=max(0.,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    from neusymnav.perception.appearance_client import _terminate_process_group
                    _terminate_process_group(self.process,grace_s=max(0.,deadline-time.monotonic())/2)
            else:
                from neusymnav.perception.appearance_client import _terminate_process_group
                _terminate_process_group(self.process,grace_s=max(0.,deadline-time.monotonic())/2)
        self.thread.join(max(0.,deadline-time.monotonic()))
        self.publication_thread.join(max(0.,deadline-time.monotonic()))
        if self._reader is not None:self._reader.join(max(0.,deadline-time.monotonic()))
        reader_pending=self._reader is not None and self._reader.is_alive()
        process_reaped=self.process is None or self.process.poll() is not None
        threads_stopped=not self.thread.is_alive() and not self.publication_thread.is_alive() and not reader_pending
        if process_reaped and self.process is not None:self.process.stdout.close()
        if process_reaped and threads_stopped:
            with self._finalize_lock:
                if self._finalizer is None:
                    self._finalizer=threading.Thread(target=self._persist_diagnostics,
                        name='neusymnav-ui-finalize',daemon=True)
                    self._finalizer.start()
            self._finalizer.join(max(0.,deadline-time.monotonic()))
        clean=(threads_stopped and process_reaped and (target_sequence is None or rendered)
            and self._finalizer is not None and not self._finalizer.is_alive()
            and self._finalizer_error is None)
        return dict(clean_shutdown=clean,process_reaped=self.process is None or self.process.poll() is not None,
            command_thread_pending=self.thread.is_alive(),reader_pending=reader_pending,
            publication_thread_pending=self.publication_thread.is_alive(),
            diagnostics_pending=self._finalizer is not None and self._finalizer.is_alive(),
            diagnostics_error=self._finalizer_error,final_publication_sequence=target_sequence,
            final_publication_rendered=rendered,status=dict(self.status))


def main():
    import argparse
    import signal
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--clock-domain',required=True)
    parser.add_argument('--assets-root');parser.add_argument('--recording-root');parser.add_argument('--smoke-exit-ms',type=int);args=parser.parse_args()
    endpoint=UiEndpoint(args.root,clock_domain=args.clock_domain)
    from PyQt5 import QtCore,QtWidgets
    from neusymnav.visualization.desktop import run_desktop
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def request_shutdown(_signum,_frame):
        # Parent cleanup uses SIGTERM after the final publication is acknowledged.
        # Let Qt close the window and flush async display telemetry before exit.
        app.quit()
    signal.signal(signal.SIGTERM,request_shutdown)
    shutdown_timer=QtCore.QTimer(app)
    shutdown_timer.setInterval(50)
    shutdown_timer.timeout.connect(lambda:app.quit() if (Path(args.root)/'shutdown.json').is_file() else None)
    shutdown_timer.start()
    QtCore.QTimer.singleShot(0,lambda:_write_atomic(Path(args.root)/'ready.json',json.dumps(dict(pid=os.getpid(),desktop='run_desktop',device_pixel_ratio=app.devicePixelRatio())).encode()))
    from neusymnav.visualization.best_view_reader import SelectedBestViewReader
    reader=None if args.assets_root is None else SelectedBestViewReader(args.assets_root,clock_domain=args.clock_domain)
    if args.recording_root:
        from neusymnav.visualization.hydra_assets import AsyncHydraAssetReader
        cloud=AsyncHydraAssetReader(args.recording_root)
    else:
        from neusymnav.visualization.point_cloud import AsyncCloudReader
        cloud=None if args.assets_root is None else AsyncCloudReader(args.assets_root)
    def rendered(sequence):
        record=dict(publication_sequence=sequence, display_cloud_revision=None,
                    display_cloud_source=None, display_cloud_capture_monotonic_ns=None,
                    display_cloud_clock_domain=None, display_cloud_points=0,
                    display_cloud_sources=0, display_cloud_graph_lag_ns=None)
        latest=None if cloud is None else cloud.latest
        if latest is not None:
            record.update(display_cloud_revision=latest.revision,
                display_cloud_source=latest.last_source.to_dict(),
                display_cloud_capture_monotonic_ns=latest.last_capture_ns,
                display_cloud_clock_domain=latest.clock_domain,
                display_cloud_points=len(latest.points),
                display_cloud_sources=len(latest.sources))
        if cloud is not None and cloud.error:
            record['display_cloud_error']=cloud.error
        if cloud is not None and hasattr(cloud,'report'):
            record['hydra_cloud_reader']=cloud.report()
        envelope=endpoint.read_latest()
        graph=None if envelope is None else envelope.sources.hydra_graph
        record['hydra_graph_revision']=None if graph is None else graph.graph_revision
        record['hydra_graph_source']=None if graph is None else graph.last_source
        if latest is not None and graph is not None and graph.last_source is not None:
            record['display_cloud_matches_graph_source']=_matches_graph_source(
                latest.last_source,graph.last_source)
            if (latest.clock_domain==graph.last_source.get('clock_domain')
                    and type(graph.last_source.get('capture_monotonic_ns')) is int):
                lag_ns=graph.last_source['capture_monotonic_ns']-latest.last_capture_ns
                if lag_ns>=0:record['display_cloud_graph_lag_ns']=lag_ns
        _write_atomic(Path(args.root)/'rendered.json',json.dumps(
            record,separators=(',',':')).encode())
    exit_code=run_desktop(endpoint.read_latest,endpoint.client,clock_domain=args.clock_domain,
        smoke_exit_ms=args.smoke_exit_ms,best_view_provider=None if reader is None else reader.read,
        cloud_reader=cloud,rendered_callback=rendered)
    final=endpoint.read_latest()
    if cloud is not None:
        if final is not None and hasattr(cloud,'flush'):cloud.flush(final,1.0)
        cloud.close(1.0)
    # The final publication callback runs before its async display-asset offer.
    # Rewrite the audit after the reader has shut down so the artifact captures
    # the actual last completed cloud source and any pending/error state.
    if final is not None:rendered(final.publication_sequence)
    return exit_code


if __name__=='__main__':raise SystemExit(main())
