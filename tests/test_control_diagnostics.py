"""Current control outcomes remain distinct from prior plan provenance."""
from dataclasses import replace

from neusymnav.contracts import NavigationDecision
from test_guard_goal_feedback import Actuator, Guard, context, fixed_navigator, pipeline, STAMP


def test_pending_pause_fault_stale_and_resume_keep_plan_provenance():
    obs, nav = context()
    decision = NavigationDecision('original', ((1.2, 1.2), (1.65, 1.2)), .1, 0., nav.revision, 'tracking')
    now = [STAMP]
    p = pipeline(obs, nav, fixed_navigator(decision), Guard('tracking', moving=True))
    p.now_ns = lambda: now[0]
    actuator = Actuator()
    assert p.control_step(actuator)['executed']
    original_plan = p._navigation_display
    original_status = p.navigation_status()
    assert p.latest_control_status()['reason'] == 'tracking'

    newer = replace(obs, key=replace(obs.key, frame_index=2), capture_monotonic_ns=STAMP + 1)
    now[0] += 2
    p._latest_depth = newer
    assert p.control_step(actuator)['reason'] == 'navigation_source_pending'
    status = p.latest_control_status()
    assert status == dict(reason='navigation_source_pending', executed=False, observed_monotonic_ns=now[0],
                          episode_id='episode', sensor_id='nav', frame_index=2,
                          capture_monotonic_ns=STAMP + 1, clock_domain=obs.clock_domain)
    assert p._navigation_display is original_plan
    assert p.navigation_status()['computed_monotonic_ns'] == original_status['computed_monotonic_ns']
    assert len(actuator.commands) == 1

    p._paused = True
    now[0] += 1
    assert p.control_step(actuator)['reason'] == 'runtime_paused'
    assert p.latest_control_status()['reason'] == 'runtime_paused'
    p._paused = False
    p._latest_nav = replace(nav, source=newer.key, capture_monotonic_ns=newer.capture_monotonic_ns, revision=8)
    class Broken(Actuator):
        def robot_pose(self, source):
            raise RuntimeError('bad pose')
    assert p.control_step(Broken())['reason'] == 'control_rejected'
    assert p.latest_control_status()['reason'] == 'control_rejected'

    p.guard = Guard('depth_stale')
    assert p.control_step(actuator)['reason'] == 'depth_stale'
    assert p.latest_control_status()['reason'] == 'depth_stale'
    assert actuator.commands[-1].linear_mps == 0
    p.guard = Guard('tracking', moving=True)
    assert p.control_step(actuator)['executed']
    assert p.latest_control_status()['reason'] == 'tracking'
    assert p.latest_control_status()['frame_index'] == 2
    assert all(v is None or isinstance(v, (str, int, bool)) for v in p.latest_control_status().values())


def test_malformed_actuator_results_are_rejected_without_diagnostic_exception():
    obs, nav = context()
    decision = NavigationDecision('original', ((1.2, 1.2), (1.65, 1.2)), .1, 0., nav.revision, 'tracking')
    for malformed in (None, [], 'invalid'):
        p = pipeline(obs, nav, fixed_navigator(decision), Guard('tracking', moving=True))
        class Invalid(Actuator):
            def execute(self, command):
                self.commands.append(command)
                return malformed
        actuator = Invalid()
        result = p.control_step(actuator)
        assert result == dict(executed=False, reason='control_rejected', error='invalid actuator result')
        assert p.latest_control_status()['reason'] == 'control_rejected'
        assert p.latest_control_status()['executed'] is False
        assert len(actuator.commands) == 1
