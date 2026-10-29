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
        self.policy=FrontierPolicy(self.planner.core,PolicyConfig(visited_viewpoint_radius_m=.3,failed_viewpoint_radius_m=.3))
        self.controller=Controller(ControllerConfig(max_nav_age_s=self.max_nav_age_ns/1e9),traversable=self.planner.core.traversable)

    def step(self, nav, robot_xy, yaw_rad, now_ns) -> NavigationDecision:
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
        choice=self.policy.select(snapshot=grid,frontiers=frontiers,robot_xy=robot_xy,now_monotonic_s=now_ns/1e9)
        if choice.path is None:return stop('no_frontiers')
        dt=.1 if self._last_ns is None else max(0.,(now_ns-self._last_ns)/1e9)
        self._last_ns=now_ns
        command=self.controller.tick(robot_xy=robot_xy,yaw_rad=yaw_rad,now_monotonic_s=now_ns/1e9,dt_s=dt,
            depth_host_monotonic_s=nav.capture_monotonic_ns/1e9,depth_front_min_m=None,depth_coverage_ok=True,
            snapshot=grid,path=choice.path,frame_id=str(nav.source),blocked_edges=self.policy.blocked_edges(nav.revision))
        path=tuple(grid.cell_to_world(*cell) for cell in choice.path.cells)
        return NavigationDecision(choice.frontier.frontier_id,path,command.linear_mps,command.yaw_rate_radps,
            nav.revision,command.reason)

    def report_goal_failure(self, goal_id, map_revision, *, goal_world_xy):
        self.policy.report_goal_failure(goal_id,map_revision,goal_world_xy=goal_world_xy)
        self.controller.reset()

    def report_goal_reached(self, goal_id, goal_world_xy):
        self.policy.report_goal_reached(goal_id,goal_world_xy)
