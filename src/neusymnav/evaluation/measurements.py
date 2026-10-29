"""Offline checks for bounded runtime telemetry; never a native certificate.

Recompute distributions and event counts from retained source-bound traces.
An incomplete trace cannot establish a whole-phase percentile or denominator.
Partial execution may retain performance support, never accuracy/completion credit.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import math
import os
import stat
from pathlib import Path

from ..contracts import FrameKey
from ..runtime.measurements import (
    MeasurementContext, MeasurementSource, BoundedMeasurements,
    MAX_INTEGER, MAX_SAMPLES, TRACE_RECORD_CHARGE, CAPTURE_RECORD_CHARGE,
    CONTEXT_CHARGE, DISTRIBUTION_SAMPLE_CHARGE, MAX_TRACE_BYTES,
    _integer, _text, _hash,
)
from .metrics import measured, unavailable, ratio


TOP = {'schema_version','context','seed_ack','launch_config','collector','resources',
       'actuation','graph_support','lifecycle','completion','native_runtime_validated'}
CONTEXT = {'schema_version','attempt_id','episode_id','clock_domain','config_sha256',
           'launch_config_sha256','seed_ack_sha256','sensor_ids'}
SOURCE = {'schema_version','key','capture_monotonic_ns','clock_domain','pose_version','calibration_id'}
KEY = {'episode_id','sensor_id','frame_index'}


def _closed(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label+' fields mismatch')


def _bool(value):
    if type(value) is not bool:raise ValueError('boolean required')
    return value


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _context(value):
    _closed(value,CONTEXT,'measurement context')
    sensors=value['sensor_ids']
    if type(sensors) is not list or not 1<=len(sensors)<=8:raise ValueError('bounded sensor list required')
    return MeasurementContext(**dict(value,sensor_ids=tuple(sensors)))


def _source(value,context):
    _closed(value,SOURCE,'measurement source');key=value['key'];_closed(key,KEY,'source key')
    # Guard raw fields before shared FrameKey constructor (.strip/int coercion).
    _text(key['episode_id'],'episode');_text(key['sensor_id'],'sensor');_integer(key['frame_index'],'frame')
    s=MeasurementSource(**dict(value,key=FrameKey(**key)))
    if s.key.episode_id!=context.episode_id or s.key.sensor_id not in context.sensor_ids or s.clock_domain!=context.clock_domain:
        raise ValueError('measurement source execution mismatch')
    return s


def _collector(value,context,*,export_overflow=False):
    template=BoundedMeasurements(context);template.stop();shape=template.finalize()
    _closed(value,shape,'collector')
    if value['context']!=asdict(context):
        # JSON arrays represent tuple sensor_ids.
        expected=asdict(context);expected['sensor_ids']=list(expected['sensor_ids'])
        if value['context']!=expected:raise ValueError('collector context mismatch')
    for name in ('schema_version','native_eligible_context','native_eligibility_status','evidence_scope','admission_semantics','travel','no_progress'):
        if type(value[name]) is not type(shape[name]) or value[name]!=shape[name]:raise ValueError('collector '+name+' mismatch')
    if _bool(value['seed_ack_bound'])!=(context.seed_ack_sha256 is not None):raise ValueError('collector seed binding mismatch')
    for name in ('complete','counter_saturated'):_bool(value[name])
    for name in ('rejected_records','contention_dropped'):_integer(value[name],name)
    for name in ('admission_counts','excluded_results'):
        _closed(value[name],shape[name],name)
        for count in value[name].values():_integer(count,name)
    if type(value['control_reasons']) is not dict or len(value['control_reasons'])>128:raise ValueError('bounded control reasons required')
    for reason,count in value['control_reasons'].items():_text(reason,'reason');_integer(count,'reason count',minimum=1)
    registry=value['capture_registry'];_closed(registry,shape['capture_registry'],'capture registry')
    cap=_integer(registry['cap'],'capture cap',MAX_SAMPLES,1)
    for name in ('retained','overflow','charged_bytes','byte_cap','record_charge_bytes'):_integer(registry[name],name)
    if registry['retained']>cap or registry['record_charge_bytes']!=CAPTURE_RECORD_CHARGE or registry['byte_cap']!=cap*CAPTURE_RECORD_CHARGE or registry['charged_bytes']!=registry['retained']*CAPTURE_RECORD_CHARGE:raise ValueError('capture registry accounting mismatch')
    storage=value['storage_budget'];_closed(storage,shape['storage_budget'],'collector storage')
    for name,expected in shape['storage_budget'].items():
        if name!='distribution_byte_cap' and (type(storage[name]) is not type(expected) or storage[name]!=expected):raise ValueError('collector storage accounting mismatch')
    sample_bytes=_integer(storage['distribution_byte_cap'],'sample bytes',3*MAX_SAMPLES*DISTRIBUTION_SAMPLE_CHARGE,3*DISTRIBUTION_SAMPLE_CHARGE)
    if sample_bytes%(3*DISTRIBUTION_SAMPLE_CHARGE):raise ValueError('sample budget mismatch')
    sample_cap=sample_bytes//(3*DISTRIBUTION_SAMPLE_CHARGE)
    trace=value['trace']
    if type(trace) is not dict:raise ValueError('trace object required')
    extra={'export_dropped_records'} if 'export_dropped_records' in trace else set()
    _closed(trace,set(shape['trace'])|extra,'trace')
    for name in ('schema_version','record_charge_bytes','storage'):
        if type(trace[name]) is not type(shape['trace'][name]) or trace[name]!=shape['trace'][name]:raise ValueError('trace schema/accounting mismatch')
    _bool(trace['writer_pending']);_integer(trace['dropped'],'trace dropped')
    exported=_integer(trace.get('export_dropped_records',0),'export dropped')
    byte_cap=_integer(trace['byte_cap'],'trace byte cap',MAX_TRACE_BYTES)
    records=trace['records']
    if type(records) is not list or len(records)>MAX_TRACE_BYTES//TRACE_RECORD_CHARGE:raise ValueError('bounded trace required')
    if _integer(trace['charged_bytes'],'trace charged bytes')!=len(records)*TRACE_RECORD_CHARGE or len(records)*TRACE_RECORD_CHARGE>byte_cap:raise ValueError('trace accounting mismatch')
    full=not(trace['dropped'] or exported or trace['writer_pending'] or export_overflow)
    meter=BoundedMeasurements(context,sample_cap=sample_cap,trace_byte_cap=MAX_TRACE_BYTES,capture_cap=cap)
    captures={};unbound=0;admission_stages={};controls=[];live_commits={}
    for record in records:
        if type(record) is not dict or type(record.get('event')) is not str:raise ValueError('closed trace record required')
        event=record['event']
        fields={'capture':{'width','height'},'detector_return':{'now_ns','origin','revision'},'object_commit':{'now_ns','origin','revision'},'control':{'now_ns','reason','map_revision','depth_age_ns'},'admission':{'outcome'}}
        if event not in fields:raise ValueError('unknown trace event')
        _closed(record,{'event','source'}|fields[event],'trace event')
        source=None if record['source'] is None else _source(record['source'],context)
        if source is None and event!='control':raise ValueError('trace event requires source')
        if event=='capture':
            if not meter.try_record_capture(source,width=record['width'],height=record['height']):raise ValueError('capture order/size/identity mismatch')
            captures[source.key]=source
            continue
        if source is not None and source.key in captures and captures[source.key]!=source:raise ValueError('trace source differs from capture')
        missing=source is not None and source.key not in captures
        if missing:
            if full:raise ValueError('trace source absent from captures')
            unbound+=1
        # Validate scalar fields even when the capture trace was dropped.
        if event in ('detector_return','object_commit'):
            _integer(record['now_ns'],'result time')
            if record['now_ns']<source.capture_monotonic_ns:raise ValueError('negative latency')
            if type(record['origin']) is not str or record['origin'] not in ('live','historical','reused','recovery'):raise ValueError('invalid result origin')
            if record['revision'] is not None:_integer(record['revision'],'result revision')
            if event=='object_commit' and record['revision'] is None:raise ValueError('commit revision missing')
            if not missing:
                # False may denote sample overflow; rejection count distinguishes invalidity.
                meter.try_record_result(source,now_ns=record['now_ns'],clock_domain=context.clock_domain,kind=event,origin=record['origin'],revision=record['revision'])
            if event=='object_commit' and record['origin']=='live':live_commits[source.key]=record['revision']
        elif event=='control':
            _integer(record['now_ns'],'control time');_integer(record['map_revision'],'map revision');_text(record['reason'],'control reason')
            age=None if source is None else record['now_ns']-source.capture_monotonic_ns
            if age is not None:_integer(age,'depth age')
            if type(record['depth_age_ns']) is not type(age) or record['depth_age_ns']!=age:raise ValueError('control depth age mismatch')
            if not missing:meter.try_record_control(source,now_ns=record['now_ns'],clock_domain=context.clock_domain,reason=record['reason'],map_revision=record['map_revision'])
            controls.append(record)
        else:
            if type(record['outcome']) is not str or record['outcome'] not in shape['admission_counts']:raise ValueError('invalid admission outcome')
            stages=admission_stages.setdefault(source.key,set());outcome=record['outcome']
            if outcome in stages or full and outcome!='offered' and 'offered' not in stages or outcome in ('durable_accepted','rejected','replaced') and stages&{'durable_accepted','rejected','replaced'}:raise ValueError('duplicate or inconsistent admission stage')
            stages.add(outcome)
            if not missing:meter.try_record_admission(source,outcome=outcome)
    meter.stop();observed=meter.finalize()
    if observed['rejected_records']:raise ValueError('invalid trace ordering or duplicate result')
    _closed(value['distributions'],shape['distributions'],'distributions')
    for name,d in value['distributions'].items():
        _closed(d,shape['distributions'][name],'distribution')
        for field in ('seen','retained','overflow'):_integer(d[field],field)
        if d['retained']!=min(d['seen'],sample_cap) or d['overflow']!=d['seen']-d['retained']:raise ValueError('distribution accounting mismatch')
        for field in ('p50','p95'):
            x=d[field]
            if x is not None and (type(x) not in (int,float) or not 0<=x<=MAX_INTEGER or not math.isfinite(x)):raise ValueError('invalid percentile')
        if not d['seen'] or d['overflow'] or value['counter_saturated']:
            if d['p50'] is not None or d['p95'] is not None:raise ValueError('unsupported whole-phase percentile')
        elif d['p50'] is None or d['p95'] is None or d['reason'] is not None:raise ValueError('supported distribution missing percentile')
        if full and d!=observed['distributions'][name]:raise ValueError('distribution differs from source trace')
        if not full and observed['distributions'][name]['seen']>d['seen']:raise ValueError('trace exceeds declared distribution')
    for name in ('admission_counts','excluded_results','control_reasons'):
        if full and value[name]!=observed[name]:raise ValueError(name+' differs from source trace')
        if not full and any(count>value[name].get(key,0) for key,count in observed[name].items()):raise ValueError(name+' exceeds declared support')
    if full and registry['retained']!=len(captures) or not full and registry['retained']<len(captures):raise ValueError('capture support differs from registry')
    expected_complete=not(value['counter_saturated'] or value['rejected_records'] or value['contention_dropped'] or registry['overflow'] or trace['dropped'] or exported or trace['writer_pending'] or export_overflow or any(d['overflow'] for d in value['distributions'].values()))
    if value['complete']!=expected_complete:raise ValueError('collector completion mismatch')
    return dict(trace_complete=full,unbound_records=unbound,observed=observed,captures=captures,controls=controls,live_commits=live_commits)


def inspect_measurements(value,*,attempt_id,config_sha256,episode_id=None,clock_domain=None):
    """Validate trace consistency and bind external execution identity.

    Seed ACK and raw actuation proof eligibility require the execution-aware
    integration checker; this function never infers eligibility from a hash.
    """
    _closed(value,TOP,'measurement artifact')
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['native_runtime_validated'] is not False:raise ValueError('measurement artifact version/certificate mismatch')
    context=_context(value['context'])
    if context.attempt_id!=attempt_id or context.config_sha256!=config_sha256 or episode_id is not None and context.episode_id!=episode_id or clock_domain is not None and context.clock_domain!=clock_domain:raise ValueError('measurement execution binding mismatch')
    if value['launch_config'] is not None and type(value['launch_config']) is not dict:raise ValueError('launch configuration must be object or null')
    if value['launch_config'] is not None and canonical_sha256(value['launch_config'])!=context.launch_config_sha256:raise ValueError('measurement launch config digest mismatch')
    ack=value['seed_ack']
    if (ack is None)!=(context.seed_ack_sha256 is None) or ack is not None and canonical_sha256(ack)!=context.seed_ack_sha256:raise ValueError('measurement seed ACK digest mismatch')
    completion=value['completion'];_closed(completion,{'complete','cap_breached','cap_breach','observer_errors','export_byte_overflow'},'completion')
    for field in ('complete','cap_breached','export_byte_overflow'):_bool(completion[field])
    _integer(completion['observer_errors'],'observer errors')
    support=_collector(value['collector'],context,export_overflow=completion['export_byte_overflow'])
    resources=resource_metrics(value['resources'])
    navigation=(value['launch_config'] or {}).get('navigation',{})
    if type(navigation) is not dict:raise ValueError('navigation launch object required')
    navigation_sensor=navigation.get('sensor_id')
    if navigation_sensor is not None:_text(navigation_sensor,'navigation sensor')
    actuation=actuation_metrics(value['actuation'],context,support,navigation_sensor=navigation_sensor)
    _lifecycle(value)
    graph=value['graph_support']
    if support['trace_complete'] and not completion['observer_errors'] and not value['collector']['rejected_records']:
        if graph['live_detector_commits']!=len(support['live_commits']):raise ValueError('graph commit count differs from live trace')
    for marker in ('first_object_commit','first_accepted_region'):
        first=graph[marker]
        if first is not None:
            key=FrameKey(**first['source'])
            if key.episode_id!=context.episode_id or key.sensor_id not in context.sensor_ids or support['trace_complete'] and key not in support['captures']:raise ValueError('graph marker source mismatch')
            if marker=='first_object_commit' and support['trace_complete'] and support['live_commits'].get(key)!=first['object_revision']:raise ValueError('first object commit absent from live trace')
    # Execution-aware binding must validate seed/config/worker provenance before
    # native eligibility is considered; this stage never grants acceptance.
    return dict(artifact_sha256=canonical_sha256(value),context=context,trace=support,resources=resources,actuation=actuation,native_eligible=False,native_runtime_validated=False)


def trace_metrics(value,inspection):
    """Only audited full retained traces produce whole-observed-phase metrics."""
    names=('capture_to_result_ms','capture_to_commit_ms','control_depth_age_ms','accepted_fraction','replaced_fraction','control_stop_reasons','stale_fraction')
    result={name:unavailable('retained trace incomplete or telemetry records rejected') for name in names}
    collector=value['collector'];checked=inspection['trace']
    if not checked['trace_complete'] or collector['rejected_records'] or collector['contention_dropped'] or collector['counter_saturated'] or collector['capture_registry']['overflow']:return result
    source='offline recomputed source-bound trace; observed execution phase only, including live queue delay beyond fast TTL'
    for name,key in [('capture_to_result_ms','capture_to_detector_return_ns'),('capture_to_commit_ms','capture_to_object_commit_ns'),('control_depth_age_ms','control_depth_age_ns')]:
        d=checked['observed']['distributions'][key]
        result[name]=measured(dict(p50=d['p50']/1e6,p95=d['p95']/1e6),support=d['seen'],source=source) if d['seen'] and not d['overflow'] else unavailable(d['reason'])
    counts=checked['observed']['admission_counts']
    for name,key in [('accepted_fraction','durable_accepted'),('replaced_fraction','replaced')]:
        result[name]=ratio(counts[key],counts['offered'],denominator_name='offered semantic keyframe events in complete retained trace')
    result['control_stop_reasons']=measured(checked['observed']['control_reasons'],support=sum(checked['observed']['control_reasons'].values()),source=source)
    result['stale_fraction']=unavailable('runtime wiring does not emit all stale transitions; absent events do not establish zero stale fraction')
    return result


def _read_telemetry_json(path, max_bytes):
    """Only these telemetry artifacts have a larger, explicitly bounded reader."""
    from .protocol import _object
    with Path(path).open('rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=max_bytes:
            raise ValueError('telemetry JSON exceeds byte bound or is not regular file')
        payload=stream.read(min(info.st_size,max_bytes)+1)
        if len(payload)!=info.st_size:raise ValueError('telemetry JSON size changed during read')
    try:
        value=json.loads(payload,object_pairs_hook=_object,
            parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite JSON number')))
        return value,len(payload)
    except (RecursionError,UnicodeError) as exc:
        raise ValueError('invalid telemetry JSON') from exc


def load_measurements(path,*,max_bytes=64*1024**2,**binding):
    _integer(max_bytes,'measurement JSON byte cap',64*1024**2,1)
    value,size=_read_telemetry_json(path,max_bytes)
    inspection=inspect_measurements(value,**binding)
    # Reader provenance only, outside the artifact schema and its digest.
    inspection['artifact_path']=Path(path).absolute()
    inspection['artifact_size_bytes']=size
    return value,inspection


def inspect_control_invocations(value,*,clock_domain):
    """Recompute invocation cadence from all starts, including STOP outcomes.

    A retained prefix only verifies lower support. It grants no whole-phase
    quantile or cadence, even when a producer supplied aggregate intervals.
    """
    keys={'schema_version','clock_domain','population','starts_monotonic_ns','total','retained',
          'dropped','complete','cap','navigation_wait','control_results','result_total',
          'result_missing','executed_results','intervals','limitation'}
    _closed(value,keys,'control invocations')
    if type(value['schema_version']) is not int or value['schema_version']!=1:
        raise ValueError('control invocation schema mismatch')
    _text(value['clock_domain'],'control invocation clock')
    if value['clock_domain']!=clock_domain:raise ValueError('control invocation clock mismatch')
    if value['population']!='actual_control_step_invocation_starts_including_stop_and_pending':
        raise ValueError('control invocation population mismatch')
    _text(value['limitation'],'control invocation limitation',maximum=512)
    cap=_integer(value['cap'],'control invocation cap',20000,1)
    for name in ('total','retained','dropped','result_total','result_missing','executed_results'):
        _integer(value[name],name)
    starts=value['starts_monotonic_ns'];total=value['total'];retained=value['retained']
    if (type(starts) is not list or len(starts)>cap or retained!=len(starts)
            or retained!=min(total,cap) or value['dropped']!=total-retained
            or _bool(value['complete'])!=(total==retained)):
        raise ValueError('control invocation retention accounting mismatch')
    previous=None
    for stamp in starts:
        _integer(stamp,'control invocation start')
        if previous is not None and stamp<previous:raise ValueError('control invocation timestamps regressed')
        previous=stamp
    waits=value['navigation_wait'];_closed(waits,{'matched','unmatched','unspecified'},'navigation wait')
    for count in waits.values():_integer(count,'navigation wait count')
    if sum(waits.values())!=total:raise ValueError('navigation wait support mismatch')
    results=value['control_results']
    if type(results) is not dict or len(results)>65:raise ValueError('bounded control results required')
    for reason,count in results.items():
        _text(reason,'control result reason');_integer(count,'control result count',minimum=1)
    if (sum(results.values())!=value['result_total'] or value['result_total']>total
            or value['result_missing']!=total-value['result_total']
            or value['executed_results']>value['result_total']):
        raise ValueError('control result accounting mismatch')
    intervals=value['intervals']
    _closed(intervals,{'count','mean_ns','max_ns','miss_50ms','miss_100ms'},'control intervals')
    count=_integer(intervals['count'],'interval count')
    if count!=max(0,total-1):raise ValueError('control interval count mismatch')
    for name in ('miss_50ms','miss_100ms'):_integer(intervals[name],name,count)
    if intervals['miss_100ms']>intervals['miss_50ms']:raise ValueError('control deadline miss accounting mismatch')
    if count:
        mean=intervals['mean_ns']
        if type(mean) not in (int,float) or not 0<=mean<=MAX_INTEGER or not math.isfinite(mean):
            raise ValueError('invalid control interval mean')
        _integer(intervals['max_ns'],'maximum control interval')
        if mean>intervals['max_ns']:raise ValueError('control mean exceeds maximum')
    elif intervals['mean_ns'] is not None or intervals['max_ns'] is not None:
        raise ValueError('empty control intervals cannot have distributions')
    deltas=[b-a for a,b in zip(starts,starts[1:])]
    observed=dict(count=len(deltas),mean_ns=None if not deltas else sum(deltas)/len(deltas),
        max_ns=None if not deltas else max(deltas),miss_50ms=sum(x>50_000_000 for x in deltas),
        miss_100ms=sum(x>100_000_000 for x in deltas))
    full=value['complete']
    if full and intervals!=observed:raise ValueError('control intervals differ from raw invocation starts')
    if not full and (observed['count']>count or (observed['max_ns'] or 0)>(intervals['max_ns'] or 0)
            or observed['miss_50ms']>intervals['miss_50ms'] or observed['miss_100ms']>intervals['miss_100ms']):
        raise ValueError('retained invocation prefix exceeds declared interval support')
    ordered=sorted(deltas)
    def percentile(p):
        if not full or not ordered:return None
        point=(len(ordered)-1)*p;lower=int(point);upper=min(lower+1,len(ordered)-1)
        return ordered[lower]+(ordered[upper]-ordered[lower])*(point-lower)
    mean=observed['mean_ns'] if full else None
    return dict(complete=full,interval_support=len(deltas),mean_interval_ns=mean,
        p95_interval_ns=percentile(.95),p99_interval_ns=percentile(.99),
        max_interval_ns=observed['max_ns'] if full else None,
        miss_50ms=observed['miss_50ms'] if full else None,
        miss_100ms=observed['miss_100ms'] if full else None,
        mean_invocation_hz=1e9/mean if mean else None)


def load_control_invocations(path,*,clock_domain):
    value,_=_read_telemetry_json(path,1024**2)
    return value,inspect_control_invocations(value,clock_domain=clock_domain)



def resource_metrics(value):
    """Check sampler summaries; these peaks remain sampled provider assertions.

    No raw instantaneous memory trace is available, so this validates accounting
    and scope metadata rather than reconstructing an absolute physical peak.
    """
    names=('rss_peak_bytes','vram_peak_bytes')
    if value is None:return {name:unavailable('resource phase not measured') for name in names}
    _closed(value,{'schema_version','scope','scope_proof','counter_saturated','start_requested_monotonic_ns','stop_requested_monotonic_ns','shutdown_observed_monotonic_ns','rss','gpu','interval_s','gpu_interval_s','gpu_timeout_s','worker_pending','pending_workers','complete','cap_breached','breached_resources','callback_errors','boundedness_certified','limitation'},'resources')
    if value['schema_version']!='runtime_resource_samples_v1' or value['scope']!='provider_root_and_descendants' or value['boundedness_certified'] is not False:raise ValueError('resource schema/scope mismatch')
    _text(value['limitation'],'resource limitation',maximum=512)
    for field in ('counter_saturated','worker_pending','complete','cap_breached'):_bool(value[field])
    _integer(value['callback_errors'],'resource callback errors')
    pending=value['pending_workers'];breached=value['breached_resources']
    for items,allowed in [(pending,{'rss','gpu'}),(breached,{'rss','gpu'})]:
        if type(items) is not list or len(items)>2 or any(type(x) is not str or x not in allowed for x in items) or len(set(items))!=len(items):raise ValueError('invalid resource status list')
    if value['worker_pending']!=bool(pending) or value['cap_breached']!=bool(breached):raise ValueError('resource lifecycle flag mismatch')
    for field in ('interval_s','gpu_interval_s','gpu_timeout_s'):
        duration=value[field]
        if type(duration) not in (int,float) or not 0<duration<=(1 if field=='gpu_timeout_s' else 60) or not math.isfinite(duration):raise ValueError('invalid sampling cadence')
    start,stop,end=(value[field] for field in ('start_requested_monotonic_ns','stop_requested_monotonic_ns','shutdown_observed_monotonic_ns'))
    for stamp in (start,stop,end):
        if stamp is not None:_integer(stamp,'resource lifecycle time')
    if stop is not None and (start is not None and stop<start) or end is not None and (stop is None or end<stop) or value['worker_pending'] and end is not None:raise ValueError('resource lifecycle time order mismatch')
    proof=value['scope_proof'];_closed(proof,{'method','root_pid','root_starttime_ticks','proc_root'},'resource scope proof')
    if proof['method'] not in ('linux_proc_pid_starttime_guard','injected_provider_unverified'):raise ValueError('unknown resource scope method')
    if proof['method']=='linux_proc_pid_starttime_guard':
        _integer(proof['root_pid'],'resource root PID',minimum=1)
        if proof['root_starttime_ticks'] is not None:_integer(proof['root_starttime_ticks'],'root start time')
        _text(proof['proc_root'],'proc root',maximum=4096)
    elif any(proof[field] is not None for field in ('root_pid','root_starttime_ticks','proc_root')):raise ValueError('unverified provider has claimed PID proof')
    rss=value['rss'];gpu=value['gpu']
    _closed(rss,{'samples','support','sampled_peak_bytes','missing_processes','read_errors','identity_changes','truncated_samples','first_sample_ns','last_sample_ns','max_sample_gap_ns','method'},'RSS samples')
    _closed(gpu,{'samples','support','sampled_peak_bytes','unavailable_reason','errors','timeouts','method'},'GPU samples')
    if rss['method']!='sampled_process_tree_rss_sum' or gpu['method']!='injected_process_tree_attributed_gpu_sample':raise ValueError('resource measurement method mismatch')
    result={}
    for channel,name in [(rss,'rss_peak_bytes'),(gpu,'vram_peak_bytes')]:
        for field in ('samples','support'):_integer(channel[field],field)
        if channel['support']>channel['samples']:raise ValueError('resource support exceeds sample count')
        peak=channel['sampled_peak_bytes']
        if channel['support']:
            _integer(peak,'sampled peak')
            if start is None:raise ValueError('resource samples without startup timestamp')
        elif peak is not None:raise ValueError('unsupported resource channel has non-null peak')
        result[name]=measured(dict(sampled_peak_bytes=peak,method=channel['method'],samples=channel['samples'],scope=value['scope'],scope_proof=proof,worker_pending=value['worker_pending'],interval_s=value['interval_s'] if channel is rss else value['gpu_interval_s'],observed_phase='startup_active_worker_cleanup_before_final_export',absolute_peak_proven=False),support=channel['support'],source='pinned resource sampler summary; sampled provider values, no raw instantaneous memory trace') if channel['support'] and not value['worker_pending'] else unavailable('resource sampler pending' if value['worker_pending'] else 'no supported samples')
    for field in ('missing_processes','read_errors','identity_changes','truncated_samples'):_integer(rss[field],field)
    for field in ('errors','timeouts'):_integer(gpu[field],field)
    if rss['truncated_samples']>rss['samples'] or gpu['errors']>gpu['samples'] or gpu['timeouts']>gpu['samples']:raise ValueError('resource error count exceeds samples')
    first,last,gap=(rss[field] for field in ('first_sample_ns','last_sample_ns','max_sample_gap_ns'))
    for stamp in (first,last,gap):
        if stamp is not None:_integer(stamp,'RSS sampling time')
    if rss['samples']:
        if first is None or last is None or start is None or not start<=first<=last or stop is not None and last>stop:raise ValueError('RSS sample lifecycle mismatch')
    elif any(stamp is not None for stamp in (first,last,gap)):raise ValueError('RSS timestamps without samples')
    if rss['samples']<2 and gap is not None:raise ValueError('RSS gap without two samples')
    if gpu['unavailable_reason'] is not None:_text(gpu['unavailable_reason'],'GPU unavailable reason')
    provider_absent=not gpu['samples'] and gpu['unavailable_reason']=='no_usable_provider'
    expected_complete=(stop is not None and end is not None and not pending and rss['samples']>0 and rss['support']==rss['samples'] and not breached and not value['callback_errors'] and not value['counter_saturated'] and (provider_absent or gpu['support']==gpu['samples']>0))
    if value['complete']!=expected_complete:raise ValueError('resource completion mismatch')
    if result['rss_peak_bytes']['support']:
        result['rss_peak_bytes']['value'].update(max_sample_gap_ns=gap,first_sample_ns=first,last_sample_ns=last)
    return result


def actuation_metrics(value,context,trace,*,navigation_sensor):
    from ..runtime.actuation_measurements import validate_actuation_source_proof,summarize_body_poses,_number,_xy
    from ..contracts import MotionCommand
    keys={'schema_version','episode_id','clock_domain','complete','distance_m','frontier_distance_m','observed_body_translation_lower_bound_m','observed_frontier_translation_lower_bound_m','accepted_commands','rejected_records','overflow','sampled_no_progress','limitation','missing_command_proofs','proof_records','body_pose_records','record_cap','record_charge_bytes','record_overflow'}
    if type(value) is not dict:raise ValueError('actuation summary required')
    extra={'export_dropped_records'} if 'export_dropped_records' in value else set()
    _closed(value,keys|extra,'actuation')
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['episode_id']!=context.episode_id or value['clock_domain']!=context.clock_domain or value['complete'] is not False or value['distance_m'] is not None or value['frontier_distance_m'] is not None:raise ValueError('actuation scope/completion mismatch')
    for key in ('accepted_commands','rejected_records','overflow','missing_command_proofs','record_overflow'):_integer(value[key],key)
    dropped=_integer(value.get('export_dropped_records',0),'actuation export dropped')
    cap=_integer(value['record_cap'],'proof record cap',20000,1)
    if cap>min(20000,trace['observed']['capture_registry']['cap']) or type(value['record_charge_bytes']) is not int or value['record_charge_bytes']!=16384:raise ValueError('actuation record accounting mismatch')
    _text(value['limitation'],'actuation limitation',maximum=1024)
    for key in ('proof_records','body_pose_records'):
        if type(value[key]) is not list or len(value[key])>cap:raise ValueError('bounded actuation records required')
    body=frontier=0.;seen=set();unbound=0;frontier_count=0
    command_keys={'source','map_revision','issued_monotonic_ns','deadline_monotonic_ns','clock_domain','linear_mps','yaw_radps','reason','source_capture_monotonic_ns'}
    for record in value['proof_records']:
        _closed(record,{'command','proof','decision'},'actuation record')
        c=record['command'];_closed(c,command_keys,'measured command');_closed(c['source'],KEY,'command source')
        for name in ('episode_id','sensor_id'):_text(c['source'][name],name)
        _integer(c['source']['frame_index'],'command frame')
        for name in ('map_revision','issued_monotonic_ns','deadline_monotonic_ns','source_capture_monotonic_ns'):_integer(c[name],name)
        for name in ('clock_domain','reason'):_text(c[name],name)
        for name in ('linear_mps','yaw_radps'):_number(c[name])
        command=MotionCommand(**dict(c,source=FrameKey(**c['source'])))
        if type(record['proof']) is not dict:raise ValueError('actuation proof object required')
        source=_source(record['proof'].get('source'),context)
        if navigation_sensor is None or source.key.sensor_id!=navigation_sensor:raise ValueError('actuation proof requires declared navigation sensor')
        checked=validate_actuation_source_proof(record['proof'],command,asdict(source),modality='depth_only')
        if source.key in seen:raise ValueError('duplicate actuation source')
        seen.add(source.key)
        registered=trace['captures'].get(source.key)
        if registered is None:
            if trace['trace_complete']:raise ValueError('actuation source absent from capture trace')
            unbound+=1
        elif registered!=source:raise ValueError('actuation source differs from capture trace')
        last_step=max([command.issued_monotonic_ns]+[action['post_step_monotonic_ns'] for action in checked['proof']['actions']])
        if not any(control['source']==asdict(source) and control['map_revision']==command.map_revision and control['now_ns']>=last_step and control['reason']==checked['proof']['reason'] for control in trace['controls']):
            if trace['trace_complete']:raise ValueError('actuation proof lacks matching control return')
            unbound+=1
        decision=record['decision'];_closed(decision,{'goal_id','map_revision','profile'},'actuation decision')
        if decision['goal_id'] is not None:_text(decision['goal_id'],'goal id')
        _text(decision['profile'],'profile')
        if _integer(decision['map_revision'],'decision map')!=command.map_revision:raise ValueError('actuation decision map mismatch')
        body+=checked['body_translation_m']
        if decision['goal_id'] is not None and decision['profile'] in ('baseline','geometry-only','appearance'):
            frontier+=checked['body_translation_m'];frontier_count+=1
    poses=[]
    for record in value['body_pose_records']:
        _closed(record,{'source','robot_xy','yaw_rad'},'body pose record')
        source=_source(record['source'],context);_xy(record['robot_xy']);_number(record['yaw_rad'])
        if navigation_sensor is None or source.key.sensor_id!=navigation_sensor:raise ValueError('body pose requires navigation source')
        registered=trace['captures'].get(source.key)
        if registered is None:
            if trace['trace_complete']:raise ValueError('body pose absent from capture trace')
            unbound+=1
        elif registered!=source:raise ValueError('body pose differs from capture trace')
        poses.append((source.capture_monotonic_ns,record['robot_xy']))
    sampled=summarize_body_poses(poses)
    all_records=not(dropped or value['record_overflow'])
    if value['accepted_commands']<len(seen) or all_records and value['accepted_commands']!=len(seen):raise ValueError('actuation command support mismatch')
    for name,recomputed in [('observed_body_translation_lower_bound_m',body),('observed_frontier_translation_lower_bound_m',frontier)]:
        reported=_number(value[name])
        if reported<0 or reported+1e-9<recomputed or all_records and not math.isclose(reported,recomputed,rel_tol=1e-12,abs_tol=1e-9):raise ValueError('actuation endpoint sum mismatch')
    if all_records and value['sampled_no_progress']!=sampled:raise ValueError('sampled no-progress differs from body records')
    if not all_records:
        _closed(value['sampled_no_progress'],sampled,'sampled no-progress')
        # Declared summary is never used without all underlying body records.
    supported=not(unbound or dropped or value['record_overflow'] or value['rejected_records'] or value['overflow'])
    return dict(distance_m=unavailable('whole-run body coverage unavailable; endpoint sums are partial lower bounds'),
        observed_body_translation_lower_bound_m=measured(body,support=len(seen),source='offline recomputed captured native-step endpoint proof; partial lower bound') if supported and seen else unavailable('no complete source-bound actuation proof support'),
        observed_frontier_translation_lower_bound_m=measured(frontier,support=frontier_count,source='same endpoint proofs plus goal/map/profile provenance; partial lower bound') if supported and frontier_count else unavailable('no complete source-bound frontier proof support'),
        no_progress_intervals=measured(sampled,support=len(poses),source='offline recomputed sampled body poses; no continuous immobility claim') if supported and poses else unavailable('no complete source-bound sampled body pose support'))


def _lifecycle(value):
    lifecycle=value['lifecycle'];completion=value['completion'];resources=value['resources'];act=value['actuation']
    _closed(lifecycle,{'runtime_clean_shutdown','runtime_pending','launcher_cleanup_clean','launcher_cleanup_status','outcome','resources_observed_phase','resource_scope_limitation'},'measurement lifecycle')
    for name in ('runtime_clean_shutdown','launcher_cleanup_clean'):_bool(lifecycle[name])
    if lifecycle['runtime_pending'] is not None:_integer(lifecycle['runtime_pending'],'runtime pending')
    status=lifecycle['launcher_cleanup_status']
    if status is not None:
        if type(status) is not dict or not set(status)<={'sensor','ui','resources','raw_recorder'}:raise ValueError('unknown launcher cleanup status')
        for clean in status.values():_bool(clean)
    if lifecycle['launcher_cleanup_clean']!=(status is not None and all(status.values())):raise ValueError('launcher cleanup certificate mismatch')
    if lifecycle['outcome'] is not None and lifecycle['outcome'] not in ('completed','incomplete','failed','runtime_finished'):raise ValueError('measurement outcome mismatch')
    if lifecycle['resources_observed_phase']!='startup_active_worker_cleanup_before_final_export':raise ValueError('resource measurement phase mismatch')
    _text(lifecycle['resource_scope_limitation'],'resource scope limitation',maximum=512)
    if completion['cap_breached']:
        cap=completion['cap_breach'];_closed(cap,{'resource','sampled_bytes','cap_bytes'},'resource cap breach')
        if cap['resource'] not in ('rss','gpu') or _integer(cap['sampled_bytes'],'sampled bytes')<=_integer(cap['cap_bytes'],'cap bytes',minimum=1):raise ValueError('invalid sampled cap breach')
    elif completion['cap_breach'] is not None:raise ValueError('cap payload without breach')
    expected=bool(value['collector']['complete'] and lifecycle['runtime_clean_shutdown'] and lifecycle['launcher_cleanup_clean'] and resources is not None and resources['complete'] and not completion['cap_breached'] and not completion['observer_errors'] and not act['record_overflow'] and not act['rejected_records'] and not act['overflow'] and not completion['export_byte_overflow'])
    if completion['complete']!=expected:raise ValueError('measurement completion certificate inconsistent')
    graph=value['graph_support'];_closed(graph,{'live_detector_commits','live_object_evidence_commits','first_object_commit','first_accepted_region','first_assigned_membership'},'graph support')
    for name in ('live_detector_commits','live_object_evidence_commits'):_integer(graph[name],name)
    if graph['live_object_evidence_commits']>graph['live_detector_commits']:raise ValueError('object commit support exceeds detector commits')
    first=graph['first_object_commit']
    if first is not None:
        _closed(first,{'source','object_revision','object_ids','committed_event_count'},'first object commit')
        _closed(first['source'],KEY,'first object source')
        for name in ('episode_id','sensor_id'):_text(first['source'][name],name)
        _integer(first['source']['frame_index'],'first object frame');_integer(first['object_revision'],'first object revision');_integer(first['committed_event_count'],'committed event count',minimum=1)
        if type(first['object_ids']) is not list or not first['object_ids'] or len(first['object_ids'])>MAX_SAMPLES:raise ValueError('bounded object ID support required')
        for object_id in first['object_ids']:_text(object_id,'object id')
        if len(set(first['object_ids']))!=len(first['object_ids']) or not graph['live_object_evidence_commits']:raise ValueError('first object support mismatch')
    elif graph['live_object_evidence_commits']:raise ValueError('missing first object evidence')
    first=graph['first_accepted_region']
    if first is not None:
        _closed(first,{'source','map_revision','region_revision','region_ids'},'first accepted region')
        _closed(first['source'],KEY,'first region source')
        for name in ('episode_id','sensor_id'):_text(first['source'][name],name)
        _integer(first['source']['frame_index'],'first region frame')
        for name in ('map_revision','region_revision'):_integer(first[name],name)
        if type(first['region_ids']) is not list or not first['region_ids'] or len(first['region_ids'])>MAX_SAMPLES:raise ValueError('bounded region ID support required')
        for region_id in first['region_ids']:_text(region_id,'region id')
        if len(set(first['region_ids']))!=len(first['region_ids']):raise ValueError('duplicate first region ID')
    first=graph['first_assigned_membership']
    if first is not None:
        _closed(first,{'object_id','region_id','object_revision','map_revision','region_revision'},'first assigned membership')
        for name in ('object_id','region_id'):_text(first[name],name)
        for name in ('object_revision','map_revision','region_revision'):_integer(first[name],name)
