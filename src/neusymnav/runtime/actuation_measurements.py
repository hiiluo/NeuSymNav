"""Bounded, source-bound native body measurements; no control or motion authority.

Proof validation establishes consistency, never authentication or native acceptance.
Partial movement sums are labelled observed lower bounds, not whole-run distance.
"""
from __future__ import annotations
from dataclasses import asdict
import copy
import hashlib
import json
import math
import threading
from ..contracts import MotionCommand, Observation, FrameKey


def _int(v):
    if type(v) is not int or not 0<=v<=2**63-1:raise ValueError('bounded integer required')
    return v


def _text(v):
    if type(v) is not str or not 0<len(v)<=128:raise ValueError('bounded builtin text required')
    try:
        if len(v.encode())>512:raise ValueError('text byte bound')
    except UnicodeError as exc:raise ValueError('invalid text') from exc
    return v


def _number(v):
    if type(v) not in (int,float) or abs(v)>1e9 or not math.isfinite(v):raise ValueError('bounded finite number required')
    return float(v)


def _xy(v):
    if type(v) not in (tuple,list) or len(v)!=2:raise ValueError('body XY required')
    return tuple(_number(x) for x in v)


def _closed(v,keys):
    if type(v) is not dict or any(type(k) is not str for k in v) or set(v)!=set(keys):raise ValueError('closed measurement fields required')


def _source(obs):
    if type(obs) is not Observation or type(obs.key) is not FrameKey:raise ValueError('typed observation source required')
    # Shared frozen dataclasses can still have a mutated __dict__. Guard every
    # raw field before calling shared validators, hashing or serialization.
    episode,sensor,index=obs.key.episode_id,obs.key.sensor_id,obs.key.frame_index
    return dict(schema_version='runtime_measurement_source_v1',key=dict(episode_id=_text(episode),sensor_id=_text(sensor),frame_index=_int(index)),capture_monotonic_ns=_int(obs.capture_monotonic_ns),clock_domain=_text(obs.clock_domain),pose_version=_int(obs.pose_version),calibration_id=_text(obs.calibration_id))


def command_sha256(command):
    if type(command) is not MotionCommand or type(command.source) is not FrameKey:raise ValueError('typed command required')
    k=command.source
    key=dict(episode_id=_text(k.episode_id),sensor_id=_text(k.sensor_id),frame_index=_int(k.frame_index))
    value=dict(source=key,map_revision=_int(command.map_revision),issued_monotonic_ns=_int(command.issued_monotonic_ns),deadline_monotonic_ns=_int(command.deadline_monotonic_ns),clock_domain=_text(command.clock_domain),linear_mps=command.linear_mps,yaw_radps=command.yaw_radps,reason=_text(command.reason),source_capture_monotonic_ns=_int(command.source_capture_monotonic_ns))
    _number(value['linear_mps']);_number(value['yaw_radps'])
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_actuation_proof(proof,command,observation):
    """Validate closed <=2-step proof against exact command and capture."""
    return validate_actuation_source_proof(proof,command,_source(observation),modality=observation.modality)


