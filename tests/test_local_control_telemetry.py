import copy
import pytest
from neusymnav.runtime.measurements import BoundedMeasurements, MeasurementContext, MeasurementSource, _navigation_diagnostics
from neusymnav.contracts import FrameKey
from neusymnav.evaluation.measurements import _collector


def setup():
    ctx=MeasurementContext('attempt','episode','host','a'*64,'b'*64,None,('nav',))
    meter=BoundedMeasurements(ctx)
    src=MeasurementSource(FrameKey('episode','nav',0),100,'host',1,'cal')
    assert meter.try_record_capture(src,width=10,height=10)
    return ctx,meter,src


def detail():
    return dict(goal_id='goal',goal_xy=[0,1],path_point_count=1,path_sample_xy=[[0,1]],
                path_sample_truncated=False,lookahead_xy=[0,1],heading_error_rad=0,
                decision_reason='tracking',control_map_scope='local_measured_depth_v1',
                world_intent=dict(source=dict(episode_id='episode',sensor_id='nav',frame_index=0),
                    capture_monotonic_ns=100,clock_domain='host',map_revision=10,
                    created_monotonic_ns=110,valid_until_monotonic_ns=2_000_000_100))


def record(meter,src,d,diagnostics=None):
    return meter.try_record_control(src,now_ns=200,clock_domain='host',reason='tracking',
                                    map_revision=1,navigation_diagnostics=d,diagnostics=diagnostics)


def test_v2_world_provenance_detached_and_offline_revalidated():
    ctx,meter,src=setup();d=detail()
    assert record(meter,src,d)
    d['world_intent']['source']['episode_id']='mutated'
    meter.stop();result=meter.finalize()
    nav=result['trace']['records'][-1]['navigation']
    assert nav['schema_version']==2 and nav['world_intent']['source']['episode_id']=='episode'
    assert _collector(result,ctx)['controls'][0]['map_revision']==1
    for field,value in [('capture_monotonic_ns',99),('clock_domain','other')]:
        bad=copy.deepcopy(result);bad['trace']['records'][-1]['navigation']['world_intent'][field]=value
        with pytest.raises(ValueError):_collector(bad,ctx)


@pytest.mark.parametrize('mutation',[
    lambda d:d.pop('control_map_scope'), lambda d:d.update(control_map_scope='world'),
    lambda d:d['world_intent'].update(extra=1),
    lambda d:d['world_intent'].update(map_revision=True),
    lambda d:d['world_intent'].update(created_monotonic_ns=99),
    lambda d:d['world_intent'].update(valid_until_monotonic_ns=2_000_000_101),
    lambda d:d['world_intent'].update(created_monotonic_ns=201),
    lambda d:d['world_intent'].update(clock_domain='other'),
    lambda d:d['world_intent']['source'].update(episode_id='foreign'),
    lambda d:d['world_intent']['source'].update(frame_index=1),
    lambda d:d['world_intent'].update(capture_monotonic_ns=101),
    lambda d:d.update(world_intent=None),
])
def test_invalid_world_scope_and_provenance_rejected(mutation):
    _,meter,src=setup();d=detail();mutation(d)
    assert not record(meter,src,d)
    meter.stop();assert meter.finalize()['rejected_records']==1


def test_null_intent_only_allows_stop_and_legacy_v1_still_supported():
    _,meter,src=setup();d=detail();d.update(world_intent=None,goal_id=None,goal_xy=None,
        path_point_count=0,path_sample_xy=[],lookahead_xy=None)
    assert record(meter,src,d)
    fields=dict(decision_reason='tracking',decision_linear_mps=.1,decision_yaw_radps=0.,
        command_reason=None,command_linear_mps=None,command_yaw_radps=None,
        command_issued_monotonic_ns=None,command_deadline_monotonic_ns=None,failure_detail=None)
    assert not record(meter,src,d,fields)
    legacy={k:v for k,v in detail().items() if k not in ('control_map_scope','world_intent')}
    assert _navigation_diagnostics(legacy)['schema_version']==1


def test_v2_worst_unicode_record_cannot_exceed_declared_byte_charge():
    text='😀'*128
    ctx=MeasurementContext('attempt',text,'host','a'*64,'b'*64,None,(text,))
    meter=BoundedMeasurements(ctx)
    src=MeasurementSource(FrameKey(text,text,0),100,'host',1,text)
    assert meter.try_record_capture(src,width=10,height=10)
    d=detail();d['world_intent']['source'].update(episode_id=text,sensor_id=text)
    d.update(goal_id=text,decision_reason=text)
    assert not record(meter,src,d)
    meter.stop();result=meter.finalize()
    assert result['rejected_records']==1 and len(result['trace']['records'])==1
