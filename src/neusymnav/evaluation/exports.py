"""Validate public runtime bundles before using any of their measurements."""
from __future__ import annotations
from .protocol import read_json, closed, digest, sha256_file


def load_runtime_export(manifest_path):
    from ..contracts import ObjectSnapshot,NavSnapshot,HierarchySnapshot,FrameKey
    from ..contracts.serialization import loads
    import numpy as np
    manifest_path=manifest_path.absolute();root=manifest_path.parent;manifest=read_json(manifest_path)
    closed(manifest,{'schema_version','clock_domain','files'},'export manifest')
    version=manifest['schema_version']
    if type(version) is not int or version not in (1,2):raise ValueError('export schema version mismatch')
    required={'summary.json','objects.json','nav.json','hierarchy.json'}
    if version==2:required.add('measurements.json')
    optional={'control-invocations.json'}
    if not isinstance(manifest['files'],dict) or set(manifest['files']) not in (required,required|optional):raise ValueError('completed export requires exact '+('five-file' if version==2 else 'four-file')+' bundle')
    for name,checksum in manifest['files'].items():
        digest(checksum)
        if (root/name).is_symlink():raise ValueError('export file must not be symlink')
        if sha256_file(root/name)!=checksum:raise ValueError('export checksum mismatch: '+name)
    summary=read_json(root/'summary.json')
    if summary.get('outcome')!='completed':raise ValueError('completed record has noncomplete runtime summary')
    obj=loads((root/'objects.json').read_text());nav=loads((root/'nav.json').read_text());hier=loads((root/'hierarchy.json').read_text())
    if not isinstance(obj,ObjectSnapshot) or not isinstance(nav,NavSnapshot) or not isinstance(hier,HierarchySnapshot):raise ValueError('export snapshot type mismatch')
    runtime=summary['runtime'];telemetry=runtime['metrics'];domain=manifest['clock_domain']
    if obj.episode_id!=nav.episode_id or obj.episode_id!=hier.episode_id or summary['episode_id']!=obj.episode_id:raise ValueError('export episode mismatch')
    if hier.object_revision!=obj.revision or hier.map_revision!=nav.revision:raise ValueError('export object/map revision mismatch')
    if nav.clock_domain!=domain or telemetry['configuration']['clock_domain']!=domain or any(o.clock_domain!=domain for o in obj.objects.values()):raise ValueError('export clock mismatch')
    revisions=dict(object=obj.revision,map=nav.revision,region=hier.region_revision,latest_nav=hier.latest_nav_revision)
    if summary.get('source_revisions')!=revisions:raise ValueError('summary source revisions mismatch')
    if set(summary.get('object_ids',[]))!=set(obj.objects):raise ValueError('summary canonical object ids mismatch')
    hierarchy_objects={key for key,node in hier.nodes.items() if node.kind=='object'}
    if hierarchy_objects!=set(obj.objects):raise ValueError('hierarchy canonical objects mismatch')
    for key,state in obj.objects.items():
        node=hier.nodes[key]
        projected_fields={'floor_id','raw_label','category','lifecycle','evidence_refs','centroid','bounds','aliases'}
        if not projected_fields<=node.attributes.keys():raise ValueError('hierarchy object projection fields missing')
        for name in ('floor_id','raw_label','category','lifecycle','evidence_refs'):
            if node.attributes.get(name)!=getattr(state,name):raise ValueError('hierarchy object '+name+' mismatch')
        for name in ('centroid','bounds'):
            projected=node.attributes.get(name);canonical=getattr(state,name)
            if not isinstance(projected,np.ndarray) or projected.dtype.kind!='f' or projected.shape!=canonical.shape or not np.array_equal(projected,canonical):
                raise ValueError('hierarchy object '+name+' geometry mismatch')
        aliases=tuple(sorted(alias for alias in obj.aliases if obj.resolve_id(alias)==key))
        if tuple(node.attributes.get('aliases',()))!=aliases:raise ValueError('hierarchy aliases mismatch')
    events=summary.get('events',[])
    if not isinstance(events,list):raise ValueError('event summary must be list')
    for event in events:
        closed(event,{'event_id','object_id','source'},'event summary row')
        digest(event['event_id'])
        closed(event['source'],{'episode_id','sensor_id','frame_index'},'event source')
        source=FrameKey(**event['source'])
        if source.episode_id!=obj.episode_id or source.sensor_id!=obj.source.sensor_id or source.frame_index>obj.source.frame_index:
            raise ValueError('event source mismatch')
        # Null is deliberately unresolved/unattributed evidence, not a
        # dangling canonical ID. The summary cannot prove its ambiguity cause.
        if event['object_id'] is not None:
            try:obj.resolve_id(event['object_id'])
            except (KeyError,ValueError,TypeError) as exc:raise ValueError('event canonical endpoint mismatch') from exc
    ids=[e['event_id'] for e in events]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate accepted event')
    total=summary.get('events_total')
    if type(total) is not int or total<len(events) or summary.get('events_complete')!=(len(events)==total):raise ValueError('event summary completeness mismatch')
    if runtime.get('clean_shutdown') is not True or runtime.get('pending')!=0 or runtime.get('failed') or runtime.get('workers_pending') or runtime.get('cleanup_pending'):
        raise ValueError('completed export has unresolved workers/failures')
    if summary.get('hierarchy_available') is not True:raise ValueError('completed hierarchy unavailable')
    control_pin=summary.get('control_invocations_artifact')
    if 'control-invocations.json' in manifest['files']:
        from .measurements import load_control_invocations
        closed(control_pin,{'path','sha256','complete'},'control invocation pin')
        if (control_pin!={'path':'control-invocations.json','sha256':manifest['files']['control-invocations.json'],'complete':True}
                or type(control_pin['complete']) is not bool):
            raise ValueError('summary control invocation pin mismatch or incomplete')
        trace,inspection=load_control_invocations(root/'control-invocations.json',clock_domain=domain)
        if not inspection['complete'] or trace['result_missing']:
            raise ValueError('completed control invocation artifact incomplete')
    elif 'control_invocations_artifact' in summary:
        raise ValueError('control invocation pin without export artifact')
    if version==2:
        from .measurements import load_measurements
        if summary.get('measurement_artifact')!=dict(path='measurements.json',sha256=manifest['files']['measurements.json']):raise ValueError('summary measurement pin mismatch')
        byte_cap=summary.get('measurement_export_byte_cap',16*1024**2)
        if type(byte_cap) is not int or not 1<=byte_cap<=64*1024**2:raise ValueError('invalid measurement export byte cap')
        artifact,inspection=load_measurements(root/'measurements.json',max_bytes=byte_cap,attempt_id=summary['attempt_id'],config_sha256=summary['config_sha256'],episode_id=obj.episode_id,clock_domain=domain)
        if artifact['completion']['complete'] is not True or artifact['lifecycle']['outcome']!='completed':raise ValueError('completed measurement artifact incomplete')
    return summary,obj,nav,hier
