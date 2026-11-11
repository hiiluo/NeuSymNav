"""Offline-only replay pose and actuator seam for recorded control cadence."""
from __future__ import annotations

from dataclasses import dataclass
import time

from ..contracts import FrameKey, MotionCommand, Observation


def source_identity(key: FrameKey):
    return key.episode_id, key.sensor_id, key.frame_index


def assert_ab_profiles_differ_only_by_ui_enabled(left,right):
    import json
    a=json.loads(json.dumps(left));b=json.loads(json.dumps(right))
    if not isinstance(a.get('ui'),dict) or not isinstance(b.get('ui'),dict):
        raise ValueError('both A/B profiles require explicit ui objects')
    a['ui']['enabled']=False;b['ui']['enabled']=False
    if a!=b:raise ValueError('A/B profiles must differ only by ui.enabled')


@dataclass(frozen=True, slots=True)
class ReplayPose:
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    pose_version: int
    robot_xy: tuple[float, float]
    yaw_rad: float


class ReplayControlClock:
    """A replay clock that advances with source timestamps and host work time."""

    def __init__(self, *, start_ns: int, clock_domain: str):
        if type(start_ns) is not int or start_ns < 0:
            raise ValueError('replay clock start must be a nonnegative integer')
        if type(clock_domain) is not str or not clock_domain.startswith('replay:'):
            raise ValueError('replay control clock requires replay domain')
        self.clock_domain=clock_domain
        self._base_ns=start_ns
        self._current_ns=start_ns
        self._wall_start_ns=time.monotonic_ns()

    def set_source_time(self, stamp_ns: int):
        if type(stamp_ns) is not int or stamp_ns < 0:
            raise ValueError('source replay timestamp must be a nonnegative integer')
        self._current_ns=max(self._current_ns,stamp_ns)

    def reset_wall_anchor(self):
        """Exclude worker/model startup from the replay freshness timeline."""
        self._wall_start_ns=time.monotonic_ns()
        self._current_ns=self._base_ns

    def now_ns(self):
        elapsed=max(0,time.monotonic_ns()-self._wall_start_ns)
        self._current_ns=max(self._current_ns,self._base_ns+elapsed)
        return self._current_ns

    def source_time(self, *, source_stamp_ns: int, source_anchor_ns: int):
        if type(source_stamp_ns) is not int or type(source_anchor_ns) is not int or source_stamp_ns<source_anchor_ns:
            raise ValueError('source timestamp precedes replay anchor')
        return self._base_ns+(source_stamp_ns-source_anchor_ns)


class OfflineReplayActuator:
    """A source-bound fake actuator; it has no simulator or IPC handle."""

    _neusymnav_offline_replay_actuator = True

    def __init__(self, poses, *, clock_domain, now_ns):
        if type(clock_domain) is not str or not clock_domain.startswith('replay:'):
            raise ValueError('offline actuator requires an isolated replay clock')
        if not callable(now_ns):raise ValueError('offline actuator requires replay clock callback')
        self.clock_domain = clock_domain
        self._poses = dict(poses)
        self._now_ns = now_ns
        self._calls = 0

    def robot_pose(self, observation: Observation):
        if not isinstance(observation, Observation) or observation.clock_domain != self.clock_domain:
            raise ValueError('offline pose lookup requires replay Observation')
        pose = self._poses.get(source_identity(observation.key))
        if pose is None:
            raise ValueError('replay pose sidecar has no exact observation source')
        if (pose.source != observation.key or pose.capture_monotonic_ns != observation.capture_monotonic_ns
                or pose.clock_domain != observation.clock_domain or pose.pose_version != observation.pose_version):
            raise ValueError('replay pose sidecar source metadata mismatch')
        return dict(source=pose.source, capture_monotonic_ns=pose.capture_monotonic_ns,
                    clock_domain=pose.clock_domain, pose_version=pose.pose_version,
                    robot_xy=pose.robot_xy, yaw_rad=pose.yaw_rad)

    def execute(self, command: MotionCommand):
        if not isinstance(command, MotionCommand) or command.clock_domain != self.clock_domain:
            raise ValueError('offline actuator accepts replay MotionCommand only')
        self._calls += 1
        if (self._now_ns() >= command.deadline_monotonic_ns
                or command.source_capture_monotonic_ns+300_000_000 < self._now_ns()
                or (command.linear_mps == 0. and command.yaw_radps == 0.)):
            return dict(executed=False, reason='expired_or_zero')
        else:
            # Simulated ACK only: this never changes pose or simulator state.
            return dict(executed=True, reason='offline_replay_ack')

    @property
    def calls(self):
        return self._calls
