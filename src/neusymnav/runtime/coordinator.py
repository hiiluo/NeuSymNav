"""One canonical graph owner, independent latest navigation, durable recovery.

Factories are explicit: native/model dependencies are never silently replaced
by fixtures. ``submit`` offers memory reservations; only ``durable_accepted``
is a persistence ACK. All source assets retain original identity and clock.
"""
from __future__ import annotations
from dataclasses import replace
from contextlib import contextmanager
import inspect
import json
import math
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from threading import Event,RLock
import time
from ..contracts import Observation,RegionSnapshot,MotionCommand,HierarchySnapshot,FrameKey,age_ns
from ..contracts.observations import validate_detection_batch,validate_appearance_batch
from ..contracts.serialization import dumps
from ..hierarchy.composer import HierarchyComposer
from ..perception.projector import Projector
from ..perception.appearance_client import attach_features
from .scheduler import Entry,KeyframeScheduler,KeyframePolicy,payload_bound
from .workers import Journal,atomic_write,background,remaining,valid_timeout
from .health import Health
from .quota import RunQuota

ROOM_PIPELINE_DISK_RESERVATION_BYTES = 2 * 1024**3 + 128 * 1024**2


def _record_timing_stage(measurements,obs,timing,stage,start_name,end_name):
    try:
        start,end=timing[start_name],timing[end_name]
        if type(start) is int and type(end) is int and end>=start:
            measurements.stage(obs,stage,start,end)
    except Exception:
        pass  # Diagnostics must never change control behavior.


class StaleNavigationCapture(ValueError):
    """A valid capture expired before pose admission; acquire a NEW source."""



