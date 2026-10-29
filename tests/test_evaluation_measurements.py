import copy,json
import pytest
from test_runtime_measurement_wiring import session
from test_runtime_scheduling import source
from neusymnav.evaluation.measurements import inspect_measurements,trace_metrics,resource_metrics,canonical_sha256


def artifact(*,trace_cap=64*1024**2,sample_cap=65536):
    from neusymnav.runtime.observability import RunMeasurements
    base=session();m=RunMeasurements(base.context,trace_byte_cap=trace_cap,sample_cap=sample_cap)
    obs=source()
    m.capture(obs);m.admission(obs,'offered');m.admission(obs,'durable_accepted')
    m.result(obs,obs.capture_monotonic_ns+2_000_000_000,'detector_return')
    m.result(obs,obs.capture_monotonic_ns+2_100_000_000,'object_commit',revision=1)
    m.control(obs,obs.capture_monotonic_ns+300_000_001,{'reason':'depth_stale'},profile='baseline')
    value=json.loads(json.dumps(m.finalize(runtime_report={'clean_shutdown':True},resources=None)))
    value['graph_support']['live_detector_commits']=1
    return value


def inspect(value):
    return inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)


def test_offline_trace_recomputes_queued_latency_and_preserves_partial_execution_support():
    value=artifact();checked=inspect(value);metrics=trace_metrics(value,checked)
    assert metrics['capture_to_result_ms']['value']==dict(p50=2000.,p95=2000.)
    assert metrics['capture_to_commit_ms']['value']==dict(p50=2100.,p95=2100.)
    assert metrics['control_depth_age_ms']['value']==dict(p50=300.000001,p95=300.000001)
    assert metrics['accepted_fraction']['value']==1.
    assert metrics['stale_fraction']['value'] is None
    assert not value['completion']['complete'] and not checked['native_eligible']


@pytest.mark.parametrize('mutate',[
    lambda x:x['collector']['distributions']['capture_to_detector_return_ns'].update(p95=1.),
    lambda x:x['collector']['admission_counts'].update(durable_accepted=0),
    lambda x:x['collector']['trace']['records'][3]['source'].update(calibration_id='different'),
    lambda x:x['collector']['trace']['records'][3]['source'].update(clock_domain='other'),
    lambda x:x['context'].update(config_sha256='c'*64),
    lambda x:x['collector']['trace']['records'][5].update(depth_age_ns=0),
    lambda x:x['collector']['capture_registry'].update(retained=0,charged_bytes=0),
    lambda x:x['collector']['trace'].update(charged_bytes=0),
    lambda x:x.update(seed_ack={'seed':1}),
    lambda x:x.update(native_runtime_validated=True),
])
def test_offline_trace_rejects_forged_summary_or_provenance(mutate):
    value=artifact();mutate(value)
    with pytest.raises(ValueError):inspect(value)


def test_dropped_trace_cannot_publish_whole_observed_phase_percentiles_or_fraction():
    value=artifact(trace_cap=8192)
    checked=inspect(value);metrics=trace_metrics(value,checked)
    assert not checked['trace']['trace_complete']
    assert metrics['capture_to_result_ms']['value'] is None
    assert metrics['accepted_fraction']['value'] is None


def test_unbound_partial_result_is_not_fabricated_as_registered_capture():
    value=artifact();trace=value['collector']['trace'];trace['records'].pop(0);trace['charged_bytes']-=8192;trace['dropped']=1;value['collector']['complete']=False
    checked=inspect(value)
    assert checked['trace']['unbound_records']==5
    assert checked['trace']['observed']['capture_registry']['retained']==0
    assert trace_metrics(value,checked)['capture_to_result_ms']['support']==0


def test_sample_overflow_does_not_become_window_percentile():
    from neusymnav.runtime.observability import RunMeasurements
    m=RunMeasurements(session().context,sample_cap=1)
    for i in range(2):
        obs=source(i,stamp=1_000_000_000+i);m.capture(obs);m.result(obs,1_000_000_100+i,'detector_return')
    value=json.loads(json.dumps(m.finalize(runtime_report={'clean_shutdown':True},resources=None)))
    checked=inspect(value)
    assert trace_metrics(value,checked)['capture_to_result_ms']['value'] is None
    value['collector']['distributions']['capture_to_detector_return_ns'].update(p50=100.,p95=100.)
    with pytest.raises(ValueError):inspect(value)


def resource_report():
    import time
    from neusymnav.runtime.resources import ResourceSampler,ResourceReading
    sampler=ResourceSampler(provider=lambda:ResourceReading(time.monotonic_ns(),1234,1),interval_s=.002)
    sampler.start()
    deadline=time.monotonic()+1
    while sampler.snapshot()['rss']['samples']<2 and time.monotonic()<deadline:time.sleep(.001)
    return sampler.close(timeout_s=1.)


