"""Bounded telemetry oracle: source proof, full-run semantics and producer isolation."""
from dataclasses import replace
import json
from threading import Thread
import pytest
from neusymnav.contracts import FrameKey
from neusymnav.runtime.measurements import BoundedMeasurements, MeasurementContext, MeasurementSource


def context(**kw):
    fields = dict(attempt_id='attempt-1', episode_id='episode-1', clock_domain='host-boot',
                  config_sha256='a'*64, launch_config_sha256='b'*64,
                  seed_ack_sha256='c'*64, sensor_ids=('rgbd', 'nav'))
    fields.update(kw)
    return MeasurementContext(**fields)


def source(index=0, capture=100, sensor='rgbd'):
    return MeasurementSource(FrameKey('episode-1', sensor, index), capture, 'host-boot', 1, 'cal-v1')


def test_source_clock_identity_and_unregistered_latency_fail_closed():
    meter = BoundedMeasurements(context())
    src = source()
    assert not meter.try_record_result(src, now_ns=200, clock_domain='host-boot', kind='detector_return')
    assert meter.try_record_capture(src, width=640, height=480)
    assert not meter.try_record_result(replace(src, clock_domain='other'), now_ns=200, clock_domain='host-boot', kind='detector_return')
    assert not meter.try_record_result(replace(src, capture_monotonic_ns=99), now_ns=200, clock_domain='host-boot', kind='detector_return')
    assert not meter.try_record_result(replace(src, pose_version=2), now_ns=200, clock_domain='host-boot', kind='detector_return')
    assert not meter.try_record_result(src, now_ns=99, clock_domain='host-boot', kind='detector_return')
    assert meter.try_record_result(src, now_ns=200, clock_domain='host-boot', kind='detector_return')
    assert not meter.try_record_result(src, now_ns=300, clock_domain='host-boot', kind='detector_return')
    meter.stop()
    result = meter.finalize()
    assert result['distributions']['capture_to_detector_return_ns']['seen'] == 1
    assert result['rejected_records'] == 6
    assert not result['complete']


def test_quantiles_are_computed_after_stop_and_historical_results_excluded():
    meter = BoundedMeasurements(context())
    for index, latency in enumerate((10, 20, 30, 40, 50)):
        src = source(index, 100 + index)
        assert meter.try_record_capture(src, width=640, height=480)
        assert meter.try_record_result(src, now_ns=src.capture_monotonic_ns+latency, clock_domain='host-boot', kind='detector_return')
        assert meter.try_record_result(src, now_ns=src.capture_monotonic_ns+latency+5,
                                      clock_domain='host-boot', kind='object_commit', revision=index+1)
    for origin in ('historical', 'reused', 'recovery'):
        assert meter.try_record_result(src, now_ns=1000, clock_domain='host-boot', kind='object_commit', origin=origin, revision=100)
    with pytest.raises(RuntimeError, match='stop'):
        meter.finalize()
    meter.stop()
    result = meter.finalize()
    detector = result['distributions']['capture_to_detector_return_ns']
    assert detector == dict(seen=5, retained=5, overflow=0, p50=30., p95=48., reason=None)
    assert result['distributions']['capture_to_object_commit_ns']['p50'] == 35.
    assert result['excluded_results'] == dict(historical=1, reused=1, recovery=1)
    assert result['travel']['body_translation_m'] is None
    assert result['trace']['records'][0]['width'] == 640
    assert result['complete']
    json.dumps(result, allow_nan=False)


def test_overflow_nulls_whole_run_quantiles_and_trace_is_bounded():
    meter = BoundedMeasurements(context(), sample_cap=2, trace_byte_cap=4096, capture_cap=4)
    for index in range(4):
        src = source(index, 100+index)
        assert not meter.try_record_capture(src, width=640, height=480)
        assert not meter.try_record_result(src, now_ns=1000, clock_domain='host-boot', kind='detector_return')
    meter.stop()
    result = meter.finalize()
    dist = result['distributions']['capture_to_detector_return_ns']
    assert (dist['seen'], dist['retained'], dist['overflow']) == (4, 2, 2)
    assert dist['p50'] is None and dist['p95'] is None
    assert dist['reason'] == 'sample_overflow'
    assert result['trace']['charged_bytes'] <= 4096
    assert result['trace']['dropped'] > 0
    assert not result['complete']