def validate_actuation_source_proof(proof,command,source,*,modality):
    """Validate against bounded source metadata; no image/capture authentication.

    Offline consumers must separately bind metadata to a registered capture and
    its declared navigation lane. The live wrapper requires a typed Observation.
    """
    _closed(source,{'schema_version','key','capture_monotonic_ns','clock_domain','pose_version','calibration_id'})
    _closed(source['key'],{'episode_id','sensor_id','frame_index'})
    expected=dict(schema_version=_text(source['schema_version']),key=dict(episode_id=_text(source['key']['episode_id']),sensor_id=_text(source['key']['sensor_id']),frame_index=_int(source['key']['frame_index'])),capture_monotonic_ns=_int(source['capture_monotonic_ns']),clock_domain=_text(source['clock_domain']),pose_version=_int(source['pose_version']),calibration_id=_text(source['calibration_id']))
    if expected['schema_version']!='runtime_measurement_source_v1':raise ValueError('source schema mismatch')
    checksum=command_sha256(command)
    if type(modality) is not str or modality!='depth_only':raise ValueError('actuation requires navigation depth source')
    if not 0<=command.linear_mps<=.2 or abs(command.yaw_radps)>math.radians(30.):raise ValueError('native motion limits exceeded')
    _closed(proof,{'schema_version','command_sha256','source','map_revision','source_pose_version','actions','complete','reason'})
    if type(proof['schema_version']) is not int or proof['schema_version']!=1 or proof['complete'] is not True:raise ValueError('complete proof v1 required')
    if type(proof['command_sha256']) is not str or proof['command_sha256']!=checksum:raise ValueError('command digest mismatch')
    s=proof['source'];_closed(s,expected)
    _closed(s['key'],expected['key'])
    for field in ('episode_id','sensor_id'):_text(s['key'][field])
    _int(s['key']['frame_index'])
    for field in ('capture_monotonic_ns','pose_version'):_int(s[field])
    for field in ('clock_domain','calibration_id','schema_version'):_text(s[field])
    if s!=expected or asdict(command.source)!=expected['key'] or command.clock_domain!=s['clock_domain'] or command.source_capture_monotonic_ns!=s['capture_monotonic_ns']:raise ValueError('source proof mismatch')
    if _int(proof['map_revision'])!=command.map_revision or _int(proof['source_pose_version'])!=s['pose_version']:raise ValueError('map/pose mismatch')
    _text(proof['reason'])
    actions=proof['actions']
    if type(actions) is not list or len(actions)>2:raise ValueError('bounded action list required')
    deadline=min(command.deadline_monotonic_ns,s['capture_monotonic_ns']+300_000_000)
    previous_time=command.issued_monotonic_ns;previous_pose=s['pose_version'];previous_xy=None;previous_yaw=None;distance=0.
    names={'index','action','amount','pre_step_monotonic_ns','post_step_monotonic_ns','pose_version_before','pose_version_after','body_before_xy','body_after_xy','yaw_before_rad','yaw_after_rad'}
    seen=[];nominal_duration=0.
    pulse_budget=min(.1,max(0.,(deadline-command.issued_monotonic_ns)/1e9))
    for i,a in enumerate(actions):
        _closed(a,names)
        if _int(a['index'])!=i:raise ValueError('action index mismatch')
        action=_text(a['action']);amount=_number(a['amount'])
        before_ns=_int(a['pre_step_monotonic_ns']);after_ns=_int(a['post_step_monotonic_ns'])
        if not previous_time<=before_ns<deadline or after_ns<before_ns:raise ValueError('step deadline/order mismatch')
        if _int(a['pose_version_before'])!=previous_pose or _int(a['pose_version_after'])!=previous_pose+1:raise ValueError('pose sequence mismatch')
        before,after=_xy(a['body_before_xy']),_xy(a['body_after_xy']);yb,ya=_number(a['yaw_before_rad']),_number(a['yaw_after_rad'])
        if previous_xy is not None and (math.dist(previous_xy,before)>1e-7 or abs(math.remainder(yb-previous_yaw,2*math.pi))>1e-7):raise ValueError('body proof discontinuity')
        displacement=math.dist(before,after);dyaw=math.remainder(ya-yb,2*math.pi)
        # Pulse amount is configured before the final TTL timestamp. The
        # timestamp certifies step admission, not real-time simulation duration.
        remaining=max(0.,(deadline-command.issued_monotonic_ns)/1e9)
        if action=='move_forward':
            if i!=0 or command.linear_mps<=0 or not 0<=amount<=min(.02,command.linear_mps*remaining)+1e-7 or displacement>amount+1e-7 or abs(dyaw)>1e-7:raise ValueError('translation bounds mismatch')
            nominal_duration+=amount/command.linear_mps
            dx,dy=after[0]-before[0],after[1]-before[1]
            forward=dx*math.cos(yb)+dy*math.sin(yb)
            lateral=-dx*math.sin(yb)+dy*math.cos(yb)
            if forward< -1e-7 or abs(lateral)>1e-7:raise ValueError('body moved outside forward segment')
        elif action in ('turn_left','turn_right'):
            if command.yaw_radps==0 or action!=('turn_left' if command.yaw_radps>0 else 'turn_right') or not 0<=amount<=min(3.,abs(math.degrees(command.yaw_radps))*remaining)+1e-7 or displacement>1e-7 or abs(dyaw)>math.radians(amount)+1e-7:raise ValueError('yaw bounds mismatch')
            nominal_duration+=math.radians(amount)/abs(command.yaw_radps)
            if dyaw*command.yaw_radps < -1e-7:raise ValueError('body yaw sign mismatch')
        else:raise ValueError('unrecognized native action')
        if nominal_duration>pulse_budget+1e-7:raise ValueError('combined nominal pulse duration exceeds command budget')
        if action in seen or (seen and seen[-1]!='move_forward'):raise ValueError('native action order mismatch')
        seen.append(action);distance+=displacement
        previous_time,previous_pose,previous_xy,previous_yaw=after_ns,a['pose_version_after'],after,ya
    return dict(proof=copy.deepcopy(proof),body_translation_m=distance,action_count=len(actions),method='measured_native_body_step_endpoints')


