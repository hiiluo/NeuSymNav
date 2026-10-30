"""Frontier-only canonical navigation over the selected 3DSG policy/controller."""
from ..contracts import NavigationDecision, age_ns
from ..mapping.occupancy import RobotGeometry
from ._grid import adapt
from .planner import Planner
from .frontiers import FrontierExtractor
from ._policy_core import FrontierPolicy, PolicyConfig
from ._controller_core import Controller, ControllerConfig


class Navigator:
    def __init__(self, robot: RobotGeometry, *, clock_domain: str, max_nav_age_ns=300_000_000):
        if not clock_domain.startswith('host_monotonic:'):
            raise ValueError('navigation requires pinned live host clock domain')
        if not 0<max_nav_age_ns<=300_000_000:raise ValueError('navigation TTL cannot exceed 300 ms')
        self.robot=robot;self.clock_domain=clock_domain;self.max_nav_age_ns=max_nav_age_ns
        self.planner=Planner(robot)
        self.extractor=FrontierExtractor(agent_radius_m=robot.radius_m,inflation_margin_m=robot.margin_m)
        self._new_policy();self._episode_id=None;self._grid_geometry=None;self._last_ns=None

    def _new_policy(self):
        self._goal_failure_watch=None
        self.last_committed_goal=None
        self.policy=FrontierPolicy(self.planner.core,PolicyConfig(commit_goal_until_reached=True,reached_distance_m=.05,visited_viewpoint_radius_m=.3,failed_viewpoint_radius_m=.3))
        self.controller=Controller(ControllerConfig(max_nav_age_s=self.max_nav_age_ns/1e9),traversable=self.planner.core.traversable)

    def step(self, nav, robot_xy, yaw_rad, now_ns) -> NavigationDecision:
        self.last_frontiers=None
        self.last_committed_goal=None
        def stop(reason):
            self.controller.reset()
            return NavigationDecision(None,(),0.,0.,nav.revision,reason)
        try: age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,self.clock_domain)
        except ValueError:
            return stop('clock_domain_mismatch' if nav.clock_domain!=self.clock_domain else 'nav_future')
        if age>self.max_nav_age_ns:return stop('nav_stale')
        if self._episode_id!=nav.episode_id:
            self._new_policy();self._episode_id=nav.episode_id;self._last_ns=None
        geometry=(nav.origin_xy,nav.resolution_m,nav.states.shape)
        if geometry!=self._grid_geometry:
            # World-space visited/failed viewpoints survive rolling origin.
            # Grid-index collision edges do not survive it.
            self.policy._failed_edges_until_revision.clear();self.controller.reset()
            self._grid_geometry=geometry
        grid=adapt(nav,self.robot.height_m,self.robot.geometry_id)
        frontiers=self.extractor.extract(grid,robot_xy,excluded_viewpoints=self.policy.visited_viewpoints(),
            excluded_viewpoint_radius_m=self.policy.config.visited_viewpoint_radius_m)
        self.last_frontiers=frontiers
        choice=self.policy.select(snapshot=grid,frontiers=frontiers,robot_xy=robot_xy,now_monotonic_s=now_ns/1e9)
        if self.policy._goal is not None and self.policy._goal_world_xy is not None:
            self.last_committed_goal=(self.policy._goal.frontier_id,self.policy._goal_world_xy)
        if choice.path is None:return stop(choice.reason)
        dt=.1 if self._last_ns is None else max(0.,(now_ns-self._last_ns)/1e9)
        self._last_ns=now_ns
        command=self.controller.tick(robot_xy=robot_xy,yaw_rad=yaw_rad,now_monotonic_s=now_ns/1e9,dt_s=dt,
            depth_host_monotonic_s=nav.capture_monotonic_ns/1e9,depth_front_min_m=None,depth_coverage_ok=True,
            snapshot=grid,path=choice.path,frame_id=str(nav.source),goal_world_xy=self.policy._goal_world_xy,blocked_edges=self.policy.blocked_edges(nav.revision))
        path=tuple(grid.cell_to_world(*cell) for cell in choice.path.cells)
        # Publish the latched world target after rolling-origin quantization.
        if self.policy.config.commit_goal_until_reached and self.policy._goal_world_xy is not None:
            path=path[:-1]+(self.policy._goal_world_xy,)
        return NavigationDecision(choice.frontier.frontier_id,path,command.linear_mps,command.yaw_rate_radps,
            nav.revision,command.reason)

    def report_goal_failure(self, goal_id, map_revision, *, goal_world_xy):
        self.policy.report_goal_failure(goal_id,map_revision,goal_world_xy=goal_world_xy)
        self.controller.reset()

    def report_goal_reached(self, goal_id, goal_world_xy):
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
        try:fresh=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,self.clock_domain)<=self.max_nav_age_ns
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
        if elapsed<8_000_000_000 or watch['count']<20:return None
        failure=dict(goal_id=goal.frontier_id,goal_xy=target,reason=reason,
                     blocked_duration_ns=elapsed,distinct_map_revisions=watch['count'])
        # Keep failed ID/spatial cooldown; never call the arrival/visited path.
        self.policy.report_goal_failure(goal.frontier_id,nav.revision,goal_world_xy=target)
        self.policy._clear_goal()
        self.controller.reset()
        self.last_committed_goal=None
        self._goal_failure_watch=None
        return failure
