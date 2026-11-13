"""Latest measured-depth safety after planning; no graph/model worker calls."""
from __future__ import annotations
import math
from collections import OrderedDict
from itertools import islice
import numpy as np
from ..contracts import MotionCommand, age_ns, GridState
from ..mapping.occupancy import capsule_cells


ESCAPE_REASONS=frozenset({'escape_rotate','escape_step'})
ESCAPE_STEP_M=.05
ESCAPE_MAX_SPEED_MPS=.15
ESCAPE_MIN_GAIN_M=.005
ESCAPE_WINDOW_M=.75


def blocked_cells(nav,height_m):
    """Cells a body may not overlap: not FREE, no floor support, or too low clearance."""
    clearance=np.asarray(nav.clearance)
    dtype=np.result_type(clearance.dtype,type(height_m))
    return ((np.asarray(nav.states)!=GridState.FREE)|~np.asarray(nav.floor_support,dtype=bool)
            |(clearance.astype(dtype,copy=False)<height_m))


def free_distance(nav,point,height_m,window_m=ESCAPE_WINDOW_M):
    """Distance from a point to the nearest blocked cell centre (capped at window_m)."""
    res=float(nav.resolution_m);ox,oy=nav.origin_xy
    rows,cols=nav.states.shape
    c0=max(0,int((point[0]-window_m-ox)/res));c1=min(cols,int((point[0]+window_m-ox)/res)+1)
    r0=max(0,int((point[1]-window_m-oy)/res));r1=min(rows,int((point[1]+window_m-oy)/res)+1)
    if c0>=c1 or r0>=r1:return 0.
    blocked=blocked_cells(nav,height_m)[r0:r1,c0:c1]
    rr,cc=np.nonzero(blocked)
    if not len(rr):return window_m
    d=np.hypot(ox+(cc+c0+.5)*res-point[0],oy+(rr+r0+.5)*res-point[1])
    return float(min(window_m,d.min()))