def test_capture_watermarks_and_capture_registry_cap_cannot_reset():
    meter = BoundedMeasurements(context(), capture_cap=2)
    assert meter.try_record_capture(source(2, 200), width=10, height=20)
    assert not meter.try_record_capture(source(1, 201), width=10, height=20)
    assert not meter.try_record_capture(source(3, 199), width=10, height=20)
    assert meter.try_record_capture(source(3, 201), width=10, height=20)
    assert not meter.try_record_capture(source(4, 202), width=10, height=20)
    assert not meter.try_record_result(source(4, 202), now_ns=300, clock_domain='host-boot', kind='detector_return')
    meter.stop()
    result = meter.finalize()
    assert result['capture_registry']['retained'] == 2
    assert result['capture_registry']['overflow'] == 1


def test_control_records_depth_age_all_reasons_and_admission_denominators():
    meter = BoundedMeasurements(context())
    src = source(sensor='nav')
    assert meter.try_record_capture(src, width=16, height=8)
    for outcome in ('offered', 'durable_accepted', 'rejected', 'replaced', 'stale'):
        assert meter.try_record_admission(src, outcome=outcome)
    for offset, reason in enumerate(('ok', 'stale_depth', 'shutdown')):
        assert meter.try_record_control(src, now_ns=200+offset, clock_domain='host-boot', reason=reason, map_revision=4)
    meter.stop()
    result = meter.finalize()
    assert result['admission_counts'] == dict(offered=1, durable_accepted=1, rejected=1, replaced=1, stale=1)
    assert result['control_reasons'] == dict(ok=1, stale_depth=1, shutdown=1)
    assert result['distributions']['control_depth_age_ns']['seen'] == 3
    assert result['distributions']['control_depth_age_ns']['p50'] == 101.
    control = [r for r in result['trace']['records'] if r['event'] == 'control']
    assert len(control) == 3 and control[0]['source']['key']['sensor_id'] == 'nav'


def test_busy_collector_returns_immediately_and_marks_incomplete():
    meter = BoundedMeasurements(context())
    src = source()
    meter._lock.acquire()
    try:
        result = []
        thread = Thread(target=lambda: result.append(meter.try_record_capture(src, width=1, height=1)))
        thread.start(); thread.join(.25)
        assert not thread.is_alive()
        assert result == [False]
    finally:
        meter._lock.release()
    meter.stop()
    assert meter.finalize()['contention_dropped'] == 1
    assert not meter.finalize()['complete']
    assert not meter.try_record_capture(src, width=1, height=1)


@pytest.mark.parametrize('kw', [{'sample_cap':65537}, {'sample_cap':True}, {'capture_cap':0}, {'trace_byte_cap':True}])
def test_caps_are_strict(kw):
    with pytest.raises((ValueError, TypeError)):
        BoundedMeasurements(context(), **kw)


def test_closed_bounded_context_and_source_validation():
    with pytest.raises(ValueError): context(attempt_id='x'*129)
    with pytest.raises(ValueError): context(config_sha256='no-hash')
    with pytest.raises(ValueError): context(sensor_ids=('rgbd','rgbd'))
    with pytest.raises((TypeError, ValueError)): source(capture=True)
    meter = BoundedMeasurements(context())
    assert not meter.try_record_capture(source(sensor='unknown'), width=1, height=1)
    assert not meter.try_record_capture(source(), width=True, height=1)
    assert meter.try_record_capture(source(), width=1, height=1)
    assert not meter.try_record_control(source(), now_ns=200, clock_domain='host-boot', reason='x'*129, map_revision=0)
    assert not meter.try_record_result(source(), now_ns=float('nan'), clock_domain='host-boot', kind='detector_return')


def test_measurement_clock_mismatch_and_missing_source_control_are_explicit():
    meter = BoundedMeasurements(context(seed_ack_sha256=None))
    src = source()
    assert meter.try_record_capture(src, width=1, height=1)
    assert not meter.try_record_result(src, now_ns=200, clock_domain='foreign', kind='detector_return')
    assert not meter.try_record_control(src, now_ns=200, clock_domain='foreign', reason='ok', map_revision=1)
    assert meter.try_record_control(None, now_ns=200, clock_domain='host-boot',
                                    reason='no_observation', map_revision=0)
    meter.stop()
    result = meter.finalize()
    assert result['control_reasons'] == {'no_observation':1}
    assert result['distributions']['control_depth_age_ns']['seen'] == 0
    assert result['trace']['records'][-1]['source'] is None
    assert result['trace']['records'][-1]['depth_age_ns'] is None
    assert not result['native_eligible_context']


