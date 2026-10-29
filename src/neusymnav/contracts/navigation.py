"""Navigation intent and expiring motion command boundaries."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from ._base import Contract, coordinates, finite, integer, text
from .graphs import NavSnapshot
from .observations import FrameKey, Observation, _key, age_ns


@dataclass(frozen=True)
class NavigationDecision(Contract):
    goal_id: str | None
    path: tuple[tuple[float, float], ...]
    desired_linear_mps: float
    desired_yaw_radps: float
    map_revision: int
    reason: str

    def __post_init__(self):
        if self.goal_id is not None:
            text(self.goal_id, 'goal_id')
        object.__setattr__(self, 'path', tuple(coordinates(point, 2, 'path') for point in self.path))
        finite(self.desired_linear_mps, 'desired_linear_mps')
        finite(self.desired_yaw_radps, 'desired_yaw_radps')
        integer(self.map_revision, 'map_revision')
        text(self.reason, 'reason')
        if self.desired_linear_mps != 0 and not self.path:
            raise ValueError('translation requires a planned path')


@dataclass(frozen=True)
class MotionCommand(Contract):
    source: FrameKey
    map_revision: int
    issued_monotonic_ns: int
    deadline_monotonic_ns: int
    clock_domain: str
    linear_mps: float
    yaw_radps: float
    reason: str
    source_capture_monotonic_ns: int

    def __post_init__(self):
        _key(self.source)
        integer(self.map_revision, 'map_revision')
        integer(self.issued_monotonic_ns, 'issued_monotonic_ns')
        integer(self.deadline_monotonic_ns, 'deadline_monotonic_ns')
        integer(self.source_capture_monotonic_ns, 'source_capture_monotonic_ns')
        text(self.clock_domain, 'clock_domain')
        if self.source_capture_monotonic_ns > self.issued_monotonic_ns or self.deadline_monotonic_ns < self.issued_monotonic_ns:
            raise ValueError('command requires capture <= issue <= deadline')
        finite(self.linear_mps, 'linear_mps')
        finite(self.yaw_radps, 'yaw_radps')
        text(self.reason, 'reason')

    def is_valid(self, now_ns: int, clock_domain: str) -> bool:
        age_ns(self.issued_monotonic_ns, self.clock_domain, now_ns, clock_domain)
        return now_ns < self.deadline_monotonic_ns


class Navigator(Protocol):
    def step(self, nav: NavSnapshot, robot_xy: tuple[float, float], yaw_rad: float,
             now_ns: int) -> NavigationDecision: ...


class MotionGuard(Protocol):
    def filter(self, decision: NavigationDecision, latest: Observation, now_ns: int) -> MotionCommand: ...
