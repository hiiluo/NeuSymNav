"""Bounded, episode-local references to committed object observations.

This cache is deliberately not an identity owner or a verifier. Scores are raw;
selection is a versioned heuristic, not a calibrated probability.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from types import MappingProxyType
from collections import Counter, deque
import io
import json
import math
import re
import numpy as np
from ..contracts import FrameKey
from ..contracts.serialization import loads
from ..contracts.observations import Observation, DetectionBatch, ObjectObservation, validate_object_observations
from ..perception.projector import Projector
from ..geometry.frames import validate_intrinsics, validate_pose


def _text(value, name, limit=256):
    if not isinstance(value, str) or not value or len(value.encode()) > limit:
        raise ValueError(f'invalid {name}')
    return value


def _array(value, shape):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError('invalid geometry')
    # Immutable bytes own the storage; setflags(write=True) cannot undo this.
    return np.frombuffer(a.tobytes(), dtype=np.float64).reshape(shape)


def _fraction(value, name):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f'invalid {name}')
    return value


@dataclass(frozen=True, eq=False)
class ViewEvidence:
    episode_id: str
    object_id: str
    event_id: str
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    object_revision: int
    geometry_hash: str
    calibration_id: str
    feature_space_id: str | None
    camera_pose_world: np.ndarray
    K: np.ndarray
    object_centroid_world: np.ndarray
    mask_fraction: float
    depth_support: float
    crop_ref: str
    mask_ref: str
    source_ref: str
    detector_score: float
    quality_components: dict
    quality_version: str
    schema_version: int = 1

    def __post_init__(self):
        for name in ('episode_id','object_id','event_id','clock_domain','calibration_id','quality_version'):
            _text(getattr(self, name), name)
        if self.feature_space_id is not None: _text(self.feature_space_id, 'feature_space_id')
        if not isinstance(self.source, FrameKey) or self.source.episode_id != self.episode_id:
            raise ValueError('source episode mismatch')
        _text(self.source.sensor_id, 'sensor_id')
        for name in ('geometry_hash','crop_ref','mask_ref','source_ref'):
            if not isinstance(getattr(self,name),str) or not re.fullmatch('[0-9a-f]{64}',getattr(self,name)):
                raise ValueError(f'invalid {name}')
        for name in ('capture_monotonic_ns','object_revision'):
            v=getattr(self,name)
            if isinstance(v,bool) or not isinstance(v,int) or v<0: raise ValueError(f'invalid {name}')
        if self.schema_version != 1: raise ValueError('unsupported evidence version')
        pose=_array(self.camera_pose_world,(4,4)); k=_array(self.K,(3,3)); center=_array(self.object_centroid_world,(3,))
        validate_pose(pose); validate_intrinsics(k)
        if np.linalg.norm(center-pose[:3,3]) < 1e-9: raise ValueError('undefined view direction')
        object.__setattr__(self,'camera_pose_world',pose); object.__setattr__(self,'K',k)
        object.__setattr__(self,'object_centroid_world',center)
        for name in ('mask_fraction','depth_support'):
            object.__setattr__(self,name,_fraction(getattr(self,name),name))
        score=float(self.detector_score)
        if not math.isfinite(score): raise ValueError('invalid raw score')
        object.__setattr__(self,'detector_score',score)
        if not hasattr(self.quality_components,'items') or len(self.quality_components)>16:
            raise ValueError('invalid quality components')
        values={_text(k,'quality component',64): _fraction(v,k) for k,v in self.quality_components.items()}
        object.__setattr__(self,'quality_components',MappingProxyType(values))

    @property
    def view_direction(self):
        delta=self.object_centroid_world-self.camera_pose_world[:3,3]
        return _array(delta/np.linalg.norm(delta),(3,))


def _charge(v):
    strings=(v.episode_id,v.object_id,v.event_id,v.source.sensor_id,v.clock_domain,v.geometry_hash,
        v.calibration_id,v.feature_space_id or '',v.crop_ref,v.mask_ref,v.source_ref,v.quality_version)
    # Conservative fixed Python/container allowance, in addition to all variable payloads.
    return 2048 + sum(len(s.encode()) for s in strings) + sum(len(k.encode())+64 for k in v.quality_components) + v.camera_pose_world.nbytes+v.K.nbytes+v.object_centroid_world.nbytes


@dataclass(frozen=True)
class ViewMemorySummary:
    episode_id: str
    object_revision: int
    evidence_revision: int
    policy_version: str
    views: object
    aliases: object
    charged_bytes: int
    eviction_counters: object
    recent_trace: tuple


class ViewMemory:
    def __init__(self, episode_id, *, max_views_per_object=6, max_objects=256, max_bytes=64*1024*1024,
                 min_baseline_m=.3, min_angle_deg=15., policy_version='view-selection:v1'):
        if any(isinstance(x,bool) or not isinstance(x,int) or x<=0 for x in (max_views_per_object,max_objects,max_bytes)):
            raise ValueError('positive integer limits required')
        if max_bytes < 4096: raise ValueError('max_bytes must accommodate fixed metadata')
        if not math.isfinite(min_baseline_m) or min_baseline_m<=0 or not math.isfinite(min_angle_deg) or not 0<min_angle_deg<=180:
            raise ValueError('invalid diversity policy')
        self.max_views_per_object=max_views_per_object; self.max_objects=max_objects; self.max_bytes=max_bytes
        self.min_baseline_m=min_baseline_m; self.min_angle_deg=min_angle_deg; self.policy_version=_text(policy_version,'policy_version')
        self.reset(episode_id)

    def reset(self, episode_id):
        self.episode_id=_text(episode_id,'episode_id'); self._views={}; self._aliases={}
        self._revision=0; self._object_revision=0; self._counters=Counter(); self._trace=deque(maxlen=32)
        self._sensor=None; self._frame=-1; self._frame_events=set(); self._frame_closed=False

    def _resolve(self, key):
        seen=set()
        while key in self._aliases:
            if key in seen: raise ValueError('alias cycle')
            seen.add(key); key=self._aliases[key]
        return key

    def _note(self, reason, event):
        self._counters[reason]=min(self._counters[reason]+1, 2**63-1); self._trace.append((reason,event))
        while self._trace and self._total()>self.max_bytes: self._trace.popleft()

    @staticmethod
    def _rank(v):
        return (v.depth_support, v.mask_fraction, v.detector_score)

    def _independent(self, a, b):
        if a.event_id == b.event_id or a.source == b.source: return False
        baseline=np.linalg.norm(a.camera_pose_world[:3,3]-b.camera_pose_world[:3,3])
        angle=math.degrees(math.acos(float(np.clip(np.dot(a.view_direction,b.view_direction),-1,1))))
        return baseline >= self.min_baseline_m and angle >= self.min_angle_deg

    def offer(self, evidence):
        if not isinstance(evidence,ViewEvidence) or evidence.episode_id != self.episode_id: raise ValueError('episode/evidence mismatch')
        if self._sensor is not None and evidence.source.sensor_id != self._sensor:
            return False
        frame=evidence.source.frame_index
        if frame < self._frame or (frame == self._frame and evidence.event_id in self._frame_events):
            return False
        if frame > self._frame:
            self._sensor=evidence.source.sensor_id; self._frame=frame; self._frame_events=set(); self._frame_closed=False
        if self._frame_closed: return False
        if len(self._frame_events)>=1536 or self._total()+128+len(evidence.event_id.encode())>self.max_bytes:
            self._frame_closed=True
            return False
        self._frame_events.add(evidence.event_id)
        return self._offer(evidence)

    def _offer(self, evidence):
        canonical=self._resolve(evidence.object_id)
        if canonical!=evidence.object_id: evidence=replace(evidence,object_id=canonical)
        if any(v.event_id==evidence.event_id for vs in self._views.values() for v in vs): return False
        if 4096+_charge(evidence)>self.max_bytes: self._note('oversize',evidence.event_id); return False
        views=self._views.setdefault(canonical,[])
        correlated=[v for v in views if not self._independent(v,evidence)]
        if correlated:
            if any(self._rank(v)>=self._rank(evidence) for v in correlated):
                if not views: self._views.pop(canonical,None)
                return False
            for v in correlated: views.remove(v); self._note('correlated_replaced',v.event_id)
        views.append(evidence)
        if len(views)>self.max_views_per_object:
            loser=min(views,key=self._rank); views.remove(loser); self._note('object_limit',loser.event_id)
        while len(self._views)>self.max_objects or self._total()>self.max_bytes:
            reason='object_limit_global' if len(self._views)>self.max_objects else 'byte_limit'
            # Evict whole objects to ensure metadata stays bounded.
            loser=min(self._views, key=lambda k:(max(self._rank(v) for v in self._views[k]),k))
            for v in self._views.pop(loser): self._note(reason,v.event_id)
        self._object_revision=max(self._object_revision,evidence.object_revision); self._revision+=1
        return any(v.event_id==evidence.event_id for vs in self._views.values() for v in vs)

    def _total(self):
        return (4096 + sum(128+len(e.encode()) for e in self._frame_events) + sum(_charge(v) for vs in self._views.values() for v in vs) + sum(256+len(a.encode())+len(b.encode()) for a,b in self._aliases.items()) + sum(128+len(r.encode())+len(e.encode()) for r,e in self._trace))

    def remap(self, aliases, current_object_centroids=None):
        # The owner publishes a full alias map. Keep only routes touching retained
        # objects or already-retained aliases; unrelated history consumes no cache.
        full={**self._aliases,**dict(aliases)}
        def resolve(key):
            seen=set()
            while key in full:
                if key in seen: raise ValueError('alias cycle')
                seen.add(key); key=full[key]
            return key
        relevant=set(self._views) | set(self._aliases)
        chosen={}
        for key in sorted(relevant):
            if key in full:
                _text(key,'alias'); target=_text(resolve(key),'alias target')
                if key!=target: chosen[key]=target
            elif key in self._aliases:
                target=resolve(self._aliases[key])
                if key!=target: chosen[key]=target
        # Aliases are hints only; owner remains canonical authority. Deterministic
        # retention ensures a large episode history cannot stop the graph lane.
        ordered=sorted(chosen.items())
        dropped=[key for key,_ in ordered[self.max_objects:]]
        chosen=dict(ordered[:self.max_objects])
        while chosen and 4096+sum(128+len(e.encode()) for e in self._frame_events)+sum(256+len(a.encode())+len(b.encode()) for a,b in chosen.items())>self.max_bytes:
            key=max(chosen); chosen.pop(key); dropped.append(key)
        items=[v for k in sorted(self._views) for v in self._views[k]]
        transformed=[]
        for v in items:
            target=resolve(v.object_id)
            center=v.object_centroid_world
            if current_object_centroids is not None and target in current_object_centroids:
                center=_array(current_object_centroids[target],(3,))
            if target!=v.object_id or not np.array_equal(center,v.object_centroid_world):
                v=replace(v,object_id=target,object_centroid_world=center)
            transformed.append(v)
        if chosen==self._aliases and all(a is b for a,b in zip(items,transformed)):
            return
        old=(self._aliases,self._views,self._revision,self._object_revision,self._counters.copy(),self._trace.copy())
        try:
            self._aliases=chosen; self._views={}
            for key in dropped: self._note('alias_limit',key)
            for v in transformed: self._offer(v)
            self._revision=old[2]+1
        except Exception:
            self._aliases,self._views,self._revision,self._object_revision,self._counters,self._trace=old
            raise

    def snapshot(self, object_revision=None):
        revision=self._object_revision if object_revision is None else object_revision
        if isinstance(revision,bool) or not isinstance(revision,int) or revision<self._object_revision: raise ValueError('invalid object revision')
        return ViewMemorySummary(self.episode_id,revision,self._revision,self.policy_version,
            MappingProxyType({k:tuple(sorted(v,key=lambda x:x.event_id)) for k,v in sorted(self._views.items())}),
            MappingProxyType(dict(self._aliases)),self._total(),MappingProxyType(dict(self._counters)),tuple(self._trace))


def read_committed_views(owner, commit):
    """Read only the supplied commit's detected views via indexed event lookups.

    Invalid or missing source/geometry is omitted; absence is not negative evidence.
    The caller can replay individual committed event IDs by constructing a commit
    with the current owner snapshot. Never read semantic ground truth.
    """
    snapshot=commit.snapshot
    if len(commit.committed_event_ids)>1536: raise ValueError('commit exceeds bounded view batch')
    result=[]
    cached_key=None; cached_source=None; cached_batch=None
    for event_id in commit.committed_event_ids:
        try:
            row=owner.ledger.connection.execute(
                'SELECT object_id,mask_asset,crop_asset,data FROM views WHERE event_id=? AND length(data)<=65536',
                (event_id,)).fetchone()
            if row is None: continue
            data=json.loads(row['data'])
            if data['evidence_kind']!='detected' or row['object_id'] is None: continue
            object_id=snapshot.resolve_id(row['object_id'])
            cache_key=(data['source_asset'],data['batch_asset'])
            if cache_key != cached_key:
                cached_key=None; cached_source=None; cached_batch=None
                cached_source=loads(owner.assets.read(cache_key[0]).decode())
                cached_batch=loads(owner.assets.read(cache_key[1]).decode())
                cached_key=cache_key
            source=cached_source; batch=cached_batch
            observed=loads(owner.assets.read(data['observation_asset']).decode())
            if not isinstance(source,Observation) or not isinstance(batch,DetectionBatch) or not isinstance(observed,ObjectObservation) or source.key!=FrameKey(**data['source']): continue
            validate_object_observations(source,batch,(observed,))
            if (batch.vocabulary_id!=data['vocabulary_id'] or source.pose_version!=data['pose_version']
                or source.clock_domain!=owner._config['clock_domain'] or source.key.sensor_id!=owner._config['primary_sensor_id']): continue
            # Keep the owner digest as provenance. Do not reconstruct its
            # byte hash from an embedding normalized again at deserialization.
            if not re.fullmatch('[0-9a-f]{64}',data['association_digest']): continue
            if event_id not in snapshot.objects[object_id].evidence_refs: continue
            if (source.geometry_hash!=data['geometry_hash'] or source.calibration_id!=data['calibration_id']
                or source.capture_monotonic_ns!=data['capture_monotonic_ns'] or source.clock_domain!=data['clock_domain']
                or observed.source!=source.key or observed.geometry_hash!=source.geometry_hash
                or observed.detection_id!=data['detection_id'] or observed.evidence_kind!='detected'
                or observed.score!=data['score'] or data['object_revision']>snapshot.revision): continue
            mask=np.load(io.BytesIO(owner.assets.read(row['mask_asset'])),allow_pickle=False)
            detection=next((d for d in batch.detections if d.detection_id==observed.detection_id),None)
            if detection is None or mask.dtype!=np.bool_ or mask.shape!=source.depth_m.shape or not np.array_equal(mask,detection.mask): continue
            # Verify content address of crop, without retaining the image.
            owner.assets.read(row['crop_asset'])
            valid=mask & source.valid_depth & (source.depth_m>=.15) & (source.depth_m<5.)
            count=int(mask.sum()); support=float(valid.sum())/count
            if not valid.any() or len(observed.points_world)==0: continue
            # The owner stores voxelized measured points (possibly subsampled).
            # Re-project only this mask and require every point to be source-derived.
            one=DetectionBatch(batch.source,batch.geometry_hash,batch.vocabulary_id,(detection,),batch.completion,batch.cap_reached)
            projected=Projector(min_points=1,max_points=source.depth_m.size).project(source,one)
            if not projected: continue
            allowed={tuple(np.round(point,7)) for point in projected[0].points_world}
            if any(tuple(np.round(point,7)) not in allowed for point in observed.points_world): continue
            fraction=count/mask.size
            feature=None if observed.appearance is None else observed.appearance.space_id
            result.append(ViewEvidence(episode_id=source.key.episode_id,object_id=object_id,event_id=event_id,
                source=source.key,capture_monotonic_ns=source.capture_monotonic_ns,clock_domain=source.clock_domain,
                object_revision=data['object_revision'],geometry_hash=source.geometry_hash,calibration_id=source.calibration_id,
                feature_space_id=feature,camera_pose_world=source.T_world_camera,K=source.K,
                object_centroid_world=np.median(observed.points_world,axis=0),mask_fraction=fraction,
                depth_support=support,crop_ref=row['crop_asset'],mask_ref=row['mask_asset'],source_ref=data['source_asset'],
                detector_score=data['score'],quality_components={'mask_fraction':fraction,'depth_support':support},
                quality_version='source-mask-depth:v1'))
        except (ValueError,TypeError,KeyError,AttributeError,OSError,UnicodeError):
            continue
    return tuple(result)
