"""Rolling map indices must not restart velocity on an unchanged safe route."""
from dataclasses import replace
import math
import numpy as np
from test_navigation import nav, geometry
from neusymnav.navigation.controller import Navigator


def test_rolling_origin_preserves_forward_acceleration_on_same_world_goal():
    states = np.full((31, 31), -1, np.int8)
    states[3:28, 3:28] = 0
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    speeds = []
    goal = None
    for index in range(6):
        snapshot = replace(nav(states, revision=index + 1,
                               origin=(0., .1 if index == 5 else 0.)),
                           capture_monotonic_ns=1_000_000_000 + index * 100_000_000)
        decision = navigator.step(snapshot, (1.55, 1.55), -math.pi / 2,
                                  snapshot.capture_monotonic_ns)
        assert decision.reason == 'tracking'
        assert decision.path
        goal = decision.goal_id if goal is None else goal
        assert decision.goal_id == goal
        speeds.append(decision.desired_linear_mps)
    assert speeds[-1] >= speeds[-2]
    assert speeds[-1] > .075


def test_gain_heading_policy_can_choose_a_forward_view_of_one_connected_frontier():
    states = np.full((41, 41), -1, np.int8)
    states[3:38, 3:38] = 0
    snapshot = nav(states)
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', gain_aware=True)
    position = (2.05, 2.05)
    decision = navigator.step(snapshot, position, math.pi / 2, snapshot.capture_monotonic_ns)
    assert decision.path
    # A boundary surrounding the robot is ONE component. Ranking needs views
    # on several sides, otherwise heading-aware cost has no choice to make.
    assert len(navigator.last_frontiers.frontiers) > 1
    assert decision.path[-1][1] > position[1]


def test_committed_tracking_skips_frontier_search_but_replans_on_current_obstacles(monkeypatch):
    states = np.full((41, 41), -1, np.int8)
    states[3:38, 3:38] = 0
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test', gain_aware=True)
    snapshot = nav(states)
    first = navigator.step(snapshot, (2.05, 2.05), math.pi / 2, snapshot.capture_monotonic_ns)
    assert first.path
    calls = []
    original = navigator.extractor.extract
    def extract(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(navigator.extractor, 'extract', extract)
    second = navigator.step(replace(snapshot, revision=2), (2.05, 2.05), math.pi / 2,
                            snapshot.capture_monotonic_ns)
    assert second.path and second.map_revision == 2
    assert second.goal_id == first.goal_id
    assert calls == []
    blocked = states.copy()
    midpoint=first.path[len(first.path)//2]
    blocked[math.floor(midpoint[1]/snapshot.resolution_m), :] = 100
    third = navigator.step(replace(snapshot, revision=3, states=blocked), (2.05, 2.05),
                           math.pi / 2, snapshot.capture_monotonic_ns)
    assert not third.path
    assert third.desired_linear_mps == third.desired_yaw_radps == 0.
    assert third.map_revision == 3
    recovered=navigator.step(replace(snapshot,revision=4), (2.05,2.05), math.pi/2,
                             snapshot.capture_monotonic_ns)
    assert recovered.path and recovered.goal_id == first.goal_id
    assert recovered.path[-1] == first.path[-1] and recovered.map_revision == 4
    assert calls == []


def test_frontier_extraction_resumes_after_reaching_committed_goal(monkeypatch):
    states=np.full((41,41),-1,np.int8);states[3:38,3:38]=0
    navigator=Navigator(geometry(),clock_domain='host_monotonic:test',gain_aware=True)
    snapshot=nav(states)
    first=navigator.step(snapshot,(2.05,2.05),math.pi/2,snapshot.capture_monotonic_ns)
    target=first.path[-1];calls=[];original=navigator.extractor.extract
    def extract(*args,**kwargs):
        calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(navigator.extractor,'extract',extract)
    reached=navigator.step(replace(snapshot,revision=2),target,math.pi/2,snapshot.capture_monotonic_ns)
    assert reached.reason == 'frontier_viewpoint_reached' and not calls
    next_choice=navigator.step(replace(snapshot,revision=3),target,math.pi/2,snapshot.capture_monotonic_ns)
    assert calls == [1]
    assert next_choice.path and next_choice.path[-1] != target