class ActuationMeasurements:
    """Bounded partial body evidence. Finalization occurs after producer stop."""
    def __init__(self,episode_id,clock_domain,*,capacity=65536):
        self.episode_id=_text(episode_id);self.clock_domain=_text(clock_domain)
        if type(capacity) is not int or not 1<=capacity<=65536:raise ValueError('invalid actuation capacity')
        self.capacity=capacity;self._lock=threading.Lock();self._seen=set();self._poses=[];self._distance=0.;self._frontier=0.;self._bad=0;self._overflow=0;self._finalized=False
    def try_record(self,command,observation,proof,*,goal_id,decision_map_revision,profile):
        if not self._lock.acquire(False):return False
        try:
            if self._finalized:raise ValueError('measurements finalized')
            checked=validate_actuation_proof(proof,command,observation)
            if observation.key.episode_id!=self.episode_id or observation.clock_domain!=self.clock_domain:raise ValueError('execution mismatch')
            identity=(observation.key.sensor_id,observation.key.frame_index)
            if identity in self._seen:raise ValueError('duplicate actuation source')
            if len(self._seen)>=self.capacity:self._overflow+=1;return False
            if goal_id is not None:_text(goal_id)
            _text(profile);_int(decision_map_revision)
            if decision_map_revision!=command.map_revision:raise ValueError('decision map mismatch')
            self._seen.add(identity);self._distance+=checked['body_translation_m']
            if goal_id is not None and profile in ('baseline','geometry-only','appearance'):self._frontier+=checked['body_translation_m']
            return True
        except (ValueError,TypeError,KeyError):self._bad=min(self._bad+1,2**63-1);return False
        finally:self._lock.release()
    def try_record_pose(self,observation,pose):
        if not self._lock.acquire(False):return False
        try:
            if self._finalized:raise ValueError('measurements finalized')
            s=_source(observation)
            _closed(pose,{'source','capture_monotonic_ns','clock_domain','pose_version','robot_xy','yaw_rad'})
            if type(pose['source']) is not FrameKey:raise ValueError('pose key required')
            k=pose['source'];_text(k.episode_id);_text(k.sensor_id);_int(k.frame_index)
            if s['clock_domain']!=self.clock_domain or pose['source']!=observation.key or _int(pose['capture_monotonic_ns'])!=s['capture_monotonic_ns'] or _text(pose['clock_domain'])!=self.clock_domain or _int(pose['pose_version'])!=s['pose_version'] or observation.key.episode_id!=self.episode_id:raise ValueError('pose proof mismatch')
            xy=_xy(pose['robot_xy']);_number(pose['yaw_rad'])
            if self._poses and s['capture_monotonic_ns']<=self._poses[-1][0]:raise ValueError('pose time moved backward')
            if len(self._poses)>=self.capacity:self._overflow+=1;return False
            self._poses.append((s['capture_monotonic_ns'],xy));return True
        except (ValueError,TypeError,KeyError):self._bad=min(self._bad+1,2**63-1);return False
        finally:self._lock.release()
    def finalize(self):
        with self._lock:
            self._finalized=True
            return dict(schema_version=1,episode_id=self.episode_id,clock_domain=self.clock_domain,complete=False,distance_m=None,frontier_distance_m=None,observed_body_translation_lower_bound_m=self._distance,observed_frontier_translation_lower_bound_m=self._frontier,accepted_commands=len(self._seen),rejected_records=self._bad,overflow=self._overflow,sampled_no_progress=summarize_body_poses(self._poses),limitation='Observed step-endpoint distances are partial lower bounds; full-run coverage requires integration proof. Sampled stationary poses do not prove continuous immobility.')


def summarize_body_poses(poses):
    """Shared offline/live sampled no-progress calculation on bounded body data."""
    if type(poses) not in (tuple,list) or len(poses)>65536:raise ValueError('bounded body pose list required')
    previous=None
    for record in poses:
        if type(record) not in (tuple,list) or len(record)!=2:raise ValueError('timestamp/body tuple required')
        stamp=_int(record[0]);_xy(record[1])
        if previous is not None and stamp<=previous:raise ValueError('body pose time moved backward')
        previous=stamp
    intervals=[];window=[];gaps=0
    for t,xy in poses:
        if window and t-window[-1][0]>1_000_000_000:window=[];gaps+=1
        window.append((t,xy))
        if t-window[0][0]>=10_000_000_000:
            travel=sum(math.dist(a[1],b[1]) for a,b in zip(window,window[1:]))
            if travel<.1:intervals.append(dict(start_ns=window[0][0],end_ns=t,observed_translation_m=travel))
            window=[(t,xy)]
    return dict(method='sampled_body_poses',window_s=10.,movement_threshold_m=.1,max_pose_gap_s=1.,pose_support=len(poses),gap_count=gaps,interval_count=len(intervals),intervals=intervals)
