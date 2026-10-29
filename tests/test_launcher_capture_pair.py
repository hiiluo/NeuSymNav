import pytest
from types import SimpleNamespace
from neusymnav.runtime import launcher


def scenario(*,failure=None):
    events=[];rgb=object();nav=object();pose=object();captures=[];pairs=[]
    def capture():events.append('capture_rgb');return rgb
    def navigation():
        events.append('capture_nav')
        if failure=='navigation':raise RuntimeError('navigation failed')
        return nav
    def body(obs):
        assert obs is nav;events.append('pose')
        if failure=='pose':raise RuntimeError('pose failed')
        return pose
    def raw(obs):
        events.append('raw_rgb' if obs is rgb else 'raw_nav')
        if failure=='raw_nav' and obs is nav:raise RuntimeError('raw admission failed')
    def publish(*args):
        events.append('pair');pairs.append(args)
        # Stand in for the actual pair's existing submit capture callbacks.
        captures.append(rgb)
        if failure=='pair':raise RuntimeError('partial pair failure')
        captures.append(nav)
    sensor=SimpleNamespace(capture=capture,capture_navigation=navigation,robot_pose=body)
    pipeline=SimpleNamespace(measurements=SimpleNamespace(capture=captures.append),submit_sensor_pair=publish)
    return sensor,pipeline,raw,events,captures,pairs,(rgb,nav,pose)


def test_capture_pair_preserves_immediate_raw_and_publishes_after_pose():
    sensor,pipeline,raw,events,captures,pairs,values=scenario()
    result=launcher._capture_sensor_pair(sensor,pipeline,raw)
    assert result==values[:2]
    assert events==['capture_rgb','raw_rgb','capture_nav','raw_nav','pose','pair']
    assert captures==list(values[:2]) and pairs==[values]


@pytest.mark.parametrize('failure,count',[('navigation',1),('pose',2),('raw_nav',2)])
def test_acquisition_failure_records_each_captured_source_without_semantic_fallback(failure,count):
    sensor,pipeline,raw,events,captures,pairs,values=scenario(failure=failure)
    with pytest.raises(RuntimeError):launcher._capture_sensor_pair(sensor,pipeline,raw)
    assert captures==list(values[:count])
    assert not pairs and 'pair' not in events
    assert events.index('raw_rgb')<events.index('capture_nav')


def test_partial_pair_failure_never_replays_capture_observer_fallback():
    sensor,pipeline,raw,events,captures,pairs,values=scenario(failure='pair')
    with pytest.raises(RuntimeError,match='partial pair'):launcher._capture_sensor_pair(sensor,pipeline,raw)
    assert captures==[values[0]] and pairs==[values]
