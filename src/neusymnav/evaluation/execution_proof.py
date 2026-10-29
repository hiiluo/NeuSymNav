"""Bind measured phases to pinned execution/seed/decoded sensor provenance.

Consistency is not authentication, native acceptance, or a physical calibration
certificate. No worker, model, device or environment is started by this module.
"""
from __future__ import annotations
from pathlib import Path
import os

from .measurements import canonical_sha256,_closed,_integer,_text,_hash
from .metrics import measured,unavailable


ACK_FIELDS={'schema_version','episode_id','clock_domain','seed','seed_method','seed_applied','config_sha256','runtime_version'}
METADATA_FIELDS={'schema_version','launch_config_sha256','worker_script_sha256','execution','seed_status','actual_resolution_hw'}


def _asset(config_path,spec,assets,label):
    _closed(spec,{'path','sha256'},label+' configured asset')
    _text(spec['path'],label+' path',maximum=4096);_hash(spec['sha256'],label+' SHA')
    expected=dict(path=os.path.abspath(Path(config_path).absolute().parent/Path(spec['path']).expanduser()),sha256=spec['sha256'])
    actual=assets.get(label)
    _closed(actual,{'path','sha256'},label+' executed asset')
    if actual!=expected:raise ValueError(label+' execution differs from pinned config asset')
    return expected


def _metadata(value,*,context,ack,worker_sha,launch):
    _closed(value,METADATA_FIELDS,'sensor runtime metadata')
    if type(value['schema_version']) is not int or value['schema_version']!=1 or value['launch_config_sha256']!=context.launch_config_sha256 or value['worker_script_sha256']!=worker_sha or value['execution']!=ack or value['seed_status']!='applied':raise ValueError('sensor execution metadata mismatch')
    dimensions=value['actual_resolution_hw']
    if type(dimensions) is not dict or not set(dimensions)<={'primary','navigation'}:raise ValueError('unknown decoded sensor lane')
    for lane,record in dimensions.items():
        _closed(record,{'resolution_hw','source','capture_monotonic_ns','clock_domain','samples','changed'},'decoded sensor resolution')
        hw=record['resolution_hw'];source=record['source']
        if type(hw) is not list or len(hw)!=2:raise ValueError('decoded resolution pair required')
        for size in hw:_integer(size,'decoded dimension',65536,1)
        _closed(source,{'episode_id','sensor_id','frame_index'},'decoded source')
        for name in ('episode_id','sensor_id'):_text(source[name],name)
        _integer(source['frame_index'],'decoded source index')
        _integer(record['capture_monotonic_ns'],'decoded source timestamp');_integer(record['samples'],'decoded sample count',minimum=1)
        if type(record['changed']) is not bool or record['clock_domain']!=context.clock_domain or source['episode_id']!=context.episode_id or source['sensor_id']!=launch[lane]['sensor_id']:raise ValueError('decoded resolution source/clock mismatch')
    return dimensions


