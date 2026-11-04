"""Opt-in arbitration; no model, ledger, sensor or actuator calls on this seam."""
from dataclasses import dataclass
import math
from threading import Thread

from ..contracts import age_ns
from ..navigation.viewpoints import ViewpointPlanner
from ..verification.reobserve import ReobserveScheduler


@dataclass(frozen=True)
class EvidenceInput:
    summary: object
    objects: object
    verification: object = None
    committed_source: object = None


class ActivePerception:
    def __init__(self, episode_id, clock_domain, mode, *, strategy='candidate'):
        if mode not in {'shadow','active'} or strategy not in {'candidate','scheduled'}:
            raise ValueError('invalid active perception mode/strategy')
        if not clock_domain.startswith('host_monotonic:'):
            raise ValueError('active perception requires live clock')
        self.mode=mode
        self.strategy=strategy
        self.scheduler=ReobserveScheduler(episode_id,clock_domain)
        self._started=False
        self.camera=None
        self.planner=None
        self.target=None
        self.capture_source=None
        self.arrived_ns=None
        self.next_plan_ns=0
        self.reason='awaiting_evidence'
        self.last_map_revision=None
        self.object_revision=None
        self.memory_status=None
        self._best_distance=None
        self._progress_ns=None
        self._proposal_thread=None
        self._proposal_result=None

    def _launch_proposal(self, token, planner, nav, xy, target, views, now_ns):
        def work():
            try:
                result=planner.plan(nav,xy,target,views,now_ns=now_ns,clock_domain=self.scheduler.clock_domain)
            except Exception:
                result=None
            self._proposal_result=(token,result)
        self._proposal_thread=Thread(target=work,name='reobserve-proposal',daemon=True)
        self._proposal_thread.start()

    def close(self, timeout_s):
        thread=self._proposal_thread
        if thread is not None:thread.join(timeout_s)
        return thread is None or not thread.is_alive()

    def _clear(self):
        self.target=None
        self.capture_source=None
        self.arrived_ns=None
        self._best_distance=None
        self._progress_ns=None

    def interrupt(self, now_ns, reason):
        self.scheduler.finish('cancelled',reason,now_ns)
        self.reason=reason
        self._clear()

    def step(self,navigator,nav,xy,yaw,now_ns,evidence,admission=None,capture_result=None):
        self.last_map_revision=nav.revision
        if not self._started:
            self.scheduler.reset(nav.episode_id,now_ns)
            self._started=True
        elif self.scheduler.episode_id!=nav.episode_id:
            self.scheduler.reset(nav.episode_id,now_ns)
            self._clear()
            self.next_plan_ns=0
        try:
            fresh=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,self.scheduler.clock_domain)<=navigator.max_nav_age_ns
        except ValueError:
            fresh=False
        if not fresh:
            self.interrupt(now_ns,'stale_navigation')
            return None
        self.scheduler.tick(now_ns)
        if evidence is None or self.camera is None:
            self.interrupt(now_ns,'missing_evidence_or_camera')
            return None
        self.object_revision=evidence.objects.revision
        self.memory_status=dict(policy_version=evidence.summary.policy_version,
            object_revision=evidence.summary.object_revision,evidence_revision=evidence.summary.evidence_revision,
            object_count=len(evidence.summary.views), view_count=sum(map(len,evidence.summary.views.values())),
            charged_bytes=evidence.summary.charged_bytes)
        acknowledged=(self.capture_source is not None and
                      (capture_result is not None and capture_result[0]==self.capture_source
                       or self.capture_source==evidence.committed_source))
        allowed_source=self.capture_source if acknowledged and (
            capture_result is None or capture_result[0]!=self.capture_source or capture_result[1]) else None
        self.scheduler.update(evidence.summary,evidence.objects,now_ns,evidence.verification,admission,
                              satisfaction_source=allowed_source)
        if acknowledged:
            self.capture_source=None
            self.reason='capture_committed' if self.scheduler.active is None else 'capture_no_independent_view'
        if self.scheduler.active is None:
            self._clear()
            queued=self.scheduler.queued()
            if not queued:
                self.reason='no_eligible_request'
                return None
            req=queued[0]
            if self.mode=='active' and self.scheduler.remaining_time_ns(now_ns)<300_000_000:
                self.reason='waiting_for_budget'
                return None
            token=(req.id,self.camera)
            result=self._proposal_result
            if result is None or result[0]!=token:
                if now_ns>=self.next_plan_ns and (self._proposal_thread is None or not self._proposal_thread.is_alive()):
                    self.next_plan_ns=now_ns+500_000_000
                    if self.planner is None:self.planner=ViewpointPlanner(navigator.robot,self.camera)
                    self._proposal_result=None
                    self._launch_proposal(token,self.planner,nav,xy,req.target,
                                          evidence.summary.views.get(req.object_id,()),now_ns)
                return None
            self._proposal_result=None
            proposal=result[1]
            if proposal is None:
                self.reason='proposal_error'
                return None
            self.reason=proposal.reason
            if self.mode=='shadow':
                self.shadow_target=req.object_id
                self.shadow_viewpoints=len(proposal.candidates)
                return None
            if self.scheduler.activate(req.id,now_ns) is None:
                self.reason='waiting_for_budget'
                return None
            if not proposal.candidates:
                self.scheduler.finish('blocked',proposal.reason,now_ns)
                return None
            if self.strategy=='scheduled':
                self.target=min(proposal.candidates,key=lambda c:(c.path.cost_m,c.world_xy))
            else:self.target=proposal.candidates[0]
            self._best_distance=math.dist(xy,self.target.world_xy)
            self._progress_ns=now_ns
            navigator.controller.reset()
        req=self.scheduler.active
        if req is None or self.target is None:return None
        # Reserve an entire command horizon before selecting reobserve motion.
        if self.scheduler.remaining_time_ns(now_ns)<300_000_000:
            self.scheduler.finish('expired','time_budget',now_ns)
            self._clear()
            self.reason='time_budget'
            return None
        if not self.planner.visible(nav,self.target.world_xy,self.target.yaw_rad,req.target):
            self.scheduler.finish('blocked','viewpoint_not_visible',now_ns)
            self._clear()
            self.reason='viewpoint_not_visible'
            return None
        distance=math.dist(xy,self.target.world_xy)
        if distance<self._best_distance-.03:
            self._best_distance=distance
            self._progress_ns=now_ns
        elif distance>.05 and now_ns-self._progress_ns>=5_000_000_000:
            self.scheduler.finish('blocked','no_progress',now_ns)
            self._clear()
            self.reason='no_progress'
            return None
        decision=navigator.track_viewpoint(nav,xy,yaw,now_ns,'reobserve:'+req.id,
                                           self.target.world_xy,self.target.yaw_rad)
        self.reason=decision.reason
        if decision.reason=='reobserve_capture_ready' and self.arrived_ns is None:
            self.arrived_ns=now_ns
        elif decision.reason!='reobserve_capture_ready':
            self.arrived_ns=None
            self.capture_source=None
        return decision

    def tag_capture(self, primary, xy, yaw):
        """Use the existing primary cadence; no extra sensor request."""
        req=self.scheduler.active
        if (self.mode!='active' or req is None or self.target is None
                or self.arrived_ns is None or self.capture_source is not None
                or primary.clock_domain!=self.scheduler.clock_domain
                or primary.key.episode_id!=req.episode_id
                or not self.arrived_ns<=primary.capture_monotonic_ns<req.expires_ns
                or self.scheduler.remaining_time_ns(primary.capture_monotonic_ns)<=0
                or math.dist(xy,self.target.world_xy)>.05
                or abs(math.remainder(yaw-self.target.yaw_rad,2*math.pi))>math.radians(6)):
            return False
        self.capture_source=primary.key
        self.reason='capture_offered'
        return True

    def outcome(self,decision,reason,rejected,now_ns):
        if decision.reason=='reobserve_capture_ready' and reason=='reobserve_capture_ready':
            return
        if rejected:
            self.scheduler.finish('blocked','motion_guard_or_actuator_veto',now_ns)
            self.reason=reason
            self._clear()

    def status(self):
        state=self.scheduler.status()
        return dict(state,mode=self.mode,strategy=self.strategy,reason=self.reason,
                    object_revision=self.object_revision,map_revision=self.last_map_revision,
                    target_xy=None if self.target is None else self.target.world_xy,
                    shadow_target=getattr(self,'shadow_target',None),
                    shadow_viewpoints=getattr(self,'shadow_viewpoints',0),
                    capture_frame=None if self.capture_source is None else self.capture_source.frame_index,
                    remaining_time_ns=self.scheduler.remaining_time_ns(),memory=self.memory_status)
