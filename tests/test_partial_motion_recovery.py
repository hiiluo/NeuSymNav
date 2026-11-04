"""Recovery requires a source-bound native partial-action proof."""
from dataclasses import replace
import copy
import pytest

from neusymnav.contracts import FrameKey
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.navigation.controller import Navigator
from neusymnav.runtime.actuation_measurements import validate_actuation_proof
from neusymnav.sensors.habitat_worker import canonical_robot_pose
from contract_helpers import observation
from test_guard_goal_feedback import Guard, context, pipeline
from test_sensor_actuation import actuator, execute


class NativePartial:
    def __init__(self, monkeypatch, corruption=None, clip=0.):
        self.worker, _, self.calls, self.clock, self.state = actuator(monkeypatch, clip=clip)
        self.worker._yaw_math = None
        self.corruption = corruption
        self.proof = None

    def robot_pose(self, obs):
        return dict(source=obs.key, capture_monotonic_ns=obs.capture_monotonic_ns,
                    clock_domain=obs.clock_domain, pose_version=obs.pose_version,
                    **canonical_robot_pose(self.state))

    def execute(self, command):
        result = execute(self.worker, command, self.worker.pose_version)
        self.proof = copy.deepcopy(self.worker.last_actuation_proof)
        if self.proof is not None:
            if self.corruption == 'missing': self.proof = None
            elif self.corruption == 'map': self.proof['map_revision'] += 1
            elif self.corruption == 'pose': self.proof['source_pose_version'] += 1
            elif self.corruption == 'source': self.proof['source']['key']['frame_index'] += 1
            elif self.corruption == 'capture': self.proof['source']['capture_monotonic_ns'] += 1
            elif self.corruption == 'clock': self.proof['source']['clock_domain'] = 'host_monotonic:other'
            elif self.corruption == 'digest': self.proof['command_sha256'] = '0' * 64
            elif self.corruption == 'position': self.proof['actions'][0]['body_before_xy'][0] += .1
            elif self.corruption == 'action': self.proof['actions'][0]['action'] = 'turn_left'
        return result

    @property
    def last_actuation_proof(self): return self.proof


def build_pipeline(monkeypatch, *, corruption=None, clip=0.):
    a = NativePartial(monkeypatch, corruption, clip)
    _, template = context()
    nav = replace(template, episode_id='ep', source=FrameKey('ep', 'nav', 1), origin_xy=(.8, -5.2), robot_geometry_id='campaign',
                  clock_domain=a.worker.clock_domain)
    navigator = Navigator(RobotGeometry('campaign', .05, 1., 0.), clock_domain=a.worker.clock_domain)
    p = pipeline(None, nav, navigator, Guard('tracking', moving=True))
    # Guard fixture produces no turn; use an actual guarded intent requesting both.
    class MovingGuard(Guard):
        def filter(self, decision, latest, now):
            return replace(super().filter(decision, latest, now), yaw_radps=.2, clock_domain=latest.clock_domain)
    p.guard = MovingGuard('tracking', moving=True)
    p.clock_domain = a.worker.clock_domain
    p.now_ns = lambda: a.clock[0]
    return p, a, nav


def step(p, a, nav, i):
    now = 1_000_000_000 + i * 400_000_000
    a.clock[0] = now
    key = FrameKey('ep', 'nav', i + 1)
    obs = observation(key=key, capture_monotonic_ns=now, clock_domain=a.worker.clock_domain,
                      pose_version=a.worker.pose_version, modality='depth_only')
    a.worker._navigation_state = dict(episode_id='ep', sensor_id='nav', frame_index=i + 1,
        capture_monotonic_ns=now, pose_version=obs.pose_version, clock_domain=obs.clock_domain,
        calibration_id=obs.calibration_id, **canonical_robot_pose(a.state))
    p._latest_depth = obs
    p._latest_nav = replace(nav, source=key, revision=7 + i, capture_monotonic_ns=now)
    result = p.control_step(a)
    return result, obs


def test_source_bound_stationary_partial_pulse_releases_only_after_confirmation(monkeypatch):
    p, a, nav = build_pipeline(monkeypatch)
    for i in range(21):
        result, obs = step(p, a, nav, i)
        assert result['executed'] and result['reason'] == 'yaw_preflight_unavailable', result
        checked = validate_actuation_proof(a.proof, p._step_command, obs)
        assert checked['body_translation_m'] == 0
        if i < 20:
            assert p.navigator.policy._goal_world_xy is not None
    assert p.navigator.policy._goal_world_xy is None
    assert p.navigation_status()['last_goal_failure']['reason'] == 'yaw_preflight_no_progress'


@pytest.mark.parametrize('corruption', ['missing', 'map', 'pose', 'source', 'capture', 'clock', 'digest', 'position', 'action'])
def test_unbound_or_missing_proof_cannot_release_goal(monkeypatch, corruption):
    p, a, nav = build_pipeline(monkeypatch, corruption=corruption)
    for i in range(23): step(p, a, nav, i)
    assert p.navigator.policy._goal_world_xy is not None
    assert p.navigator._goal_failure_watch is None


def test_actual_forward_progress_does_not_trigger_partial_failure(monkeypatch):
    p, a, nav = build_pipeline(monkeypatch, clip=1.)
    for i in range(23):
        result, obs = step(p, a, nav, i)
        assert result['reason'] == 'yaw_preflight_unavailable'
        assert validate_actuation_proof(a.proof, p._step_command, obs)['body_translation_m'] > 1e-7
    assert p.navigator.policy._goal_world_xy is not None
    assert p.navigator._goal_failure_watch is None


def test_pause_interrupts_partial_failure_confirmation(monkeypatch):
    p, a, nav = build_pipeline(monkeypatch)
    for i in range(10): step(p, a, nav, i)
    assert p.navigator._goal_failure_watch is not None
    p._paused = True
    assert p.control_step(a)['reason'] == 'runtime_paused'
    assert p.navigator._goal_failure_watch is None
    p._paused = False
    for i in range(10, 22): step(p, a, nav, i)
    assert p.navigator.policy._goal_world_xy is not None


def test_pure_turn_without_forward_proof_never_counts(monkeypatch):
    p, a, nav = build_pipeline(monkeypatch)
    p.guard.moving = False
    for i in range(23):
        result, _ = step(p, a, nav, i)
        assert not result['executed']
    assert p.navigator.policy._goal_world_xy is not None
    assert p.navigator._goal_failure_watch is None
