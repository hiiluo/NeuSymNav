"""One canonical graph owner, independent latest navigation, durable recovery.

Factories are explicit: native/model dependencies are never silently replaced
by fixtures. ``submit`` offers memory reservations; only ``durable_accepted``
is a persistence ACK. All source assets retain original identity and clock.
"""
from __future__ import annotations
from dataclasses import replace
from copy import deepcopy
from contextlib import contextmanager, nullcontext
import inspect
import json
import math
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from threading import Event,RLock
import time
import numpy as np
from ..contracts import Observation,RegionSnapshot,MotionCommand,age_ns
from ..contracts.observations import validate_detection_batch,validate_appearance_batch
from ..contracts.serialization import dumps
from ..hierarchy.composer import HierarchyComposer,publication_objects
from ..perception.projector import Projector
from ..perception.appearance_client import attach_features
from ..mapping.gpu_raycast_client import CompletedRequestDeadline
from .scheduler import Entry,KeyframeScheduler,KeyframePolicy,payload_bound
from .workers import Journal,atomic_write,background,remaining,valid_timeout
from .health import Health
from .quota import RunQuota

ROOM_PIPELINE_DISK_RESERVATION_BYTES = 2 * 1024**3 + 128 * 1024**2


def _stationary_partial_yaw_refusal(actuator, result, command, source, xy, yaw):
    """Accept only source-bound measured zero translation, never a collision claim."""
    if (not isinstance(result,dict) or result.get('executed') is not True or
            result.get('reason')!='yaw_preflight_unavailable' or command.linear_mps<=0 or
            command.yaw_radps==0):
        return False
    try:
        from .actuation_measurements import validate_actuation_proof
        checked=validate_actuation_proof(actuator.last_actuation_proof,command,source)
        proof=checked['proof'];actions=proof['actions']
        if (proof['reason']!=result['reason'] or len(actions)!=1 or
                actions[0]['action']!='move_forward' or actions[0]['amount']<=0 or
                result.get('actions')!=[dict(action=actions[0]['action'],amount=actions[0]['amount'])] or
                type(result.get('displacement_m')) not in (int,float) or
                not math.isfinite(result['displacement_m']) or
                abs(result['displacement_m']-checked['body_translation_m'])>1e-7):
            return False
        # The measurement validator uses 1e-7m/rad for source/action continuity.
        return (checked['body_translation_m']<=1e-7 and
                math.dist(actions[0]['body_before_xy'],xy)<=1e-7 and
                abs(math.remainder(actions[0]['yaw_before_rad']-yaw,2*math.pi))<=1e-7)
    except Exception:
        return False


def _active_display(status, objects):
    if status is None:return None
    active=status.get('active') or {}
    fresh=status.get('object_revision')==objects.revision
    return dict(mode=status['mode'], object_revision=objects.revision, stale=not fresh,
                target=(active.get('object_id') or status.get('shadow_target')) if fresh else None,
                state=active.get('state','idle') if fresh else 'historical',
                reason=status['reason'], remaining_time_ns=status['remaining_time_ns'])


