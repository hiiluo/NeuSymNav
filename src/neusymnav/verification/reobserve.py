"""Episode-local bounded requests for additional committed object views.

The scheduler never drives the robot or changes verification/admission state.
All times are in the explicitly supplied monotonic clock domain.
"""
from __future__ import annotations
from collections import Counter, deque
from dataclasses import dataclass, replace, asdict
import math
from uuid import uuid4
import numpy as np

_ANY_NEW_SOURCE = object()


@dataclass(frozen=True)
class ReobserveRequest:
    id: str
    episode_id: str
    object_id: str
    object_revision: int
    evidence_revision: int
    reason: str
    created_ns: int
    expires_ns: int
    attempts: int
    max_attempts: int
    state: str
    cancel_reason: str | None
    target: tuple[float, float, float]
    baseline_event_refs: tuple
    activated_ns: int | None = None


class ReobserveScheduler:
    def __init__(self, episode_id, clock_domain, *, max_queue=32, max_attempts_per_object=3,
                 request_ttl_ns=30_000_000_000, attempt_timeout_ns=10_000_000_000,
                 max_time_fraction=.2, max_tracked_objects=256):
        if not isinstance(clock_domain,str) or not clock_domain: raise ValueError('invalid clock domain')
        if any(isinstance(x,bool) or not isinstance(x,int) or x<=0 for x in
               (max_queue,max_attempts_per_object,request_ttl_ns,attempt_timeout_ns,max_tracked_objects)):
            raise ValueError('positive integer limits required')
        if not math.isfinite(max_time_fraction) or not 0<max_time_fraction<=.2: raise ValueError('invalid time fraction')
        self.clock_domain=clock_domain; self.max_queue=max_queue; self.max_attempts_per_object=max_attempts_per_object
        self.request_ttl_ns=request_ttl_ns; self.attempt_timeout_ns=attempt_timeout_ns
        self.max_time_fraction=max_time_fraction; self.max_tracked_objects=max_tracked_objects
        self.reset(episode_id,0)

    def reset(self, episode_id, now_ns):
        if not isinstance(episode_id,str) or not episode_id: raise ValueError('invalid episode')
        self._valid_time(now_ns)
        self.episode_id=episode_id; self._start=now_ns; self._last=now_ns; self._spent=0
        self._queue={}; self._active=None; self._history=deque(maxlen=128); self._counts=Counter()
        self._groups={}; self._attempts={}; self._last_support={}; self._baseline=()
        self._latest_object_revision=-1; self._latest_evidence_revision=-1
        self._pending_baseline={}

    @staticmethod
    def _valid_time(now):
        if isinstance(now,bool) or not isinstance(now,int) or now<0: raise ValueError('invalid monotonic time')

    def _advance(self, now):
        self._valid_time(now)
        if now<self._last: raise ValueError('clock replay')
        if self._active:
            # Count the entire elapsed wall time, including gaps after a deadline.
            self._spent+=now-self._last
        self._last=now

    def _terminal(self, request, state, reason):
        request=replace(request,state=state,cancel_reason=reason)
        self._history.append(request); self._counts[reason]=min(2**63-1,self._counts[reason]+1)
        self._queue.pop(request.id,None)
        if self._active and self._active.id==request.id: self._active=None; self._baseline=()
        return request

    def tick(self, now_ns):
        self._advance(now_ns)
        for req in tuple(self._queue.values()):
            if now_ns>=req.expires_ns: self._terminal(req,'expired','request_deadline')
        if self._active:
            r=self._active
            if now_ns>=r.expires_ns: self._terminal(r,'expired','request_deadline')
            elif now_ns-r.activated_ns>=self.attempt_timeout_ns: self._terminal(r,'expired','attempt_deadline')
            elif self._spent>=self.max_time_fraction*(now_ns-self._start): self._terminal(r,'expired','time_budget')

    def queued(self): return tuple(self._queue.values())
    @property
    def active(self): return self._active

    def activate(self, request_id, now_ns):
        self.tick(now_ns)
        r=self._queue.get(request_id)
        if r is None or self._active is not None: return None
        if self._spent>=self.max_time_fraction*(now_ns-self._start): return None
        group=self._groups[r.object_id]; attempts=self._attempts[group]+1
        if attempts>self.max_attempts_per_object: self._terminal(r,'blocked','attempt_limit'); return None
        self._attempts[group]=attempts; self._queue.pop(request_id)
        self._active=replace(r,state='active',attempts=attempts,activated_ns=now_ns)
        self._baseline=self._pending_baseline.pop(request_id,())
        return self._active

    def finish(self, state, reason, now_ns):
        self.tick(now_ns)
        if state not in {'blocked','cancelled','expired'}: raise ValueError('invalid external terminal state')
        if not isinstance(reason,str) or not reason or len(reason)>128: raise ValueError('invalid reason')
        if self._active is None: return None
        # Keep bounded diagnostic vocabulary without accepting unlimited labels.
        if reason not in self._counts and len(self._counts)>=64:reason='external_'+state
        return self._terminal(self._active,state,reason)

    def remaining_time_ns(self, now_ns=None):
        now=self._last if now_ns is None else max(self._last,now_ns)
        spent=self._spent+(now-self._last if self._active is not None else 0)
        credit=int(self.max_time_fraction*(now-self._start))-spent
        if self._active is not None:
            credit=min(credit,self._active.expires_ns-now,
                       self._active.activated_ns+self.attempt_timeout_ns-now)
        return max(0,credit)

    def _group(self, oid):
        if oid not in self._groups:
            if len(self._groups)>=self.max_tracked_objects: return None
            self._groups[oid]=oid; self._attempts[oid]=0
        return self._groups[oid]

    def _merge(self, old, new):
        a=self._groups.get(old); b=self._groups.get(new)
        if a is None and b is None: return
        if a is None:
            if len(self._groups)<self.max_tracked_objects: self._groups[old]=b
            return
        if b is None:
            if len(self._groups)>=self.max_tracked_objects: return
            self._groups[new]=a; return
        if a!=b:
            self._attempts[b]=min(self.max_attempts_per_object,self._attempts[a]+self._attempts[b])
            del self._attempts[a]
            for key,value in self._groups.items():
                if value==a: self._groups[key]=b
            # Conservatively retain all support fingerprints from both identities.
            self._last_support[b]=self._last_support.get(a,frozenset()) | self._last_support.get(b,frozenset())
            self._last_support.pop(a,None)

    @staticmethod
    def _independent(a,b):
        if a.event_id==b.event_id or a.source==b.source: return False
        baseline=float(np.linalg.norm(a.camera_pose_world[:3,3]-b.camera_pose_world[:3,3]))
        angle=math.degrees(math.acos(float(np.clip(np.dot(a.view_direction,b.view_direction),-1,1))))
        return baseline>=.3 and angle>=15

    def update(self, summary, objects, now_ns, verification=None, admission=None, *, satisfaction_source=_ANY_NEW_SOURCE):
        self.tick(now_ns)
        if self.clock_domain.lower().startswith('replay:'):return
        if summary.episode_id!=self.episode_id or objects.episode_id!=self.episode_id:
            for r in (*self.queued(), *((self._active,) if self._active else ())): self._terminal(r,'cancelled','episode_changed')
            return
        if summary.object_revision!=objects.revision or objects.revision<self._latest_object_revision or summary.evidence_revision<self._latest_evidence_revision: return
        self._latest_object_revision=objects.revision; self._latest_evidence_revision=summary.evidence_revision
        for old,new in objects.aliases.items(): self._merge(old,objects.resolve_id(new))
        for r in (*self.queued(), *((self._active,) if self._active else ())):
            obj=objects.objects.get(r.object_id)
            if obj is None: self._terminal(r,'cancelled','identity_changed'); continue
            if obj.clock_domain!=self.clock_domain or obj.last_seen_ns>now_ns or now_ns-obj.last_seen_ns>30_000_000_000:
                self._terminal(r,'cancelled','source_stale'); continue
            if np.linalg.norm(obj.centroid-np.asarray(r.target))>.10: self._terminal(r,'cancelled','object_moved'); continue
            if r.state=='active':
                views=summary.views.get(r.object_id,())
                if any((satisfaction_source is _ANY_NEW_SOURCE or v.source==satisfaction_source)
                       and v.clock_domain==self.clock_domain and r.activated_ns<=v.capture_monotonic_ns<=now_ns
                       and v.depth_support>=.6 and all(self._independent(v,b) for b in self._baseline)
                       for v in views): self._terminal(r,'satisfied','new_independent_evidence')
        live={r.object_id for r in self.queued()}
        if self._active: live.add(self._active.object_id)
        for oid,obj in objects.objects.items():
            if oid in live or obj.lifecycle in {'verified','retired','merged'}: continue
            if obj.clock_domain!=self.clock_domain or obj.last_seen_ns>now_ns or now_ns-obj.last_seen_ns>30_000_000_000: continue
            if not np.isfinite(obj.centroid).all(): continue
            if admission is not None and admission.episode_id==self.episode_id and admission.object_revision==objects.revision:
                decision=admission.decisions.get(oid)
                if decision and decision.state=='admitted': continue
            record=None
            if verification is not None and verification.episode_id==self.episode_id and verification.object_revision==objects.revision:
                record=verification.objects.get(oid)
                if record and record.status=='verified': continue
            views=tuple(v for v in summary.views.get(oid,()) if v.episode_id==self.episode_id and v.object_id==oid
                and v.clock_domain==self.clock_domain and 0<=now_ns-v.capture_monotonic_ns<=30_000_000_000
                and v.object_revision<=objects.revision and v.depth_support>=.6)
            if not views: continue
            conflict=bool(record and (record.status=='conflict' or 'conflict' in record.reason))
            if len(views)>=3 and not conflict: continue
            group=self._group(oid)
            if group is None or self._attempts[group]>=self.max_attempts_per_object: continue
            support=frozenset((v.event_id,v.source) for v in views)
            if support.issubset(self._last_support.get(group,frozenset())): continue
            if len(self._queue)>=self.max_queue: break
            r=ReobserveRequest(str(uuid4()),self.episode_id,oid,objects.revision,summary.evidence_revision,
                'label_conflict' if conflict else 'insufficient_views',now_ns,now_ns+self.request_ttl_ns,
                self._attempts[group],self.max_attempts_per_object,'queued',None,tuple(float(x) for x in obj.centroid),
                tuple(sorted((v.event_id,v.source) for v in views)))
            self._queue[r.id]=r; self._pending_baseline[r.id]=views; self._last_support[group]=support
        # Baselines for removed requests must not accumulate.
        self._pending_baseline={k:v for k,v in self._pending_baseline.items() if k in self._queue}

    def status(self):
        def plain(r):
            d=asdict(r); d['baseline_event_refs']=[(e,asdict(s)) for e,s in r.baseline_event_refs]; return d
        return {'episode_id':self.episode_id,'queued':len(self._queue),'active':None if self._active is None else plain(self._active),
                'terminal_history':[plain(r) for r in self._history], 'reason_counts':dict(self._counts),
                'tracked_objects':len(self._groups),'active_time_ns':self._spent}
