"""Latest measured-depth safety after planning; no graph/model worker calls."""
from __future__ import annotations
import math
from collections import OrderedDict
from itertools import islice
import numpy as np
from ..contracts import MotionCommand, age_ns, GridState
from ..mapping.occupancy import capsule_cells


class MotionGuard:
    def __init__(self, mapper, *, clock_domain: str, max_depth_age_ns=300_000_000,
                 command_horizon_ns=100_000_000, bootstrap_corridor_m=.1):
        if not clock_domain.startswith('host_monotonic:'):raise ValueError('guard requires pinned live host domain')
        if not 0<max_depth_age_ns<=300_000_000:raise ValueError('depth TTL cannot exceed 300 ms')
        if command_horizon_ns<=0 or not math.isfinite(bootstrap_corridor_m) or bootstrap_corridor_m<=0:
            raise ValueError('invalid guard motion horizon')
        self.mapper=mapper;self.clock_domain=clock_domain;self.max_depth_age_ns=max_depth_age_ns
        self.command_horizon_ns=command_horizon_ns;self.bootstrap_corridor_m=bootstrap_corridor_m
        self._bound=None;self._watermarks={}
        # Geometry only: no map state, floor support, clearance or verdict.
        # Immutable cell tuples are capped at 64 entries of at most 512 cells.
        self._geometry_cache=OrderedDict()

    def bind_nav(self, nav, *, robot_xy, yaw_rad):
        if nav.robot_geometry_id!=self.mapper.robot.geometry_id:raise ValueError('robot geometry mismatch')
        if nav.floor_z_m!=self.mapper.floor_z_m or nav.calibration_hash!=self.mapper.calibration_hash:
            raise ValueError('floor datum mismatch')
        if len(robot_xy)!=2 or not all(math.isfinite(v) for v in (*robot_xy,yaw_rad)):raise ValueError('invalid robot pose')
        if self._bound is not None and nav.episode_id!=self._bound[0].episode_id:self._watermarks.clear()
        self._bound=(nav,tuple(robot_xy),yaw_rad)

    def _stop(self, decision, latest, now_ns, reason):
        # Future/cross-domain rejected input cannot be the timestamp evidence of
        # a command. Use an already accepted live map source, never alter capture.
        if self._bound is not None and self._bound[0].clock_domain==self.clock_domain and self._bound[0].capture_monotonic_ns<=now_ns:
            nav=self._bound[0];source,capture=nav.source,nav.capture_monotonic_ns
        else:raise ValueError('no valid live source for stopped command; actuator must remain stopped')
        return MotionCommand(source,nav.revision,now_ns,now_ns,self.clock_domain,0.,0.,reason,capture)

    def filter(self, decision, latest, now_ns) -> MotionCommand:
        stop=lambda reason:self._stop(decision,latest,now_ns,reason)
        if latest.clock_domain!=self.clock_domain:return stop('clock_domain_mismatch')
        try: age=age_ns(latest.capture_monotonic_ns,latest.clock_domain,now_ns,self.clock_domain)
        except ValueError:return stop('depth_future')
        if age>self.max_depth_age_ns:return stop('depth_stale')
        if self._bound is None:return stop('nav_unavailable')
        nav,robot_xy,yaw=self._bound
        if latest.key.episode_id!=nav.episode_id:return stop('episode_mismatch')
        if nav.clock_domain!=self.clock_domain:return stop('clock_domain_mismatch')
        try:nav_age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,self.clock_domain)
        except ValueError:return stop('nav_future')
        if nav_age>self.max_depth_age_ns:return stop('nav_stale')
        if decision.map_revision!=nav.revision:return stop('path_map_revision_stale')
        sensor=(latest.key.episode_id,latest.key.sensor_id)
        watermark=self._watermarks.get(sensor)
        if latest.key.sensor_id==nav.source.sensor_id and latest.key.frame_index<nav.source.frame_index:
            return stop('sensor_replay')
        if watermark is not None and (latest.key.frame_index<=watermark[0] or latest.capture_monotonic_ns<watermark[1]):
            return stop('sensor_replay')
        self._watermarks[sensor]=(latest.key.frame_index,latest.capture_monotonic_ns)
        if decision.desired_linear_mps<0:return stop('reverse_motion_unsupported')
        if decision.desired_linear_mps==0 and decision.desired_yaw_radps==0:return stop(decision.reason)
        if abs(decision.desired_linear_mps)>.2 or abs(decision.desired_yaw_radps)>math.radians(30.):return stop('motion_limits_exceeded')
        duration=self.command_horizon_ns/1e9
        distance=max(self.bootstrap_corridor_m,decision.desired_linear_mps*duration)
        # Constant v,w differs from its initial tangent by at most
        # integral_0^t |v*w|s ds. Inflating the capsule by this bound contains
        # the complete curved pulse, including simultaneous translation/yaw.
        swept_margin=.5*abs(decision.desired_linear_mps*decision.desired_yaw_radps)*duration**2
        result=self.mapper.bootstrap(latest,robot_xy=robot_xy,yaw_rad=yaw,
            corridor_m=distance if decision.desired_linear_mps else 0.,swept_margin_m=swept_margin)
        if not result.ready:return stop(result.reason)
        # Verify the actual swept forward pulse, independent of desired bearing.
        end=(robot_xy[0]+decision.desired_linear_mps*duration*math.cos(yaw),
             robot_xy[1]+decision.desired_linear_mps*duration*math.sin(yaw))
        if not self._clear(nav,robot_xy,end,swept_margin_m=swept_margin):return stop('footprint_not_observed')
        if decision.desired_linear_mps and not decision.path:return stop('no_valid_path')
        if decision.desired_linear_mps:
            # Intent path also needs observed support; don't trust caller claims.
            points=(robot_xy,)+tuple(decision.path)
            if any(not self._clear(nav,a,b) for a,b in zip(points,points[1:])):return stop('path_segment_blocked')
        deadline=min(latest.capture_monotonic_ns+self.max_depth_age_ns,
                     nav.capture_monotonic_ns+self.max_depth_age_ns,now_ns+self.command_horizon_ns)
        if now_ns>=deadline:return stop('depth_stale')
        return MotionCommand(latest.key,nav.revision,now_ns,deadline,self.clock_domain,
            decision.desired_linear_mps,decision.desired_yaw_radps,decision.reason,latest.capture_monotonic_ns)

    def _clear(self,nav,start,end,*,swept_margin_m=0.):
        radius=self.mapper.robot.radius_m+self.mapper.robot.margin_m+swept_margin_m
        key=(tuple(nav.origin_xy),nav.resolution_m,tuple(start),tuple(end),radius)
        # Optional reuse is initialized independently of map binding.
        cache=getattr(self,'_geometry_cache',None)
        if cache is None:cache=self._geometry_cache=OrderedDict()
        cached=cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            return self._cells_clear(nav,cached)
        cells=iter(capsule_cells(nav.origin_xy,nav.resolution_m,start,end,radius))
        first=tuple(islice(cells,512));batch=first;small=True
        while batch:
            if not self._cells_clear(nav,batch):return False
            batch=tuple(islice(cells,512))
            if batch:small=False;first=()
        if small:
            if len(cache)>=64:cache.popitem(last=False)
            cache[key]=first
        return True

    def _cells_clear(self,nav,cells):
        if not cells:return True
        # capsule_cells yields Python integer indices, including indices outside
        # native integer range for extreme public geometry calls. Those cannot
        # index an ndarray and must fail before any array access.
        try:indices=np.asarray(cells,dtype=np.intp)
        except OverflowError:return False
        rows,cols=indices.T
        if not np.all((rows>=0)&(rows<nav.states.shape[0])&(cols>=0)&(cols<nav.states.shape[1])):
            return False
        if not np.all(nav.states[rows,cols]==GridState.FREE):return False
        if not np.all(nav.floor_support[rows,cols]):return False
        height=self.mapper.robot.height_m
        # Scalar float32 >= Python float promotes to float64, whereas ndarray
        # comparison may round the threshold down to float32. Preserve the old
        # scalar predicate, including higher precision clearance arrays.
        clearance=nav.clearance[rows,cols]
        dtype=np.result_type(clearance.dtype,type(height))
        return bool(np.all(clearance.astype(dtype,copy=False)>=height))