def _measurement_caps(artifact,inspection,summary,config,context):
    """Authorize retained evidence budgets against the exact executed recipe."""
    from ..runtime.measurements import DISTRIBUTION_SAMPLE_CHARGE
    options=config.get('measurements',{})
    capture_cap=options.get('capture_cap',65536)
    sample_cap=options.get('sample_cap',65536)
    trace_cap=options.get('trace_byte_cap',64*1024**2)
    proof_cap=min(capture_cap,options.get('proof_record_cap',4096))
    collector=artifact['collector']
    actual=(collector['capture_registry']['cap'],
            collector['storage_budget']['distribution_byte_cap'],
            collector['trace']['byte_cap'],artifact['actuation']['record_cap'])
    expected=(capture_cap,3*sample_cap*DISTRIBUTION_SAMPLE_CHARGE,trace_cap,proof_cap)
    if actual!=expected:raise ValueError('measurement capture/sample/trace/proof caps differ from pinned recipe')
    export_cap=(64 if 'long_demo' in config else 16)*1024**2
    declared=summary.get('measurement_export_byte_cap',export_cap)
    if type(declared) is not int or declared!=export_cap:
        raise ValueError('measurement export cap differs from pinned recipe')
    size=inspection.get('artifact_size_bytes')
    if size is not None and _integer(size,'measurement artifact size',64*1024**2,1)>export_cap:
        raise ValueError('measurement artifact bytes exceed pinned export cap')
    if 'control_invocations_artifact' not in summary:return
    pin=summary['control_invocations_artifact']
    _closed(pin,{'path','sha256','complete'},'control invocation pin')
    _hash(pin['sha256'],'control invocation SHA')
    if pin['path']!='control-invocations.json' or type(pin['complete']) is not bool:
        raise ValueError('invalid control invocation pin')
    artifact_path=inspection.get('artifact_path')
    if not isinstance(artifact_path,(str,Path)):
        raise ValueError('control artifact requires file-backed measurement inspection')
    target=Path(artifact_path).absolute().parent/'control-invocations.json'
    if target.is_symlink():raise ValueError('control invocation file must not be symlink')
    from .protocol import sha256_file
    from .measurements import load_control_invocations
    try:
        if sha256_file(target)!=pin['sha256']:raise ValueError('control invocation checksum mismatch')
        packet,checked=load_control_invocations(target,clock_domain=context.clock_domain)
    except OSError as exc:
        raise ValueError('cannot read pinned control invocation artifact') from exc
    control_cap=config.get('runtime',{}).get('control_sample_cap',20000)
    if packet['cap']!=control_cap:raise ValueError('control invocation cap differs from pinned recipe')
    if pin['complete']!=checked['complete']:raise ValueError('control invocation pin completeness mismatch')
    if summary.get('outcome')=='completed' and (not checked['complete'] or packet['result_missing']):
        raise ValueError('completed execution control invocation artifact incomplete')


