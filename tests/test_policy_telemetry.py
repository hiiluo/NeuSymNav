"""Policy diagnostics are copied with their own source, never relabeled."""
from test_guard_goal_feedback import context, pipeline, real_navigator, Guard, Actuator


def test_policy_status_is_source_bound_and_independently_copied():
    obs,nav=context();p=pipeline(obs,nav,real_navigator(),Guard())
    p.control_step(Actuator())
    status=p.navigation_status()['policy']
    assert status['map_revision']==nav.revision
    assert status['capture_monotonic_ns']==obs.capture_monotonic_ns
    assert status['source']['frame_index']==obs.key.frame_index
    status['source']['frame_index']=-1
    assert p.navigation_status()['policy']['source']['frame_index']==obs.key.frame_index
