import copy,json
import pytest
from test_runtime_measurement_wiring import session
from test_runtime_scheduling import source
from neusymnav.evaluation.measurements import (inspect_measurements,trace_metrics,resource_metrics,
    canonical_sha256,analyze_control_stages)
from neusymnav.runtime.measurements import TRACE_RECORD_CHARGE


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


def test_offline_trace_accepts_and_validates_source_bound_stage_timing():
    value=artifact();trace=value['collector']['trace']
    source=copy.deepcopy(trace['records'][0]['source'])
    capture_ns=source['capture_monotonic_ns']
    stage=dict(event='stage',source=source,stage='navmap_update',start_ns=capture_ns-10,
        end_ns=capture_ns+10,duration_ns=20)
    trace['records'].insert(1,stage);trace['charged_bytes']+=TRACE_RECORD_CHARGE
    assert inspect(value)['trace']['trace_complete']
    stage['stage']='unregistered_stage'
    with pytest.raises(ValueError):inspect(value)
    stage['stage']='navmap_update'
    stage['duration_ns']=19
    with pytest.raises(ValueError):inspect(value)


def test_control_stage_report_binds_source_windows_and_does_not_sum_overlapping_phases():
    value=artifact();trace=value['collector']['trace'];source=copy.deepcopy(trace['records'][0]['source'])
    capture_ns=source['capture_monotonic_ns']
    for stage,duration in (('navmap_update',20),('navmap_core_integrate',12),('control_loop',5)):
        trace['records'].insert(1,dict(event='stage',source=copy.deepcopy(source),stage=stage,
            start_ns=capture_ns+10,end_ns=capture_ns+10+duration,duration_ns=duration))
        trace['charged_bytes']+=TRACE_RECORD_CHARGE
    checked=inspect(value);report=analyze_control_stages(value,checked)
    assert report['trace_complete'] is True
    assert report['stages']['navmap_update']['p95_ms']==0.00002
    assert report['stages']['navmap_core_integrate']['max_ms']==0.000012
    assert report['stages']['control_loop']['support']==1
    assert report['composition_note'].startswith('Stage durations overlap')


def test_incomplete_stage_trace_reports_observed_support_but_withholds_percentiles():
    value=artifact(trace_cap=8192);checked=inspect(value)
    report=analyze_control_stages(value,checked)
    assert report['trace_complete'] is False
    assert report['stages']['navmap_update']['support']==0
    assert report['stages']['navmap_update']['p95_ms'] is None
    assert report['stages']['navmap_update']['status']=='unavailable'


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


def test_resource_sample_trace_has_validated_bounded_provenance():
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();rss=report['rss']
    trace=rss['sample_trace']
    metrics=resource_metrics(report)
    assert metrics['rss_peak_bytes']['value']['sample_trace_provenance']==dict(
        schema_version=1,retained_records=len(trace),dropped_records=rss['sample_trace_dropped'],
        record_cap=rss['sample_trace_cap'],discarded_after_stop=rss['discarded_after_stop'])


def test_resource_complete_trace_reconciles_sampled_peak_and_support():
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report()
    report['rss']['sampled_peak_bytes']=0
    with pytest.raises(ValueError):resource_metrics(report)


def test_resource_complete_trace_rejects_record_peak_below_summary_peak():
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report()
    for record in report['rss']['sample_trace']:record['rss_bytes']=0
    assert report['rss']['sampled_peak_bytes']==1234
    with pytest.raises(ValueError):resource_metrics(report)


def test_resource_complete_trace_reconciles_provider_errors_and_aggregate_support():
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();record=report['rss']['sample_trace'][0]
    record.update(rss_bytes=None,supported=False,read_errors=1)
    with pytest.raises(ValueError):resource_metrics(report)


@pytest.mark.parametrize('field',[
    'missing_processes','read_errors','identity_changes','truncated_samples',
    'first_sample_ns','last_sample_ns','max_sample_gap_ns',
])
def test_resource_complete_trace_reconciles_error_and_time_summaries(field):
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();summary=report['rss']
    summary[field]=(summary[field] or 0)+1
    with pytest.raises(ValueError):resource_metrics(report)


def test_resource_sampler_rollback_withholds_provider_support_and_adds_read_error():
    import time
    from neusymnav.runtime.resources import ResourceSampler,ResourceReading
    from neusymnav.evaluation.measurements import resource_metrics
    stamps=None
    def provider():
        nonlocal stamps
        if stamps is None:
            base=time.monotonic_ns();stamps=iter((base+1,base+100,base+50,base+200))
        return ResourceReading(next(stamps),1234,1)
    sampler=ResourceSampler(provider=provider,interval_s=.1)
    sampler.start();deadline=time.monotonic()+2
    while sampler.snapshot()['rss']['samples']<4 and time.monotonic()<deadline:time.sleep(.001)
    report=sampler.close(timeout_s=1.)
    assert report['rss']['support']==3
    assert report['rss']['read_errors']==1
    assert all(record['supported'] for record in report['rss']['sample_trace'])
    assert resource_metrics(report)['rss_peak_bytes']['value']['sampled_peak_bytes']==1234


def test_resource_discarded_after_stop_record_does_not_change_accepted_aggregates():
    import copy
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();rss=report['rss']
    discarded=copy.deepcopy(rss['sample_trace'][-1])
    discarded.update(disposition='discarded_after_stop',rss_bytes=987654321)
    discarded['sampled_at_ns']=discarded['received_ns']
    rss['sample_trace'].append(discarded);rss['discarded_after_stop']+=1
    assert resource_metrics(report)['rss_peak_bytes']['value']['sampled_peak_bytes']==rss['sampled_peak_bytes']