class Pipeline:
    """Episode-scoped runtime with injected, worker-owned resources.

    ``owner_factory()`` creates ObjectOwner in the sole graph thread.
    ``detector_factory().infer(obs)`` is called once; result is journaled before
    commit so restart reuses it. Optional ``verifier_factory(owner)`` owns its
    durable derived ledger in that same thread. Encoder/region factories follow
    the locked P05/P06 APIs. mapper/navigator/guard are dedicated navigation
    resources, never shared with graph/model workers.
    """
    def __init__(self,root,*,episode_id,primary_sensor_id,clock_domain,
                 owner_factory,detector_factory,verifier_factory=None,encoder_factory=None,
                 region_factory=None,mapper=None,navigator=None,guard=None,
                 now_ns=time.monotonic_ns,keyframe_policy=None,projector=None,
                 floor_id,actual_profile='geometry-only',
                 byte_cap=32*1024**2,raw_cap=2*1024**3,total_cap=8*1024**3,
                 startup_timeout_s=5.,publisher=None,measurements=None,keyframe_sampling='novelty',admission_mode='off',
                 active_perception=None,active_body_z_m=None):
        self._active=None
        self._active_memory=None
        self._active_input=None
        self._active_capture_expected=None
        self._active_capture_result=None
        self._active_status=None
        self._active_body_z_m=active_body_z_m
        self._active_camera_fault=False
        active_options=active_perception or {}
        if active_options.get('mode','off')!='off':
            from .active_perception import ActivePerception
            from ..verification.view_memory import ViewMemory
            if active_body_z_m is None or navigator is None:
                raise ValueError('active perception requires fixed-height live navigation')
            self._active=ActivePerception(episode_id,clock_domain,active_options['mode'],
                                          strategy=active_options.get('strategy','candidate'))
            self._active_memory=ViewMemory(episode_id)
        if type(admission_mode) is not str or admission_mode not in {'off','shadow','enforce'}:
            raise ValueError('invalid object admission mode')
        self._admission_mode=admission_mode;self._admission_snapshot=None
        self._admission_status=dict(mode=admission_mode,status='off' if admission_mode=='off' else 'unavailable',reason='not_evaluated')
        if type(keyframe_sampling) is not str or keyframe_sampling not in {'novelty','capacity_deferred'}:
            raise ValueError('keyframe_sampling must be novelty or capacity_deferred')
        if not all(isinstance(v,str) and v for v in (episode_id,primary_sensor_id,clock_domain,floor_id,actual_profile)):
            raise ValueError('explicit episode/sensor/clock/floor/profile identities required')
        valid_timeout(startup_timeout_s)
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.episode_id=episode_id;self.primary_sensor_id=primary_sensor_id;self.clock_domain=clock_domain
        self.floor_id=floor_id;self.now_ns=now_ns;self.publisher=publisher;self.measurements=measurements
        self.owner_factory=owner_factory;self.detector_factory=detector_factory;self.verifier_factory=verifier_factory
        self.encoder_factory=encoder_factory;self.region_factory=region_factory
        self.room_pipeline_factory=room_pipeline_factory
        self.mapper=mapper;self.navigator=navigator;self.guard=guard
        core=getattr(mapper,'_core',None)
        if core is not None:self._require_run_path(core._tile_archive.directory,'NavMapper tile_archive_dir')
        self.policy=keyframe_policy or KeyframePolicy();self.projector=projector or Projector()
        self._keyframe_sampling=keyframe_sampling
        self._semantic_sampling=dict(seen=0,deferred_capacity=0,policy_evaluated=0,policy_unselected=0,offered=0)
        self._semantic_sampling_saturated=False
        self.scheduler=KeyframeScheduler(byte_cap=byte_cap);self.quota=RunQuota(self.root,raw_cap=raw_cap,total_cap=total_cap)
        from ..mapping.occupancy import NavMapper
        self._archive_write_reserved = type(mapper) is NavMapper
        if self._archive_write_reserved:
            mapper.bind_archive_reservation(self._navigation_archive_scope)
        self.health=Health(actual_profile);self._lock=RLock();self._control_lock=RLock()
        self._wake=Event();self._nav_wake=Event();self._region_wake=Event();self._ready=Event();self._recorder_done=Event()
        self._closing=False;self._paused=False;self._stop_requested=False;self._deadline=None
        self._latest_depth=None;self._nav_input=None;self._nav_pose_input=None;self._latest_nav=None;self._region_input=None
        self._latest_overview_tiles=None
        self._pose_offer=None;self._pose_watermark=None;self._place_input=None
        self._place_counts=dict(offered=0,pose_replaced=0,pair_replaced=0,consumed=0,stale=0,unmatched=0)
        self._place_status='unavailable_no_measured_pose'
        self._accepted_nav=None;self._regions=None;self._objects=None;self._hierarchy=None;self._hierarchy_nav=None;self._publication_revisions=None
        self._region_diagnostics={};self._accepted_region_scope='local_snapshot'
        self._room_queue=deque();self._room_queue_bytes=0;self._room_inflight_bytes=0
        self._room_publication=None;self._room_session=None;self._room_failure=None
        self._room_journal=deque(maxlen=8192)
        self._room_journal_dropped=0
        self._room_counts=dict(offered=0,queued=0,session_admitted=0,rejected=0,processed=0,queue_dropped=0)
        self._room_wake=Event()
        self._prior_incomplete=False;self._fast=None;self._processed=None;self._captured=None;self._last_index=-1;self._last_stamp=-1
        self._counts=dict(submitted=0,offered=0,durable_accepted=0,committed=0,missing=0,recovered=0,detector_calls=0)
        self._journal_counts=dict(accepted=0,committed=0,pending=0);self._cleanup_pending={};self._worker_done={}
        self._config=dict(schema_version=1,episode_id=episode_id,primary_sensor_id=primary_sensor_id,
                          clock_domain=clock_domain,floor_id=floor_id,actual_profile=actual_profile)
        if keyframe_sampling!='novelty':self._config['keyframe_sampling']=keyframe_sampling
        if admission_mode!='off':self._config['object_admission_mode']=admission_mode
        self._threads={}
        self._threads['graph']=background('graph',self._graph_run)
        if not self._ready.wait(startup_timeout_s):
            self.health.fail('startup',TimeoutError('graph startup/recovery deadline exceeded'))
        if not self.health.snapshot()['failed']:
            self._threads['recorder']=background('recorder',self._recorder_run)
            if mapper is not None:self._threads['navigation']=background('navigation',self._navigation_run)
            if region_factory is not None:self._threads['region']=background('region',self._region_run)
            if room_pipeline_factory is not None:self._threads['room_pipeline']=background('room-pipeline',self._room_pipeline_run)
        else:self._recorder_done.set()

    def _require_run_path(self,path,label):
        path=Path(path)
        if any(p.is_symlink() for p in (path,*path.parents)) or not path.resolve().is_relative_to(self.root):
            raise ValueError(label+' must be inside the runtime run root; configure an explicit run-local directory')

    def _fail(self,name,error):
        self.health.fail(name,error)
        with self._lock:self.scheduler.failed=str(error)
        self._wake.set();self._nav_wake.set();self._region_wake.set()

    def submit(self,obs:Observation)->None:
        if not isinstance(obs,Observation):raise TypeError('submit requires Observation')
        if self.measurements is not None:self.measurements.capture(obs)
        # No hashes, serialization, inference, map integration or disk access here.
        with self._lock:
            self._counts['submitted']+=1
            if self.measurements is not None and self.measurements.stop_requested.is_set():
                self._paused=True;self._stop_requested=True
            if obs.key.episode_id!=self.episode_id or obs.clock_domain!=self.clock_domain:
                self._counts['missing']+=1;raise ValueError('source episode/clock mismatch')
            age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)
            if self._closing or self._paused or self.health.snapshot()['failed'] or not self._ready.is_set():
                self._counts['missing']+=1;self.health.increment('rejected');return
            if obs.modality=='rgbd':
                if obs.key.sensor_id!=self.primary_sensor_id:raise ValueError('graph lane requires primary RGB-D sensor')
                if obs.key.frame_index<=self._last_index or obs.capture_monotonic_ns<self._last_stamp:
                    raise ValueError('source order moved backward')
            self._captured=obs.key
            if obs.modality=='depth_only':
                if self._latest_depth is not None and (obs.key.sensor_id!=self._latest_depth.key.sensor_id or
                    obs.key.frame_index<=self._latest_depth.key.frame_index or obs.capture_monotonic_ns<self._latest_depth.capture_monotonic_ns):
                    raise ValueError('navigation source replay or sensor change')
                self._latest_depth=obs
            if self.mapper is not None:
                if self._nav_input is not None:self.health.increment('nav_replaced')
                self._nav_input=obs
                proof=self._pose_offer
                self._nav_pose_input=None
                if obs.modality=='depth_only' and proof is not None and proof[0]==(obs.key,obs.capture_monotonic_ns,obs.clock_domain,obs.pose_version):
                    self._nav_pose_input=proof[1];self._pose_offer=None
                self._nav_wake.set()
            if obs.modality!='rgbd':return
            if self.room_pipeline_factory is not None:
                self._offer_room_input_locked(obs)
            self._last_index=obs.key.frame_index;self._last_stamp=obs.capture_monotonic_ns
            if self._semantic_sampling['seen']==(1<<63)-1:
                # Stop before incrementing any population: independent counter
                # clamping would destroy the two conservation equalities.
                self._semantic_sampling_saturated=True
                self._counts['missing']+=1;self.health.increment('rejected')
                self._fail('semantic_sampling',OverflowError('semantic sampling counter exhausted'))
                return
            self._semantic_sampling['seen']+=1
            active=getattr(self,'_active',None)
            tagged=active is not None and active.capture_source==obs.key
            if self._keyframe_sampling=='capacity_deferred' and self.scheduler.semantic_busy():
                self._semantic_sampling['deferred_capacity']+=1
                if tagged:active.capture_source=None;active.reason='capture_deferred_capacity'
                return
            self._semantic_sampling['policy_evaluated']+=1
            selected,reason,novelty=self.policy.propose(obs)
            if tagged:selected,reason=True,'active_reobserve'
            if not selected:
                self._semantic_sampling['policy_unselected']+=1
                return
            self._semantic_sampling['offered']+=1
            self._counts['offered']+=1
            if self.measurements is not None:self.measurements.admission(obs,'offered')
            entry=Entry(obs,payload_bound(obs),novelty,reason)
            accepted,replaced,_=self.scheduler.offer(entry)
            if not accepted:
                if tagged:active.capture_source=None;active.reason='capture_rejected'
                self._counts['missing']+=1;self.health.increment('rejected')
                if self.measurements is not None:self.measurements.admission(obs,'rejected')
                return
            if active is not None and any(v.observation.key==active.capture_source for v in replaced):
                active.capture_source=None;active.reason='capture_replaced'
            self._counts['missing']+=len(replaced)
            if self.measurements is not None:
                for victim in replaced:self.measurements.admission(victim.observation,'replaced')
            self.policy.commit(obs)
            self._wake.set()

    def submit_sensor_pair(self,primary,navigation,pose):
        """Publish a captured RGB-D/depth pair under one navigation queue lock.

        Only pending queue selection is atomic. An older inflight map may finish;
        recorder, health/cap changes or callback failures have no rollback promise.
        Acquisition and raw persistence belong outside this bounded admission seam.
        """
        if not isinstance(primary,Observation) or not isinstance(navigation,Observation):
            raise TypeError('sensor pair requires two Observations')
        if primary.modality!='rgbd' or navigation.modality!='depth_only':
            raise ValueError('sensor pair requires primary RGB-D then navigation depth')
        if primary.key.sensor_id!=self.primary_sensor_id or navigation.key.sensor_id==self.primary_sensor_id:
            raise ValueError('sensor pair requires configured primary and distinct navigation sensor')
        control=self._control_lock if getattr(self,'_active',None) is not None else nullcontext()
        with control,self._lock:
            for obs in (primary,navigation):
                if obs.key.episode_id!=self.episode_id or obs.clock_domain!=self.clock_domain:
                    raise ValueError('sensor pair episode/clock mismatch')
                age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)
            if primary.capture_monotonic_ns>navigation.capture_monotonic_ns or primary.pose_version!=navigation.pose_version:
                raise ValueError('sensor pair capture order/body pose changed')
            if primary.key.frame_index<=self._last_index or primary.capture_monotonic_ns<self._last_stamp:
                raise ValueError('source order moved backward')
            previous=self._latest_depth
            if previous is not None and (navigation.key.sensor_id!=previous.key.sensor_id or
                navigation.key.frame_index<=previous.key.frame_index or navigation.capture_monotonic_ns<previous.capture_monotonic_ns):
                raise ValueError('navigation source replay or sensor change')
            self._validated_robot_pose(navigation,pose)
            self._validate_pose_order(navigation)
            active=getattr(self,'_active',None)
            if active is not None and not self._active_camera_fault:
                from ..navigation.viewpoints import CameraModel
                model=CameraModel.from_observation(primary,pose['robot_xy'],pose['yaw_rad'],self._active_body_z_m)
                if active.camera is None:active.camera=model
                elif (model.image_shape_hw!=active.camera.image_shape_hw
                      or not np.allclose(model.K,active.camera.K,rtol=0,atol=1e-8)
                      or not np.allclose(model.T_body_camera,active.camera.T_body_camera,rtol=0,atol=1e-5)):
                    active.interrupt(self.now_ns(),'camera_mount_changed')
                    active.camera=None;active.planner=None;self._active_camera_fault=True
                if active.camera is not None and active.tag_capture(primary,pose['robot_xy'],pose['yaw_rad']):
                    self._active_capture_expected=primary.key
                    self._active_capture_result=None
            self.submit(primary)
            self.submit_robot_pose(navigation,pose)
            self.submit(navigation)

    def submit_navigation(self,navigation,pose):
        """Admit one fresh depth/pose transaction without replaying primary RGB.

        Keep pose and navigation queue selection atomic with respect to mapper
        dequeue, just as submit_sensor_pair does for a newly captured pair.
        """
        if not isinstance(navigation,Observation) or navigation.modality!='depth_only':
            raise ValueError('navigation admission requires depth_only Observation')
        if navigation.key.sensor_id==self.primary_sensor_id:
            raise ValueError('navigation admission requires distinct navigation sensor')
        with self._lock:
            self._validated_robot_pose(navigation,pose)
            self._validate_pose_order(navigation)
            self.submit_robot_pose(navigation,pose)
            self.submit(navigation)

    def _validated_robot_pose(self,observation,pose):
        """Check exact measured provenance without admission or observer effects."""
        names={'source','capture_monotonic_ns','clock_domain','pose_version','robot_xy','yaw_rad'}
        obs=observation
        if not isinstance(obs,Observation) or obs.modality!='depth_only':raise ValueError('body pose requires its exact depth_only Observation')
        if not isinstance(pose,Mapping) or set(pose)!=names:raise ValueError('body pose requires closed measured provenance fields')
        identity=(obs.key,obs.capture_monotonic_ns,obs.clock_domain,obs.pose_version)
        if (pose['source'],pose['capture_monotonic_ns'],pose['clock_domain'],pose['pose_version'])!=identity:
            raise ValueError('body pose source/time/domain/version mismatch')
        if type(pose['capture_monotonic_ns']) is not int or type(pose['pose_version']) is not int:
            raise ValueError('body pose integer provenance required')
        if obs.key.episode_id!=self.episode_id or obs.clock_domain!=self.clock_domain or not self.clock_domain.startswith('host_monotonic:'):
            raise ValueError('body pose admission requires current live episode clock')
        if age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)>300_000_000:
            raise ValueError('body pose source is stale')
        xy=pose['robot_xy']
        if not isinstance(xy,(tuple,list)) or len(xy)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*xy,pose['yaw_rad'])):
            raise ValueError('finite measured robot_xy/yaw required')
        return identity,dict(pose,robot_xy=tuple(float(v) for v in xy))

    def _validate_pose_order(self,obs):
        if self._pose_watermark is not None:
            key,stamp=self._pose_watermark
            if obs.key.sensor_id!=key.sensor_id or obs.key.frame_index<=key.frame_index or obs.capture_monotonic_ns<stamp:
                raise ValueError('body pose source replay/order mismatch')

    def submit_robot_pose(self,observation,pose):
        """Offer one measured body pose before submit of its exact depth capture.

        This seam never infers body position from a camera transform. Navigation
        atomically pins the proof with its queued input; graph owns all place work.
        """
        obs=observation
        identity,proof=self._validated_robot_pose(obs,pose)
        with self._lock:
            if self._closing or self.health.snapshot()['failed']:return
            self._validate_pose_order(obs)
            if self._pose_offer is not None:self._place_counts['pose_replaced']+=1
            self._pose_offer=(identity,proof);self._pose_watermark=(obs.key,obs.capture_monotonic_ns)
            self._place_counts['offered']+=1
        if self.measurements is not None:self.measurements.pose(obs,proof)

    def _consume_place(self):
        with self._lock:pair=self._place_input;self._place_input=None
        if pair is None:return
        nav,proof=pair
        if age_ns(nav.capture_monotonic_ns,nav.clock_domain,self.now_ns(),self.clock_domain)>300_000_000:
            with self._lock:self._place_counts['stale']+=1
            return
        if not hasattr(self,'_composer'):self._composer=HierarchyComposer(robot=getattr(self.mapper,'robot',None))
        if self._composer.places is None:
            self._place_status='unavailable_robot_geometry';return
        snapshot=self._composer.observe_place(nav,proof['robot_xy'],pose_source=proof['source'],
            capture_monotonic_ns=proof['capture_monotonic_ns'],clock_domain=proof['clock_domain'])
        self._place_status='observed' if snapshot.places else 'unavailable_floor_clearance'
        with self._lock:self._place_counts['consumed']+=1


    def _recorder_run(self):
        journal=None
        try:
            journal=Journal(self.root,self._config)
            while True:
                entry=self.scheduler.next_to_record()
                if entry is None:
                    if self._closing or self.health.snapshot()['failed']:break
                    self._wake.wait(.01);self._wake.clear();continue
                key=('source',entry.index)
                persisted=False
                try:
                    self.quota.reserve(key,entry.payload_bytes*2+131072,entry.payload_bytes*2)
                    ref=journal.accept(entry.observation)
                    persisted=True
                    if self.measurements is not None:self.measurements.admission(entry.observation,'durable_accepted')
                    self.scheduler.accepted(entry,ref)
                    with self._lock:self._counts['durable_accepted']+=1
                except BaseException:
                    # A persisted ACK remains accepted even if scheduling then
                    # fails; reservation/write failures have no durable ACK.
                    if not persisted and self.measurements is not None:self.measurements.admission(entry.observation,'rejected')
                    raise
                finally:self.quota.release(key)
                self._wake.set()
        except BaseException as exc:self._fail('recorder',exc)
        finally:
            if journal is not None:
                try:
                    complete=not self._counts['missing'] and not self._prior_incomplete and self._counts['offered']==self._counts['durable_accepted'] and not self.health.snapshot()['failed']
                    cert=dict(complete=complete,stopped=True,offered_count=self._counts['offered'],
                              durable_accepted_count=self._counts['durable_accepted'],missing_count=self._counts['missing'],
                              prior_incomplete=self._prior_incomplete,persisted=journal.counts(),
                              source_identity='original_capture_key_geometry_clock')
                    self.quota.reserve('certificate',16384)
                    try:atomic_write(self.root/'recording-certificate.json',json.dumps(cert,sort_keys=True).encode())
                    finally:self.quota.release('certificate')
                except BaseException as exc:self._fail('recorder-certificate',exc)
                journal.close()
            self._worker_done['recorder']=True;self._recorder_done.set();self._wake.set()

    def _cleanup(self,name,resource):
        if resource is None or not hasattr(resource,'close'):return True
        try:
            method=resource.close
            if 'timeout_s' in inspect.signature(method).parameters:
                report=method(timeout_s=(remaining(self._deadline) if self._deadline else 1.))
            else:report=method()
            if isinstance(report,dict) and report.get('clean_shutdown') is False:
                self._cleanup_pending[name]=report
                return False
            elif bool(getattr(resource,'is_alive',False)):
                self._cleanup_pending[name]='worker remains alive'
                return False
            else:self._cleanup_pending.pop(name,None)
            return True
        except BaseException as exc:
            # In particular AppearanceShutdownPending may mean Popen is still
            # creating a process even if its current is_alive property is false.
            self._cleanup_pending[name]=f'{type(exc).__name__}: {exc}'
            return False

    def _graph_run(self):
        journal=owner=detector=encoder=verifier=None
        try:
            if self.measurements is not None and self.measurements.stop_requested.is_set():
                raise RuntimeError('resource cap breached before graph/model startup')
            self.quota.reserve('startup',3*1024**2)
            journal=Journal(self.root,self._config)
            certificate_path=self.root/'recording-certificate.json'
            if certificate_path.exists():
                self._prior_incomplete=not json.loads(certificate_path.read_text()).get('complete',False)
            atomic_write(certificate_path,json.dumps(dict(complete=False,stopped=False,reason='runtime_active_or_unclean_exit')).encode())
            owner=self.owner_factory()
            if hasattr(owner,'ledger'):
                self._require_run_path(owner.ledger.root,'ObjectOwner ledger root')
                owner_config=json.loads(owner.ledger.get('config'))
                for identity in ('episode_id','primary_sensor_id','clock_domain','floor_id'):
                    if owner_config[identity]!=self._config[identity]:raise ValueError('owner '+identity+' mismatch')
            # Snapshot the durable admission watermark before replay or any new
            # commits; opening on first publication mislabels live negatives as a crash gap.
            self._admission_journal=None
            if self._admission_mode!='off':
                try:
                    from ..objects.admission import AdmissionJournal, AdmissionPolicy
                    self._admission_journal=AdmissionJournal(owner,AdmissionPolicy())
                except Exception as exc:
                    self._admission_startup_error=str(exc)
            detector=self.detector_factory()
            encoder=None if self.encoder_factory is None else self.encoder_factory()
            if self.verifier_factory is not None:
                # Explicit recovery can rebuild the complete derived ledger.
                # Reserve its persisted row payload/index/WAL growth before
                # even constructing it; fixed startup headroom is insufficient
                # for a long accepted history. Queries stay in the graph lane.
                replay_budget=1024*1024
                if hasattr(owner,'ledger'):
                    for table in ('batches','views','negatives'):
                        size,count=owner.ledger.connection.execute(
                            f'SELECT coalesce(sum(length(cast(data AS BLOB))),0),count(*) FROM {table}').fetchone()
                        replay_budget+=4*size+32768*count
                self.quota.reserve('verification-replay',replay_budget)
                try:
                    verifier=self.verifier_factory(owner)
                    if hasattr(verifier,'root'):self._require_run_path(verifier.root,'VerificationOwner root')
                    if hasattr(verifier,'replay'):verifier.replay()
                finally:self.quota.release('verification-replay')
            self.quota.release('startup')
            self.scheduler.watermark=max(journal.watermark(),getattr(owner,'dispatch_watermark',-1))
            self._last_index=self.scheduler.watermark
            self._admission_owner=owner
            self._objects=owner.snapshot()
            self._verification=None if verifier is None or not hasattr(verifier,'snapshot') else verifier.snapshot()
            # Drain persisted accepted refs BEFORE enabling new admission.
            while journal.next_pending() is not None:
                index=journal.next_pending();obs=journal.load(index)
                self._validate_recovery_source(obs)
                journal.watermark(index)
                self._process(obs,journal,owner,detector,encoder,verifier,recovery=True)
                self._counts['recovered']+=1
            # Recovery may have advanced beyond the watermark that existed at
            # process start. Restore both source ordering dimensions before
            # exposing readiness, including complete-empty frame timestamps.
            self.scheduler.watermark=max(journal.watermark(),getattr(owner,'dispatch_watermark',-1))
            self._last_index=self.scheduler.watermark
            if hasattr(owner,'ledger'):
                checkpoint=owner.ledger.get('checkpoint')
                if checkpoint is not None:self._last_stamp=json.loads(checkpoint)['capture_watermark']
            self._journal_counts=journal.counts();self._ready.set()
            while True:
                if self.health.snapshot()['failed']:break
                entry=self.scheduler.take_next(journal.watermark)
                if entry is not None:
                    self._process(entry.observation,journal,owner,detector,encoder,verifier)
                    self.scheduler.complete(entry);self._journal_counts=journal.counts()
                self._consume_place()
                self._publish(verifier)
                if (self._closing and self._recorder_done.is_set() and not self.scheduler.snapshot()['pending']
                    and (self.mapper is None or self._worker_done.get('navigation',False))
                    and (self.region_factory is None or self._worker_done.get('region',False))
                    and self._place_input is None):
                    # Producers can finish between the preceding publication
                    # and this predicate. Flush once after observing quiescence.
                    self._publish(verifier)
                    break
                self._wake.wait(.01);self._wake.clear()
        except BaseException as exc:self._fail('graph',exc)
        finally:
            self._ready.set()
            if journal is not None:
                self._journal_counts=journal.counts();journal.close()
            for name,resource in (('verifier',verifier),('encoder',encoder),('detector',detector),('owner',owner)):
                self._cleanup(name,resource)
            self._worker_done['graph']=True

    def _validate_recovery_source(self,obs):
        if obs.key.episode_id!=self.episode_id or obs.key.sensor_id!=self.primary_sensor_id or obs.clock_domain!=self.clock_domain:
            raise ValueError('accepted source does not match runtime identity')
        # Host boot mismatch was rejected by journal config; original capture
        # timestamps remain original and old evidence remains historical.
        age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)

    def _process(self,obs,journal,owner,detector,encoder,verifier,*,recovery=False):
        batch=journal.result(obs.key.frame_index)
        measurement_origin='recovery' if recovery else 'reused' if batch is not None else 'historical' if self.clock_domain.startswith('replay:') else 'live'
        start_age=age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)
        start_fresh=not recovery and start_age<=250_000_000 and not self.clock_domain.lower().startswith('replay:')
        if not start_fresh:self.health.increment('inference_start_stale')
        if batch is None:
            batch=detector.infer(obs)
            measured_return_ns=self.now_ns()
            self._counts['detector_calls']+=1
            if self.measurements is not None:self.measurements.result(obs,measured_return_ns,'detector_return',origin=measurement_origin)
            validate_detection_batch(obs,batch)
            # Bound detector journal + WAL before making the durable result ACK.
            key=('result',obs.key.frame_index);self.quota.reserve(key,3*len(dumps(batch).encode())+131072)
            try:journal.result(obs.key.frame_index,batch)
            finally:self.quota.release(key)
        else:validate_detection_batch(obs,batch)
        items=journal.prepared(obs.key.frame_index)
        if items is None:
            items=self.projector.project(obs,batch)
            if encoder is not None:
                features=encoder.encode(obs,batch)
                if features is not None:
                    validate_appearance_batch(obs,batch,features)
                    selected=replace(features,features={item.detection_id:features.features[item.detection_id]
                        for item in items if item.detection_id in features.features})
                    items=attach_features(items,selected)
            key=('prepared',obs.key.frame_index)
            self.quota.reserve(key,4*sum(len(dumps(item).encode()) for item in items)+131072)
            try:journal.prepared(obs.key.frame_index,items)
            finally:self.quota.release(key)
        # Storage upper bound includes full trial checkpoint, source/batch,
        # observation, masks/crops, WAL amplification and temporary asset files.
        # Reservations serialize with recorder reservations over the entire run.
        asset_bytes=len(dumps(obs).encode())+len(dumps(batch).encode())+sum(len(dumps(item).encode()) for item in items)
        crop_mask_bytes=sum(d.mask.nbytes+obs.rgb.nbytes for d in batch.detections)
        checkpoint_bytes=len(dumps(owner.snapshot()).encode())+sum(len(dumps(item).encode()) for item in items)*4
        key=('commit',obs.key.frame_index)
        self.quota.reserve(key,8*(asset_bytes+crop_mask_bytes+checkpoint_bytes)+1024*1024)
        try:
            commit=owner.commit(obs,batch,items)
            measured_commit_ns=self.now_ns()
            if self.measurements is not None:
                self.measurements.result(obs,measured_commit_ns,'object_commit',origin=measurement_origin,revision=commit.snapshot.revision)
                self.measurements.committed(obs,commit,origin=measurement_origin,projected_count=len(items))
            if verifier is not None:
                if recovery:
                    consume=getattr(verifier,'consume_historical',None)
                    if not callable(consume):
                        raise RuntimeError('verifier cannot acknowledge historical recovery safely')
                    consume(commit)
                else:verifier.consume(commit)
            journal.done(obs.key.frame_index)
        finally:self.quota.release(key)
        verification=None if verifier is None or not hasattr(verifier,'snapshot') else verifier.snapshot()
        active_input=None
        memory=getattr(self,'_active_memory',None)
        if memory is not None:
            from .active_perception import EvidenceInput
            from ..verification.view_memory import read_committed_views
            try:
                memory.remap(commit.snapshot.aliases)
                for view in read_committed_views(owner,commit):memory.offer(view)
                fresh_source=(obs.key if measurement_origin=='live' and start_fresh
                    and age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)<=750_000_000 else None)
                active_input=EvidenceInput(memory.snapshot(commit.snapshot.revision),commit.snapshot,verification,fresh_source)
            except (ValueError,OSError,TypeError,KeyError):
                self.health.increment('active_view_memory_unavailable')
        with self._lock:
            if memory is not None:
                self._active_input=active_input
                if self._active_capture_expected==obs.key:
                    self._active_capture_result=(obs.key,active_input is not None and active_input.committed_source==obs.key)
                    self._active_capture_expected=None
            self._objects=commit.snapshot;self._verification=verification;self._processed=obs.key;self._last_processed_capture=obs.capture_monotonic_ns;self._counts['committed']+=1
            now=self.now_ns()
            if start_fresh and age_ns(obs.capture_monotonic_ns,obs.clock_domain,now,self.clock_domain)<=750_000_000:
                self._fast=(obs,batch)
            else:self._fast=None;self.health.increment('semantic_stale')

    @contextmanager
    def _navigation_archive_scope(self):
        core = self.mapper._core
        budget = 2*(core.MAX_PLANAR_MEMORY_BYTES+core.MAX_HEIGHT_MEMORY_BYTES)+1024*1024
        self.quota.reserve('navigation-archive', budget)
        try:
            yield
        finally:
            self.quota.release('navigation-archive')

    def _navigation_run(self):
        try:
            while True:
                with self._lock:
                    obs=self._nav_input;proof=self._nav_pose_input
                    self._nav_input=None;self._nav_pose_input=None
                if obs is None:
                    if self._closing or self.health.snapshot()['failed']:break
                    self._nav_wake.wait(.02);self._nav_wake.clear();continue
                core=getattr(self.mapper,'_core',None)
                budget=(2*(core.MAX_PLANAR_MEMORY_BYTES+core.MAX_HEIGHT_MEMORY_BYTES)+1024*1024) if core is not None and not getattr(self,'_archive_write_reserved',False) else 0
                if budget:self.quota.reserve('navigation-archive',budget)
                try:
                    nav=self.mapper.update(obs)
                except CompletedRequestDeadline:
                    # No map state or frame watermark was committed. Keep the
                    # previous source unchanged: control remains source-pending
                    # until a genuinely new observation maps successfully.
                    self.health.increment('mapping_deadline_missed')
                    self._wake.set()
                    continue
                finally:
                    if budget:self.quota.release('navigation-archive')
                overview = None
                try:
                    provider = getattr(self.mapper, 'overview_tiles', None)
                    if provider is not None:overview = provider()
                except Exception:
                    pass  # Optional display data must never fail control.
                room_provider=getattr(self.mapper,'room_input_tiles',None)
                room_tiles=None
                if callable(room_provider):
                    try:room_tiles=room_provider()
                    except Exception:pass  # Region lane reports unavailable; control proceeds.
                with self._lock:
                    self._latest_nav=nav
                    self._latest_overview_tiles=overview
                    if proof is not None:
                        if self._place_input is not None:self._place_counts['pair_replaced']+=1
                        self._place_input=(nav,proof)
                    else:self._place_counts['unmatched']+=1
                    if self.region_factory is not None:
                        self._region_input=(nav,room_tiles) if callable(room_provider) else nav
                        self._region_wake.set()
                self._wake.set()
        except BaseException as exc:self._fail('navigation',exc)
        finally:
            self._cleanup('mapper',self.mapper);self._worker_done['navigation']=True;self._wake.set()

    @staticmethod
    def _room_payload_budget(obs):
        raw=0
        for name in ('rgb','depth_m','valid_depth','K','T_world_camera'):
            value=getattr(obs,name,None)
            if hasattr(value,'nbytes'):raw+=int(value.nbytes)
        return 2*((raw*4)//3+8192)+raw

    def _record_room_event(self,event):
        if len(self._room_journal)==self._room_journal.maxlen:
            self._room_journal_dropped+=1
        self._room_journal.append(event)

    def _offer_room_input_locked(self,obs):
        self._room_counts['offered']+=1
        budget=self._room_payload_budget(obs)
        if self._room_failure is not None:
            self._room_counts['rejected']+=1
            self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=False,reason='room_worker_failed'))
            return
        if len(self._room_queue)>=2 or self._room_queue_bytes+self._room_inflight_bytes+budget>32*1024**2:
            self._room_counts['rejected']+=1;self._room_counts['queue_dropped']+=1
            self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=False,reason='room_queue_full',estimated_bytes=budget))
            return
        self._room_queue.append((obs,budget));self._room_queue_bytes+=budget
        self._room_counts['queued']+=1
        self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=True,reason='room_queue_admitted',estimated_bytes=budget))
        self._room_wake.set()

    def _mark_room_publication_stale(self,error):
        previous=self._room_publication
        if previous is None:return
        regions=previous.regions
        if regions is not None and not regions.stale:
            regions=replace(regions,stale=True)
        self._room_publication=replace(previous,regions=regions,regions_stale=True,
            replay_required=True,failure_reason=str(error))

    def _room_pipeline_run(self):
        session=None;quota_reserved=False
        try:
            session=self.room_pipeline_factory()
            self.quota.reserve('room-pipeline-recording',ROOM_PIPELINE_DISK_RESERVATION_BYTES,
                               covered_path=session.run_dir)
            quota_reserved=True
            with self._lock:self._room_session=session
            while True:
                with self._lock:
                    if self._room_queue:
                        obs,budget=self._room_queue.popleft();self._room_queue_bytes-=budget
                        self._room_inflight_bytes=budget
                    else:
                        obs=None;budget=0
                    closing=self._closing
                if obs is None:
                    if closing:break
                    self._room_wake.wait(.05);self._room_wake.clear();continue
                admission=session.submit(obs)
                with self._lock:
                    self._record_room_event(dict(frame_index=obs.key.frame_index,
                        accepted=bool(admission.accepted),reason=str(admission.reason),
                        admission_id=admission.admission_id))
                    if admission.accepted:self._room_counts['session_admitted']+=1
                    else:self._room_counts['rejected']+=1
                if admission.accepted:
                    while not session.wait_idle(.05):
                        if session.health.get('failed'):
                            break
                    publication=session.snapshot()
                    health=session.health
                    with self._lock:
                        if publication is not None:self._room_publication=publication
                        if health.get('failed'):
                            self._room_failure=health.get('failure_reason') or 'room worker failed'
                            self._mark_room_publication_stale(self._room_failure)
                        elif publication is not None:
                            self._room_counts['processed']+=1
                with self._lock:
                    self._room_inflight_bytes=0
                    if self._room_failure is not None:
                        while self._room_queue:
                            queued,_=self._room_queue.popleft()
                            self._record_room_event(dict(frame_index=queued.key.frame_index,
                                accepted=False,reason='room_worker_failed'))
                            self._room_counts['rejected']+=1
                        self._room_queue_bytes=0
                self._wake.set()
        except BaseException as exc:
            with self._lock:
                self._room_failure=f'{type(exc).__name__}: {exc}'
                self._mark_room_publication_stale(self._room_failure)
                self._room_counts['rejected']+=len(self._room_queue)
                self._room_queue.clear();self._room_queue_bytes=0;self._room_inflight_bytes=0
                self._record_room_event(dict(accepted=False,reason='room_worker_failed',error=self._room_failure))
        finally:
            clean=True if session is None else self._cleanup('room_pipeline',session)
            if quota_reserved and clean:self.quota.release('room-pipeline-recording')
            with self._lock:self._room_session=None
            self._worker_done['room_pipeline']=True;self._wake.set()

    def _region_run(self):
        backend=None
        try:
            backend=self.region_factory()
            while True:
                with self._lock:pending=self._region_input;self._region_input=None
                if pending is None:
                    if (self._closing and (self.mapper is None or self._worker_done.get('navigation',False))) or self.health.snapshot()['failed']:break
                    self._region_wake.wait(.02);self._region_wake.clear();continue
                scope='local_snapshot';unavailable=None
                if isinstance(pending,tuple):
                    local,tiles=pending;scope='accumulated_measured_occupancy_v1'
                    try:
                        from ..mapping.room_map import RoomMapEvidence,build_room_map
                        nav=build_room_map(RoomMapEvidence(tiles,self.mapper.robot),local)
                    except (ValueError,MemoryError,OverflowError) as exc:
                        nav=local;unavailable='room_input_unavailable:'+str(exc)
                else:nav=pending
                regions=backend.mark_unavailable(nav,unavailable) if unavailable else backend.update(nav)
                diagnostic=getattr(backend,'diagnostics',None)
                stats=diagnostic() if callable(diagnostic) else {}
                stats=dict(stats,input_scope=scope,retained_input_complete=unavailable is None)
                if self.measurements is not None:self.measurements.region(nav,regions)
                with self._lock:
                    if regions.source_map_revision==nav.revision:
                        self._accepted_nav=nav
                        self._accepted_region_scope=scope if unavailable is None else 'room_input_unavailable'
                    elif self._accepted_nav is None or regions.source_map_revision!=self._accepted_nav.revision:
                        raise ValueError('region response has no matching retained source map')
                    self._regions=regions
                    self._region_diagnostics=stats
                self._wake.set()
        except BaseException as exc:self._fail('region',exc)
        finally:
            self._cleanup('region',backend);self._worker_done['region']=True;self._wake.set()

    def _publish(self,verifier=None):
        # Snapshot only pointers under the control lock; geometry/validation is
        # graph work and cannot hold submit/control hostage.
        with self._lock:
            objects=self._objects;latest=self._latest_nav;regions=self._regions;nav=self._accepted_nav
            room_publication=self._room_publication
            scope=getattr(self,'_accepted_region_scope','local_snapshot')
            captured=self._captured;processed=self._processed;verification=self._verification
            object_capture=getattr(self,'_last_processed_capture',None);depth=self._latest_depth
            active_status=getattr(self,'_active_status',None)
        if objects is None or latest is None:return
        if regions is None and self.region_factory is not None:return
        if regions is None:
            nav=latest;regions=RegionSnapshot(latest.episode_id,0,latest.revision,self.floor_id,{},True)
        if nav is None:return
        revisions=(objects.revision,nav.revision,regions.revision,latest.revision,regions.stale)
        now=self.now_ns()
        # Coalesce map/region churn at the advertised graph cadence. Object
        # commits (including aliases) publish promptly; control uses its own
        # latest measured map and never waits for this projection. Closing
        # bypasses cadence so the graph owner flushes the drained final bundle.
        previous=self._publication_revisions
        if (previous is not None and previous[0]==objects.revision
            and not self._closing
            and now-self._last_publication_ns<100_000_000):return
        if verifier is not None:
            if hasattr(verifier,'expire'):
                self.quota.reserve('verification-expiry',1024*1024+32768*len(objects.objects))
                try:verifier.expire()
                finally:self.quota.release('verification-expiry')
            if hasattr(verifier,'snapshot'):verification=verifier.snapshot()
        mode=getattr(self,'_admission_mode','off')
        admission=None
        if mode!='off':
            try:
                journal=getattr(self,'_admission_journal',None)
                if journal is None or verifier is None:
                    raise ValueError(getattr(self,'_admission_startup_error','committed evidence provider unavailable'))
                admission=journal.evaluate(verifier)
                # Do not treat unavailable data as a negative vote or an empty graph.
                if (admission.episode_id!=objects.episode_id or admission.object_revision!=objects.revision or
                        admission.evidence_revision!=objects.revision or
                        set(admission.decisions)!=set(objects.objects) or
                        any(d.availability!='available' for d in admission.decisions.values())):
                    raise ValueError('admission evidence unavailable or revision mismatch')
                with self._lock:
                    self._admission_snapshot=admission
                    self._admission_status=dict(mode=mode,status='available',reason=None,
                        object_revision=admission.object_revision,evidence_revision=admission.evidence_revision,
                        policy_version=admission.policy_version,policy_hash=admission.policy_hash,
                        counts={state:sum(d.state==state for d in admission.decisions.values())
                                for state in ('candidate','admitted','review_required')},
                        decisions={key:dict(state=d.state,availability=d.availability,reason_codes=list(d.reason_codes),
                                            evidence_refs=list(d.evidence_refs),quality=dict(d.quality))
                                   for key,d in admission.decisions.items()})
            except Exception as exc:
                with self._lock:self._admission_status=dict(mode=mode,status='unavailable',reason=str(exc)[:256],
                    stale=getattr(self,'_hierarchy',None) is not None)
                self._notify_admission_display()
                if mode=='enforce':return
        if mode!='off':self._notify_admission_display()
        try:
            public_objects=publication_objects(objects,admission,mode)
        except ValueError as exc:
            with self._lock:self._admission_status=dict(mode=mode,status='unavailable',reason=str(exc),stale=getattr(self,'_hierarchy',None) is not None)
            return
        if not hasattr(self,'_composer'):self._composer=HierarchyComposer(robot=getattr(self.mapper,'robot',None))
        result=self._composer.compose(objects,nav,regions,latest_nav_revision=latest.revision,
                                      now_ns=self.now_ns(),clock_domain=self.clock_domain,
                                      room_pipeline=room_publication)
        if scope=='accumulated_measured_occupancy_v1':
            nodes=dict(result.nodes)
            for key,node in nodes.items():
                if node.kind in {'floor','region','source_region'}:
                    nodes[key]=replace(node,attributes=dict(node.attributes,geometry_input_scope=scope,
                        source_map_shape=tuple(nav.states.shape),source_map_origin=nav.origin_xy,
                        source_map_resolution_m=nav.resolution_m,cell_evidence='historical_measured_classification'))
            edges=tuple(replace(edge,provenance=dict(edge.provenance,geometry_input_scope=scope,
                cell_evidence='historical_measured_classification'))
                if edge.kind in {'place_connected_to','in_region','in_source_region','region_contains_place','region_adjacent_to','source_region_adjacent_to'}
                else edge for edge in result.edges)
            result=replace(result,nodes=nodes,edges=edges)
        result=replace(result,statuses=dict(result.statuses,places=self._place_status))
        with self._lock:
            if self.health.snapshot()['failed']:return
            # New navigation may have arrived during composition. Publish this
            # internally coherent result with its explicit latest-nav tag;
            # next worker tick will compose the new generation.
            self._hierarchy=result;self._hierarchy_nav=nav
            self._publication_revisions=revisions;self._last_publication_ns=now
            self._verification=verification
            missing=self._counts['missing']
        if self.measurements is not None:self.measurements.publication(result)
        if self.publisher is not None:
            from ..visualization.publisher import DisplaySources
            display_verification=self._display_verification(verification)
            if mode=='enforce' and display_verification is not None:
                display_verification=replace(display_verification,objects={k:v for k,v in display_verification.objects.items() if k in public_objects.objects})
            # Publication ages refer to the exact pinned bundle, even when a
            # newer navigation result arrived while composition was running.
            now=self.now_ns()
            ages=dict(depth=None if depth is None else age_ns(depth.capture_monotonic_ns,depth.clock_domain,now,self.clock_domain),
                map=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now,self.clock_domain),
                objects=None if object_capture is None else age_ns(object_capture,self.clock_domain,now,self.clock_domain),
                verification=None,
                room_map=None if room_publication is None else age_ns(
                    room_publication.latest_map.capture_monotonic_ns,
                    room_publication.latest_map.clock_domain,now,self.clock_domain))
            if verification is not None:
                evidence_ages=[age_ns(view.capture_monotonic_ns,view.clock_domain,now,self.clock_domain)
                    for state in verification.objects.values() for view in state.best_views]
                if evidence_ages:ages['verification']=max(evidence_ages)
            self.publisher.publish(result,dict(captured_frame_id=captured,processed_frame_id=processed,
                published_frame_id=objects.source,source_age_ns=ages,dropped_count=missing,
                replaced_count=self.scheduler.counts['replaced'],actual_profile=self.health.profile,
                sources=DisplaySources(nav=nav,objects=public_objects,verification=display_verification,admission=admission,
                    active_perception=_active_display(active_status,objects))))

    @staticmethod
    def _display_verification(verification):
        if verification is None:return None
        from ..visualization.publisher import (DisplayVerificationSnapshot,DisplayVerificationRecord,DisplayVerificationEvidence)
        objects={}
        for key,state in verification.objects.items():
            if state.status=='verified' and not state.best_views:
                raise ValueError('verified display state requires committed evidence gallery')
            status=state.status if state.status in {'verified','unknown'} else 'unverified'
            evidence=tuple(DisplayVerificationEvidence(v.source,v.object_revision,v.capture_monotonic_ns,
                v.clock_domain,v.event_id) for v in state.best_views)
            objects[key]=DisplayVerificationRecord(verification.episode_id,key,state.object_revision,status,evidence)
        return DisplayVerificationSnapshot(verification.episode_id,verification.object_revision,objects)

    def _notify_admission_display(self):
        notify=getattr(self.publisher,'set_admission_status',None)
        if callable(notify):
            status=self.object_admission_status()
            try:notify({key:status.get(key) for key in ('mode','status','reason','stale')})
            except Exception:pass  # Display diagnostics never control the graph lane.

    def object_admission_status(self):
        with self._lock:return deepcopy(getattr(self,'_admission_status',dict(mode='off',status='off')))

    def snapshot(self):
        with self._lock:return self._hierarchy

    def snapshot_bundle(self):
        """Return the canonical hierarchy and its exact immutable map together.

        Best-effort display consumers may retain an older publication. They
        never own this canonical pair or determine final export coherence.
        """
        with self._lock:return self._hierarchy,self._hierarchy_nav

    def room_pipeline_snapshot(self):
        """Return the independent Rebuild M3/M5 publication, if configured."""
        with self._lock:return self._room_publication

    def fast_semantics(self):
        with self._lock:
            if self._fast is None:return None
            obs,batch=self._fast
            if age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)>750_000_000:return None
            return obs,batch

    def navigation_status(self):
        """Bounded diagnostic intent/reason, independent of actuator result labels."""
        with self._lock:
            plan=getattr(self,'_navigation_display',None)
            counts=dict(getattr(self,'_navigation_reason_counts',{}))
            last_failure=getattr(self,'_last_goal_failure',None)
            policy=deepcopy(getattr(self.navigator,'last_policy_status',None))
        if plan is None:return dict(reason='navigation_unavailable',reason_counts=counts,policy=policy)
        nav,frontiers,decision,reason,computed,rejected,held_goal=plan
        goal=held_goal or ((decision.goal_id,decision.path[-1]) if not rejected and decision.goal_id and decision.path else None)
        return dict(map_revision=nav.revision,computed_monotonic_ns=computed,
            reason=reason,decision_reason=decision.reason,reason_counts=counts,last_goal_failure=last_failure,
            goal_id=None if goal is None else goal[0],goal_xy=None if goal is None else goal[1],
            route_available=bool(decision.path) and not rejected,
            frontier_count=0 if frontiers is None else len(frontiers.frontiers),policy=policy)

    def latest_control_status(self):
        """Last completed control result, with its own capture provenance."""
        with self._lock:
            value=getattr(self,'_latest_control_status',None)
            return None if value is None else dict(value)

    def navigation_display(self):
        """UI-lane projection of the last actual plan; never a control input."""
        with self._lock:
            plan=getattr(self,'_navigation_display',None)
            paused=self._paused;closing=self._closing
        if plan is None:return None
        from ..visualization.navigation_overlay import from_plan
        nav,frontiers,decision,reason,computed,rejected,held_goal=plan
        if closing or self.health.snapshot()['failed']:reason='runtime_stopped'
        elif paused:reason='runtime_paused'
        clear=rejected or reason in {'runtime_paused','runtime_stopped','bootstrap_blocked','footprint_not_observed','path_segment_blocked'}
        return from_plan(nav,frontiers,decision,reason,computed,clear_goal=clear,
            held_goal=None if reason in {'runtime_paused','runtime_stopped'} else held_goal)

    def live_navigation_display(self):
        """Read the latest immutable map pointer; UI work stays outside control."""
        with self._lock:return self._latest_nav

    def global_map_display(self):
        """Immutable overview tiles only; dense assembly runs on the UI lane."""
        with self._lock:return self._latest_overview_tiles

    def _source_ages_locked(self):
        now=self.now_ns()
        def age(obs):
            if obs is None:return None
            try:return age_ns(obs.capture_monotonic_ns,obs.clock_domain,now,self.clock_domain)
            except ValueError:return None
        return dict(depth=age(self._latest_depth),map=age(self._accepted_nav or self._latest_nav),
                    objects=(None if self._objects is None or self._processed is None else
                             age_ns(self._last_processed_capture,self.clock_domain,now,self.clock_domain))
                    if hasattr(self,'_last_processed_capture') else None)

    def semantic_sampling_snapshot(self):
        """Fixed-size selection counters; deferred inputs have no retained refs."""
        with self._lock:
            return dict(schema_version=1,mode=self._keyframe_sampling,
                        policy_version='idle-semantic-v1' if self._keyframe_sampling=='capacity_deferred' else 'all-primary-novelty-v1',
                        **self._semantic_sampling,counter_saturated=self._semantic_sampling_saturated)

    def telemetry(self):
        with self._lock:
            report=dict(**self._counts,object_admission=self.object_admission_status(),semantic_sampling=self.semantic_sampling_snapshot(),configuration=dict(self._config,
                            depth_max_age_ns=300_000_000,semantic_max_age_ns=750_000_000,
                            inference_start_max_age_ns=250_000_000,publication_interval_ns=100_000_000,
                            appearance_enabled=self.encoder_factory is not None,verification_enabled=self.verifier_factory is not None,
                            regions_enabled=self.region_factory is not None,
                            keyframe_policy=type(self.policy).__name__,
                            min_translation_m=getattr(self.policy,'distance',None),min_yaw_rad=getattr(self.policy,'angle',None)),
                        source_age_ns=self._source_ages_locked(),regions=dict(getattr(self,'_region_diagnostics',{})),
                        room_pipeline=dict(enabled=self.room_pipeline_factory is not None,
                            failed=self._room_failure,counts=dict(self._room_counts),
                            queued_frames=len(self._room_queue),queued_estimated_bytes=self._room_queue_bytes,
                            inflight_estimated_bytes=self._room_inflight_bytes,
                            queue_byte_cap=32*1024**2,
                            publication=None if self._room_publication is None else dict(
                                map_revision=self._room_publication.latest_map.revision,
                                accepted_map_revision=self._room_publication.accepted_map_revision,
                                regions_stale=self._room_publication.regions_stale,
                                replay_required=self._room_publication.replay_required),
                            journal=list(self._room_journal),journal_dropped=self._room_journal_dropped),
                        journal=dict(self._journal_counts),ready=self._ready.is_set() and not self.health.snapshot()['failed'],paused=self._paused,
                        stop_requested=self._stop_requested,cleanup_pending=dict(self._cleanup_pending),
                        places=dict(self._place_counts,status=self._place_status,pose_pending=self._pose_offer is not None,pair_pending=self._place_input is not None))
        # In particular quota.lock can cover a filesystem scan. Never acquire
        # it while holding the lock needed by source admission and control.
        if getattr(self,'_active',None) is not None:report['active_perception']=self._active_status
        return dict(report,scheduler=self.scheduler.snapshot(),health=self.health.snapshot(),quota=self.quota.snapshot(),navigation=self.navigation_status(),latest_control=self.latest_control_status())

    def control_step(self,actuator,*,robot_xy=None,yaw_rad=None):
        with self._control_lock:
            if self.measurements is not None and self.measurements.stop_requested.is_set():
                self._paused=True;self._stop_requested=True
            self._step_command=None;self._step_decision=None;self._step_source=None
            self._step_navigation_observed=False
            self._step_reobserve=False
            result=self._control_step(actuator,robot_xy=robot_xy,yaw_rad=yaw_rad)
            if not isinstance(result,dict):
                result=dict(executed=False,reason='control_rejected',error='invalid actuator result')
            active=getattr(self,'_active',None)
            if active is not None:
                if result.get('reason') in {'runtime_paused','runtime_stopped','navigation_unavailable',
                                            'navigation_source_pending','control_rejected'}:
                    active.interrupt(self.now_ns(),result['reason'])
                with self._lock:self._active_status=active.status()
            source=self._step_source
            reason=result.get('reason')
            if not isinstance(reason,str) or not reason:reason='executed' if result.get('executed') else 'unknown'
            observation=dict(reason=reason[:256],
                executed=result.get('executed') is True,observed_monotonic_ns=self.now_ns(),
                episode_id=None if source is None else source.key.episode_id,
                sensor_id=None if source is None else source.key.sensor_id,
                frame_index=None if source is None else source.key.frame_index,
                capture_monotonic_ns=None if source is None else source.capture_monotonic_ns,
                clock_domain=None if source is None else source.clock_domain)
            with self._lock:self._latest_control_status=observation
            if not self._step_navigation_observed:
                reset=getattr(self.navigator,'reset_goal_failure_watch',None)
                if callable(reset):reset()
            if self.measurements is not None:
                proof=None
                if self._step_command is not None:
                    try:proof=getattr(actuator,'last_actuation_proof',None)
                    except Exception:pass
                self.measurements.control(self._step_source,self.now_ns(),result,command=self._step_command,
                    decision=self._step_decision,proof=proof,profile=self.health.profile.split(':')[0])
            return result

    def _control_step(self,actuator,*,robot_xy=None,yaw_rad=None):
        """Fresh navigation -> guard -> actual source-bound execute seam.

        Guard/actuator exceptions never fall back to a bare action or republish
        an old capture. The caller can keep capturing while detector/disk hangs.
        """
        with self._control_lock:
            with self._lock:latest=self._latest_depth;nav=self._latest_nav
            self._step_source=latest
            # Pause ACK is serialized after the last finite actuator pulse.
            # Subsequent captures may supersede its pose; asking the actuator
            # for that retained source would conceal pause as a source failure.
            # No synthetic stopped command/proof or automatic resume is needed.
            if self._paused or self._closing:
                return dict(executed=False,reason='runtime_paused' if self._paused and not self._closing else 'runtime_stopped')
            if latest is None or nav is None or self.guard is None or self.navigator is None:
                with self._lock:self._navigation_display=None
                return dict(executed=False,reason='navigation_unavailable')
            if nav.source!=latest.key or nav.capture_monotonic_ns!=latest.capture_monotonic_ns or nav.clock_domain!=latest.clock_domain:
                return dict(executed=False,reason='navigation_source_pending')
            try:
                pose=actuator.robot_pose(latest)
                if pose['source']!=latest.key or pose['capture_monotonic_ns']!=latest.capture_monotonic_ns or pose['clock_domain']!=self.clock_domain or pose['pose_version']!=latest.pose_version:
                    raise ValueError('actuation pose source mismatch')
                xy=tuple(pose['robot_xy']);yaw=pose['yaw_rad']
                if robot_xy is not None and tuple(robot_xy)!=xy or yaw_rad is not None and yaw_rad!=yaw:
                    raise ValueError('caller pose does not match captured robot pose')
                now=self.now_ns();self.guard.bind_nav(nav,robot_xy=xy,yaw_rad=yaw)
                decision=None
                if self._paused or self._closing or self.health.snapshot()['failed']:
                    command=MotionCommand(latest.key,nav.revision,now,now,self.clock_domain,0.,0.,'runtime_stopped',latest.capture_monotonic_ns)
                else:
                    active=getattr(self,'_active',None)
                    if active is not None:
                        with self._lock:
                            evidence=self._active_input;admission=self._admission_snapshot
                            capture_result=getattr(self,"_active_capture_result",None);self._active_capture_result=None
                        decision=active.step(self.navigator,nav,xy,yaw,self.now_ns(),evidence,admission,capture_result)
                        self._step_reobserve=decision is not None
                    if decision is None:decision=self.navigator.step(nav,xy,yaw,self.now_ns())
                    if self._step_reobserve and active.scheduler.remaining_time_ns(self.now_ns())<100_000_000:
                        active.interrupt(self.now_ns(),'time_budget')
                        decision=replace(decision,desired_linear_mps=0.,desired_yaw_radps=0.,reason='reobserve_budget_stop')
                    self._step_decision=decision
                    command=self.guard.filter(decision,latest,self.now_ns())
                if age_ns(latest.capture_monotonic_ns,latest.clock_domain,self.now_ns(),self.clock_domain)>300_000_000:
                    self.health.increment('depth_stale')
                    command=replace(command,linear_mps=0.,yaw_radps=0.,reason='depth_stale')
                # A geometric veto must reach the policy that selected this
                # exact target. Otherwise a held goal can be requested forever
                # while the guard correctly keeps both motion components zero.
                report_failure=getattr(self.navigator,'report_goal_failure',None)
                if (not self._step_reobserve and decision is not None and decision.goal_id and decision.path
                        and (decision.desired_linear_mps or decision.desired_yaw_radps)
                        and decision.map_revision==nav.revision==command.map_revision
                        and command.clock_domain==self.clock_domain==latest.clock_domain==nav.clock_domain
                        and command.source==latest.key
                        and command.source_capture_monotonic_ns==latest.capture_monotonic_ns
                        and command.linear_mps==command.yaw_radps==0.
                        and command.reason in {'bootstrap_blocked','footprint_not_observed','path_segment_blocked'}
                        and callable(report_failure)):
                    report_failure(decision.goal_id,nav.revision,goal_world_xy=decision.path[-1])
                if self._step_reobserve and (command.linear_mps or command.yaw_radps):
                    checked_ns=self.now_ns()
                    horizon=max(0,command.deadline_monotonic_ns-checked_ns)
                    if self._active.scheduler.remaining_time_ns(checked_ns)<horizon:
                        self._active.interrupt(checked_ns,'time_budget')
                        command=replace(command,linear_mps=0.,yaw_radps=0.,reason='reobserve_budget_stop')
                self._step_command=command
                result=actuator.execute(command)
                self._last_command=command
                if decision is not None:
                    # One immutable pointer only; geometry copies/DTO creation
                    # run on the coalesced UI lane, never inside control.
                    rejected=(not isinstance(result,dict) or result.get('executed') is not True
                              or command.linear_mps==command.yaw_radps==0.)
                    display_reason=(result.get('reason') or command.reason) if rejected and isinstance(result,dict) else command.reason
                    if display_reason=='expired_or_zero':display_reason=command.reason
                    stationary=_stationary_partial_yaw_refusal(actuator,result,command,latest,xy,yaw)
                    watch_reason='yaw_preflight_no_progress' if stationary else display_reason
                    observe_result=getattr(self.navigator,'observe_navigation_result',None)
                    if self._step_reobserve:
                        self._active.outcome(decision,watch_reason,rejected or stationary,self.now_ns())
                        failure=None
                    else:
                        failure=(observe_result(nav,xy,self.now_ns(),watch_reason,rejected or stationary)
                                 if callable(observe_result) else None)
                        self._step_navigation_observed=callable(observe_result)
                    if failure is not None:
                        display_reason='goal_failed_no_progress:'+watch_reason
                        with self._lock:self._last_goal_failure=failure
                    with self._lock:
                        counts=getattr(self,'_navigation_reason_counts',None)
                        if counts is None:self._navigation_reason_counts=counts={}
                        key=display_reason if display_reason in counts or len(counts)<64 else 'other'
                        counts[key]=min(counts.get(key,0)+1,2**63-1)
                        self._navigation_display=(nav,getattr(self.navigator,'last_frontiers',None),decision,display_reason,self.now_ns(),rejected,getattr(self.navigator,'last_committed_goal',None))
                return result
            except Exception as exc:
                with self._lock:self._navigation_display=None
                return dict(executed=False,reason='control_rejected',error=f'{type(exc).__name__}: {exc}')

    def handle_ui_command(self,command):
        from ..visualization.publisher import UiCommand,UiCommandAck
        if not isinstance(command,UiCommand):raise ValueError('UiCommand required')
        now=self.now_ns();reason=None
        try:
            if age_ns(command.requested_monotonic_ns,command.clock_domain,now,self.clock_domain)>2_000_000_000:
                reason='command_stale'
        except ValueError:reason='command_clock_mismatch_or_future'
        # Serializing against the synchronous actuator means any prior pulse
        # has finished before ACK. Later paused calls issue no further pulse.
        with self._control_lock:
            if reason is None and self.now_ns()-command.requested_monotonic_ns>2_000_000_000:reason='command_stale'
            with self._lock:
                if reason is None and (not self._ready.is_set() or self.health.snapshot()['failed'] or self._closing):reason='runtime_unavailable'
                if reason is None:
                    self._paused=True
                    if command.action=='stop':self._stop_requested=True
        return UiCommandAck(command.request_uuid,'accepted' if reason is None else 'rejected',reason,self.now_ns(),self.clock_domain)

    def close(self,timeout_s:float)->dict:
        timeout_s=valid_timeout(timeout_s);deadline=time.monotonic()+timeout_s
        control_acquired=self._control_lock.acquire(timeout=remaining(deadline))
        with self._lock:self._closing=True;self._paused=True;self._deadline=deadline;self.scheduler.closed=True
        if control_acquired:
            try:
                active=getattr(self,'_active',None)
                if active is not None:
                    active.interrupt(self.now_ns(),'runtime_stopped')
                    with self._lock:self._active_status=active.status()
            finally:self._control_lock.release()
        # Eager resources remain owned even if graph startup prevented the
        # navigation thread (and its finally block) from ever starting.
        if 'navigation' not in self._threads and self.mapper is not None:
            self._cleanup('mapper',self.mapper)
        self._wake.set();self._nav_wake.set();self._region_wake.set();self._room_wake.set()
        for name in ('recorder','navigation','region','room_pipeline','graph'):
            thread=self._threads.get(name)
            if thread is not None:thread.join(remaining(deadline))
        alive=[name for name,thread in self._threads.items() if thread.is_alive()]
        schedule=self.scheduler.snapshot();health=self.health.snapshot()
        pending=max(self._journal_counts['pending'],schedule['pending']+schedule['inflight'])
        failed=dict(health['failed']);pending_workers=alive+list(self._cleanup_pending)+([] if control_acquired else ['control'])
        active=getattr(self,'_active',None)
        if active is not None and not active.close(remaining(deadline)):
            pending_workers.append('reobserve_proposal')
        clean=not pending_workers and not pending and not failed
        report=dict(drained=self._counts['committed'],pending=pending,failed=failed,
                    room_pipeline_failed=self._room_failure,
                    semantic_sampling=self.semantic_sampling_snapshot(),
                    replay_required=bool(pending or failed or pending_workers),clean_shutdown=clean,
                    workers_pending=pending_workers,cleanup_pending=dict(self._cleanup_pending),
                    recorder_certificate=dict(complete=bool(clean and not self._counts['missing'] and not self._prior_incomplete),
                        offered_count=self._counts['offered'],durable_accepted_count=self._counts['durable_accepted'],
                        missing_count=self._counts['missing'],stopped=not alive),
                    actual_profile=self.health.profile,metrics=self.telemetry())
        # Certificate write itself cannot make public close overrun its deadline.
        # Only the worker writes final certificates; this report is authoritative
        # while workers remain pending. No completed file on a timed-out close.
        return report
