"""Missing map output is neither new obstruction evidence nor a recovery."""
from dataclasses import replace
from test_guard_goal_feedback import context, real_navigator, pipeline, Guard, Actuator


def test_pending_capture_preserves_but_does_not_advance_geometric_failure_evidence():
    obs, nav = context()
    navigator = real_navigator()
    runtime = pipeline(obs, nav, navigator, Guard())
    actuator = Actuator()
    runtime.control_step(actuator)
    previous = dict(navigator._goal_failure_watch)
    target = navigator.policy._goal_world_xy
    runtime._latest_nav = replace(nav, source=replace(nav.source, frame_index=99))
    result = runtime.control_step(actuator)
    assert result['reason'] == 'navigation_source_pending'
    assert navigator._goal_failure_watch == previous
    assert navigator.policy._goal_world_xy == target