def test_resource_dropped_trace_uses_retained_aggregate_lower_bounds():
    import copy
    from neusymnav.runtime.resources import MAX_RESOURCE_DIAGNOSTIC_RECORDS
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();rss=report['rss'];record=copy.deepcopy(rss['sample_trace'][0])
    rss['sample_trace']=[copy.deepcopy(record) for _ in range(MAX_RESOURCE_DIAGNOSTIC_RECORDS)]
    rss.update(samples=MAX_RESOURCE_DIAGNOSTIC_RECORDS+1,support=MAX_RESOURCE_DIAGNOSTIC_RECORDS+1,
        sampled_peak_bytes=record['rss_bytes'],missing_processes=0,read_errors=0,identity_changes=0,
        truncated_samples=0,first_sample_ns=record['sampled_at_ns'],last_sample_ns=record['sampled_at_ns'],
        max_sample_gap_ns=0,sample_trace_dropped=1)
    assert resource_metrics(report)['rss_peak_bytes']['support']==MAX_RESOURCE_DIAGNOSTIC_RECORDS+1
    report['complete']=False
    rss['support']=MAX_RESOURCE_DIAGNOSTIC_RECORDS-1
    with pytest.raises(ValueError):resource_metrics(report)


def _current_control_invocation_report():
    from neusymnav.runtime.launcher import _ControlInvocations
    obs=source();trace=_ControlInvocations(4)
    trace.record(1,navigation_ready=True)
    trace.skip_run_deadline(obs,navigation_ready=True)
    trace.skip_run_deadline(obs,navigation_ready=False)
    return trace.snapshot(obs.clock_domain)


def test_control_invocation_inspector_accepts_current_producer_deadline_skips():
    from neusymnav.evaluation.measurements import inspect_control_invocations
    value=_current_control_invocation_report()
    assert value['run_deadline_skips']['total']==2
    assert inspect_control_invocations(value,clock_domain=value['clock_domain'])['complete']


def test_control_invocation_inspector_keeps_older_artifact_without_deadline_skips():
    from neusymnav.evaluation.measurements import inspect_control_invocations
    value=_current_control_invocation_report();value.pop('run_deadline_skips')
    assert inspect_control_invocations(value,clock_domain=value['clock_domain'])['complete']


@pytest.mark.parametrize('mutate',[
    lambda value:value['run_deadline_skips'].update(total=1),
    lambda value:value['run_deadline_skips'].update(navigation_ready=True),
    lambda value:value['run_deadline_skips']['last_source'].update(frame_index=True),
    lambda value:value['run_deadline_skips']['last_source'].update(extra='field'),
])
def test_control_invocation_inspector_rejects_forged_deadline_skips(mutate):
    from neusymnav.evaluation.measurements import inspect_control_invocations
    value=_current_control_invocation_report();mutate(value)
    with pytest.raises(ValueError):inspect_control_invocations(value,clock_domain=value['clock_domain'])


@pytest.mark.parametrize('mutate',[
    lambda rss:rss.update(sample_trace_schema_version=2),
    lambda rss:rss['sample_trace'][0].update(unexpected='field'),
    lambda rss:rss.update(discarded_after_stop=rss['discarded_after_stop']+1),
    lambda rss:rss['sample_trace'][0].update(received_ns=0),
])
def test_resource_sample_trace_rejects_unknown_or_inconsistent_provenance(mutate):
    from neusymnav.evaluation.measurements import resource_metrics
    report=resource_report();mutate(report['rss'])
    with pytest.raises(ValueError):resource_metrics(report)


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
    from neusymnav.contracts import NavigationDecision
    decision=NavigationDecision('frontier1',((1.,2.),),command.linear_mps,
        command.yaw_radps,command.map_revision,'frontier')
    m.control(obs,proof['actions'][-1]['post_step_monotonic_ns'],{'reason':'executed'},
        command=command,proof=proof,decision=decision,profile='baseline')
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


@pytest.mark.parametrize('mutate',[
    lambda value:value.update(extra='unrecognized'),
    lambda value:value.update(command_deadline_monotonic_ns=value['command_issued_monotonic_ns']-1),
    lambda value:value.update(decision_linear_mps=float('inf')),
    lambda value:value.update(failure_detail='invented_failure'),
])
def test_control_diagnostics_are_closed_and_bounded(mutate):
    value=moving_artifact();diagnostics=value['collector']['trace']['records'][1]['diagnostics']
    mutate(diagnostics)
    with pytest.raises(ValueError):inspect(value)


def test_control_navigation_diagnostics_require_versioned_closed_shape():
    value=moving_artifact();record=value['collector']['trace']['records'][1]
    record['navigation']=dict(schema_version=1,goal_id='frontier1',goal_xy=[1.,2.],
        path_point_count=1,path_sample_xy=[[1.,2.]],path_sample_truncated=False,
        lookahead_xy=None,heading_error_rad=0.,decision_reason='frontier')
    assert inspect(value)['actuation']['observed_body_translation_lower_bound_m']['value']==pytest.approx(.01)
    record['navigation']['schema_version']=2
    with pytest.raises(ValueError,match='schema'):
        inspect(value)


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
