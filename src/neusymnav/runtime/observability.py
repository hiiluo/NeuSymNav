"""Run-local observer wiring: telemetry never grants control or identity authority.

Producers do no I/O or quantile work. Final assembly runs after runtime shutdown;
partial support and sampled resources never auto-certify native acceptance.
"""
from __future__ import annotations
from dataclasses import asdict
import threading
import copy
from ..contracts import FrameKey
from .measurements import MeasurementSource,BoundedMeasurements
from .actuation_measurements import ActuationMeasurements,_source


class RunMeasurements:
    def __init__(self,context,*,sample_cap=65536,trace_byte_cap=64*1024**2,capture_cap=65536,proof_record_cap=4096):
        if type(proof_record_cap) is not int or not 1<=proof_record_cap<=20000:
            raise ValueError('proof_record_cap must be an integer in [1,20000]')
        self.context=context
        self.collector=BoundedMeasurements(context,sample_cap=sample_cap,trace_byte_cap=trace_byte_cap,capture_cap=capture_cap)
        self.actuation=ActuationMeasurements(context.episode_id,context.clock_domain,capacity=capture_cap)
        self.stop_requested=threading.Event();self._cap=None;self._errors=0
        self._graph=dict(live_detector_commits=0,live_object_evidence_commits=0,first_object_commit=None,first_accepted_region=None,first_assigned_membership=None)
        self._missing_actuation=0;self._final=None;self._closed=False
        self._proof_records=[];self._pose_records=[];self._proof_cap=min(capture_cap,proof_record_cap);self._proof_overflow=0
    def cap_breach(self,payload):
        # Sampler callback: one bounded payload, no runtime locks or disk work.
        if self._cap is None:self._cap=dict(payload)
        self.stop_requested.set()
    def _error(self):self._errors=min(self._errors+1,2**63-1)
    def _source(self,obs):
        s=_source(obs);k=s['key']
        return MeasurementSource(FrameKey(**k),s['capture_monotonic_ns'],s['clock_domain'],s['pose_version'],s['calibration_id'])
    def capture(self,obs):
        if self._closed:return False
        try:return self.collector.try_record_capture(self._source(obs),width=int(obs.depth_m.shape[1]),height=int(obs.depth_m.shape[0]))
        except Exception:self._error();return False
    def admission(self,obs,outcome):
        if self._closed:return False
        try:return self.collector.try_record_admission(self._source(obs),outcome=outcome)
        except Exception:self._error();return False
    def result(self,obs,now_ns,kind,*,origin='live',revision=None):
        if self._closed:return False
        try:return self.collector.try_record_result(self._source(obs),now_ns=now_ns,clock_domain=self.context.clock_domain,kind=kind,origin=origin,revision=revision)
        except Exception:self._error();return False
    def committed(self,obs,commit,*,origin,projected_count):
        if self._closed or origin!='live':return
        try:
            self._graph['live_detector_commits']=min(self._graph['live_detector_commits']+1,2**63-1)
            snapshot=commit.snapshot
            if obs.clock_domain!=self.context.clock_domain or snapshot.episode_id!=self.context.episode_id or snapshot.source!=obs.key:raise ValueError('commit measurement source mismatch')
            touched=[o for o in snapshot.objects.values() if o.revision==snapshot.revision]
            if projected_count and touched:
                self._graph['live_object_evidence_commits']=min(self._graph['live_object_evidence_commits']+1,2**63-1)
                if self._graph['first_object_commit'] is None:
                    self._graph['first_object_commit']=dict(source=asdict(obs.key),object_revision=snapshot.revision,object_ids=[o.object_id for o in touched],committed_event_count=len(commit.committed_event_ids))
        except Exception:self._error()
    def pose(self,obs,pose):
        if self._closed:return False
        try:
            valid=self.actuation.try_record_pose(obs,pose)
            if valid:
                if len(self._pose_records)>=self._proof_cap:
                    self._proof_overflow=min(self._proof_overflow+1,2**63-1);return False
                self._pose_records.append(dict(source=_source(obs),robot_xy=list(pose['robot_xy']),yaw_rad=pose['yaw_rad']))
            if not valid:self._error()
            return valid
        except Exception:self._error();return False
    def region(self,nav,regions):
        if self._closed:return False
        try:
            if regions.episode_id!=self.context.episode_id or nav.episode_id!=self.context.episode_id or nav.clock_domain!=self.context.clock_domain:raise ValueError('region source mismatch')
            if not regions.stale and regions.regions and regions.source_map_revision==nav.revision and self._graph['first_accepted_region'] is None:
                self._graph['first_accepted_region']=dict(source=asdict(nav.source),map_revision=nav.revision,region_revision=regions.revision,region_ids=sorted(regions.regions))
        except Exception:self._error()
    def publication(self,hierarchy):
        if self._closed:return False
        try:
            if hierarchy.episode_id!=self.context.episode_id:raise ValueError('hierarchy source mismatch')
            if self._graph['first_assigned_membership'] is None:
                for edge in hierarchy.edges:
                    if edge.kind=='in_region' and edge.status=='assigned':
                        self._graph['first_assigned_membership']=dict(object_id=edge.source_id,region_id=edge.target_id,object_revision=hierarchy.object_revision,map_revision=hierarchy.map_revision,region_revision=hierarchy.region_revision)
                        break
        except Exception:self._error()
    def control(self,obs,now_ns,result,*,command=None,decision=None,proof=None,profile):
        if self._closed:return False
        try:
            src=None if obs is None else self._source(obs)
            recorded=self.collector.try_record_control(src,now_ns=now_ns,clock_domain=self.context.clock_domain,reason=result.get('reason','unreported_control_result'),map_revision=0 if command is None else command.map_revision)
            if command is not None:
                if proof is None:self._missing_actuation=min(self._missing_actuation+1,2**63-1)
                else:
                    valid=self.actuation.try_record(command,obs,proof,goal_id=None if decision is None else decision.goal_id,decision_map_revision=command.map_revision if decision is None else decision.map_revision,profile=profile)
                    if not valid:self._error()
                    elif len(self._proof_records)>=self._proof_cap:self._proof_overflow=min(self._proof_overflow+1,2**63-1)
                    else:
                        goal=None if decision is None else decision.goal_id
                        if type(profile) is not str or len(profile)>128 or goal is not None and (type(goal) is not str or len(goal)>128):raise ValueError('bounded decision provenance required')
                        self._proof_records.append(dict(command=asdict(command),proof=copy.deepcopy(proof),decision=dict(goal_id=goal,map_revision=command.map_revision if decision is None else decision.map_revision,profile=profile)))
            return recorded
        except Exception:self._error();return False
    def finalize(self,*,runtime_report,resources,seed_ack=None,launch_config=None,outcome=None,cleanup=None):
        if self._final is not None:return copy.deepcopy(self._final)
        self._closed=True
        self.collector.stop();collector=self.collector.finalize();actuation=self.actuation.finalize()
        cleanup_clean=(cleanup is not None and all(type(certificate) is dict and certificate.get('clean_shutdown') is True for certificate in cleanup.values()))
        complete=(collector['complete'] and runtime_report.get('clean_shutdown') is True and cleanup_clean and resources is not None and resources['complete'] and not self.stop_requested.is_set() and not self._errors and not self._proof_overflow and not actuation['rejected_records'] and not actuation['overflow'])
        self._final=dict(schema_version=1,context=asdict(self.context),seed_ack=seed_ack,launch_config=launch_config,
            collector=collector,resources=resources,actuation=dict(actuation,missing_command_proofs=self._missing_actuation,proof_records=copy.deepcopy(self._proof_records),body_pose_records=copy.deepcopy(self._pose_records),record_cap=self._proof_cap,record_charge_bytes=16384,record_overflow=self._proof_overflow),graph_support=copy.deepcopy(self._graph),
            lifecycle=dict(runtime_clean_shutdown=runtime_report.get('clean_shutdown') is True,runtime_pending=runtime_report.get('pending'),launcher_cleanup_clean=cleanup_clean,launcher_cleanup_status=None if cleanup is None else {name:certificate.get('clean_shutdown') is True if type(certificate) is dict else False for name,certificate in cleanup.items()},outcome=outcome,resources_observed_phase='startup_active_worker_cleanup_before_final_export',resource_scope_limitation='sampled process tree; final artifact serialization/export occurs after sampler stop'),
            completion=dict(complete=bool(complete),cap_breached=self.stop_requested.is_set(),cap_breach=copy.deepcopy(self._cap),observer_errors=self._errors,export_byte_overflow=False),native_runtime_validated=False)
        return copy.deepcopy(self._final)
