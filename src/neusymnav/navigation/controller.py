"""Frontier-only canonical navigation over the selected 3DSG policy/controller."""
import math
from ..contracts import NavigationDecision, age_ns
from ..mapping.occupancy import RobotGeometry
from ._grid import adapt
from .planner import Planner
from .frontiers import FrontierExtractor, FrontierSet
from ._policy_core import FrontierPolicy, PolicyConfig
from ._controller_core import Controller, ControllerConfig


class Navigator:
    def __init__(self, robot: RobotGeometry, *, clock_domain: str, max_nav_age_ns=300_000_000,
                 nominal_speed_mps=.15, discrete_heading_control=False, gain_aware=False,
                 acceleration_mps2=.15, hybrid_pulse_control=False,offline_replay=False,
                 goal_selection_max_age_ns=None,tour=None,max_pulse_s=None,start_unknown_tolerance=0.):
        if type(offline_replay) is not bool or (offline_replay and not clock_domain.startswith('replay:')):
            raise ValueError('offline navigation mode requires an isolated replay clock')
        from .clock_domains import is_live
        if not (clock_domain.startswith('replay:') if offline_replay else is_live(clock_domain)):
            raise ValueError('navigation requires pinned live host clock domain')
        if not 0<max_nav_age_ns<=300_000_000:raise ValueError('navigation TTL cannot exceed 300 ms')
        # Goal SELECTION only (world frontier choice and its failure watch). It
        # never certifies motion: with local depth control every command is
        # re-planned and guarded on the current <=300 ms local depth frame.
        if goal_selection_max_age_ns is not None and (type(goal_selection_max_age_ns) is not int
                or not max_nav_age_ns<=goal_selection_max_age_ns<=2_000_000_000):
            raise ValueError('goal selection age must be an int in [navigation TTL, 2 s]')
        self.goal_selection_max_age_ns=goal_selection_max_age_ns
        # Longest guarded pulse (s). The controller never requests more yaw or
        # distance than one pulse can execute without overshoot.
        if max_pulse_s is not None and (type(max_pulse_s) not in (int,float) or not .1<=max_pulse_s<=.5):
            raise ValueError('max pulse must be in [0.1, 0.5] s')
        self.max_pulse_s=None if max_pulse_s is None else float(max_pulse_s)
        from .start_footprint import validate_tolerance
        self.start_unknown_tolerance=validate_tolerance(start_unknown_tolerance)
        self.start_unknown_cleared=0
        from .tour import TourFollower,TourPlan
        if tour is not None and not isinstance(tour,(TourPlan,TourFollower)):
            raise ValueError('tour must be a TourPlan or TourFollower')
        self.tour=TourFollower(tour) if isinstance(tour,TourPlan) else tour
        self.tour_fallback_active=False
        self.tour_fallback_steps=0
        if (type(nominal_speed_mps) not in (int,float) or not 0<nominal_speed_mps<=.2):
            raise ValueError('nominal navigation speed must be in (0, 0.2] m/s')
        self.robot=robot;self.clock_domain=clock_domain;self.max_nav_age_ns=max_nav_age_ns
        self.nominal_speed_mps=float(nominal_speed_mps)
        if (type(acceleration_mps2) not in (int,float) or not math.isfinite(acceleration_mps2)
                or not 0<acceleration_mps2<=1.):raise ValueError('navigation acceleration must be in (0, 1] m/s²')
        self.acceleration_mps2=float(acceleration_mps2)
        if any(type(value) is not bool for value in (discrete_heading_control,gain_aware,hybrid_pulse_control)):
            raise ValueError('navigation modes must be boolean')
        if discrete_heading_control and hybrid_pulse_control:raise ValueError('steering modes are mutually exclusive')
        self.discrete_heading_control=discrete_heading_control;self.gain_aware=gain_aware
        self.hybrid_pulse_control=hybrid_pulse_control
        self.planner=Planner(robot)
        self.extractor=FrontierExtractor(agent_radius_m=robot.radius_m,inflation_margin_m=robot.margin_m,
            max_viewpoints_per_frontier=8 if gain_aware else 1,
            min_viewpoint_separation_m=.5 if gain_aware else .35)
        self._new_policy();self._episode_id=None;self._grid_geometry=None;self._last_ns=None
        self.last_control_diagnostics=None

    def _new_policy(self):
        self._goal_failure_watch=None
        self.last_committed_goal=None
        self.policy=FrontierPolicy(self.planner.core,PolicyConfig(commit_goal_until_reached=True,reached_distance_m=.05,visited_viewpoint_radius_m=.3,failed_viewpoint_radius_m=.3,
            frontier_gain_weight=.6 if self.gain_aware else 0.,
            min_goal_distance_m=.6 if self.gain_aware else 0.,
            turn_cost_m_per_rad=.35 if self.gain_aware else 0.))
        self.controller=Controller(ControllerConfig(nominal_speed_mps=self.nominal_speed_mps,
            acceleration_mps2=self.acceleration_mps2,
            yaw_acceleration_radps2=math.radians(180. if self.discrete_heading_control or self.hybrid_pulse_control else 45.),
            discrete_heading_control=self.discrete_heading_control,
            **({'hybrid_pulse_control':True} if self.hybrid_pulse_control else {}),
            **({'max_dt_s':self.max_pulse_s} if self.max_pulse_s is not None else {}),
            max_nav_age_s=self.max_nav_age_ns/1e9),traversable=self.planner.core.traversable)

    def step(self, nav, robot_xy, yaw_rad, now_ns) -> NavigationDecision:
        self.last_frontiers=None
        self.last_committed_goal=None
        self.last_control_diagnostics=None
        def stop(reason):
            self.controller.reset()
            self.last_control_diagnostics=dict(goal_id=None,goal_xy=None,path_point_count=0,
                path_sample_xy=[],path_sample_truncated=False,lookahead_xy=None,
                heading_error_rad=None,decision_reason=reason)
            return NavigationDecision(None,(),0.,0.,nav.revision,reason)
        try: age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,self.clock_domain)
        except ValueError:
            return stop('clock_domain_mismatch' if nav.clock_domain!=self.clock_domain else 'nav_future')
        if age>self._selection_age_limit_ns:return stop('nav_stale')
        if self._episode_id!=nav.episode_id:
            self._new_policy();self._episode_id=nav.episode_id;self._last_ns=None
        geometry=(nav.origin_xy,nav.resolution_m,nav.states.shape)
        if geometry!=self._grid_geometry:
            # World-space visited/failed viewpoints survive rolling origin.
            # Grid-index collision edges do not survive it.
            self.policy._failed_edges_until_revision.clear()
            # Rolling the raster changes indices, not the robot's velocity.
            # Every path and swept pulse is revalidated on the new snapshot.
            if self._grid_geometry is None or geometry[1:]!=self._grid_geometry[1:]:
                self.controller.reset()
            self._grid_geometry=geometry
        if self.start_unknown_tolerance:
            from .start_footprint import tolerate_robot_footprint
            nav,cleared=tolerate_robot_footprint(nav,robot_xy,self.robot,self.start_unknown_tolerance)
            self.start_unknown_cleared+=cleared>0
        grid=adapt(nav,self.robot.height_m,self.robot.geometry_id)
        tour_reason=None
        if self.tour is not None and not self.tour.complete:
            selection=self.tour.select(grid,robot_xy,now_ns/1e9,self.planner.core,yaw_rad=yaw_rad)
            if selection.reason=='tour_scan':
                # In-place scan step: a reference "path" from the robot toward
                # the target heading. The local follower only rotates for
                # scan-* intents and reports world_goal_reached when aligned.
                self.tour_fallback_active=False
                self.controller.reset()
                path=(tuple(float(v) for v in robot_xy),tuple(float(v) for v in selection.goal_world_xy))
                self.last_control_diagnostics=dict(goal_id=selection.goal_id,goal_xy=list(path[-1]),
                    path_point_count=2,path_sample_xy=[],path_sample_truncated=False,lookahead_xy=None,
                    heading_error_rad=None,decision_reason='tour_scan')
                return NavigationDecision(selection.goal_id,path,0.,0.,nav.revision,'tour_scan')
            if selection.path is not None:
                self.tour_fallback_active=False
                return self._emit(nav,grid,age,selection.goal_id,selection.path,selection.goal_world_xy,
                    robot_xy,yaw_rad,now_ns,latch_goal=False)
            if not self.tour.complete:
                # No route point is plannable on the observed map: explore with
                # frontiers this step instead of standing still (standing still
                # never reveals the unobserved route).
                tour_reason=selection.reason
                self.tour_fallback_active=True
                self.tour_fallback_steps+=1
            # Tour finished: continue with frontier exploration below.
        if self.gain_aware and self.policy._goal is not None and self.policy._goal_world_xy is not None:
            # A held goal is replanned against EVERY current map below. Full
            # boundary extraction serves goal selection, not path following.
            # Do not relabel the last extracted boundaries as fresh UI data.
            frontiers=FrontierSet(grid.revision,grid.as_of_frame_id,(), 'committed_goal_tracking')
        else:
            frontiers=self.extractor.extract(grid,robot_xy,excluded_viewpoints=self.policy.visited_viewpoints(),
                excluded_viewpoint_radius_m=self.policy.config.visited_viewpoint_radius_m)
            self.last_frontiers=frontiers
        choice=self.policy.select(snapshot=grid,frontiers=frontiers,robot_xy=robot_xy,now_monotonic_s=now_ns/1e9,
            robot_yaw_rad=yaw_rad if self.gain_aware else None)
        if self.policy._goal is not None and self.policy._goal_world_xy is not None:
            self.last_committed_goal=(self.policy._goal.frontier_id,self.policy._goal_world_xy)
        if choice.path is None:return stop(choice.reason if tour_reason is None else tour_reason)
        return self._emit(nav,grid,age,choice.frontier.frontier_id,choice.path,self.policy._goal_world_xy,
            robot_xy,yaw_rad,now_ns,latch_goal=self.policy.config.commit_goal_until_reached,
            blocked_edges=self.policy.blocked_edges(nav.revision))

    def _emit(self,nav,grid,age,goal_id,path_result,goal_world_xy,robot_xy,yaw_rad,now_ns,*,
              latch_goal,blocked_edges=frozenset()):
        path=tuple(grid.cell_to_world(*cell) for cell in path_result.cells)
        # Publish the latched world target after rolling-origin quantization.
        if latch_goal and goal_world_xy is not None:
            path=path[:-1]+(tuple(goal_world_xy),)
        goal_xy=goal_world_xy or path[-1]
        if age>self.max_nav_age_ns:
            # Selection-only on a map older than the motion TTL: publish the
            # chosen route as a reference, never a velocity command from it.
            self.controller.reset()
            self.last_control_diagnostics=dict(goal_id=goal_id,goal_xy=list(goal_xy),
                path_point_count=len(path),path_sample_xy=[],path_sample_truncated=False,
                lookahead_xy=None,heading_error_rad=None,decision_reason='world_goal_selected')
            return NavigationDecision(goal_id,path,0.,0.,nav.revision,'world_goal_selected')
        dt=.1 if self._last_ns is None else max(0.,(now_ns-self._last_ns)/1e9)
        self._last_ns=now_ns
        command=self.controller.tick(robot_xy=robot_xy,yaw_rad=yaw_rad,now_monotonic_s=now_ns/1e9,dt_s=dt,
            depth_host_monotonic_s=nav.capture_monotonic_ns/1e9,depth_front_min_m=None,depth_coverage_ok=True,
            snapshot=grid,path=path_result,frame_id=str(nav.source),goal_world_xy=goal_world_xy,blocked_edges=blocked_edges)
        detail=self.controller.last_diagnostics or {}
        self.last_control_diagnostics=dict(
            goal_id=goal_id,goal_xy=list(goal_xy),
            path_point_count=detail.get('path_point_count',len(path)),
            path_sample_xy=detail.get('path_sample_xy',[]),
            path_sample_truncated=detail.get('path_sample_truncated',False),
            lookahead_xy=detail.get('lookahead_xy'),
            heading_error_rad=detail.get('heading_error_rad'),
            decision_reason=command.reason)
        return NavigationDecision(goal_id,path,command.linear_mps,command.yaw_rate_radps,
            nav.revision,command.reason)

    @property
    def _selection_age_limit_ns(self):
        return self.goal_selection_max_age_ns or self.max_nav_age_ns

    def report_goal_failure(self, goal_id, map_revision, *, goal_world_xy):
        self.policy.report_goal_failure(goal_id,map_revision,goal_world_xy=goal_world_xy)
        self.controller.reset()

    def report_goal_reached(self, goal_id, goal_world_xy):
        if self.tour is not None and isinstance(goal_id,str) and goal_id.startswith('scan-'):
            self.tour.report_scan_done(goal_id)
            return
        if self.tour is not None and isinstance(goal_id,str) and goal_id.startswith('tour-'):
            try:index=int(goal_id.split('-',1)[1])
            except ValueError:index=None
            self.tour.report_reached(tuple(goal_world_xy),index=index)
            return
        self.policy.report_goal_reached(goal_id,goal_world_xy)

    def reset_goal_failure_watch(self):
        self._goal_failure_watch=None

    def observe_navigation_result(self, nav, robot_xy, now_ns, reason, stopped):
        """Confirm persistent geometric failure using fresh measured poses/maps.

        This is recovery of failed intent; no observation or safety gate is
        relaxed and a target is never marked reached by this watchdog.
        """
        import math
        target=self.policy._goal_world_xy
        goal=self.policy._goal
        eligible=(reason in {'bootstrap_blocked','footprint_not_observed',
                    'path_segment_blocked','collision_blocked','committed_goal_waiting_after_collision',
                    'committed_goal_outside_map'} or reason.startswith('committed_goal_blocked:'))
        try:fresh=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,self.clock_domain)<=self._selection_age_limit_ns
        except ValueError:fresh=False
        if (not stopped or not eligible or not fresh or target is None or goal is None
                or nav.episode_id!=self._episode_id):
            self._goal_failure_watch=None
            return None
        distance=math.dist(robot_xy,target)
        key=(goal.frontier_id,target)
        watch=self._goal_failure_watch
        if (watch is None or watch['key']!=key or now_ns<watch['start_ns']
                or now_ns-watch['last_ns']>1_000_000_000
                or distance<=watch['distance_m']-.03 or nav.revision<watch['revision']):
            watch=dict(key=key,start_ns=now_ns,last_ns=now_ns,distance_m=distance,revision=nav.revision,count=1)
            self._goal_failure_watch=watch
            return None
        watch['last_ns']=now_ns
        if nav.revision>watch['revision']:
            watch['count']+=1
            watch['revision']=nav.revision
        elapsed=now_ns-watch['start_ns']
        if reason=='committed_goal_blocked:goal_not_traversable':
            min_duration_ns,min_revisions=1_000_000_000,6
        else:
            min_duration_ns,min_revisions=8_000_000_000,20
        if elapsed<min_duration_ns or watch['count']<min_revisions:return None
        failure=dict(goal_id=goal.frontier_id,goal_xy=target,reason=reason,
                     blocked_duration_ns=elapsed,distinct_map_revisions=watch['count'])
        # Keep failed ID/spatial cooldown; never call the arrival/visited path.
        self.policy.report_goal_failure(goal.frontier_id,nav.revision,goal_world_xy=target)
        self.policy._clear_goal()
        self.controller.reset()
        self.last_committed_goal=None
        self._goal_failure_watch=None
        return failure