def test_maximum_scalar_payloads_fit_charge_and_snapshot_is_detached():
    from neusymnav.runtime.measurements import TRACE_RECORD_CHARGE
    text = '\U0001f642'*128
    ctx = context(episode_id=text, clock_domain=text, sensor_ids=(text,))
    src = MeasurementSource(FrameKey(text,text,(1<<63)-1), (1<<63)-2, text, (1<<63)-1, text)
    meter = BoundedMeasurements(ctx, trace_byte_cap=2*TRACE_RECORD_CHARGE)
    assert meter.try_record_capture(src, width=65536, height=65536)
    assert meter.try_record_control(src, now_ns=(1<<63)-1, clock_domain=text,
                                    reason=text, map_revision=(1<<63)-1)
    assert not meter.try_record_admission(src, outcome='offered')
    meter.stop()
    result = meter.finalize()
    for record in result['trace']['records']:
        assert len(json.dumps(record, ensure_ascii=True).encode()) <= TRACE_RECORD_CHARGE
    assert result['capture_registry']['charged_bytes'] <= result['capture_registry']['byte_cap']
    result['trace']['records'][0]['source']['key']['episode_id'] = 'mutated'
    result['context']['sensor_ids'] = ['mutated']
    assert meter.finalize()['trace']['records'][0]['source']['key']['episode_id'] == text


def test_old_registered_capture_can_finish_after_newer_capture():
    meter = BoundedMeasurements(context())
    old, new = source(0, 100), source(1, 200)
    assert meter.try_record_capture(old, width=1, height=1)
    assert meter.try_record_capture(new, width=1, height=1)
    assert meter.try_record_result(old, now_ns=300, clock_domain='host-boot', kind='detector_return')
    assert meter.try_record_result(old, now_ns=301, clock_domain='host-boot', kind='object_commit', revision=1)


def test_sample_only_overflow_returns_false_and_keeps_seen_denominator():
    meter = BoundedMeasurements(context(), sample_cap=1)
    src = source()
    assert meter.try_record_capture(src, width=1, height=1)
    assert meter.try_record_control(src, now_ns=200, clock_domain='host-boot', reason='ok', map_revision=1)
    assert not meter.try_record_control(src, now_ns=201, clock_domain='host-boot', reason='ok', map_revision=1)
    meter.stop()
    result = meter.finalize()
    assert result['control_reasons']['ok'] == 2
    assert result['distributions']['control_depth_age_ns']['seen'] == 2
    assert result['distributions']['control_depth_age_ns']['p50'] is None


def test_giant_integers_and_frame_identifiers_never_enter_registry():
    with pytest.raises(ValueError): source(index=1<<64)
    with pytest.raises(ValueError): MeasurementSource(FrameKey('x'*129,'rgbd',0), 1, 'host-boot', 0, 'cal')
    with pytest.raises(ValueError): source(capture=1<<64)


def test_backward_control_clock_and_commit_before_detector_are_rejected():
    meter = BoundedMeasurements(context())
    src = source()
    assert meter.try_record_capture(src, width=1, height=1)
    assert meter.try_record_control(src, now_ns=200, clock_domain='host-boot', reason='ok', map_revision=1)
    assert not meter.try_record_control(src, now_ns=199, clock_domain='host-boot', reason='ok', map_revision=1)
    assert meter.try_record_result(src, now_ns=200, clock_domain='host-boot', kind='detector_return')
    assert not meter.try_record_result(src, now_ns=199, clock_domain='host-boot', kind='object_commit', revision=1)
    assert meter.try_record_result(src, now_ns=201, clock_domain='host-boot', kind='object_commit', revision=1)


