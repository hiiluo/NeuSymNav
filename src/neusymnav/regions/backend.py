"""Single region owner: native candidate -> guard -> tracker -> publication."""
from __future__ import annotations
import threading
from copy import copy
import numpy as np
from ..contracts import NavSnapshot, RegionGrid, Region, RegionSnapshot
from .dude_client import DuDeWorkerClient,DuDeConfig
from .pipeline import RegionUpdateProcessor
from ._types import Polygon2D
from .geometry import intersection_area,valid_ring

class RegionBackend:
    def __init__(self,binary=None,*,floor_id: str,config:DuDeConfig|None=None,client=None,reset_on_geometry_change=False):
        if not isinstance(floor_id,str) or not floor_id:raise ValueError('floor_id required')
        if type(reset_on_geometry_change) is not bool:raise ValueError('reset_on_geometry_change must be bool')
        if client is not None and binary is not None:raise ValueError('supply binary or client')
        if client is None and binary is None:raise ValueError('explicit DuDe executable required')
        self.client=client if client is not None else DuDeWorkerClient(binary,config)
        self.floor_id=floor_id;self.processor=RegionUpdateProcessor();self._snapshot=None
        self.accepted_nav=None;self.inflight_nav=None;self.last_reason=None
        self._last_request=-1;self._episode=None;self._lock=threading.Lock()
        self._reset_on_geometry_change=reset_on_geometry_change;self._native_geometry=None
        self._stats=dict(requests=0,accepted_updates=0,rejected_updates=0,native_resets=0)
        self._reasons={}

    def diagnostics(self):
        with self._lock:return dict(self._stats,reason_counts=dict(self._reasons))

    def _begin(self,nav):
        if self._episode is not None and nav.episode_id!=self._episode:raise ValueError('new episode requires a new region owner')
        if nav.revision<=self._last_request:raise ValueError('region input revisions must increase')
        self._episode=nav.episode_id;self._last_request=nav.revision
        self._stats.update(requests=self._stats['requests']+1,last_input_revision=nav.revision,
            last_input_shape=list(nav.states.shape),last_input_origin=list(nav.origin_xy),
            last_input_resolution_m=nav.resolution_m,last_raw_region_count=None,
            last_native_status=None,last_native_branch=None,last_native_invoked=False)

    def mark_unavailable(self,nav,reason):
        """Reject incomplete input without mutating native state or canonical tracks."""
        if not isinstance(nav,NavSnapshot):raise ValueError('expected NavSnapshot')
        with self._lock:
            self._begin(nav)
            return self._stale(nav,reason)

    def _stale(self,nav,reason):
        self.last_reason=reason
        self._stats['rejected_updates']+=1
        key=str(reason)[:160]
        if key not in self._reasons and len(self._reasons)>=32:key='other'
        self._reasons[key]=self._reasons.get(key,0)+1
        self._stats['last_rejection_reason']=str(reason)[:160]
        old=self._snapshot
        if old is None:return RegionSnapshot(nav.episode_id,0,nav.revision,self.floor_id,{},True)
        return RegionSnapshot(old.episode_id,old.revision,old.source_map_revision,old.floor_id,old.regions,True)

    def update(self,nav:NavSnapshot)->RegionSnapshot:
        if not isinstance(nav,NavSnapshot):raise ValueError('expected NavSnapshot')
        with self._lock:
            self._begin(nav)
            if not np.any(nav.states==0):return self._stale(nav,'no_observed_free_support')
            self.inflight_nav=nav
            try:
                geometry=(nav.origin_xy,nav.resolution_m,nav.states.shape)
                if self._reset_on_geometry_change and self._native_geometry is not None and self._native_geometry!=geometry:
                    ack=self.client.reset()
                    if not isinstance(ack,dict) or ack.get('status')!='reset':raise ValueError('native geometry reset was not acknowledged')
                    self._stats['native_resets']+=1
                self._native_geometry=geometry
                self._stats['last_native_invoked']=True
                response,observations=self.client.integrate(RegionGrid.from_nav(nav),timestamp_s=nav.capture_monotonic_ns/1e9)
                self._stats.update(last_raw_region_count=len(observations),last_native_status=response['status'],last_native_branch=response.get('branch'),
                    last_kernel_invoked=response.get('diagnostics',{}).get('kernel_invoked'))
                if response['status']=='rejected':return self._stale(nav,response.get('rejection_reason','native_rejected'))
                # Validate all derived polygons before allowing tracker mutation.
                for o in observations:
                    if o.source_grid_revision!=nav.revision:raise ValueError('candidate revision mismatch')
                    if not valid_ring(o.polygon.outer):raise ValueError('region polygon must be simple and nonzero')
                    Region('validation',np.array(o.polygon.outer,float))
                trial=copy(self.processor)
                trial.guard=copy(self.processor.guard)
                trial.tracker=copy(self.processor.tracker)
                trial.tracker._tracks=[copy(t) for t in self.processor.tracker._tracks]
                result=trial.update(observations,free_cells=int(np.count_nonzero(nav.states==0)),unknown_cells=int(np.count_nonzero(nav.states==-1)),expected_cells=nav.states.size)
                if not result.accepted:return self._stale(nav,result.reason)
                old={} if self._snapshot is None else self._snapshot.regions
                def name(i):return f'region:{self.floor_id}:{i}'
                current={}
                for r in result.current_regions:
                    predecessors=tuple(sorted(key for key,p in old.items() if intersection_area(r.polygon,Polygon2D(tuple(map(tuple,p.polygon))))>1e-10))
                    key=name(r.persistent_id)
                    current[key]=Region(key,np.array(r.polygon.outer,float),predecessors,tuple(name(i) for i in r.adjacent_region_ids))
                snapshot=RegionSnapshot(nav.episode_id,1 if self._snapshot is None else self._snapshot.revision+1,nav.revision,self.floor_id,current,False)
                self.processor=trial;self._snapshot=snapshot;self.accepted_nav=nav;self.last_reason=None
                self._stats['accepted_updates']+=1;self._stats['last_rejection_reason']=None
                return snapshot
            except (ValueError,OSError,RuntimeError) as exc:
                return self._stale(nav,str(exc))
            finally:self.inflight_nav=None

    def close(self):self.client.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