def set_gil_switch_interval(seconds):
    """Set the interpreter GIL switch interval; returns the previous value."""
    import sys as _sys
    if type(seconds) is not float or not math.isfinite(seconds) or not .0005<=seconds<=.005:
        raise ValueError('gil switch interval must be in [0.0005, 0.005] s')
    previous=_sys.getswitchinterval();_sys.setswitchinterval(seconds)
    return previous

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
                 startup_timeout_s=5.,publisher=None,measurements=None,keyframe_sampling='novelty',
                 room_pipeline_factory=None,room_fps_cap_hz=None,room_queue_policy='bounded_fifo',
                 allow_fresh_map_lag=False,scene_graph_backend='legacy',hydra_runtime_factory=None,
                 offline_replay_control=False,local_depth_control=False,world_navigation_hz=None,
                 world_intent_ttl_ns=2_000_000_000,local_sampling_stride=None,
                 command_horizon_ns=100_000_000,rotation_horizon_ns=None,
                 overview_refresh_ns=None,gil_switch_interval_s=None,start_unknown_tolerance=0.):
        if scene_graph_backend not in {'legacy','hydra'}:raise ValueError('scene_graph_backend must be legacy or hydra')
        if scene_graph_backend=='hydra' and (hydra_runtime_factory is None or room_pipeline_factory is not None or region_factory is not None or verifier_factory is not None or encoder_factory is not None):
            raise ValueError('Hydra backend requires its runtime factory and excludes legacy region/room/verification/appearance workers')
        if type(allow_fresh_map_lag) is not bool:raise ValueError('allow_fresh_map_lag must be boolean')
        self.allow_fresh_map_lag=allow_fresh_map_lag
        if type(offline_replay_control) is not bool:raise ValueError('offline_replay_control must be boolean')
        if offline_replay_control and not clock_domain.startswith('replay:'):
            raise ValueError('offline replay control requires an isolated replay clock')
        self.offline_replay_control=offline_replay_control
        if type(keyframe_sampling) is not str or keyframe_sampling not in {'novelty','capacity_deferred'}:
            raise ValueError('keyframe_sampling must be novelty or capacity_deferred')
        if room_fps_cap_hz is not None and (type(room_fps_cap_hz) not in (int,float)
                or not math.isfinite(room_fps_cap_hz) or not 0 < room_fps_cap_hz <= 20):
            raise ValueError('room_fps_cap_hz must be positive finite and <= 20')
        if type(room_queue_policy) is not str or room_queue_policy not in {'bounded_fifo','latest_wins'}:
            raise ValueError('room_queue_policy must be bounded_fifo or latest_wins')
        if room_queue_policy=='latest_wins' and room_fps_cap_hz is None:
            raise ValueError('latest_wins room queue requires an explicit room_fps_cap_hz')
        if not all(isinstance(v,str) and v for v in (episode_id,primary_sensor_id,clock_domain,floor_id,actual_profile)):
            raise ValueError('explicit episode/sensor/clock/floor/profile identities required')
        valid_timeout(startup_timeout_s)
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.episode_id=episode_id;self.primary_sensor_id=primary_sensor_id;self.clock_domain=clock_domain
        self.floor_id=floor_id;self.now_ns=now_ns;self.publisher=publisher;self.measurements=measurements
        self.owner_factory=owner_factory;self.detector_factory=detector_factory;self.verifier_factory=verifier_factory
        self.scene_graph_backend=scene_graph_backend;self.hydra_runtime_factory=hydra_runtime_factory
        self._hydra_runtime=None;self._hydra_failure=None;self._hydra_snapshot=None;self._hydra_diagnostics=None
        self._hydra_close_report=None
        self._hydra_projection=None;self._hydra_publication_key=None;self._hydra_publication_ns=0
        self._hydra_display_revision=0
        self._hydra_counts=dict(offered=0,queued=0,replaced=0,rejected=0,processed=0)
        self.encoder_factory=encoder_factory;self.region_factory=region_factory
        self.room_pipeline_factory=room_pipeline_factory
        self._room_fps_cap_hz=None if room_fps_cap_hz is None else float(room_fps_cap_hz)
        self._room_min_period_ns=None if room_fps_cap_hz is None else int(math.ceil(1_000_000_000/float(room_fps_cap_hz)))
        self._room_queue_policy=room_queue_policy
        self._room_last_selected_capture_ns=None
        self.mapper=mapper;self.navigator=navigator;self.guard=guard
        if type(local_depth_control) is not bool:raise ValueError('local_depth_control must be boolean')
        if local_depth_control and (mapper is None or navigator is None or guard is None):
            raise ValueError('local depth control requires mapper, navigator and guard')
        if world_navigation_hz is not None:
            if (type(world_navigation_hz) not in (int,float) or not math.isfinite(world_navigation_hz)
                    or not 0<world_navigation_hz<=10):
                raise ValueError('world_navigation_hz must be in (0,10]')
            if not local_depth_control:raise ValueError('world_navigation_hz requires local_depth_control')
        if (type(world_intent_ttl_ns) is not int or not 2_000_000_000<=world_intent_ttl_ns<=5_000_000_000):
            raise ValueError('world_intent_ttl_ns must be an int in [2 s, 5 s]')
        if not local_depth_control and (world_intent_ttl_ns!=2_000_000_000 or local_sampling_stride is not None
                                        or command_horizon_ns!=100_000_000 or rotation_horizon_ns is not None
                                        or start_unknown_tolerance):
            raise ValueError('world intent TTL, local sampling stride and pulse horizons require local_depth_control')
        self.world_intent_ttl_ns=world_intent_ttl_ns
        self.local_depth_control=local_depth_control
        self.world_navigation_hz=None if world_navigation_hz is None else float(world_navigation_hz)
        # Display/room overview refresh period on the world thread. Its cost
        # grows with explored area and competes with control for the GIL.
        if overview_refresh_ns is not None and (type(overview_refresh_ns) is not int
                or not 500_000_000<=overview_refresh_ns<=10_000_000_000):
            raise ValueError('overview_refresh_ns must be an int in [0.5 s, 10 s]')
        self.overview_refresh_ns=overview_refresh_ns
        self._last_overview_refresh_ns=None
        self.overview_refresh_counts=dict(refreshed=0,skipped=0)
        self._hydra_polled_token=None
        self.hydra_poll_counts=dict(polled=0,skipped=0)
        # Shorter GIL switch interval: the control thread waits less for the
        # GIL while the world thread runs long Python/numpy sections.
        self._previous_switch_interval=(None if gil_switch_interval_s is None
                                        else set_gil_switch_interval(gil_switch_interval_s))
        self.gil_switch_interval_s=gil_switch_interval_s
        if local_depth_control:
            from ..navigation.local_control import LocalMeasuredMap, LocalFollower
            from ..navigation.safety import MotionGuard
            self._local_map=LocalMeasuredMap(mapper,sampling_stride=local_sampling_stride);self._local_follower=LocalFollower(navigator)
            self._local_guard=MotionGuard(self._local_map.mapper,clock_domain=clock_domain,
                now_ns=now_ns,offline_replay=offline_replay_control,
                command_horizon_ns=command_horizon_ns,rotation_horizon_ns=rotation_horizon_ns,
                pace_to_wall_time=command_horizon_ns!=100_000_000 or rotation_horizon_ns is not None,
                start_unknown_tolerance=start_unknown_tolerance)
            self._local_intent=None;self._local_feedback=deque(maxlen=1)
            self._local_intent_generation=0
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
        self._step_navigation_diagnostics=None
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
        self._room_counts=dict(candidates=0,fps_limited=0,offered=0,queued=0,queue_replaced=0,
            session_admitted=0,rejected=0,processed=0,queue_dropped=0,age_clock_errors=0)
        self._room_latency_samples={key:deque(maxlen=8192) for key in
            ('source_age_at_start','source_age_at_completion','queue_wait','service')}
        self._room_wake=Event()
        self._prior_incomplete=False;self._fast=None;self._processed=None;self._captured=None;self._last_index=-1;self._last_stamp=-1
        self._counts=dict(submitted=0,offered=0,durable_accepted=0,committed=0,missing=0,recovered=0,detector_calls=0)
        self._journal_counts=dict(accepted=0,committed=0,pending=0);self._cleanup_pending={};self._worker_done={}
        self._config=dict(schema_version=1,episode_id=episode_id,primary_sensor_id=primary_sensor_id,
                          clock_domain=clock_domain,floor_id=floor_id,actual_profile=actual_profile)
        if allow_fresh_map_lag:self._config['navigation_map_policy']='fresh_map_current_depth_v1'
        if local_depth_control:self._config['navigation_map_policy']='local_measured_depth_v1'
        if self.world_navigation_hz is not None:self._config['world_navigation_hz']=self.world_navigation_hz
        if world_intent_ttl_ns!=2_000_000_000:self._config['world_intent_ttl_ns']=world_intent_ttl_ns
        if local_sampling_stride is not None:self._config['local_sampling_stride']=local_sampling_stride
        if keyframe_sampling!='novelty':self._config['keyframe_sampling']=keyframe_sampling
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
        if getattr(self,'local_depth_control',False):self._invalidate_local_intent()
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
            if self.mapper is not None and (not self.offline_replay_control or obs.modality=='depth_only'):
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
            if self._keyframe_sampling=='capacity_deferred' and self.scheduler.semantic_busy():
                self._semantic_sampling['deferred_capacity']+=1
                return
            self._semantic_sampling['policy_evaluated']+=1
            selected,reason,novelty=self.policy.propose(obs)
            if not selected:
                self._semantic_sampling['policy_unselected']+=1
                return
            self._semantic_sampling['offered']+=1
            self._counts['offered']+=1
            if self.measurements is not None:self.measurements.admission(obs,'offered')
            entry=Entry(obs,payload_bound(obs),novelty,reason)
            accepted,replaced,_=self.scheduler.offer(entry)
            if not accepted:
                self._counts['missing']+=1;self.health.increment('rejected')
                if self.measurements is not None:self.measurements.admission(obs,'rejected')
                return
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
        with self._lock:
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
        allowed_clock=(self.clock_domain.startswith('replay:') if self.offline_replay_control
                       else self.clock_domain.startswith('host_monotonic:'))
        if obs.key.episode_id!=self.episode_id or obs.clock_domain!=self.clock_domain or not allowed_clock:
            raise ValueError('body pose admission requires current live episode clock')
        capture_age=age_ns(obs.capture_monotonic_ns,obs.clock_domain,self.now_ns(),self.clock_domain)
        xy=pose['robot_xy']
        if not isinstance(xy,(tuple,list)) or len(xy)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*xy,pose['yaw_rad'])):
            raise ValueError('finite measured robot_xy/yaw required')
        if capture_age>300_000_000:raise StaleNavigationCapture('body pose source is stale')
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
            if name=='hydra' and isinstance(report,dict):self._hydra_close_report=report
            if isinstance(report,dict) and (report.get('clean_shutdown') is False or report.get('complete') is False):
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
        journal=owner=detector=encoder=verifier=hydra_runtime=None
        try:
            if self.measurements is not None and self.measurements.stop_requested.is_set():
                raise RuntimeError('resource cap breached before graph/model startup')
            self.quota.reserve('startup',3*1024**2)
            journal=Journal(self.root,self._config)
            certificate_path=self.root/'recording-certificate.json'
            if certificate_path.exists():
                self._prior_incomplete=not json.loads(certificate_path.read_text()).get('complete',False)
            atomic_write(certificate_path,json.dumps(dict(complete=False,stopped=False,reason='runtime_active_or_unclean_exit')).encode())
            if self.scene_graph_backend=='hydra':
                hydra_runtime=self.hydra_runtime_factory()
                diagnostics=getattr(hydra_runtime,'diagnostics',None)
                with self._lock:
                    self._hydra_runtime=hydra_runtime
                    self._hydra_diagnostics=diagnostics() if callable(diagnostics) else None
            else:owner=self.owner_factory()
            if owner is not None and hasattr(owner,'ledger'):
                self._require_run_path(owner.ledger.root,'ObjectOwner ledger root')
                owner_config=json.loads(owner.ledger.get('config'))
                for identity in ('episode_id','primary_sensor_id','clock_domain','floor_id'):
                    if owner_config[identity]!=self._config[identity]:raise ValueError('owner '+identity+' mismatch')
            detector=self.detector_factory()
            encoder=None if self.encoder_factory is None else self.encoder_factory()
            if self.scene_graph_backend=='legacy' and self.verifier_factory is not None:
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
            self._objects=None if owner is None else owner.snapshot()
            self._verification=None if verifier is None or not hasattr(verifier,'snapshot') else verifier.snapshot()
            # Drain persisted accepted refs BEFORE enabling new admission.
            while journal.next_pending() is not None:
                index=journal.next_pending();obs=journal.load(index)
                self._validate_recovery_source(obs)
                journal.watermark(index)
                if self.scene_graph_backend=='hydra':self._process_hydra(obs,journal,detector,hydra_runtime,recovery=True)
                else:self._process(obs,journal,owner,detector,encoder,verifier,recovery=True)
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
                    if self.scene_graph_backend=='hydra':self._process_hydra(entry.observation,journal,detector,hydra_runtime)
                    else:self._process(entry.observation,journal,owner,detector,encoder,verifier)
                    self.scheduler.complete(entry);self._journal_counts=journal.counts()
                self._consume_place()
                if self.scene_graph_backend=='hydra' and hydra_runtime is not None and self._hydra_poll_due(hydra_runtime):
                    snapshot=hydra_runtime.snapshot()
                    project=getattr(hydra_runtime,'projection',None)
                    projection=project() if callable(project) else None
                    with self._lock:
                        self._hydra_snapshot=snapshot
                        if projection is not None:self._hydra_projection=projection
                        reason=(snapshot.get('failure_reason') if isinstance(snapshot,Mapping)
                                else getattr(snapshot,'failure_reason',None))
                        if reason:self._hydra_failure=str(reason)
                if self.scene_graph_backend=='legacy':self._publish(verifier)
                else:self._publish_hydra()
                if (self._closing and self._recorder_done.is_set() and not self.scheduler.snapshot()['pending']
                    and (self.mapper is None or self._worker_done.get('navigation',False))
                    and (self.region_factory is None or self._worker_done.get('region',False))
                    and self._place_input is None):
                    # Producers can finish between the preceding publication
                    # and this predicate. Flush once after observing quiescence.
                    if self.scene_graph_backend=='legacy':self._publish(verifier)
                    else:self._publish_hydra(force=True)
                    break
                self._wake.wait(.01);self._wake.clear()
        except BaseException as exc:
            if self.scene_graph_backend=='hydra':
                with self._lock:self._hydra_failure=f'{type(exc).__name__}: {exc}'
                self._ready.set()
            else:self._fail('graph',exc)
        finally:
            self._ready.set()
            if journal is not None:
                self._journal_counts=journal.counts();journal.close()
            if hydra_runtime is not None:
                self._cleanup('hydra',hydra_runtime)
                self._publish_hydra_after_close(hydra_runtime)
                with self._lock:self._hydra_runtime=None
            for name,resource in (('verifier',verifier),('encoder',encoder),('detector',detector),('owner',owner)):
                self._cleanup(name,resource)
            self._worker_done['graph']=True

    def _publish_hydra_after_close(self,hydra_runtime):
        """Refresh the display from the graph after close drains accepted work."""
        snapshot=hydra_runtime.snapshot()
        project=getattr(hydra_runtime,'projection',None)
        projection=project() if callable(project) else None
        with self._lock:
            self._hydra_snapshot=snapshot
            if projection is not None:self._hydra_projection=projection
            reason=(snapshot.get('failure_reason') if isinstance(snapshot,Mapping)
                    else getattr(snapshot,'failure_reason',None))
            if reason:self._hydra_failure=str(reason)
        self._publish_hydra(force=True)

    def _process_hydra(self,obs,journal,detector,hydra_runtime,*,recovery=False):
        """Offer from the durable graph lane; child failures stay graph-local."""
        batch=journal.result(obs.key.frame_index)
        if batch is None:
            batch=detector.infer(obs);validate_detection_batch(obs,batch)
            measured_return_ns=self.now_ns();self._counts['detector_calls']+=1
            if self.measurements is not None:
                self.measurements.result(obs,measured_return_ns,'detector_return',
                    origin='recovery' if recovery else 'historical' if self.clock_domain.startswith('replay:') else 'live')
            key=('hydra-result',obs.key.frame_index)
            self.quota.reserve(key,3*len(dumps(batch).encode())+131072)
            try:journal.result(obs.key.frame_index,batch)
            finally:self.quota.release(key)
        else:validate_detection_batch(obs,batch)
        with self._lock:self._hydra_counts['offered']+=1
        if self._hydra_failure is None:
            try:
                admission=hydra_runtime.offer(obs,batch)
                with self._lock:
                    self._hydra_counts['queued']+=admission.status=='queued'
                    self._hydra_counts['replaced']+=admission.status=='replaced'
                    self._hydra_counts['rejected']+=admission.status not in {'queued','replaced'}
                    self._hydra_snapshot=hydra_runtime.snapshot()
                    if self._hydra_snapshot is not None and self._hydra_snapshot.failure_reason:
                        self._hydra_failure=self._hydra_snapshot.failure_reason
            except BaseException as exc:
                with self._lock:self._hydra_failure=f'{type(exc).__name__}: {exc}';self._hydra_counts['rejected']+=1
        else:
            with self._lock:self._hydra_counts['rejected']+=1
        journal.done(obs.key.frame_index)
        with self._lock:
            self._processed=obs.key;self._last_processed_capture=obs.capture_monotonic_ns
            self._counts['committed']+=1;self._hydra_counts['processed']+=1

    def _publish_hydra(self,*,force=False):
        """Publish a native graph snapshot on the display lane, separate from control."""
        if self.publisher is None:return
        with self._lock:
            projection=self._hydra_projection;nav=self._latest_nav
            captured=self._captured;processed=self._processed
            failure=self._hydra_failure
            display_revision=self._hydra_display_revision+1
        now=self.now_ns()
        key=(None if projection is None else projection.graph_revision,
             None if nav is None else nav.revision,
             None if projection is None else projection.status,failure)
        if not force and key==self._hydra_publication_key and now-self._hydra_publication_ns<100_000_000:return
        map_age=None if nav is None else age_ns(nav.capture_monotonic_ns,nav.clock_domain,now,self.clock_domain)
        hierarchy=HierarchySnapshot(self.episode_id,
            display_revision,0,0 if nav is None else nav.revision,0,
            {},(),{'legacy_hierarchy':'unavailable_hydra_backend',
                'hydra_graph':'unavailable' if projection is None else projection.status,
                'hydra_failure':failure or ''},0 if nav is None else nav.revision,
            0 if map_age is None else map_age)
        from ..visualization.publisher import DisplaySources
        metrics=dict(captured_frame_id=captured,processed_frame_id=processed,
            published_frame_id=None if projection is None or projection.last_source is None else
                FrameKey(projection.last_source['episode_id'],projection.last_source['sensor_id'],
                         projection.last_source['frame_index']),
            source_age_ns={} if map_age is None else {'map':map_age},dropped_count=self._counts['missing'],
            replaced_count=self.scheduler.counts['replaced'],actual_profile=self.health.profile,
            sources=DisplaySources(nav=nav,hydra_graph=projection))
        self.publisher.publish(hierarchy,metrics)
        with self._lock:
            self._hydra_display_revision=display_revision
            self._hydra_publication_key=key;self._hydra_publication_ns=now

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
        with self._lock:
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

    def _wait_world_navigation_slot(self, deadline):
        """Wait before dequeue so source admission can keep replacing pending data."""
        while not self._closing and not self.health.snapshot()['failed']:
            delay=deadline-time.monotonic()
            if delay<=0:return
            # Events wake shutdown immediately; short polling bounds races
            # between wake and clear without ever holding the admission lock.
            self._nav_wake.wait(min(delay,.02));self._nav_wake.clear()

    def _navigation_run(self):
        try:
            rate=getattr(self,'world_navigation_hz',None)
            period=None if rate is None else 1./rate
            next_start=0.
            while True:
                if period is not None:self._wait_world_navigation_slot(next_start)
                with self._lock:
                    obs=self._nav_input;proof=self._nav_pose_input
                    self._nav_input=None;self._nav_pose_input=None
                if obs is None:
                    if self._closing or self.health.snapshot()['failed']:break
                    self._nav_wake.wait(.02);self._nav_wake.clear();continue
                if period is not None:next_start=time.monotonic()+period
                core=getattr(self.mapper,'_core',None)
                budget=(2*(core.MAX_PLANAR_MEMORY_BYTES+core.MAX_HEIGHT_MEMORY_BYTES)+1024*1024) if core is not None and not getattr(self,'_archive_write_reserved',False) else 0
                if budget:self.quota.reserve('navigation-archive',budget)
                fast_update=getattr(self.mapper,'update_for_control',None)
                refresh_overview=getattr(self.mapper,'refresh_overview',None)
                deferred_overview=callable(fast_update) and callable(refresh_overview)
                map_start_ns=time.monotonic_ns()
                try:nav=fast_update(obs) if deferred_overview else self.mapper.update(obs)
                finally:
                    map_end_ns=time.monotonic_ns()
                    if self.measurements is not None:
                        self.measurements.stage(obs,'navmap_update',map_start_ns,map_end_ns)
                        phases=getattr(self.mapper,'last_update_stages',None)
                        if isinstance(phases,dict):
                            for stage,(start_ns,end_ns) in tuple(phases.items()):
                                self.measurements.stage(obs,stage,start_ns,end_ns)
                    if budget:self.quota.release('navigation-archive')
                publish_start_ns=time.monotonic_ns()
                with self._lock:
                    self._latest_nav=nav
                    if deferred_overview:self._latest_overview_tiles=None
                    if proof is not None:
                        if self._place_input is not None:self._place_counts['pair_replaced']+=1
                        self._place_input=(nav,proof)
                    else:self._place_counts['unmatched']+=1
                publish_end_ns=time.monotonic_ns()
                if self.local_depth_control and proof is not None:
                    intent_start_ns=time.monotonic_ns()
                    try:self._update_world_intent(nav,proof)
                    finally:
                        if self.measurements is not None:
                            self.measurements.stage(obs,'world_navigation_intent',intent_start_ns,time.monotonic_ns())
                if self.measurements is not None:
                    self.measurements.stage(obs,'navmap_publish',publish_start_ns,publish_end_ns)
                # Navigation/control can consume the immutable snapshot while
                # display-only overview tiles are refreshed below.
                self._wake.set()
                overview = None
                counts=getattr(self,'overview_refresh_counts',None)
                due=self._overview_refresh_due(time.monotonic_ns())
                if deferred_overview and not due and counts is not None:counts['skipped']+=1
                if deferred_overview and due:
                    self._last_overview_refresh_ns=time.monotonic_ns()
                    if counts is not None:counts['refreshed']+=1
                    overview_start_ns=time.monotonic_ns()
                    try:refresh_overview(nav)
                    except Exception:pass
                    finally:
                        overview_end_ns=time.monotonic_ns()
                        if self.measurements is not None:
                            self.measurements.stage(obs,'navmap_overview_refresh',overview_start_ns,overview_end_ns)
                            phases=getattr(self.mapper,'last_overview_stages',None)
                            if isinstance(phases,dict):
                                for stage,(start_ns,end_ns) in tuple(phases.items()):
                                    self.measurements.stage(obs,stage,start_ns,end_ns)
                try:
                    provider = getattr(self.mapper, 'overview_tiles', None)
                    if provider is not None:overview = provider()
                except Exception:
                    pass  # Optional display data must never fail control.
                room_provider=getattr(self.mapper,'room_input_tiles',None) if self.region_factory is not None else None
                room_tiles=None
                if callable(room_provider):
                    room_start_ns=time.monotonic_ns()
                    try:room_tiles=room_provider()
                    except Exception:pass  # Region lane reports unavailable; control proceeds.
                    finally:
                        if self.measurements is not None:
                            self.measurements.stage(obs,'navmap_room_input',room_start_ns,time.monotonic_ns())
                with self._lock:
                    self._latest_overview_tiles=overview
                    if self.region_factory is not None:
                        self._region_input=(nav,room_tiles) if callable(room_provider) else nav
                        self._region_wake.set()
                self._wake.set()
        except BaseException as exc:self._fail('navigation',exc)
        finally:
            self._cleanup('mapper',self.mapper);self._worker_done['navigation']=True;self._wake.set()

    def _hydra_poll_due(self,hydra_runtime):
        """Re-read the Hydra snapshot/projection only after its state changed.

        Both deep-copy/re-project the whole (growing) graph; polling them on
        every graph-lane wake starved the control thread of the GIL."""
        token_fn=getattr(hydra_runtime,'state_token',None)
        token=token_fn() if callable(token_fn) else None
        if token is None:return True
        if token==getattr(self,'_hydra_polled_token',None):
            counts=getattr(self,'hydra_poll_counts',None)
            if counts is not None:counts['skipped']+=1
            return False
        self._hydra_polled_token=token
        counts=getattr(self,'hydra_poll_counts',None)
        if counts is not None:counts['polled']+=1
        return True

    def _overview_refresh_due(self,now_ns):
        period=getattr(self,'overview_refresh_ns',None);last=getattr(self,'_last_overview_refresh_ns',None)
        return period is None or last is None or now_ns-last>=period

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
        self._room_counts['candidates']+=1
        if self._room_min_period_ns is not None:
            previous=self._room_last_selected_capture_ns
            if previous is not None and obs.capture_monotonic_ns-previous<self._room_min_period_ns:
                self._room_counts['fps_limited']+=1
                self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=False,
                    reason='room_fps_cap',fps_cap_hz=self._room_fps_cap_hz))
                return
            self._room_last_selected_capture_ns=obs.capture_monotonic_ns
        self._room_counts['offered']+=1
        budget=self._room_payload_budget(obs)
        if self._room_failure is not None:
            self._room_counts['rejected']+=1
            self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=False,reason='room_worker_failed'))
            return
        max_pending=1 if self._room_queue_policy=='latest_wins' else 2
        replaced=None
        if self._room_queue_policy=='latest_wins' and self._room_queue:
            replaced=self._room_queue[0]
        bytes_after_replace=self._room_queue_bytes-(0 if replaced is None else replaced[1])
        if ((len(self._room_queue)>=max_pending and replaced is None)
                or bytes_after_replace+self._room_inflight_bytes+budget>32*1024**2):
            self._room_counts['rejected']+=1;self._room_counts['queue_dropped']+=1
            self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=False,reason='room_queue_full',estimated_bytes=budget))
            return
        if replaced is not None:
            replaced_obs,replaced_budget,_=self._room_queue.popleft()
            self._room_queue_bytes-=replaced_budget
            self._room_counts['queue_replaced']+=1;self._room_counts['queue_dropped']+=1
            self._record_room_event(dict(frame_index=replaced_obs.key.frame_index,accepted=False,
                reason='room_queue_replaced_by_newer',replacement_frame_index=obs.key.frame_index,
                estimated_bytes=replaced_budget))
        self._room_queue.append((obs,budget,time.perf_counter_ns()));self._room_queue_bytes+=budget
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
                        obs,budget,enqueued_perf_ns=self._room_queue.popleft();self._room_queue_bytes-=budget
                        self._room_inflight_bytes=budget
                    else:
                        obs=None;budget=0;enqueued_perf_ns=0
                    closing=self._closing
                if obs is None:
                    if closing:break
                    self._room_wake.wait(.05);self._room_wake.clear();continue
                room_start_perf_ns=time.perf_counter_ns()
                now_ns=self.now_ns()
                source_age_start_ns=(now_ns-obs.capture_monotonic_ns
                    if obs.clock_domain==self.clock_domain and now_ns>=obs.capture_monotonic_ns else None)
                queue_wait_ms=max(0,room_start_perf_ns-enqueued_perf_ns)/1_000_000
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
                    room_service_ms=max(0,time.perf_counter_ns()-room_start_perf_ns)/1_000_000
                    completion_ns=self.now_ns()
                    source_age_completion_ns=(completion_ns-obs.capture_monotonic_ns
                        if obs.clock_domain==self.clock_domain and completion_ns>=obs.capture_monotonic_ns else None)
                    for key,value in (('queue_wait',queue_wait_ms),('service',room_service_ms)):
                        self._room_latency_samples[key].append(value)
                    if source_age_start_ns is None or source_age_completion_ns is None:
                        self._room_counts['age_clock_errors']+=1
                    else:
                        self._room_latency_samples['source_age_at_start'].append(source_age_start_ns/1_000_000)
                        self._room_latency_samples['source_age_at_completion'].append(source_age_completion_ns/1_000_000)
                    self._record_room_event(dict(frame_index=obs.key.frame_index,accepted=True,
                        reason='room_update_finished',queue_wait_ms=queue_wait_ms,service_ms=room_service_ms,
                        source_age_at_start_ms=None if source_age_start_ns is None else source_age_start_ns/1_000_000,
                        source_age_at_completion_ms=None if source_age_completion_ns is None else source_age_completion_ns/1_000_000))
                    self._room_inflight_bytes=0
                    if self._room_failure is not None:
                        while self._room_queue:
                            queued,_,_=self._room_queue.popleft()
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
                sources=DisplaySources(nav=nav,objects=objects,verification=display_verification,
                    room_pipeline=room_publication)))

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

    def snapshot(self):
        with self._lock:return self._hierarchy

    def scene_graph_query(self):
        """Read one canonical Hydra generation without blocking the control lock.

        Returns None before graph availability or after runtime shutdown.
        Object candidates remain semantic hypotheses, not traversable goals.
        """
        with self._lock:runtime=getattr(self,'_hydra_runtime',None)
        return None if runtime is None else runtime.scene_graph_query()

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
            world={}
            if getattr(self,'local_depth_control',False):
                latest=getattr(self,'_world_planner_latest',None)
                world=dict(world_planner=dict(
                    reason_counts=dict(getattr(self,'_world_planner_reason_counts',{})),
                    latest=None if latest is None else dict(latest,source=dict(latest['source'])),
                    last_goal_failure=last_failure))
                if getattr(self,'overview_refresh_ns',None) is not None:
                    world['world_planner']['overview_refresh']=dict(getattr(self,'overview_refresh_counts',{}),
                        period_ms=self.overview_refresh_ns//1_000_000)
                guard=getattr(self,'_local_guard',None)
                if getattr(guard,'start_unknown_tolerance',0):
                    world['world_planner']['start_unknown']=dict(tolerance=guard.start_unknown_tolerance,
                        guard_tolerated=int(guard.start_unknown_tolerated),
                        world_cleared=int(getattr(self.navigator,'start_unknown_cleared',0)),
                        local_cleared=int(getattr(getattr(self,'_local_follower',None),'start_unknown_cleared',0)))
                if getattr(self,'gil_switch_interval_s',None) is not None:
                    world['world_planner']['gil_switch_interval_ms']=self.gil_switch_interval_s*1000.
                tour=getattr(self.navigator,'tour',None)
                if tour is not None:
                    world['world_planner']['tour']=dict(tour.status(),
                        frontier_fallback_steps=int(getattr(self.navigator,'tour_fallback_steps',0)),
                        frontier_fallback_active=bool(getattr(self.navigator,'tour_fallback_active',False)))
        if plan is None:return dict(reason='navigation_unavailable',reason_counts=counts,**world)
        nav,frontiers,decision,reason,computed,rejected,held_goal=plan
        goal=held_goal or ((decision.goal_id,decision.path[-1]) if not rejected and decision.goal_id and decision.path else None)
        return dict(map_revision=nav.revision,computed_monotonic_ns=computed,
            reason=reason,decision_reason=decision.reason,reason_counts=counts,last_goal_failure=last_failure,
            goal_id=None if goal is None else goal[0],goal_xy=None if goal is None else goal[1],
            route_available=bool(decision.path) and not rejected,
            frontier_count=0 if frontiers is None else len(frontiers.frontiers),**world)

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
            def latency_summary(values):
                ordered=sorted(values)
                if not ordered:return dict(samples=0,p50_ms=None,p95_ms=None,max_ms=None)
                def percentile(fraction):return ordered[min(len(ordered)-1,math.ceil(fraction*len(ordered))-1)]
                return dict(samples=len(ordered),p50_ms=percentile(.50),p95_ms=percentile(.95),max_ms=ordered[-1])
        hydra_snapshot=self._hydra_snapshot
        hydra_close=self._hydra_close_report
        hydra_export=None if hydra_close is None else dict(
            complete=bool(hydra_close.get('complete')),
            manifest_path=hydra_close.get('manifest_path'),
            manifest_sha256=hydra_close.get('manifest_sha256'),
            graph_asset_verified=bool(hydra_close.get('graph_asset_verified')),
            failure_reason=hydra_close.get('failure_reason'))
        if hydra_snapshot is not None and not isinstance(hydra_snapshot,Mapping):
            hydra_snapshot={key:getattr(hydra_snapshot,key,None) for key in (
                'episode_id','graph_revision','last_capture_monotonic_ns','last_clock_domain',
                'input_prefix_sha256','config_sha256','source_sha256','build_sha256',
                'graph_asset_sha256','graph_asset_bytes','node_counts','edge_count','stale',
                'replay_required','failure_reason')}
        report=dict(**self._counts,semantic_sampling=self.semantic_sampling_snapshot(),configuration=dict(self._config,
                            scene_graph_backend=self.scene_graph_backend,
                            depth_max_age_ns=300_000_000,semantic_max_age_ns=750_000_000,
                            inference_start_max_age_ns=250_000_000,publication_interval_ns=100_000_000,
                            appearance_enabled=self.encoder_factory is not None,verification_enabled=self.verifier_factory is not None,
                            regions_enabled=self.region_factory is not None,
                            keyframe_policy=type(self.policy).__name__,
                            min_translation_m=getattr(self.policy,'distance',None),min_yaw_rad=getattr(self.policy,'angle',None)),
                        source_age_ns=self._source_ages_locked(),regions=dict(getattr(self,'_region_diagnostics',{})),
                        room_pipeline=dict(enabled=self.room_pipeline_factory is not None,
                            failed=self._room_failure,counts=dict(self._room_counts),
                            admission=dict(fps_cap_hz=self._room_fps_cap_hz,queue_policy=self._room_queue_policy,
                                max_pending_frames=1 if self._room_queue_policy=='latest_wins' else 2),
                            latency_ms={key:latency_summary(values) for key,values in self._room_latency_samples.items()},
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
                        hydra=dict(backend='hydra' if self.scene_graph_backend=='hydra' else None,
                            failure=self._hydra_failure,counts=dict(self._hydra_counts),snapshot=hydra_snapshot,
                            diagnostics=self._hydra_diagnostics,native_export=hydra_export),
                        places=dict(self._place_counts,status=self._place_status,pose_pending=self._pose_offer is not None,pair_pending=self._place_input is not None))
        # In particular quota.lock can cover a filesystem scan. Never acquire
        # it while holding the lock needed by source admission and control.
        return dict(report,scheduler=self.scheduler.snapshot(),health=self.health.snapshot(),quota=self.quota.snapshot(),navigation=self.navigation_status(),
                    navmap_retention=dict(getattr(self.mapper,'retention_diagnostics',{})))

    def _update_world_intent(self, nav, proof):
        """Only the navigation worker owns policy and processes feedback."""
        from ..navigation.local_control import WorldIntent
        with self._lock:
            generation=getattr(self,'_local_intent_generation',0)
            previous=self._local_intent
            feedback=self._local_feedback.pop() if self._local_feedback else None
            self._local_feedback.clear()
            stopped=self._paused or self._closing or bool(self.health.snapshot()['failed'])
        if stopped:
            self._invalidate_local_intent()
            self.navigator.reset_goal_failure_watch()
            return
        if previous is not None and not previous.compatible(nav,self.now_ns()):
            previous=None
        if feedback is not None:
            intent,xy,reason,rejected=feedback
            if previous is intent:
                # Missing current local evidence is a conservative stop, not
                # proof that the world target is unreachable. Existing recovery
                # requires persistent failure across fresh WORLD revisions.
                if reason=='world_goal_reached':
                    self.navigator.report_goal_reached(intent.goal_id,intent.path[-1])
                    previous=None
                result=self.navigator.observe_navigation_result(nav,xy,self.now_ns(),
                    'path_segment_blocked' if reason=='local_path_blocked' else reason,rejected)
                if result is not None:
                    previous=None
                    with self._lock:self._last_goal_failure=result
        decision=self.navigator.step(nav,proof['robot_xy'],proof['yaw_rad'],self.now_ns())
        if not decision.path:
            # A held world target may become untraversable before the local
            # follower gets an intent. Its own fresh no-path STOP must advance
            # recovery even while local control has nothing to feed back.
            failure=self.navigator.observe_navigation_result(nav,proof['robot_xy'],
                self.now_ns(),decision.reason,True)
            if failure is not None:
                with self._lock:self._last_goal_failure=failure
        candidate=None
        if decision.goal_id and decision.path:
            try:candidate=WorldIntent.from_decision(nav,decision.goal_id,decision.path,self.now_ns(),
                    ttl_ns=getattr(self,'world_intent_ttl_ns',2_000_000_000))
            except ValueError:pass
        elif decision.reason=='nav_stale':
            candidate=previous
        # A control fault or pause that occurred during planning invalidates
        # this publication. Never resurrect an intent across that boundary.
        with self._lock:
            if (generation==getattr(self,'_local_intent_generation',0)
                    and not self._paused and not self._closing and not self.health.snapshot()['failed']):
                self._local_intent=candidate
            counts=getattr(self,'_world_planner_reason_counts',None)
            if counts is None:self._world_planner_reason_counts=counts={}
            reason=decision.reason if decision.reason in counts or len(counts)<64 else 'other'
            counts[reason]=min(counts.get(reason,0)+1,2**63-1)
            computed=self.now_ns()
            try:source_age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,computed,self.clock_domain)
            except ValueError:source_age=None
            self._world_planner_latest=dict(
                source=dict(episode_id=nav.source.episode_id,sensor_id=nav.source.sensor_id,
                            frame_index=nav.source.frame_index),
                capture_monotonic_ns=nav.capture_monotonic_ns,clock_domain=nav.clock_domain,
                map_revision=nav.revision,computed_monotonic_ns=computed,source_age_ns=source_age,
                reason=decision.reason,goal_id=decision.goal_id,path_point_count=len(decision.path),
                intent_available=self._local_intent is not None)

    def _invalidate_local_intent(self, *, expected=None):
        """Clear expired intent by identity; faults invalidate the whole epoch."""
        with self._lock:
            if expected is not None and self._local_intent is not expected:
                return False
            self._local_intent=None
            # Expiry of A must neither clear a published B nor cancel a fresh B
            # currently being planned. Fault/pause still invalidate both.
            if expected is None:
                self._local_intent_generation=getattr(self,'_local_intent_generation',0)+1
            feedback=getattr(self,'_local_feedback',None)
            if feedback is not None and (expected is None or (feedback and feedback[0][0] is expected)):
                feedback.clear()
            return True

    @staticmethod
    def _local_stop_diagnostics(reason):
        return dict(goal_id=None,goal_xy=None,path_point_count=0,path_sample_xy=[],
            path_sample_truncated=False,lookahead_xy=None,heading_error_rad=None,
            decision_reason=reason,control_map_scope='local_measured_depth_v1',world_intent=None)

    def _local_control_step(self,actuator,*,robot_xy=None,yaw_rad=None):
        with self._lock:
            latest=self._latest_depth
            intent=self._local_intent
            generation=getattr(self,'_local_intent_generation',0)
        self._step_source=latest
        self._step_navigation_diagnostics=self._local_stop_diagnostics('navigation_unavailable')
        if self._paused or self._closing or self.health.snapshot()['failed']:
            reason='runtime_paused' if self._paused and not self._closing else 'runtime_stopped'
            self._invalidate_local_intent();self._local_follower.reset()
            self._step_navigation_diagnostics=self._local_stop_diagnostics(reason)
            return dict(executed=False,reason=reason)
        if latest is None:
            self._invalidate_local_intent();self._local_follower.reset()
            return dict(executed=False,reason='navigation_unavailable')
        try:
            pose=actuator.robot_pose(latest)
            if (pose['source']!=latest.key or pose['capture_monotonic_ns']!=latest.capture_monotonic_ns
                    or pose['clock_domain']!=self.clock_domain or pose['pose_version']!=latest.pose_version):
                raise ValueError('actuation pose source mismatch')
            xy=tuple(pose['robot_xy']);yaw=pose['yaw_rad']
            if (robot_xy is not None and tuple(robot_xy)!=xy) or (yaw_rad is not None and yaw_rad!=yaw):
                raise ValueError('caller pose does not match captured robot pose')
            stage_start_ns=time.monotonic_ns()
            try:nav=self._local_map.snapshot(latest,robot_xy=xy)
            finally:
                if self.measurements is not None:
                    self.measurements.stage(latest,'local_depth_map',stage_start_ns,time.monotonic_ns())
            self._local_guard.bind_nav(nav,robot_xy=xy,yaw_rad=yaw)
            stage_start_ns=time.monotonic_ns()
            try:decision=self._local_follower.step(nav,intent,xy,yaw,self.now_ns())
            finally:
                if self.measurements is not None:
                    self.measurements.stage(latest,'local_path_follow',stage_start_ns,time.monotonic_ns())
            self._step_decision=decision
            if decision.reason=='world_intent_stale':self._invalidate_local_intent(expected=intent)
            detail=dict(self._local_follower.last_control_diagnostics)
            world=None if intent is None or not intent.same_scope(nav) else dict(source=dict(episode_id=intent.source.episode_id,
                sensor_id=intent.source.sensor_id,frame_index=intent.source.frame_index),
                capture_monotonic_ns=intent.capture_monotonic_ns,clock_domain=intent.clock_domain,
                map_revision=intent.map_revision,created_monotonic_ns=intent.created_monotonic_ns,
                valid_until_monotonic_ns=intent.valid_until_monotonic_ns)
            detail.update(control_map_scope='local_measured_depth_v1',world_intent=world)
            self._step_navigation_diagnostics=detail
            stage_start_ns=time.monotonic_ns()
            try:command=self._local_guard.filter(decision,latest,self.now_ns())
            finally:
                if self.measurements is not None:
                    self.measurements.stage(latest,'local_motion_guard',stage_start_ns,time.monotonic_ns())
            if intent is not None and self.now_ns()>=intent.valid_until_monotonic_ns:
                command=replace(command,linear_mps=0.,yaw_radps=0.,reason='world_intent_stale')
                self._invalidate_local_intent(expected=intent)
            elif intent is not None and (command.linear_mps or command.yaw_radps):
                command=replace(command,deadline_monotonic_ns=min(command.deadline_monotonic_ns,
                    intent.valid_until_monotonic_ns))
            if self._paused or self._closing or self.health.snapshot()['failed']:
                command=replace(command,linear_mps=0.,yaw_radps=0.,reason='runtime_stopped')
                self._invalidate_local_intent()
            elif generation!=getattr(self,'_local_intent_generation',0) and command.reason!='world_intent_stale':
                command=replace(command,linear_mps=0.,yaw_radps=0.,reason='world_intent_invalidated')
            self._step_command=command
            result=actuator.execute(command);self._last_command=command
            stopped=(not isinstance(result,dict) or result.get('executed') is not True
                     or command.linear_mps==command.yaw_radps==0.)
            display_reason=(result.get('reason') or command.reason) if stopped and isinstance(result,dict) else command.reason
            if display_reason=='expired_or_zero':display_reason=command.reason
            with self._lock:
                if intent is not None and intent.compatible(nav,self.now_ns()) and hasattr(self,'_local_feedback'):
                    self._local_feedback.append((intent,xy,display_reason,stopped))
                counts=getattr(self,'_navigation_reason_counts',None)
                if counts is None:self._navigation_reason_counts=counts={}
                key=display_reason if display_reason in counts or len(counts)<64 else 'other'
                counts[key]=min(counts.get(key,0)+1,2**63-1)
                self._navigation_display=(nav,None,decision,display_reason,self.now_ns(),stopped,
                    None if intent is None else (intent.goal_id,intent.path[-1]))
            return result
        except Exception as exc:
            self._invalidate_local_intent();self._local_follower.reset()
            if self._step_command is None:
                self._step_decision=None
                self._step_navigation_diagnostics=self._local_stop_diagnostics('control_rejected')
            with self._lock:self._navigation_display=None
            return dict(executed=False,reason='control_rejected',error=f'{type(exc).__name__}: {exc}')

    def _navigation_map_compatible(self,nav,latest):
        if nav is None or latest is None:return False
        exact=(nav.source==latest.key and nav.capture_monotonic_ns==latest.capture_monotonic_ns
               and nav.clock_domain==latest.clock_domain)
        if exact:return True
        if not getattr(self,'allow_fresh_map_lag',False):return False
        # A world map may lag the body pose, but never its safety lifetime.
        # Current measured-depth bootstrap and swept-footprint checks remain
        # mandatory in MotionGuard; map and command keep DIFFERENT source IDs.
        if (nav.episode_id!=latest.key.episode_id or nav.source.episode_id!=latest.key.episode_id
                or nav.source.sensor_id!=latest.key.sensor_id
                or nav.source.frame_index>=latest.key.frame_index
                or nav.capture_monotonic_ns>latest.capture_monotonic_ns
                or nav.clock_domain!=latest.clock_domain or latest.clock_domain!=self.clock_domain):return False
        now=self.now_ns()
        return (0<=now-nav.capture_monotonic_ns<=300_000_000
                and 0<=now-latest.capture_monotonic_ns<=300_000_000)

    def control_step(self,actuator,*,robot_xy=None,yaw_rad=None):
        if getattr(self,'offline_replay_control',False):
            from .replay_control import OfflineReplayActuator
            if type(actuator) is not OfflineReplayActuator:
                raise TypeError('offline replay control only accepts OfflineReplayActuator')
        with self._control_lock:
            if self.measurements is not None and self.measurements.stop_requested.is_set():
                self._paused=True;self._stop_requested=True
            self._step_command=None;self._step_decision=None;self._step_source=None
            self._step_navigation_diagnostics=None
            self._step_navigation_observed=False
            control_start_ns=time.monotonic_ns()
            try:result=self._control_step(actuator,robot_xy=robot_xy,yaw_rad=yaw_rad)
            finally:
                control_end_ns=time.monotonic_ns()
                if self.measurements is not None and self._step_source is not None:
                    self.measurements.stage(self._step_source,'control_loop',control_start_ns,control_end_ns)
                    timing=getattr(actuator,'last_actuation_timing',None)
                    if isinstance(timing,dict) and timing.get('clock_domain')==self._step_source.clock_domain:
                        _record_timing_stage(self.measurements,self._step_source,timing,
                            'actuation_roundtrip','host_request_start_ns','host_response_received_ns')
                        _record_timing_stage(self.measurements,self._step_source,timing,
                            'sensor_worker_dispatch','worker_request_received_ns','worker_handler_start_ns')
                        _record_timing_stage(self.measurements,self._step_source,timing,
                            'sensor_worker_handler','worker_handler_start_ns','worker_handler_end_ns')
                        for stage in timing.get('worker_stages',()):
                            if isinstance(stage,dict):
                                self.measurements.stage(self._step_source,stage.get('stage'),
                                    stage.get('start_ns'),stage.get('end_ns'))
            # A missing exact map supplies no new evidence either way. Keep
            # the watch unchanged; Navigator itself restarts it after >1 s
            # without fresh observations. Pause/error still cancels the window.
            if (not getattr(self,'local_depth_control',False) and not self._step_navigation_observed and
                    (not isinstance(result,dict) or result.get('reason')!='navigation_source_pending')):
                reset=getattr(self.navigator,'reset_goal_failure_watch',None)
                if callable(reset):reset()
            if self.measurements is not None:
                proof=None
                if self._step_command is not None:
                    try:proof=getattr(actuator,'last_actuation_proof',None)
                    except Exception:pass
                self.measurements.control(self._step_source,self.now_ns(),result,command=self._step_command,
                    decision=self._step_decision,proof=proof,profile=self.health.profile.split(':')[0],
                    navigation=self._step_navigation_diagnostics)
            return result

    def _control_step(self,actuator,*,robot_xy=None,yaw_rad=None):
        """Fresh navigation -> guard -> actual source-bound execute seam.

        Guard/actuator exceptions never fall back to a bare action or republish
        an old capture. The caller can keep capturing while detector/disk hangs.
        """
        if getattr(self,'local_depth_control',False):
            return self._local_control_step(actuator,robot_xy=robot_xy,yaw_rad=yaw_rad)
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
            if not self._navigation_map_compatible(nav,latest):
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
                    decision=self.navigator.step(nav,xy,yaw,self.now_ns())
                    self._step_decision=decision
                    detail=getattr(self.navigator,'last_control_diagnostics',None)
                    if isinstance(detail,dict):self._step_navigation_diagnostics=dict(detail)
                    command=self.guard.filter(decision,latest,self.now_ns())
                if age_ns(latest.capture_monotonic_ns,latest.clock_domain,self.now_ns(),self.clock_domain)>300_000_000:
                    self.health.increment('depth_stale')
                    command=replace(command,linear_mps=0.,yaw_radps=0.,reason='depth_stale')
                # A geometric veto must reach the policy that selected this
                # exact target. Otherwise a held goal can be requested forever
                # while the guard correctly keeps both motion components zero.
                report_failure=getattr(self.navigator,'report_goal_failure',None)
                if (decision is not None and decision.goal_id and decision.path
                        and (decision.desired_linear_mps or decision.desired_yaw_radps)
                        and decision.map_revision==nav.revision==command.map_revision
                        and command.clock_domain==self.clock_domain==latest.clock_domain==nav.clock_domain
                        and command.source==latest.key
                        and command.source_capture_monotonic_ns==latest.capture_monotonic_ns
                        and command.linear_mps==command.yaw_radps==0.
                        and command.reason in {'bootstrap_blocked','footprint_not_observed','path_segment_blocked'}
                        and callable(report_failure)):
                    report_failure(decision.goal_id,nav.revision,goal_world_xy=decision.path[-1])
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
                    observe_result=getattr(self.navigator,'observe_navigation_result',None)
                    failure=(observe_result(nav,xy,self.now_ns(),display_reason,rejected)
                             if callable(observe_result) else None)
                    self._step_navigation_observed=callable(observe_result)
                    if failure is not None:
                        display_reason='goal_failed_no_progress:'+display_reason
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
                    if getattr(self,'local_depth_control',False):self._invalidate_local_intent()
        return UiCommandAck(command.request_uuid,'accepted' if reason is None else 'rejected',reason,self.now_ns(),self.clock_domain)

    def close(self,timeout_s:float)->dict:
        if getattr(self,'_previous_switch_interval',None) is not None:
            import sys as _sys
            _sys.setswitchinterval(self._previous_switch_interval);self._previous_switch_interval=None
        timeout_s=valid_timeout(timeout_s);deadline=time.monotonic()+timeout_s
        control_acquired=self._control_lock.acquire(timeout=remaining(deadline))
        with self._lock:self._closing=True;self._paused=True;self._deadline=deadline;self.scheduler.closed=True
        if getattr(self,'local_depth_control',False):self._invalidate_local_intent()
        if control_acquired:self._control_lock.release()
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
        clean=not pending_workers and not pending and not failed and self._room_failure is None
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
