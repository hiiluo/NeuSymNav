"""Execution-config and partial measurement seams for version-two suites."""
from __future__ import annotations
from pathlib import Path
import copy
import yaml


def planned_config(path):
    """Read pinned template bytes without pretending missing calibration is ready."""
    path=Path(path)
    if path.stat().st_size>256*1024:raise ValueError('planned config exceeds byte bound')
    payload=path.read_text()
    for token in yaml.scan(payload):
        if isinstance(token,(yaml.tokens.AliasToken,yaml.tokens.AnchorToken)):raise ValueError('planned config aliases forbidden')
    node=yaml.compose(payload)
    def check(n,depth=0):
        if depth>16:raise ValueError('planned config nesting bound')
        if isinstance(n,yaml.MappingNode):
            keys=set()
            for key,child in n.value:
                if not isinstance(key,yaml.ScalarNode) or key.value in keys:raise ValueError('planned config duplicate or complex key')
                keys.add(key.value);check(child,depth+1)
        elif isinstance(n,yaml.SequenceNode):
            for child in n.value:check(child,depth+1)
    check(node);value=yaml.safe_load(payload)
    if type(value) is not dict:raise ValueError('planned config mapping required')
    return value


def recipe(value,base):
    """Only episode ID and simulator seed vary within a frozen recipe.

    Asset paths are resolved relative to their own config before comparison.
    """
    def normalize(item):
        if type(item) is dict:
            if set(item)=={'path','sha256'}:
                from .protocol import digest,text
                digest(item['sha256']);text(item['path'],'recipe asset path')
                import os
                return dict(path=os.path.abspath(Path(base)/Path(item['path']).expanduser()),sha256=item['sha256'])
            return {k:normalize(v) for k,v in item.items()}
        if type(item) is list:return [normalize(v) for v in item]
        return item
    result=normalize(copy.deepcopy(value))
    if type(result.get('episode')) is not dict or type(result.get('sensor_config')) is not dict:raise ValueError('v2 requires episode and sensor recipe')
    result['episode'].pop('id',None);result['sensor_config'].pop('seed',None)
    return result


def validate_attempt_config(suite,base,entry,*,executed=False):
    from .protocol import asset
    path=asset(base,entry['execution_config']);profile_path=asset(base,suite['profile']['config'])
    if executed:
        from ..runtime.configuration import load_config
        value=load_config(path).data
    else:value=planned_config(path)
    reference=planned_config(profile_path)
    seed=value.get('sensor_config',{}).get('seed')
    if type(seed) is not int or seed!=entry['seed'] or not 0<=seed<=2**32-1:raise ValueError('execution_config seed mismatch')
    if recipe(value,path.parent)!=recipe(reference,profile_path.parent):raise ValueError('execution_config differs from frozen recipe beyond seed/episode')
    if value.get('sensor_config',{}).get('primary',{}).get('resolution_hw')!=suite['profile']['configured_resolution_hw']:raise ValueError('configured resolution differs from frozen profile')
    if value.get('mode')!='live' or value.get('appearance_mode','off')!='off':raise ValueError('v2 requires seeded live appearance-off recipe')
    return path,value


def inspect_result(suite,base,entry,record,*,summary=None):
    """Pinned failed phases retain performance only; no coherent graph invented."""
    from .protocol import asset,read_json
    from .measurements import load_measurements,trace_metrics
    from .execution_proof import bind_execution
    config_path,config=validate_attempt_config(suite,base,entry,executed=True)
    record_path=asset(base,entry['result']);root=record_path.parent
    provenance=read_json(record['_provenance'])
    pinned_summary=read_json(asset(root,record['summary']))
    if summary is not None and summary!=pinned_summary:raise ValueError('result pinned summary differs from export summary')
    summary=pinned_summary
    if summary.get('outcome')!=record['outcome']:raise ValueError('result outcome differs from measured runtime summary')
    measurement_path=asset(root,record['measurements'])
    if record['outcome']=='completed':
        manifest=read_json(record['_manifest'])
        if manifest.get('schema_version')!=2 or manifest.get('files',{}).get('measurements.json')!=record['measurements']['sha256'] or (record['_manifest'].parent/'measurements.json').resolve()!=measurement_path.resolve() or (record['_manifest'].parent/'summary.json').resolve()!=asset(root,record['summary']).resolve():raise ValueError('completed result pins differ from measured export bundle')
    # Summary pin resolves from the summary's own directory, independently of
    # the result record's base (both may be in different output directories).
    summary_path=asset(root,record['summary'])
    pin=summary.get('measurement_artifact')
    if asset(summary_path.parent,pin).resolve()!=measurement_path.resolve() or pin['sha256']!=record['measurements']['sha256']:raise ValueError('result and summary measurement pins differ')
    artifact,inspection=load_measurements(measurement_path,attempt_id=summary['attempt_id'],config_sha256=entry['execution_config']['sha256'],episode_id=config['episode']['id'])
    execution=bind_execution(artifact,inspection,provenance=provenance,summary=summary,config_path=config_path,executed_config=config,seed=entry['seed'])
    from .execution_proof import _asset
    detector=config.get('detector',{})
    for key,profile_key in [('checkpoint','model'),('taxonomy','taxonomy')]:
        spec=detector.get(key)
        if type(spec) is not dict or spec.get('sha256')!=suite['profile'][profile_key]['sha256']:raise ValueError('frozen detector '+profile_key+' recipe mismatch')
        _asset(config_path,spec,provenance['assets'],'detector.'+key)
    scene=next(s for s in suite['scenes'] if s['scene_id']==entry['scene_id'])
    if scene['input_kind']!='scene' or provenance['assets'].get('sensor_config.scene',{}).get('sha256')!=scene['input']['sha256']:raise ValueError('measured v2 scene differs from scheduled input')
    metrics=trace_metrics(artifact,inspection);metrics.update(inspection['resources']);metrics.update(inspection['actuation'])
    metrics['actual_input_resolution_hw']=execution['actual_input_resolution_hw']
    checks=dict(measurement_integrity='pass',seed_execution=execution['seed_execution'],native_eligible_context=execution['native_eligible_context'],measurement_complete=artifact['completion']['complete'])
    return metrics,checks,summary,artifact