def test_resource_sampled_peak_remains_explicitly_sampled_not_absolute():
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();metrics=resource_metrics(report)
    rss=metrics['rss_peak_bytes']
    assert rss['value']['sampled_peak_bytes']==1234
    assert rss['value']['absolute_peak_proven'] is False
    assert rss['value']['scope_proof']['method']=='injected_provider_unverified'
    assert metrics['vram_peak_bytes']['value'] is None
    assert report['boundedness_certified'] is False


@pytest.mark.parametrize('mutate',[
    lambda x:x['rss'].update(support=x['rss']['samples']+1),
    lambda x:x['gpu'].update(sampled_peak_bytes=0),
    lambda x:x.update(boundedness_certified=True),
    lambda x:x.update(complete=False),
    lambda x:x['rss'].update(first_sample_ns=0),
    lambda x:x.update(worker_pending=True),
])
def test_resource_summary_cannot_create_unsupported_peak_or_certificate(mutate):
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();mutate(report)
    with pytest.raises(ValueError):resource_metrics(report)


def test_pending_sampler_retains_no_final_peak_credit():
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();report.update(worker_pending=True,pending_workers=['rss'],shutdown_observed_monotonic_ns=None,complete=False)
    assert resource_metrics(report)['rss_peak_bytes']['value'] is None


def moving_artifact():
    from dataclasses import asdict
    from test_actuation_measurements import evidence
    from neusymnav.runtime.observability import RunMeasurements
    from neusymnav.runtime.measurements import MeasurementContext
    from neusymnav.evaluation.measurements import canonical_sha256
    obs,command,proof=evidence();launch={'navigation':{'sensor_id':obs.key.sensor_id}}
    ctx=session().context
    m=RunMeasurements(MeasurementContext(ctx.attempt_id,ctx.episode_id,ctx.clock_domain,ctx.config_sha256,canonical_sha256(launch),None,ctx.sensor_ids))
    m.capture(obs)
    pose=dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=(0.,0.),yaw_rad=0.)
    m.pose(obs,pose)
    from types import SimpleNamespace
    m.control(obs,proof['actions'][-1]['post_step_monotonic_ns'],{'reason':'executed'},command=command,proof=proof,decision=SimpleNamespace(goal_id='frontier1',map_revision=1),profile='baseline')
    return json.loads(json.dumps(m.finalize(runtime_report={'clean_shutdown':True},resources=None,launch_config=launch)))


def test_actual_body_endpoint_proof_recomputed_as_partial_lower_bound():
    value=moving_artifact();checked=inspect(value)
    assert checked['actuation']['distance_m']['value'] is None
    assert checked['actuation']['observed_body_translation_lower_bound_m']['value']==pytest.approx(.01)
    assert checked['actuation']['observed_frontier_translation_lower_bound_m']['value']==pytest.approx(.01)
    assert checked['actuation']['no_progress_intervals']['value']['pose_support']==1


@pytest.mark.parametrize('mutate',[
    lambda x:x['actuation'].update(observed_body_translation_lower_bound_m=999),
    lambda x:x['actuation']['proof_records'][0]['proof']['actions'][0].update(body_after_xy=[0.,.01]),
    lambda x:x['actuation']['body_pose_records'][0]['source'].update(calibration_id='different'),
    lambda x:x['actuation']['sampled_no_progress'].update(interval_count=1),
    lambda x:x['actuation']['proof_records'][0]['decision'].update(map_revision=9),
    lambda x:x['actuation'].update(distance_m=.01),
])
def test_actuation_summary_requires_matching_endpoint_and_source_proof(mutate):
    value=moving_artifact();mutate(value)
    with pytest.raises(ValueError):inspect(value)


def test_pending_cleanup_cannot_be_relabelled_complete():
    value=artifact();value['completion']['complete']=True
    with pytest.raises(ValueError):inspect(value)


def test_actual_cpu_worker_launcher_artifact_is_inspectable(tmp_path,monkeypatch):
    from test_runtime_measurement_wiring import test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    summary=json.loads((tmp_path/'out/summary.json').read_text())
    value=json.loads((tmp_path/'out/measurements.json').read_text())
    checked=inspect_measurements(value,attempt_id=summary['attempt_id'],config_sha256=summary['config_sha256'],episode_id=summary['episode_id'])
    assert checked['trace']['observed']['capture_registry']['retained']>0
    assert not checked['native_eligible']


def test_duplicate_admission_events_cannot_create_acceptance_denominator():
    value=artifact();trace=value['collector']['trace'];trace['records'].insert(2,copy.deepcopy(trace['records'][1]));trace['charged_bytes']+=8192;value['collector']['admission_counts']['offered']+=1
    with pytest.raises(ValueError):inspect(value)


def test_endpoint_proof_needs_corresponding_control_return_after_native_step():
    value=moving_artifact();control=value['collector']['trace']['records'][1]
    control['now_ns']=1_000_000_010;control['depth_age_ns']=10
    value['collector']['distributions']['control_depth_age_ns'].update(p50=10.,p95=10.)
    with pytest.raises(ValueError,match='control return'):inspect(value)


