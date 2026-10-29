"""Closed, hash-pinned offline P10 protocol. Never starts a native campaign.

All frozen scene/seed slots are accounted for. Missing samples retain an explicit
outcome and are never transformed into zero accuracy or successful native runs.
Paths in pins are relative to their containing JSON file unless absolute.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

from .metrics import ratio, runtime_metrics


OUTCOMES={'completed','incomplete','failed','timeout','missing'}


def sha256_file(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON field: '+key)
        result[key]=value
    return result


def read_json(path):
    path=Path(path)
    if path.stat().st_size>16*1024**2:raise ValueError('evaluation JSON exceeds 16 MiB')
    return json.loads(path.read_text(),object_pairs_hook=_object,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite JSON number')))


def closed(value,keys,label):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError(label+' fields must be exactly '+', '.join(sorted(keys)))


def text(value,label):
    if not isinstance(value,str) or not value.strip():raise ValueError(label+' must be nonempty text')


def digest(value):
    if not isinstance(value,str) or len(value)!=64 or any(x not in '0123456789abcdef' for x in value):raise ValueError('expected lowercase SHA-256')


def asset(base,value,*,verify=True):
    closed(value,{'path','sha256'},'asset');text(value['path'],'asset path');digest(value['sha256'])
    path=(Path(base)/value['path']).absolute()
    if verify and sha256_file(path)!=value['sha256']:raise ValueError('asset checksum mismatch: '+str(path))
    return path


def _load_suite(path):
    value=read_json(path);base=Path(path).absolute().parent
    closed(value,{'schema_version','suite_id','scope','requested_scene_count','duration_s','scenes','seeds','profile','budgets','attempts','comparators'},'suite')
    if type(value['schema_version']) is not int or value['schema_version'] not in (1,2):raise ValueError('suite schema_version must be 1 or 2')
    text(value['suite_id'],'suite_id')
    if value['scope'] not in {'native_core','fixture_correctness'}:raise ValueError('invalid suite scope')
    if type(value['requested_scene_count']) is not int or value['requested_scene_count']!=2:raise ValueError('requested_scene_count must be 2')
    if type(value['duration_s']) not in (int,float) or not math.isfinite(value['duration_s']) or not 0<value['duration_s']<=300:raise ValueError('duration_s outside (0,300]')
    seeds=value['seeds']
    if not isinstance(seeds,list) or not 1<=len(seeds)<=2 or any(type(x) is not int or x<0 for x in seeds) or len(set(seeds))!=len(seeds):raise ValueError('need 1..2 unique integer seeds')
    scenes=value['scenes']
    if not isinstance(scenes,list) or not 1<=len(scenes)<=2:raise ValueError('need 1..2 scenes')
    seen=set()
    for scene in scenes:
        closed(scene,{'scene_id','input_kind','input','offline_gt'},'scene');text(scene['scene_id'],'scene_id')
        if scene['scene_id'] in seen:raise ValueError('duplicate scene')
        seen.add(scene['scene_id'])
        if scene['input_kind'] not in {'scene','recording'}:raise ValueError('input_kind must be scene or recording')
        asset(base,scene['input'])
        if scene['offline_gt'] is not None:asset(base,scene['offline_gt'])
    profile=value['profile']
    closed(profile,{'id','appearance_mode','config','model','taxonomy','configured_resolution_hw'},'profile');text(profile['id'],'profile id')
    if profile['appearance_mode']!='off':raise ValueError('P10 core appearance must remain off')
    for name in ('config','model','taxonomy'):asset(base,profile[name])
    hw=profile['configured_resolution_hw']
    if not isinstance(hw,list) or len(hw)!=2 or any(type(n) is not int or n<=0 for n in hw):raise ValueError('invalid configured_resolution_hw')
    budgets=value['budgets'];closed(budgets,{'rss_bytes','vram_bytes','raw_bytes','export_bytes'},'budgets')
    limits=dict(rss_bytes=10*1024**3,vram_bytes=5*1024**3,raw_bytes=2*1024**3,export_bytes=8*1024**3)
    if any(type(budgets[k]) is not int or not 0<budgets[k]<=limits[k] for k in limits):raise ValueError('budget exceeds P10 cap')
    expected={(scene,seed) for scene in seen for seed in seeds};actual=set()
    if not isinstance(value['attempts'],list):raise ValueError('attempts must be list')
    for entry in value['attempts']:
        closed(entry,{'scene_id','seed','result','missing_reason'}|({'execution_config'} if value['schema_version']==2 else set()),'attempt')
        if type(entry['seed']) is not int:raise ValueError('attempt seed must be integer')
        key=(entry['scene_id'],entry['seed'])
        if key not in expected or key in actual:raise ValueError('duplicate or out of suite attempt')
        actual.add(key)
        if value['schema_version']==2:
            from .suite_v2 import validate_attempt_config
            validate_attempt_config(value,base,entry)
        if entry['result'] is None:text(entry['missing_reason'],'missing reason')
        else:
            if entry['missing_reason'] is not None:raise ValueError('recorded attempt cannot have missing_reason')
            asset(base,entry['result'])
    if actual!=expected:raise ValueError('every scheduled slot must be explicitly listed')
    closed(value['comparators'],{'legacy_new','legacy_cg','appearance_on'},'comparators')
    for comparator in value['comparators'].values():
        closed(comparator,{'status','reason','artifact'},'comparator')
        if comparator['status'] not in {'missing','blocked','available'}:raise ValueError('invalid comparator status')
        text(comparator['reason'],'comparator reason')
        if comparator['status']=='available':asset(base,comparator['artifact'])
        elif comparator['artifact'] is not None:raise ValueError('unavailable comparator cannot have artifact')
    return value,base


def _result(base,entry):
    if entry['result'] is None:return dict(outcome='missing',attempted=False,reason=entry['missing_reason'],export=None,provenance=None)
    path=asset(base,entry['result']);record=read_json(path)
    version=record.get('schema_version') if type(record) is dict else None
    if type(version) is not int or version not in (1,2):raise ValueError('result version must be 1 or 2')
    closed(record,{'schema_version','scene_id','seed','outcome','attempted','reason','export','provenance'}|({'measurements','summary'} if version==2 else set()),'result')
    if version==2 and (record['measurements'] is None or record['summary'] is None or record['provenance'] is None):raise ValueError('result v2 requires measurement/summary/provenance pins')
    if record['scene_id']!=entry['scene_id'] or type(record['seed']) is not int or record['seed']!=entry['seed']:raise ValueError('result scene/seed mismatch')
    if record['outcome'] not in OUTCOMES or type(record['attempted']) is not bool:raise ValueError('invalid result outcome/attempted')
    if record['attempted']!=(record['outcome']!='missing'):raise ValueError('only missing slots are unattempted')
    if record['outcome']!='completed':text(record['reason'],'noncomplete reason')
    if record['provenance'] is not None:record['_provenance']=asset(path.parent,record['provenance'])
    if record['export'] is not None:record['_manifest']=asset(path.parent,record['export'])
    elif record['outcome']=='completed':raise ValueError('completed requires pinned export manifest')
    return record


def evaluate_suite(suite_path,*,out)->dict:
    """Evaluate supplied evidence; completed fixture evaluation is not P10 acceptance.

    Native gates stay not_proven without measured traces, RSS/VRAM, progress and
    independent review. A result JSON cannot self-certify those missing proofs.
    Invalid protocol/provenance raises ValueError before any score is published.
    """
    suite_path=Path(suite_path).absolute();suite,base=_load_suite(suite_path)
    output=Path(out).absolute();output.mkdir(parents=True,exist_ok=True)
    frozen_hash=sha256_file(suite_path)
    frozen=output/'frozen-suite.json'
    if frozen.exists() and sha256_file(frozen)!=frozen_hash:raise ValueError('output already belongs to another frozen suite')
    frozen.write_bytes(suite_path.read_bytes())
    counts=dict(planned=len(suite['attempts']),attempted=0,completed=0,incomplete=0,failed=0,timeout=0,missing=0);runs=[]
    executions={name:set() for name in ('attempt_id','export_path','export_sha256','provenance_path','provenance_sha256')}
    measured_executions={name:set() for name in ('attempt_id','measurement_sha256','summary_sha256','provenance_sha256')}
    for entry in suite['attempts']:
        from .metrics import empty_quality
        record=_result(base,entry);metrics=runtime_metrics();quality=empty_quality();limitations=[];checks={}
        declared_outcome=record['outcome']
        if entry['result'] is not None and record['schema_version']!=suite['schema_version']:raise ValueError('suite/result version mismatch')
        if declared_outcome=='completed':
            from .exports import load_runtime_export
            summary,objects,nav,hierarchy=load_runtime_export(record['_manifest'])
            if '_provenance' not in record:raise ValueError('completed record requires pinned execution provenance')
            provenance=read_json(record['_provenance'])
            if provenance['attempt_id']!=summary['attempt_id'] or provenance['clock_domain']!=nav.clock_domain:raise ValueError('execution provenance attempt/clock mismatch')
            execution=dict(attempt_id=summary['attempt_id'],export_path=str(record['_manifest'].resolve()),
                export_sha256=record['export']['sha256'],provenance_path=str(record['_provenance'].resolve()),
                provenance_sha256=record['provenance']['sha256'])
            for name,identity in execution.items():
                if identity in executions[name]:raise ValueError('duplicate completed execution: '+name)
                executions[name].add(identity)
            config_pin=entry['execution_config'] if suite['schema_version']==2 else suite['profile']['config']
            if provenance['config_sha256']!=config_pin['sha256']:raise ValueError('frozen config mismatch')
            from ..runtime.configuration import load_config
            executed_config=load_config(asset(base,config_pin)).data
            if provenance.get('effective_config')!=executed_config:raise ValueError('effective configuration differs from pinned config contents')
            scene=next(s for s in suite['scenes'] if s['scene_id']==entry['scene_id'])
            expected_input=scene['input']['sha256']
            if scene['input_kind']=='recording' and summary.get('source_input_sha256')!=expected_input:raise ValueError('frozen replay input mismatch')
            used=provenance.get('assets',{})
            model_key='fixture.detections' if summary['mode']=='fixture_cpu_no_models' else 'detector.checkpoint'
            if used.get(model_key,{}).get('sha256')!=suite['profile']['model']['sha256']:raise ValueError('frozen model mismatch')
            if scene['input_kind']=='scene' and used.get('sensor_config.scene',{}).get('sha256')!=expected_input:raise ValueError('frozen scene mismatch')
            if summary['mode']=='live' and used.get('detector.taxonomy',{}).get('sha256')!=suite['profile']['taxonomy']['sha256']:raise ValueError('frozen taxonomy mismatch')
            if suite['scope']=='native_core' and summary['mode']!='live':raise ValueError('fixture export cannot satisfy native scheduled attempt')
            resolution=None
            if scene['input_kind']=='recording':
                # Replay has no stochastic seed inlet. Seed 0 denotes the
                # deterministic recording; relabelling it cannot add trials.
                if entry['seed']!=0:raise ValueError('deterministic replay execution requires seed 0')
                from ..recording.replay import ReplayReader
                reader=ReplayReader(asset(base,scene['input']).parent)
                primary=executed_config['episode']['primary_sensor_id'];source_keys=set()
                for observation in reader.source_frames():
                    source_keys.add(observation.key)
                    if observation.key.sensor_id==primary and observation.modality=='rgbd':
                        hw=list(observation.depth_m.shape)
                        if hw!=suite['profile']['configured_resolution_hw']:raise ValueError('recording source resolution differs from frozen resolution')
                        resolution=hw
                if resolution is None:raise ValueError('recording has no executed primary RGB-D resolution support')
                from ..contracts import FrameKey
                for event in summary['events']:
                    if FrameKey(**event['source']) not in source_keys:raise ValueError('event source absent from pinned recording')
            else:
                configured=executed_config.get('sensor_config',{}).get('primary',{}).get('resolution_hw')
                if configured!=suite['profile']['configured_resolution_hw']:raise ValueError('native configured resolution differs from frozen effective configuration')
            if summary['mode']=='live' and suite['schema_version']==1:
                # The locked launcher exports no executed simulator seed. Do
                # not accept a self-reported result seed as execution proof.
                raise ValueError('native execution seed proof unavailable in current runtime exports')
            metrics=runtime_metrics(summary,nav=nav,hierarchy=hierarchy)
            if resolution is not None:
                from .metrics import measured
                metrics['actual_input_resolution_hw']=measured(resolution,source='checksum-validated pinned recording primary RGB-D source frames; replay input, not native sensor trace')
            if suite['schema_version']==2:
                from .suite_v2 import inspect_result
                measured_metrics,measured_checks,phase_summary,phase_artifact=inspect_result(suite,base,entry,record,summary=summary)
                metrics.update(measured_metrics)
            unresolved=sum(event['object_id'] is None for event in summary['events'])
            checks=dict(export_integrity='pass',clean_shutdown='pass',event_summary_complete=summary['events_complete'],event_summary_count=len(summary['events']),events_total=summary['events_total'],unresolved_event_summary_count=unresolved)
            if suite['schema_version']==2:checks.update(measured_checks)
            if unresolved:limitations.append('null event endpoints retain unresolved/unattributed detection evidence; summary does not prove ambiguity cause or canonical identity')
            if scene['offline_gt'] is not None:
                from .gt_isolation import load_offline_gt
                from .metrics import evaluate_objects
                from ..contracts import Taxonomy
                gt=load_offline_gt(asset(base,scene['offline_gt']))
                if gt['scene_id']!=scene['scene_id'] or gt['input_sha256']!=expected_input:raise ValueError('offline GT scene/input mismatch')
                quality=evaluate_objects(objects,gt,Taxonomy.load(asset(base,suite['profile']['taxonomy'])))
            limitations.append('fixture execution proves replay wiring only; no native detection, locomotion, memory peak or latency claim' if summary['mode']=='fixture_cpu_no_models' else 'native acceptance needs complete measured memory/latency/progress evidence')
        else:
            limitations.append('no compatible completed runtime export supplied')
            if suite['schema_version']==2 and entry['result'] is not None:
                from .suite_v2 import inspect_result
                measured_metrics,measured_checks,phase_summary,phase_artifact=inspect_result(suite,base,entry,record)
                metrics.update(measured_metrics);checks.update(measured_checks)
                limitations.append('partial observed execution phase only; no label/geometry/identity accuracy or completed credit')
        if suite['schema_version']==2 and entry['result'] is not None:
            phase_identity=dict(attempt_id=phase_summary['attempt_id'],measurement_sha256=record['measurements']['sha256'],summary_sha256=record['summary']['sha256'],provenance_sha256=record['provenance']['sha256'])
            for name,identity in phase_identity.items():
                if identity in measured_executions[name]:raise ValueError('duplicate measured execution: '+name)
                measured_executions[name].add(identity)
        counts[record['outcome']]+=1;counts['attempted']+=int(record['attempted'])
        runs.append(dict(scene_id=entry['scene_id'],seed=entry['seed'],outcome=record['outcome'],attempted=record['attempted'],reason=record['reason'],
                         metrics=metrics,quality=quality,checks=checks,limitations=limitations))
    failed=counts['failed']+counts['timeout']>0
    gt_scenes={r['scene_id'] for r in runs if r['quality']['geometry']['support']>0}
    support=dict(gt_scenes_with_observed_geometry=len(gt_scenes),labeled_run_objects=sum(r['quality']['label']['support'] for r in runs),
        geometry_visible_run_objects=sum(r['quality']['geometry']['support'] for r in runs),
        gt_object_scope_run_total=sum(r['quality']['geometry'].get('gt_scope_objects',0) for r in runs),
        identity_observations=0,reason='counts include per-attempt support; repeated scene seeds repeat object support, not independent GT objects')
    report=dict(schema_version=suite['schema_version'],suite_id=suite['suite_id'],suite_sha256=frozen_hash,scope=suite['scope'],counts=counts,quality_support=support,
        completion_fraction=ratio(counts['completed'],counts['planned'],denominator_name='all planned scene/seed attempts'),runs=runs,
        outcome='failed' if failed else 'completed' if counts['completed']==counts['planned'] and suite['scope']=='fixture_correctness' else 'incomplete',native_runtime_validated=False,
        configured_resolution_hw=suite['profile']['configured_resolution_hw'],appearance=dict(default='off',promotion='not_proven'),
        comparators=suite['comparators'],gates=dict(hard_correctness='not_proven',export_integrity='pass' if counts['completed']==counts['planned'] else 'not_proven',packaging='fixture_pass' if counts['completed'] and suite['scope']=='fixture_correctness' else 'not_proven',runtime_boundedness='not_proven',useful_core_demonstration='insufficient demonstration'),
        limitations=(['pilot/incomplete: fewer than two pinned scenes'] if len(suite['scenes'])<2 else [])+['Native gates are not auto-certified from result JSON: measured latency/control traces, process-tree RSS/VRAM peaks, native object commits, frontier distance and accepted rooms/memberships plus independent correctness review are required. Existing exports do not provide all instrumentation.'])
    (output/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return report
