"""Bounded primary RGB-D queue; adapted from 3DSG keyframe_scheduler.

Only reservations may be replaced. Once fsynced, an accepted keyframe remains
recoverable until graph + verification ACK. The recorder shares this queue's
byte budget, rather than hiding another full image queue behind it.
"""
from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
import math

PROTECTED = frozenset({'first_view', 'doorway', 'new_region', 'frontier_viewpoint'})


def payload_bound(obs):
    """O(array count) upper bound for schema1 base64 source + journal metadata."""
    size = sum(getattr(obs, n).nbytes for n in
               ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera', 'no_return', 'far_plane')
               if getattr(obs, n) is not None)
    chars = sum(len(v) for v in (obs.key.episode_id, obs.key.sensor_id,
                               obs.calibration_id, obs.clock_domain))
    return 2 * size + 16384 + 36 * chars


@dataclass
class Entry:
    observation: object
    payload_bytes: int
    novelty: float
    protected_reason: str | None = None
    state: str = 'reserved'
    ref: str | None = None

    @property
    def index(self): return self.observation.key.frame_index
    @property
    def protected(self): return self.protected_reason is not None


class KeyframeScheduler:
    def __init__(self, *, byte_cap=32 * 1024**2, max_pending=2, max_protected_pending=1):
        if type(byte_cap) is not int or not 0 < byte_cap <= 32 * 1024**2:
            raise ValueError('payload cap must be <=32 MiB')
        if type(max_pending) is not int or not 1 <= max_pending <= 2:
            raise ValueError('pending cap must be <=2')
        if type(max_protected_pending) is not int or not 0 <= max_protected_pending <= 1:
            raise ValueError('protected pending cap must be <=1')
        self.byte_cap=byte_cap; self.max_pending=max_pending; self.max_protected=max_protected_pending
        self.pending=[]; self.inflight=None; self.watermark=-1; self.closed=False; self.failed=None
        self.lock=RLock(); self.counts=dict(offered=0,reserved=0,rejected=0,replaced=0,accepted=0,processed=0)
        self.peak_bytes=0; self.peak_pending=0

    def offer(self, entry):
        if not isinstance(entry,Entry) or not math.isfinite(entry.novelty) or entry.novelty<0:
            raise ValueError('invalid keyframe reservation')
        if type(entry.payload_bytes) is not int or entry.payload_bytes<=0:
            raise ValueError('payload bytes must be a positive integer')
        if entry.protected_reason is not None and entry.protected_reason not in PROTECTED:
            raise ValueError('unknown protected reason')
        with self.lock:
            self.counts['offered']+=1
            if self.closed or self.failed or getattr(self,'dispatch_pending',False) or entry.index<=self.watermark:
                return self._reject('closed_failed_or_watermark')
            if any(p.index==entry.index for p in self.pending) or self.inflight and self.inflight.index==entry.index:
                return self._reject('duplicate')
            pending=list(self.pending); replaced=[]
            same=[p for p in pending if p.protected==entry.protected]
            limit=self.max_protected if entry.protected else self.max_pending
            if entry.protected and len(same)>=limit or not entry.protected and same:
                candidates=[p for p in same if p.state=='reserved']
                if not candidates: return self._reject('durable_or_recording_pending')
                victim=min(candidates,key=lambda p:(p.novelty,-p.index if entry.protected else p.index))
                if entry.novelty<=victim.novelty:return self._reject('pending_has_higher_novelty')
                pending.remove(victim);replaced.append(victim)
            if entry.protected and not self.max_protected:return self._reject('protected_disabled')
            if len(pending)>=self.max_pending:return self._reject('pending_queue_full')
            total=(self.inflight.payload_bytes if self.inflight else 0)+sum(p.payload_bytes for p in pending)+entry.payload_bytes
            if total>self.byte_cap:return self._reject('payload_byte_cap')
            pending.append(entry);pending.sort(key=lambda p:p.index);self.pending=pending
            self.counts['reserved']+=1;self.counts['replaced']+=len(replaced)
            self.peak_bytes=max(self.peak_bytes,total);self.peak_pending=max(self.peak_pending,len(pending))
            return True,tuple(replaced),'reserved'

    def _reject(self,reason):
        self.counts['rejected']+=1;return False,(),reason

    def semantic_busy(self):
        """Authoritative idle-lane selection check, with no work or I/O wait.

        Pipeline serializes producers around this check and the later offer.
        Workers can only advance existing entries, so an empty lane cannot
        become busy until that sole producer offers its selected capture.
        """
        with self.lock:
            return bool(self.pending or self.inflight is not None or getattr(self,'dispatch_pending',False))

    def next_to_record(self):
        with self.lock:
            if self.failed:return None
            for p in self.pending:
                if p.state=='reserved':p.state='recording';return p
            return None

    def accepted(self,entry,ref):
        with self.lock:
            entry.state='durable';entry.ref=ref;self.counts['accepted']+=1

    def take_next(self, persist_watermark):
        with self.lock:
            if self.failed or self.inflight or not self.pending or self.pending[0].state!='durable':return None
            entry=self.pending[0]
            self.pending.pop(0);self.inflight=entry;self.dispatch_pending=True
        # No lock held during fsync: submit must never wait for disk IO.
        persist_watermark(entry.index)
        with self.lock:
            self.watermark=entry.index;self.dispatch_pending=False
        return entry

    def complete(self,entry):
        with self.lock:
            if self.inflight is not entry:raise RuntimeError('lease mismatch')
            self.inflight=None;self.counts['processed']+=1

    def snapshot(self):
        with self.lock:
            return dict(pending=len(self.pending), protected_pending=sum(p.protected for p in self.pending),
                        byte_cap=self.byte_cap,max_pending=self.max_pending,max_protected_pending=self.max_protected,
                        inflight=int(self.inflight is not None),payload_bytes=sum(p.payload_bytes for p in self.pending)+(self.inflight.payload_bytes if self.inflight else 0),
                        peak_bytes=self.peak_bytes,peak_pending=self.peak_pending,watermark=self.watermark,
                        counts=dict(self.counts),failure=self.failed)


class KeyframePolicy:
    """3DSG translation/yaw novelty, without its unbounded frontier ID set."""
    def __init__(self,min_translation_m=.25,min_yaw_rad=math.radians(20)):
        self.distance=min_translation_m;self.angle=min_yaw_rad;self.last=None;self.previous_yaw=None;self.rotation=0.
        if min_translation_m<=0 or min_yaw_rad<=0:raise ValueError('positive novelty thresholds required')

    def propose(self,obs):
        pose=obs.T_world_camera;xy=(float(pose[0,3]),float(pose[1,3]));yaw=math.atan2(pose[1,2],pose[0,2])
        if self.previous_yaw is not None:self.rotation+=abs((yaw-self.previous_yaw+math.pi)%math.tau-math.pi)
        self.previous_yaw=yaw
        if self.last is None:return True,'first_view',1.
        distance=math.hypot(xy[0]-self.last[0],xy[1]-self.last[1])
        if distance<self.distance and self.rotation<self.angle:return False,None,0.
        return True,None,max(.01,distance+.25*self.rotation)

    def commit(self,obs):
        self.last=tuple(obs.T_world_camera[:2,3]);self.rotation=0.