def bind_execution(artifact,inspection,*,provenance,summary,config_path,executed_config,seed):
    """Check exact launch recipe, ACK and separate startup/final sensor metadata.

    Partial startup without an ACK remains supported as an observed resource
    phase; it cannot become seed/resolution proof. Caller must first validate
    artifact trace/summary pins and executed_config against frozen config bytes.
    """
    if inspection.get('artifact_sha256')!=canonical_sha256(artifact):raise ValueError('inspection belongs to different or mutated measurement artifact')
    context=inspection['context'];_integer(seed,'suite seed',2**32-1)
    from .protocol import sha256_file
    from ..runtime.configuration import load_config
    if sha256_file(config_path)!=context.config_sha256 or load_config(config_path).data!=executed_config:raise ValueError('effective config argument differs from pinned file bytes')
    for value in (summary,provenance):
        if type(value) is not dict or value.get('attempt_id')!=context.attempt_id or value.get('config_sha256')!=context.config_sha256:raise ValueError('execution attempt/config differs from measurement context')
    if provenance.get('effective_config')!=executed_config or provenance.get('clock_domain')!=context.clock_domain:raise ValueError('effective execution config/clock mismatch')
    if summary.get('mode')!='live' or not context.clock_domain.startswith('host_monotonic:'):raise ValueError('measured seed proof requires live host clock')
    if executed_config.get('mode')!='live' or executed_config.get('episode',{}).get('id')!=context.episode_id:raise ValueError('configured measurement episode/mode mismatch')
    if summary.get('episode_id',context.episode_id)!=context.episode_id:raise ValueError('summary measurement episode mismatch')
    _measurement_caps(artifact,inspection,summary,executed_config,context)
    launch=artifact['launch_config'];sensor=executed_config.get('sensor_config')
    if type(sensor) is not dict or type(sensor.get('seed')) is not int or sensor['seed']!=seed:raise ValueError('configured seed differs from scheduled seed')
    assets=provenance.get('assets')
    if type(assets) is not dict:raise ValueError('execution asset provenance required')
    expected=dict(sensor);scene=expected.pop('scene',None);dataset=expected.pop('scene_dataset',None)
    expected['scene_id']=_asset(config_path,scene,assets,'sensor_config.scene')['path']
    if dataset is not None:expected['scene_dataset_config_file']=_asset(config_path,dataset,assets,'sensor_config.scene_dataset')['path']
    expected['episode_id']=context.episode_id
    if launch!=expected or canonical_sha256(expected)!=context.launch_config_sha256:raise ValueError('resolved sensor launch differs from pinned recipe')
    launch_proof=provenance.get('sensor_launch');_closed(launch_proof,{'configuration','config_sha256','runtime_metadata'},'sensor launch provenance')
    if launch_proof['configuration']!=launch or launch_proof['config_sha256']!=context.launch_config_sha256:raise ValueError('startup launch provenance mismatch')
    sensors=[]
    for lane in ('primary','navigation'):
        if type(launch.get(lane)) is not dict:raise ValueError('declared sensor lane required')
        sensors.append(_text(launch[lane].get('sensor_id'),'sensor id'))
    if len(set(sensors))!=2 or tuple(sensors)!=context.sensor_ids or executed_config['episode'].get('primary_sensor_id')!=sensors[0]:raise ValueError('measurement context sensor lanes mismatch')
    if artifact['lifecycle']['outcome']!=summary.get('outcome'):raise ValueError('measurement outcome differs from runtime summary')
    cleanup=summary.get('cleanup',{})
    if type(cleanup) is not dict:raise ValueError('summary cleanup required')
    expected_cleanup={name:certificate.get('clean_shutdown') is True if type(certificate) is dict else False for name,certificate in cleanup.items()}
    if artifact['lifecycle']['launcher_cleanup_status']!=expected_cleanup:raise ValueError('measurement cleanup differs from runtime summary')
    if summary.get('outcome')=='completed' and not artifact['completion']['complete']:raise ValueError('completed execution has incomplete measured phase')
    worker_runtime=summary.get('worker_runtime',{})
    if type(worker_runtime) is not dict:raise ValueError('summary worker runtime must be an object')
    ack=artifact['seed_ack']
    unsupported=unavailable('sensor startup did not produce executed seed/decoded resolution support')
    if ack is None:
        if summary.get('outcome')=='completed' or launch_proof['runtime_metadata'] is not None or provenance.get('phase')!='before_sensor_model_startup':raise ValueError('absent seed ACK inconsistent with startup phase')
        if inspection['trace']['observed']['capture_registry']['retained']:raise ValueError('capture trace without startup ACK')
        return dict(native_eligible_context=False,seed_execution=unsupported,actual_input_resolution_hw=unsupported,native_runtime_validated=False)
    _closed(ack,ACK_FIELDS,'executed seed ACK')
    if type(ack['schema_version']) is not int or ack['schema_version']!=1 or type(ack['seed']) is not int or ack['seed']!=seed or ack['seed_applied'] is not True or ack['seed_method']!='habitat_sim.Simulator.seed' or ack['episode_id']!=context.episode_id or ack['clock_domain']!=context.clock_domain or ack['config_sha256']!=context.launch_config_sha256:raise ValueError('executed seed ACK mismatch')
    _text(ack['runtime_version'],'Habitat runtime version',maximum=256)
    if launch_proof['runtime_metadata'] is None and provenance.get('phase')=='before_sensor_model_startup' and summary.get('outcome')!='completed':
        if inspection['trace']['observed']['capture_registry']['retained']:raise ValueError('captures present before recorded startup ACK')
        return dict(native_eligible_context=False,seed_execution=unavailable('ACK only retained in partial artifact; no acknowledged startup execution provenance'),actual_input_resolution_hw=unsupported,native_runtime_validated=False)
    worker_spec=executed_config.get('workers',{}).get('sensor',{}).get('script')
    worker=_asset(config_path,worker_spec,assets,'workers.sensor.script')
    start=_metadata(launch_proof['runtime_metadata'],context=context,ack=ack,worker_sha=worker['sha256'],launch=launch)
    if 'navigation' not in start:raise ValueError('recorded startup provenance lacks first navigation capture')
    final_metadata=worker_runtime.get('sensor')
    if final_metadata is None:
        if summary.get('outcome')=='completed':raise ValueError('completed sensor execution lacks final decoded metadata')
        final={}
    else:final=_metadata(final_metadata,context=context,ack=ack,worker_sha=worker['sha256'],launch=launch)
    # Startup captured navigation only; final metadata may add primary captures.
    for lane,record in start.items():
        last=final.get(lane)
        if last is not None and (last['samples']<record['samples'] or last['source']['frame_index']<record['source']['frame_index'] or last['capture_monotonic_ns']<record['capture_monotonic_ns']):raise ValueError('decoded sensor metadata went backward')
    from ..contracts import FrameKey
    captures=inspection['trace']['captures'];rows={}
    capture_records={FrameKey(**r['source']['key']):r for r in artifact['collector']['trace']['records'] if r['event']=='capture'}
    audited_primary=[]
    for lane,record in final.items():
        key=FrameKey(**record['source']);registered=captures.get(key)
        capture_record=capture_records.get(key)
        if registered is not None and (registered.capture_monotonic_ns!=record['capture_monotonic_ns'] or capture_record is None or [capture_record['height'],capture_record['width']]!=record['resolution_hw']):raise ValueError('decoded resolution differs from registered capture')
        if summary.get('outcome')=='completed' and (registered is None or record['changed'] or record['resolution_hw']!=launch[lane].get('resolution_hw')):raise ValueError('completed decoded resolution unsupported or changed')
        lane_captures=[(source,capture_records[source_key]) for source_key,source in captures.items() if source_key.sensor_id==key.sensor_id]
        if any(source.key.frame_index>key.frame_index or source.capture_monotonic_ns>record['capture_monotonic_ns'] for source,_ in lane_captures):raise ValueError('final decoded source precedes audited capture')
        # Navigation startup is captured before Pipeline exists. Count its
        # distinct source once for consistency, without adding metadata-only
        # samples to the audited primary-resolution population.
        startup=start.get(lane)
        if not record['changed'] and (any([capture['height'],capture['width']]!=record['resolution_hw'] for _,capture in lane_captures) or
                (startup is not None and (startup['changed'] or startup['resolution_hw']!=record['resolution_hw']))):
            raise ValueError('decoded stable resolution contradicts observed dimensions or startup change')
        startup_missing=startup is not None and FrameKey(**startup['source']) not in captures
        if record['samples']<len(lane_captures)+int(startup_missing):raise ValueError('decoded sample counter smaller than observed sources')
        if lane=='primary':audited_primary=[capture for _,capture in lane_captures if [capture['height'],capture['width']]==record['resolution_hw']]
        rows[lane]=record
    primary=rows.get('primary')
    resolution=unavailable('no audited primary RGB-D capture at the final decoded resolution')
    if primary is not None and audited_primary:
        subset=not inspection['trace']['trace_complete'] or len(audited_primary)!=primary['samples']
        resolution=measured(primary['resolution_hw'],support=len(audited_primary),source='source-unique audited capture trace '+('subset' if subset else 'population')+' at final decoded primary RGB-D resolution; metadata sample counter='+str(primary['samples'])+'; startup metadata is separate; changed='+str(primary['changed']))
    if summary.get('outcome')=='completed' and (primary is None or 'navigation' not in rows):raise ValueError('completed run requires both decoded sensor lanes')
    return dict(native_eligible_context=bool(artifact['completion']['complete'] and primary is not None and not primary['changed']),seed_execution=measured(dict(seed=seed,method=ack['seed_method'],runtime_version=ack['runtime_version']),source='startup executed seed ACK bound to exact config/attempt/host clock; consistency, not independent physical authentication'),actual_input_resolution_hw=resolution,native_runtime_validated=False)
