"""Closed long-demo export evidence, independent timing and bounded proofs."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from neusymnav.evaluation.exports import load_runtime_export
from neusymnav.evaluation.measurements import load_measurements, inspect_measurements


def timing():
    return dict(schema_version=1, clock_domain='fixture',
        population='actual_control_step_invocation_starts_including_stop_and_pending',
        starts_monotonic_ns=[1_000_000_000,1_050_000_000,1_150_000_000,1_300_000_000],
        total=4,retained=4,dropped=0,complete=True,cap=20000,
        navigation_wait=dict(matched=2,unmatched=1,unspecified=1),
        control_results=dict(executed=1,depth_stale=3),result_total=4,result_missing=0,executed_results=1,
        intervals=dict(count=3,mean_ns=100_000_000.,max_ns=150_000_000,miss_50ms=2,miss_100ms=1),
        limitation='capture/map waits contribute to intervals; no timer catchup; raw quantiles require complete starts')


def bundle(tmp_path, *, trace=None):
    from neusymnav.runtime.launcher import replay
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'export'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    value=timing() if trace is None else trace
    manifest=json.loads((root/'export-manifest.json').read_text())
    value['clock_domain']=manifest['clock_domain']
    (root/'control-invocations.json').write_text(json.dumps(value))
    checksum=hashlib.sha256((root/'control-invocations.json').read_bytes()).hexdigest()
    summary=json.loads((root/'summary.json').read_text())
    summary['control_invocations_artifact']=dict(path='control-invocations.json',sha256=checksum,complete=value['complete'])
    (root/'summary.json').write_text(json.dumps(summary))
    manifest['files']['summary.json']=hashlib.sha256((root/'summary.json').read_bytes()).hexdigest()
    manifest['files']['control-invocations.json']=checksum
    (root/'export-manifest.json').write_text(json.dumps(manifest))
    return root,manifest,summary


def test_completed_bundle_accepts_only_pinned_control_starts(tmp_path):
    root,_,_=bundle(tmp_path)
    summary,*_=load_runtime_export(root/'export-manifest.json')
    assert summary['control_invocations_artifact']['complete'] is True


def test_timing_inspector_recomputes_all_intervals_including_stop():
    from neusymnav.evaluation.measurements import inspect_control_invocations
    checked=inspect_control_invocations(timing(),clock_domain='fixture')
    assert checked['mean_interval_ns']==100_000_000.
    assert checked['p95_interval_ns']==pytest.approx(145_000_000.)
    assert checked['p99_interval_ns']==pytest.approx(149_000_000.)
    assert checked['miss_50ms']==2 and checked['miss_100ms']==1
    assert checked['interval_support']==3 and checked['complete']
    assert checked['mean_invocation_hz']==10.


@pytest.mark.parametrize('mutate',[
    lambda x:x['intervals'].update(mean_ns=1.),
    lambda x:x['intervals'].update(miss_50ms=0),
    lambda x:x['intervals'].update(max_ns=100),
    lambda x:x['intervals'].update(count=2),
    lambda x:x.update(clock_domain='other'),
    lambda x:x.update(complete=False),
    lambda x:x.update(cap=20001),
    lambda x:x.update(starts_monotonic_ns=[1_000_000_000,0,1_150_000_000,1_300_000_000]),
    lambda x:x.update(starts_monotonic_ns=[True,1_050_000_000,1_150_000_000,1_300_000_000]),
    lambda x:x.update(retained=3),
    lambda x:x.update(result_total=3),
    lambda x:x.update(executed_results=5),
    lambda x:x.update(unknown=True),
    lambda x:x['navigation_wait'].update(matched=10),
], ids=['mean','misses','max','count','clock','complete','cap','regressed','boolean','retained','results','executed','extra','waits'])
def test_timing_inspector_rejects_forged_or_unbounded_evidence(mutate):
    from neusymnav.evaluation.measurements import inspect_control_invocations
    value=timing();mutate(value)
    with pytest.raises(ValueError):inspect_control_invocations(value,clock_domain='fixture')


def test_truncated_timing_cannot_publish_whole_phase_quantiles():
    from neusymnav.evaluation.measurements import inspect_control_invocations
    value=timing();value.update(cap=2,retained=2,dropped=2,complete=False)
    value['starts_monotonic_ns']=value['starts_monotonic_ns'][:2]
    checked=inspect_control_invocations(value,clock_domain='fixture')
    assert not checked['complete']
    assert checked['p95_interval_ns'] is None and checked['mean_invocation_hz'] is None


@pytest.mark.parametrize('kind',['unknown-file','missing-pin','wrong-pin','pin-extra','incomplete'])
def test_export_rejects_unclosed_or_unbound_control_evidence(tmp_path,kind):
    value=timing()
    if kind=='incomplete':
        value.update(cap=2,retained=2,dropped=2,complete=False);value['starts_monotonic_ns']=value['starts_monotonic_ns'][:2]
    root,manifest,summary=bundle(tmp_path,trace=value)
    if kind=='unknown-file':
        (root/'arbitrary.json').write_text('{}');manifest['files']['arbitrary.json']=hashlib.sha256(b'{}').hexdigest()
    if kind=='missing-pin':summary.pop('control_invocations_artifact')
    if kind=='wrong-pin':summary['control_invocations_artifact']['sha256']='0'*64
    if kind=='pin-extra':summary['control_invocations_artifact']['extra']=True
    (root/'summary.json').write_text(json.dumps(summary));manifest['files']['summary.json']=hashlib.sha256((root/'summary.json').read_bytes()).hexdigest()
    (root/'export-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):load_runtime_export(root/'export-manifest.json')


def test_long_proof_cap_preserves_independent_endpoint_checks():
    from test_evaluation_measurements import moving_artifact
    value=moving_artifact();value['actuation']['record_cap']=20000
    checked=inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)
    assert checked['actuation']['observed_body_translation_lower_bound_m']['value']==pytest.approx(.01)
    value['actuation']['proof_records'][0]['proof']['actions'][0]['body_after_xy']=[0.,.01]
    with pytest.raises(ValueError):inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)


@pytest.mark.parametrize('cap',[True,0,20001,65536])
def test_proof_cap_stays_bounded(cap):
    from test_evaluation_measurements import moving_artifact
    value=moving_artifact();value['actuation']['record_cap']=cap
    with pytest.raises(ValueError):inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)


def test_measurement_reader_accepts_bounded_long_export_without_raising_other_json_caps(tmp_path):
    from test_evaluation_measurements import artifact
    from neusymnav.evaluation.protocol import read_json
    path=tmp_path/'measurements.json';path.write_text(json.dumps(artifact())+' '*(16*1024**2))
    value,checked=load_measurements(path,attempt_id='test-attempt',config_sha256='a'*64)
    assert checked['context'].attempt_id=='test-attempt'
    with pytest.raises(ValueError):read_json(path)
    with pytest.raises(ValueError):load_measurements(path,max_bytes=16*1024**2,attempt_id='test-attempt',config_sha256='a'*64)


def test_measurement_reader_rejects_over_64mib_before_read(tmp_path):
    path=tmp_path/'measurements.json'
    with path.open('wb') as stream:stream.truncate(64*1024**2+1)
    with pytest.raises(ValueError):load_measurements(path,attempt_id='test-attempt',config_sha256='a'*64)


def test_proof_cap_cannot_exceed_capture_registry_capacity():
    from test_evaluation_measurements import moving_artifact
    value=moving_artifact()
    value['collector']['capture_registry'].update(cap=2,byte_cap=2*8192)
    value['actuation']['record_cap']=3
    with pytest.raises(ValueError,match='actuation record accounting'):
        inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)


def test_long_trace_bound_does_not_disable_source_inspection():
    from test_evaluation_measurements import moving_artifact
    value=moving_artifact();value['collector']['trace']['byte_cap']=512*1024**2
    checked=inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)
    assert checked['trace']['trace_complete']
    value['actuation']['body_pose_records'][0]['source']['calibration_id']='wrong-calibration'
    with pytest.raises(ValueError,match='differs from capture'):
        inspect_measurements(value,attempt_id='test-attempt',config_sha256='a'*64)


def test_export_checks_control_digest_before_decoding(tmp_path):
    root,_,_=bundle(tmp_path)
    target=root/'control-invocations.json';target.write_text(target.read_text()+' ')
    with pytest.raises(ValueError,match='checksum'):
        load_runtime_export(root/'export-manifest.json')


def test_timing_empty_population_has_no_fabricated_percentile():
    from neusymnav.evaluation.measurements import inspect_control_invocations
    value=timing();value.update(total=0,retained=0,starts_monotonic_ns=[],navigation_wait=dict(matched=0,unmatched=0,unspecified=0),control_results={},result_total=0,executed_results=0)
    value['intervals']=dict(count=0,mean_ns=None,max_ns=None,miss_50ms=0,miss_100ms=0)
    checked=inspect_control_invocations(value,clock_domain='fixture')
    assert checked['interval_support']==0
    assert checked['mean_invocation_hz'] is None and checked['p95_interval_ns'] is None


def test_telemetry_duplicate_fields_are_rejected(tmp_path):
    from test_evaluation_measurements import artifact
    payload=json.dumps(artifact());path=tmp_path/'measurements.json'
    path.write_text(payload[:-1]+',"schema_version":1}')
    with pytest.raises(ValueError,match='duplicate'):
        load_measurements(path,attempt_id='test-attempt',config_sha256='a'*64)


def execution_inspection(value,args):
    return inspect_measurements(value,attempt_id=args['summary']['attempt_id'],config_sha256=args['summary']['config_sha256'])


def repin_execution_config(value,args):
    args['config_path'].write_text(json.dumps(args['executed_config']))
    checksum=hashlib.sha256(args['config_path'].read_bytes()).hexdigest()
    value['context']['config_sha256']=checksum
    value['collector']['context']['config_sha256']=checksum
    args['summary']['config_sha256']=checksum
    args['provenance']['config_sha256']=checksum
    args['provenance']['effective_config']=copy.deepcopy(args['executed_config'])


@pytest.mark.parametrize('change',[
    lambda a,k:a['actuation'].update(record_cap=20000),
    lambda a,k:a['actuation'].update(record_cap=2048),
    lambda a,k:a['collector']['trace'].update(byte_cap=512*1024**2),
    lambda a,k:a['collector']['capture_registry'].update(cap=65535,byte_cap=65535*8192),
    lambda a,k:a['collector']['storage_budget'].update(distribution_byte_cap=3*65535*64),
    lambda a,k:k['summary'].update(measurement_export_byte_cap=64*1024**2),
], ids=['long-proof-in-legacy','lower-proof-than-config','long-trace-in-legacy','capture-cap','sample-cap','export-cap'])
def test_execution_binding_rejects_caps_different_from_pinned_recipe(tmp_path,change):
    from test_execution_proof import execution
    from neusymnav.evaluation.execution_proof import bind_execution
    value,_,args=execution(tmp_path);change(value,args)
    checked=execution_inspection(value,args)
    with pytest.raises(ValueError,match='cap|budget'):
        bind_execution(value,checked,**args)


def test_execution_binding_accepts_explicit_long_effective_caps(tmp_path):
    from test_execution_proof import execution
    from neusymnav.evaluation.execution_proof import bind_execution
    value,_,args=execution(tmp_path)
    args['executed_config'].update(long_demo=dict(max_duration_s=600,payload_format='npz_v2'),
        measurements=dict(enabled=True,capture_cap=10000,sample_cap=20000,trace_byte_cap=512*1024**2,proof_record_cap=15000))
    repin_execution_config(value,args)
    value['collector']['capture_registry'].update(cap=10000,byte_cap=10000*8192)
    value['collector']['storage_budget']['distribution_byte_cap']=3*20000*64
    value['collector']['trace']['byte_cap']=512*1024**2
    value['actuation']['record_cap']=10000
    args['summary']['measurement_export_byte_cap']=64*1024**2
    checked=execution_inspection(value,args)
    assert bind_execution(value,checked,**args)['seed_execution']['support']==1


def test_execution_binding_requires_control_bytes_for_pinned_optional_artifact(tmp_path):
    from test_execution_proof import execution
    from neusymnav.evaluation.execution_proof import bind_execution
    value,checked,args=execution(tmp_path)
    args['summary']['control_invocations_artifact']=dict(path='control-invocations.json',sha256='0'*64,complete=True)
    with pytest.raises(ValueError,match='control|artifact'):
        bind_execution(value,checked,**args)


@pytest.mark.parametrize('kind',['valid','wrong-cap','bad-digest','symlink'])
def test_execution_binding_checks_optional_control_cap_and_sibling_pin(tmp_path,kind):
    from test_execution_proof import execution
    from neusymnav.evaluation.execution_proof import bind_execution
    value,_,args=execution(tmp_path)
    args['executed_config']['runtime']=dict(primary_hz=5,navigation_hz=20,control_sample_cap=1000)
    repin_execution_config(value,args)
    packet=timing();packet['clock_domain']=value['context']['clock_domain'];packet['cap']=20000 if kind=='wrong-cap' else 1000
    target=tmp_path/'control-invocations.json';target.write_text(json.dumps(packet))
    if kind=='symlink':
        other=tmp_path/'other-control.json';target.rename(other);target.symlink_to(other)
    checksum=hashlib.sha256(target.read_bytes()).hexdigest()
    args['summary']['control_invocations_artifact']=dict(path=target.name,sha256='0'*64 if kind=='bad-digest' else checksum,complete=True)
    path=tmp_path/'measurements.json';path.write_text(json.dumps(value))
    _,checked=load_measurements(path,attempt_id=args['summary']['attempt_id'],config_sha256=args['summary']['config_sha256'])
    if kind=='valid':assert bind_execution(value,checked,**args)['seed_execution']['support']==1
    else:
        with pytest.raises(ValueError,match='control|cap|symlink|checksum'):
            bind_execution(value,checked,**args)


def test_incomplete_execution_retains_seed_support_with_truncated_control_prefix(tmp_path):
    from test_execution_proof import execution
    from neusymnav.evaluation.execution_proof import bind_execution
    value,_,args=execution(tmp_path)
    args['executed_config']['runtime']=dict(primary_hz=5,navigation_hz=20,control_sample_cap=2)
    repin_execution_config(value,args)
    packet=timing();packet.update(clock_domain=value['context']['clock_domain'],cap=2,retained=2,dropped=2,complete=False)
    packet['starts_monotonic_ns']=packet['starts_monotonic_ns'][:2]
    target=tmp_path/'control-invocations.json';target.write_text(json.dumps(packet))
    args['summary']['control_invocations_artifact']=dict(path=target.name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),complete=False)
    path=tmp_path/'measurements.json';path.write_text(json.dumps(value))
    _,checked=load_measurements(path,attempt_id=args['summary']['attempt_id'],config_sha256=args['summary']['config_sha256'])
    result=bind_execution(value,checked,**args)
    assert result['seed_execution']['support']==1
    assert result['native_runtime_validated'] is False
    args['summary']['control_invocations_artifact']['complete']=True
    with pytest.raises(ValueError,match='complete|pin'):
        bind_execution(value,checked,**args)


def test_legacy_file_backed_measurements_cannot_exceed_pinned_export_cap(tmp_path):
    from test_execution_proof import execution
    from neusymnav.evaluation.execution_proof import bind_execution
    value,_,args=execution(tmp_path)
    path=tmp_path/'measurements.json';path.write_text(json.dumps(value)+' '*(16*1024**2))
    _,checked=load_measurements(path,attempt_id=args['summary']['attempt_id'],config_sha256=args['summary']['config_sha256'])
    with pytest.raises(ValueError,match='cap|budget'):
        bind_execution(value,checked,**args)
