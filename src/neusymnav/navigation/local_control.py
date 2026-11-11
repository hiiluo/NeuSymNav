"""Isolated world intent and current measured-depth control primitives."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class WorldIntent:
    source: object
    capture_monotonic_ns: int
    clock_domain: str
    map_revision: int
    created_monotonic_ns: int
    valid_until_monotonic_ns: int
    floor_z_m: float
    floor_datum_source: str
    calibration_hash: str
    robot_geometry_id: str
    goal_id: str
    path: tuple

    @classmethod
    def from_decision(cls, nav, goal_id, path, now_ns, *, ttl_ns=2_000_000_000):
        # The intent is a reference route, never motion evidence: the local
        # follower re-plans and guards every command on a <=300 ms depth frame.
        if type(ttl_ns) is not int or not 2_000_000_000 <= ttl_ns <= 5_000_000_000:
            raise ValueError('world intent TTL must be an int in [2 s, 5 s]')
        path = tuple(tuple(float(v) for v in point) for point in path)
        if (not goal_id or not path or len(path) > 4096
                or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in path)
                or not nav.capture_monotonic_ns <= now_ns <= nav.capture_monotonic_ns + ttl_ns):
            raise ValueError('invalid world intent')
        return cls(nav.source, nav.capture_monotonic_ns, nav.clock_domain, nav.revision,
                   now_ns, nav.capture_monotonic_ns + ttl_ns,
                   nav.floor_z_m, nav.floor_datum_source, nav.calibration_hash,
                   nav.robot_geometry_id, goal_id, path)

    def same_scope(self, nav):
        return (self.source.episode_id == nav.episode_id
                and self.source.sensor_id == nav.source.sensor_id
                and self.source.frame_index <= nav.source.frame_index
                and self.capture_monotonic_ns <= nav.capture_monotonic_ns
                and (self.source.frame_index != nav.source.frame_index
                     or self.capture_monotonic_ns == nav.capture_monotonic_ns)
                and self.clock_domain == nav.clock_domain
                and self.floor_z_m == nav.floor_z_m
                and self.floor_datum_source == nav.floor_datum_source
                and self.calibration_hash == nav.calibration_hash
                and self.robot_geometry_id == nav.robot_geometry_id)

    def compatible(self, nav, now_ns):
        return (self.same_scope(nav)
                and self.created_monotonic_ns <= now_ns <= self.valid_until_monotonic_ns)


class LocalMeasuredMap:
    """One-frame safety maps with a counter independent of the world mapper."""
    def __init__(self, world_mapper, *, sampling_stride=None):
        from ..mapping.occupancy import NavMapper
        core = world_mapper._core
        # Opt-in coarser ray lattice for the per-frame safety map only. Cells
        # without a ray stay UNKNOWN (never free); default keeps the mapper's.
        if sampling_stride is None:
            sampling_stride = core.sampling_stride
        if type(sampling_stride) is not int or not 1 <= sampling_stride <= 4:
            raise ValueError('local sampling stride must be an int in [1, 4]')
        self.sampling_stride = sampling_stride
        self.mapper = NavMapper(robot=world_mapper.robot, floor_z_m=world_mapper.floor_z_m,
            floor_datum_source=world_mapper.floor_datum_source,
            calibration_hash=world_mapper.calibration_hash,
            resolution_m=core.grid.resolution_m,
            origin_xy=(core.grid.origin_x_m, core.grid.origin_z_m),
            tile_size_cells=core.grid.tile_size_cells, height_bin_m=core.height_bin_m,
            min_depth_m=core.min_depth_m, max_depth_m=core.max_depth_m,
            sampling_stride=sampling_stride,
            snapshot_radius_m=min(world_mapper.snapshot_radius_m,
                max(1., world_mapper.robot.radius_m + world_mapper.robot.margin_m + .4)))
        self._revision = 0
        self._episode = None
        self._last_key = None
        self._last_capture = None
        self._domain = None

    def snapshot(self, observation, *, robot_xy):
        from dataclasses import replace
        from ..mapping.local_coverage import collect_local_measured_votes
        if observation.modality != 'depth_only':
            raise ValueError('local map requires depth-only observation')
        if self._episode is None:
            self._episode = observation.key.episode_id
            self._domain = observation.clock_domain
        if (observation.key.episode_id != self._episode or observation.clock_domain != self._domain
                or (self._last_key is not None and (observation.key.sensor_id != self._last_key.sensor_id
                    or observation.key.frame_index <= self._last_key.frame_index
                    or observation.capture_monotonic_ns < self._last_capture))):
            raise ValueError('local map source replay or scope mismatch')
        x, y = (float(v) for v in robot_xy)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError('invalid robot position')
        core = self.mapper._core
        resolution = core.grid.resolution_m
        center = core.grid.world_to_grid(float(observation.T_world_camera[0,3]),
                                        float(observation.T_world_camera[1,3]))
        half = math.ceil(self.mapper.snapshot_radius_m / resolution)
        min_r, min_c = center[0] - half, center[1] - half
        end_r, end_c = center[0] + half + 1, center[1] + half + 1
        bounds = ((core.grid.origin_x_m + min_c * resolution,
                   core.grid.origin_z_m + min_r * resolution),
                  (core.grid.origin_x_m + end_c * resolution,
                   core.grid.origin_z_m + end_r * resolution))
        votes, _, _ = collect_local_measured_votes(observation, self.mapper._core,
            bounds, grid_bounds=(min_r, min_c, end_r, end_c))
        nav = self.mapper._coverage_from_votes(observation, votes)
        self._revision += 1
        nav = replace(nav, revision=self._revision)
        self._last_key, self._last_capture = observation.key, observation.capture_monotonic_ns
        # The guard can reuse this exact current-frame evidence for bootstrap.
        self.mapper._current_coverage = (observation.geometry_hash, nav)
        return nav


class LocalFollower:
    def __init__(self, navigator):
        from .planner import Planner
        from ._controller_core import Controller
        self.planner = Planner(navigator.robot)
        self.controller = Controller(navigator.controller.config, traversable=self.planner.core.traversable)
        self.start_unknown_tolerance = float(getattr(navigator, 'start_unknown_tolerance', 0.) or 0.)
        self.start_unknown_cleared = 0
        self._last_ns = None
        self.last_control_diagnostics = None

    def reset(self):
        self.controller.reset()
        self._last_ns = None

    SCAN_TOLERANCE_RAD = math.radians(8.)
    SCAN_MAX_YAW_RADPS = math.radians(30.)

    def _scan_step(self, nav, intent, robot_xy, yaw_rad, stop):
        """Rotate in place toward the scan heading; no translation, ever."""
        from ..contracts import NavigationDecision
        (x0, y0), (x1, y1) = intent.path[0], intent.path[-1]
        heading = math.atan2(y1 - y0, x1 - x0)
        error = math.remainder(heading - float(yaw_rad), math.tau)
        if abs(error) <= self.SCAN_TOLERANCE_RAD:
            return stop('world_goal_reached')
        pulse_s = max(.1, float(getattr(self.controller.config, 'max_dt_s', .1)))
        rate = math.copysign(min(self.SCAN_MAX_YAW_RADPS, abs(error) / pulse_s), error)
        self.controller.reset()
        self.last_control_diagnostics = dict(goal_id=intent.goal_id, goal_xy=list(intent.path[-1]),
            path_point_count=len(intent.path), path_sample_xy=[], path_sample_truncated=False,
            lookahead_xy=None, heading_error_rad=error, decision_reason='tour_scan')
        return NavigationDecision(intent.goal_id, tuple(intent.path), 0., rate, nav.revision, 'tour_scan')

    def step(self, nav, intent, robot_xy, yaw_rad, now_ns):
        from ..contracts import NavigationDecision, age_ns
        from ._grid import adapt
        def stop(reason):
            self.reset()
            self.last_control_diagnostics = dict(goal_id=None, goal_xy=None, path_point_count=0,
                path_sample_xy=[], path_sample_truncated=False, lookahead_xy=None,
                heading_error_rad=None, decision_reason=reason)
            return NavigationDecision(None, (), 0., 0., nav.revision, reason)
        if intent is None:
            return stop('world_intent_unavailable')
        if not intent.compatible(nav, now_ns):
            return stop('world_intent_stale')
        try:
            if age_ns(nav.capture_monotonic_ns, nav.clock_domain, now_ns, intent.clock_domain) > 300_000_000:
                return stop('nav_stale')
        except ValueError:
            return stop('nav_stale')
        if intent.goal_id.startswith('scan-') and len(intent.path) >= 2:
            return self._scan_step(nav, intent, robot_xy, yaw_rad, stop)
        if math.dist(robot_xy, intent.path[-1]) <= .05:
            return stop('world_goal_reached')
        if self.start_unknown_tolerance:
            from .start_footprint import tolerate_robot_footprint
            nav, cleared = tolerate_robot_footprint(nav, robot_xy, self.planner.robot,
                                                    self.start_unknown_tolerance)
            self.start_unknown_cleared += cleared > 0
        grid = adapt(nav, self.planner.robot.height_m, self.planner.robot.geometry_id)
        # Start at the closest original path point, then retain only its
        # contiguous forward prefix inside the measured local raster.
        nearest = min(range(len(intent.path)), key=lambda i: math.dist(robot_xy, intent.path[i]))
        prefix = []
        for point in intent.path[nearest:]:
            cell = grid.world_to_cell(*point)
            if cell is None:
                break
            if not prefix or cell != prefix[-1]:
                prefix.append(cell)
        # One shared bounded search; failed far endpoints must not trigger an
        # A* traversal for every original world-path sample on the fast lane.
        candidates = self.planner.plan_many(nav, robot_xy, tuple(prefix)) if prefix else {}
        path = next((candidates[cell] for cell in reversed(prefix)
                     if candidates[cell].success and len(candidates[cell].cells) > 1), None)
        if path is None:
            return stop('local_path_blocked')
        dt = .1 if self._last_ns is None else max(0., (now_ns - self._last_ns) / 1e9)
        self._last_ns = now_ns
        command = self.controller.tick(robot_xy=robot_xy, yaw_rad=yaw_rad,
            now_monotonic_s=now_ns/1e9, dt_s=dt, depth_host_monotonic_s=nav.capture_monotonic_ns/1e9,
            depth_front_min_m=None, depth_coverage_ok=True, snapshot=grid, path=path,
            frame_id=str(nav.source), goal_world_xy=grid.cell_to_world(*path.cells[-1]))
        points = tuple(grid.cell_to_world(*cell) for cell in path.cells)
        detail = self.controller.last_diagnostics or {}
        self.last_control_diagnostics = dict(goal_id=intent.goal_id, goal_xy=list(intent.path[-1]),
            path_point_count=detail.get('path_point_count',len(points)),
            path_sample_xy=detail.get('path_sample_xy',[]),
            path_sample_truncated=detail.get('path_sample_truncated',False),
            lookahead_xy=detail.get('lookahead_xy'), heading_error_rad=detail.get('heading_error_rad'),
            decision_reason=command.reason)
        return NavigationDecision(intent.goal_id, points, command.linear_mps,
                                  command.yaw_rate_radps, nav.revision, command.reason)