def test_missing_control_in_dropped_trace_cannot_credit_body_proof():
    value=moving_artifact();trace=value['collector']['trace']
    trace['records'].pop(1);trace['charged_bytes']-=8192;trace['dropped']+=1
    value['collector']['complete']=False
    checked=inspect(value)
    assert checked['actuation']['observed_body_translation_lower_bound_m']['value'] is None


def test_control_return_reason_must_match_attached_actuation_proof():
    value=moving_artifact();record=value['collector']['trace']['records'][1]
    record['reason']='control_rejected'
    value['collector']['control_reasons']={'control_rejected':1}
    with pytest.raises(ValueError):inspect(value)


def test_no_frontier_attribution_has_no_frontier_measurement_support():
    value=moving_artifact()
    value['actuation']['proof_records'][0]['decision']['goal_id']=None
    value['actuation']['observed_frontier_translation_lower_bound_m']=0.
    checked=inspect(value)
    assert checked['actuation']['observed_body_translation_lower_bound_m']['value']==pytest.approx(.01)
    assert checked['actuation']['observed_frontier_translation_lower_bound_m']['value'] is None


def test_huge_json_integer_percentile_is_a_validation_error():
    value=artifact()
    value['collector']['distributions']['capture_to_detector_return_ns']['p95']=10**1000
    with pytest.raises(ValueError):inspect(value)


@pytest.mark.parametrize('launch',[[],[1]],ids=['empty-array','nonempty-array'])
def test_array_launch_configuration_is_a_validation_error(launch):
    from neusymnav.evaluation.measurements import canonical_sha256
    value=artifact();value['launch_config']=launch
    checksum=canonical_sha256(launch)
    value['context']['launch_config_sha256']=checksum
    value['collector']['context']['launch_config_sha256']=checksum
    with pytest.raises(ValueError):inspect(value)


def test_huge_resource_cadence_is_a_validation_error():
    value=resource_report();value['interval_s']=10**1000
    with pytest.raises(ValueError):resource_metrics(value)


def test_resource_complete_requires_observed_shutdown_timestamp():
    value=resource_report();assert value['complete']
    value['shutdown_observed_monotonic_ns']=None
    with pytest.raises(ValueError):resource_metrics(value)


@pytest.mark.parametrize('navigation',[None,[],[1],1],ids=['null','empty-array','array','integer'])
def test_nested_navigation_container_is_a_validation_error(navigation):
    value=artifact();value['launch_config']={'navigation':navigation}
    checksum=canonical_sha256(value['launch_config'])
    value['context']['launch_config_sha256']=checksum
    value['collector']['context']['launch_config_sha256']=checksum
    with pytest.raises(ValueError):inspect(value)


def test_null_trace_container_is_a_validation_error():
    value=artifact();value['collector']['trace']=None
    with pytest.raises(ValueError):inspect(value)


def test_partial_trace_with_retained_matching_control_keeps_body_support():
    value=moving_artifact()
    value['collector']['trace']['dropped']=1;value['collector']['complete']=False
    checked=inspect(value)
    assert checked['actuation']['observed_body_translation_lower_bound_m']['value']==pytest.approx(.01)


def test_valid_attributed_zero_motion_keeps_frontier_support():
    value=moving_artifact()
    value['actuation']['proof_records'][0]['proof']['actions'][0]['body_after_xy']=[0.,0.]
    value['actuation']['observed_body_translation_lower_bound_m']=0.
    value['actuation']['observed_frontier_translation_lower_bound_m']=0.
    checked=inspect(value)
    metric=checked['actuation']['observed_frontier_translation_lower_bound_m']
    assert metric['value']==0. and metric['support']==1


def test_unknown_profile_has_no_frontier_support_but_retains_body():
    value=moving_artifact();value['actuation']['proof_records'][0]['decision']['profile']='unrecognized'
    value['actuation']['observed_frontier_translation_lower_bound_m']=0.
    checked=inspect(value)
    assert checked['actuation']['observed_frontier_translation_lower_bound_m']['support']==0
    assert checked['actuation']['observed_body_translation_lower_bound_m']['value']==pytest.approx(.01)


def test_inspection_digest_binds_exact_canonical_artifact():
    value=artifact();checked=inspect(value)
    assert checked['artifact_sha256']==canonical_sha256(value)
    value['lifecycle']['outcome']='failed'
    assert checked['artifact_sha256']!=canonical_sha256(value)


@pytest.mark.parametrize('field',['interval_s','gpu_interval_s','gpu_timeout_s'])
def test_huge_cadence_bounds_all_channels(field):
    report=resource_report();report[field]=10**1000
    with pytest.raises(ValueError):resource_metrics(report)


def test_resource_shutdown_order_is_checked():
    report=resource_report();report['shutdown_observed_monotonic_ns']=report['stop_requested_monotonic_ns']-1
    with pytest.raises(ValueError):resource_metrics(report)