class MotionGuard:
    def __init__(self, mapper, *, clock_domain: str, max_depth_age_ns=300_000_000,
                 command_horizon_ns=100_000_000, now_ns=None,
                 offline_replay=False, rotation_horizon_ns=None, pace_to_wall_time=False,
                 start_unknown_tolerance=0., escape=False, column_fallback_cells=0):
        if type(offline_replay) is not bool or (offline_replay and not clock_domain.startswith('replay:')):
            raise ValueError('offline guard mode requires an isolated replay clock')
        from .clock_domains import is_live, is_simulated
        if not (clock_domain.startswith('replay:') if offline_replay else is_live(clock_domain)):
            raise ValueError('guard requires pinned live host domain')
        if not 0<max_depth_age_ns<=300_000_000:raise ValueError('depth TTL cannot exceed 300 ms')
        if command_horizon_ns<=0:
            raise ValueError('invalid guard motion horizon')
        # Opt-in: in-place yaw of the cylindrical footprint sweeps no new
        # cells, so a pure-rotation pulse may outlive the depth TTL (it must
        # still be ISSUED on fresh depth with the current footprint observed
        # clear). None keeps rotation under the translation rules.
        if rotation_horizon_ns is not None and (type(rotation_horizon_ns) is not int
                or not 100_000_000<=rotation_horizon_ns<=500_000_000):
            raise ValueError('invalid guard rotation horizon')
        if type(pace_to_wall_time) is not bool:raise ValueError('pace_to_wall_time must be boolean')
        if pace_to_wall_time and is_simulated(clock_domain):
            raise ValueError('wall-time pacing is undefined in a simulated clock domain')
        self.mapper=mapper;self.clock_domain=clock_domain;self.max_depth_age_ns=max_depth_age_ns
        self.command_horizon_ns=command_horizon_ns;self.rotation_horizon_ns=rotation_horizon_ns
        # Opt-in real-time pacing: a pulse longer than 100 ms is never longer
        # than the wall time since the previous issued motion command, so the
        # robot never moves faster than commanded when the loop is slow.
        self.pace_to_wall_time=pace_to_wall_time
        self._last_issued_ns=None
        # Opt-in: UNKNOWN cells inside the robot's own current footprint (no
        # OCCUPIED cell, at most this fraction) count as FREE for the start
        # disc only; see navigation/start_footprint.py.
        from .start_footprint import validate_tolerance
        self.start_unknown_tolerance=validate_tolerance(start_unknown_tolerance)
        self.start_unknown_tolerated=0
        # Opt-in escape (approved 12/11/2026, ObjectNav lockstep runs): when the
        # robot's centre is inside the safety margin of an obstacle, the normal
        # checks refuse every command forever. Commands whose reason is
        # 'escape_rotate' / 'escape_step' are then checked against the BODY
        # radius (no margin): in-place rotation needs the body disc observed
        # free; a step is at most ESCAPE_STEP_M long and must end farther from
        # every non-free cell than it starts. All other commands are unchanged.
        if type(escape) is not bool:raise ValueError('escape must be boolean')
        self.escape=escape
        self.escape_issued=0
        # Opt-in body-column fallback (approved 12/11/2026, ObjectNav lockstep
        # runs): in the fresh-frame bootstrap, up to this many footprint cells
        # whose floor was measured, planar cell voted free and body column
        # free of any return - but with some body height bins unreached by any
        # ray (occluded from above the robot) - may use the ACCUMULATED map's
        # FREE verdict for those bins. See NavMapper._column_fallback. 0 = off.
        from ..mapping.occupancy import MAX_COLUMN_FALLBACK_CELLS
        if type(column_fallback_cells) is not int or not 0<=column_fallback_cells<=MAX_COLUMN_FALLBACK_CELLS:
            raise ValueError('column_fallback_cells must be an int in [0, %d]'%MAX_COLUMN_FALLBACK_CELLS)
        self.column_fallback_cells=column_fallback_cells
        self.column_fallback_used=0
        self._raw_nav=None
        if now_ns is not None and not callable(now_ns):raise ValueError('issue clock must be callable')
        self._now_ns=now_ns
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
        self._raw_nav=nav                       # never the tolerated copy (column fallback)
        if self.start_unknown_tolerance:
            # Same disc as the planner and local follower (shared helper).
            from .start_footprint import tolerate_robot_footprint
            nav,_cleared=tolerate_robot_footprint(nav,robot_xy,self.mapper.robot,self.start_unknown_tolerance)
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
        if decision.reason in ESCAPE_REASONS:
            if not self.escape:return stop('escape_disabled')
            return self._escape(decision,latest,now_ns,nav,robot_xy,yaw,age,nav_age)
        if decision.desired_linear_mps==0 and decision.desired_yaw_radps==0:return stop(decision.reason)
        if abs(decision.desired_linear_mps)>.2 or abs(decision.desired_yaw_radps)>math.radians(30.):return stop('motion_limits_exceeded')
        # Bound geometry checks by the longest pulse that can still be issued
        # before either source expires. The issue time is read again after all
        # checks, so this is an upper bound on the eventual swept distance.
        rotation_only=decision.desired_linear_mps==0 and self.rotation_horizon_ns is not None
        if not self.pace_to_wall_time:elapsed_ns=max(self.command_horizon_ns,self.rotation_horizon_ns or 0)
        elif self._last_issued_ns is None or now_ns<self._last_issued_ns:elapsed_ns=100_000_000
        else:elapsed_ns=max(100_000_000,now_ns-self._last_issued_ns)
        if rotation_only:
            duration_ns=min(self.rotation_horizon_ns,elapsed_ns)
        else:
            duration_ns=min(self.command_horizon_ns,elapsed_ns,
                            self.max_depth_age_ns-age,
                            self.max_depth_age_ns-nav_age)
        if duration_ns<=0:return stop('depth_stale')
        duration=duration_ns/1e9
        distance=decision.desired_linear_mps*duration
        # Constant v,w differs from its initial tangent by at most
        # integral_0^t |v*w|s ds. Inflating the capsule by this bound contains
        # the complete curved pulse, including simultaneous translation/yaw.
        swept_margin=.5*abs(decision.desired_linear_mps*decision.desired_yaw_radps)*duration**2
        result=self.mapper.bootstrap(latest,robot_xy=robot_xy,yaw_rad=yaw,
            corridor_m=distance if decision.desired_linear_mps else 0.,swept_margin_m=swept_margin,
            **({'start_unknown_fraction':self.start_unknown_tolerance} if self.start_unknown_tolerance else {}),
            **self._fallback_args())
        if self.start_unknown_tolerance and getattr(result,'start_tolerated',0):self.start_unknown_tolerated+=1
        if getattr(result,'column_fallback',0):self.column_fallback_used+=1
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
        # Geometry checks can take a meaningful part of a 100 ms pulse. Issue
        # only after they finish; the ORIGINAL observation/map TTL still bounds
        # the command. Neither capture time nor measured evidence is refreshed.
        issued=now_ns if self._now_ns is None else self._now_ns()
        if type(issued) is not int or issued<now_ns:raise ValueError('issue clock moved backwards')
        if rotation_only:
            # Issue still requires the source to be within its TTL.
            if issued>=min(latest.capture_monotonic_ns,nav.capture_monotonic_ns)+self.max_depth_age_ns:
                return self._stop(decision,latest,issued,'depth_stale')
            deadline=issued+duration_ns
        else:
            deadline=min(latest.capture_monotonic_ns+self.max_depth_age_ns,
                         nav.capture_monotonic_ns+self.max_depth_age_ns,issued+duration_ns)
        if issued>=deadline:return self._stop(decision,latest,issued,'depth_stale')
        self._last_issued_ns=issued
        return MotionCommand(latest.key,nav.revision,issued,deadline,self.clock_domain,
            decision.desired_linear_mps,decision.desired_yaw_radps,decision.reason,latest.capture_monotonic_ns)

    def _escape(self,decision,latest,now_ns,nav,robot_xy,yaw,age,nav_age):
        stop=lambda reason:self._stop(decision,latest,now_ns,reason)
        rotate=decision.reason=='escape_rotate'
        if rotate and (decision.desired_linear_mps!=0 or decision.desired_yaw_radps==0):return stop('escape_invalid')
        if not rotate and (not 0<decision.desired_linear_mps<=ESCAPE_MAX_SPEED_MPS or decision.desired_yaw_radps!=0):
            return stop('escape_invalid')
        if abs(decision.desired_yaw_radps)>math.radians(30.):return stop('motion_limits_exceeded')
        body=self.mapper.robot.radius_m
        if rotate:
            horizon=self.rotation_horizon_ns or self.command_horizon_ns
            duration_ns=min(horizon,self.max_depth_age_ns-age,self.max_depth_age_ns-nav_age) if self.rotation_horizon_ns is None else horizon
            distance=0.
        else:
            duration_ns=min(self.command_horizon_ns,self.max_depth_age_ns-age,self.max_depth_age_ns-nav_age,
                            int(ESCAPE_STEP_M/decision.desired_linear_mps*1e9))
            distance=decision.desired_linear_mps*duration_ns/1e9
        if duration_ns<=0:return stop('depth_stale')
        result=self.mapper.bootstrap(latest,robot_xy=robot_xy,yaw_rad=yaw,corridor_m=distance,body_only=True,
                                     **self._fallback_args())
        if not result.ready:return stop('escape_'+result.reason)
        if getattr(result,'column_fallback',0):self.column_fallback_used+=1
        end=(robot_xy[0]+distance*math.cos(yaw),robot_xy[1]+distance*math.sin(yaw))
        if not self._clear(nav,robot_xy,end,radius_m=body):return stop('escape_body_not_clear')
        if not rotate and not free_distance(nav,end,self.mapper.robot.height_m)>free_distance(nav,robot_xy,self.mapper.robot.height_m)+ESCAPE_MIN_GAIN_M:
            return stop('escape_not_away')
        issued=now_ns if self._now_ns is None else self._now_ns()
        if type(issued) is not int or issued<now_ns:raise ValueError('issue clock moved backwards')
        if rotate and self.rotation_horizon_ns is not None:
            if issued>=min(latest.capture_monotonic_ns,nav.capture_monotonic_ns)+self.max_depth_age_ns:
                return self._stop(decision,latest,issued,'depth_stale')
            deadline=issued+duration_ns
        else:
            deadline=min(latest.capture_monotonic_ns+self.max_depth_age_ns,
                         nav.capture_monotonic_ns+self.max_depth_age_ns,issued+duration_ns)
        if issued>=deadline:return self._stop(decision,latest,issued,'depth_stale')
        self._last_issued_ns=issued
        self.escape_issued+=1
        return MotionCommand(latest.key,nav.revision,issued,deadline,self.clock_domain,
            decision.desired_linear_mps,decision.desired_yaw_radps,decision.reason,latest.capture_monotonic_ns)

    def _fallback_args(self):
        if not self.column_fallback_cells or self._raw_nav is None:return {}
        return dict(column_fallback_nav=self._raw_nav,column_fallback_max_cells=self.column_fallback_cells)

    def _clear(self,nav,start,end,*,swept_margin_m=0.,radius_m=None):
        radius=(self.mapper.robot.radius_m+self.mapper.robot.margin_m if radius_m is None else radius_m)+swept_margin_m
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