def test_reason_vocabulary_and_counter_saturation_mark_incomplete():
    from neusymnav.runtime.measurements import MAX_INTEGER
    meter = BoundedMeasurements(context())
    for index in range(128):
        assert meter.try_record_control(None, now_ns=index, clock_domain='host-boot', reason=str(index), map_revision=0)
    assert not meter.try_record_control(None, now_ns=129, clock_domain='host-boot', reason='new-reason', map_revision=0)
    # Direct state injection reaches a boundedness edge impossible to run 2^63 times.
    meter._reasons['0'] = MAX_INTEGER
    assert not meter.try_record_control(None, now_ns=130, clock_domain='host-boot', reason='0', map_revision=0)
    meter.stop()
    result = meter.finalize()
    assert result['control_reasons']['0'] == MAX_INTEGER
    assert result['counter_saturated'] and not result['complete']


def test_caller_framekey_mutation_cannot_rewrite_registered_provenance():
    meter = BoundedMeasurements(context())
    src = source()
    assert meter.try_record_capture(src, width=1, height=1)
    src.key.__dict__['episode_id'] = 'tampered'
    assert not meter.try_record_result(src, now_ns=200, clock_domain='host-boot', kind='detector_return')
    # Original identity remains registered even though caller changed its own object.
    assert meter.try_record_result(source(), now_ns=200, clock_domain='host-boot', kind='detector_return')
    fresh = source(1,101)
    fresh.key.__dict__['sensor_id'] = 'x'*10000
    assert not meter.try_record_capture(fresh, width=1, height=1)
    meter.stop()
    records = meter.finalize()['trace']['records']
    assert records[0]['source']['key']['episode_id'] == 'episode-1'


def test_old_live_capture_latency_is_included_even_after_ttl():
    meter = BoundedMeasurements(context())
    old, new = source(0,100), source(1,1_000_000_100)
    assert meter.try_record_capture(old,width=1,height=1)
    assert meter.try_record_capture(new,width=1,height=1)
    assert meter.try_record_result(old,now_ns=2_000_000_100,clock_domain='host-boot',kind='detector_return')
    meter.stop()
    result = meter.finalize()
    assert result['distributions']['capture_to_detector_return_ns']['p95'] == 2_000_000_000.
    assert sum(result['excluded_results'].values()) == 0
    assert result['seed_ack_bound'] and not result['native_eligible_context']


@pytest.mark.parametrize('field,value', [
    ('episode_id', 'text_subclass'), ('sensor_id', 'text_subclass'),
    ('episode_id', 'x'*129), ('sensor_id', '\U0001f642'*129),
    ('frame_index', True), ('frame_index', 1<<64), ('frame_index', 'int_subclass'),
    ('capture_monotonic_ns', True), ('pose_version', 1<<64),
    ('clock_domain', 'text_subclass'), ('calibration_id', 'text_subclass'),
    ('schema_version', 'text_subclass'),
    ('calibration_id', '\ud800'),
])
def test_raw_source_guards_run_before_any_shared_constructor(field,value,monkeypatch):
    callbacks=[]
    class ExternalText(str):
        def strip(self,*args,**kwargs):
            callbacks.append('external_strip')
            return super().strip(*args,**kwargs)
    class ExternalInt(int):
        def __int__(self):
            callbacks.append('external_int')
            return super().__int__()
        def __lt__(self,other):
            callbacks.append('external_lt')
            return super().__lt__(other)
    src = source()
    meter = BoundedMeasurements(context())
    assert meter.try_record_capture(src,width=1,height=1)
    if value == 'text_subclass':
        value = ExternalText('episode-1' if field == 'episode_id' else 'rgbd')
    elif value == 'int_subclass':
        value = ExternalInt(0)
    if field in ('episode_id','sensor_id','frame_index'):
        src.key.__dict__[field] = value
    else:
        object.__setattr__(src,field,value)
    original = FrameKey.__post_init__
    def constructor(key):
        callbacks.append('shared_constructor')
        original(key)
    monkeypatch.setattr(FrameKey,'__post_init__',constructor)
    assert not meter.try_record_capture(src,width=1,height=1)
    assert not meter.try_record_result(src,now_ns=200,clock_domain='host-boot',kind='detector_return')
    assert not meter.try_record_control(src,now_ns=200,clock_domain='host-boot',reason='ok',map_revision=1)
    assert not meter.try_record_admission(src,outcome='offered')
    assert callbacks == []
    meter.stop()
    result = meter.finalize()
    assert result['rejected_records'] == 4 and not result['complete']
