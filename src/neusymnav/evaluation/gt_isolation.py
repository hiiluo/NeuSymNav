"""Offline semantic annotations and actual deterministic replay isolation proof.

Only this evaluator module reads semantic annotation paths. The runtime receives
its unchanged recording and config. Shared explicit replay sessions keep hashes,
clock-dependent geometry/evidence and canonical IDs directly comparable.
"""
from __future__ import annotations
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from .protocol import read_json,closed,text,digest,sha256_file


def load_offline_gt(path):
    value=read_json(path)
    closed(value,{'schema_version','scene_id','input_sha256','coordinate_convention','geometry_metric','provenance','objects','visible_object_ids'},'offline GT')
    if type(value['schema_version']) is not int or value['schema_version']!=1:raise ValueError('offline GT version must be 1')
    for name in ('scene_id','provenance'):text(value[name],name)
    digest(value['input_sha256'])
    if value['coordinate_convention']!='canonical_z_up_m_v1':raise ValueError('offline GT coordinate convention mismatch')
    if value['geometry_metric'] not in {'aabb_xy_iou_v1','aabb_volume_iou_v1'}:raise ValueError('unsupported offline geometry metric')
    if not isinstance(value['objects'],list) or len(value['objects'])>4096:raise ValueError('offline GT object bound exceeded')
    ids=set()
    from .metrics import aabb_iou,aabb_xy_iou
    for obj in value['objects']:
        closed(obj,{'gt_id','raw_label','bounds'},'GT object');text(obj['gt_id'],'GT id')
        if obj['gt_id'] in ids:raise ValueError('duplicate GT identity')
        ids.add(obj['gt_id'])
        if obj['raw_label'] is not None:text(obj['raw_label'],'GT label')
        (aabb_iou if value['geometry_metric']=='aabb_volume_iou_v1' else aabb_xy_iou)(obj['bounds'],obj['bounds'])
    visible=value['visible_object_ids']
    if not isinstance(visible,list) or any(not isinstance(x,str) for x in visible) or len(set(visible))!=len(visible) or not set(visible)<=ids:
        raise ValueError('visible GT identities must be unique subset of scope')
    return value


def audit_runtime_imports(package_root=None):
    """Static import audit across every package module outside evaluator/CLI.

    Includes deferred imports and both relative/absolute spelling. Dynamic code
    cannot be proven by AST; an actual isolated import trace complements this.
    """
    root=Path(package_root) if package_root else Path(__file__).parents[1]
    checked=[];violations=[]
    for path in sorted(root.rglob('*.py')):
        relative=path.relative_to(root)
        if relative.parts[0]=='evaluation' or relative.name=='cli.py':continue
        checked.append(str(relative));module='neusymnav.'+'.'.join(relative.with_suffix('').parts)
        package=module.rpartition('.')[0]
        if relative.name=='__init__.py':package=module.rsplit('.__init__',1)[0]
        tree=ast.parse(path.read_text(),filename=str(path))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import):names=[item.name for item in node.names]
            elif isinstance(node,ast.ImportFrom):
                name=node.module or ''
                if node.level:
                    try:name=importlib.util.resolve_name('.'*node.level+name,package)
                    except (ValueError,ImportError):name='invalid_relative_import'
                names=[name]
                if name=='neusymnav':names.extend('neusymnav.'+item.name for item in node.names)
            for name in names:
                if name=='evaluation' or name.startswith('evaluation.') or name=='neusymnav.evaluation' or name.startswith('neusymnav.evaluation.'):
                    violations.append(dict(file=str(relative),line=node.lineno,module=name))
    return dict(checked_files=checked,violations=violations,scope='AST import audit; evaluator and CLI offline dispatch excluded')


def runtime_output_hashes(root):
    """Preserve raw hashes; exclude only hierarchy publication sequence number."""
    root=Path(root)
    raw={name:sha256_file(root/name) for name in ('objects.json','nav.json','hierarchy.json')}
    projection=read_json(root/'hierarchy.json')
    del projection['payload']['fields']['revision']
    canonical=dict(raw)
    canonical['hierarchy.json']=hashlib.sha256(json.dumps(projection,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return raw,canonical


def audit_gt_isolation(recording_path,config_path,gt_paths,*,out):
    """Run two real Pipelines, changing only evaluator-only semantic GT.

    No UUID/ID/evidence/geometry normalization is performed. The hierarchy's
    publication sequence counter alone is excluded: scheduling may publish the
    same pinned snapshots once or twice. Session files are
    cloned before either run, and independently validated by ReplaySession.open.
    """
    if len(gt_paths)!=2:raise ValueError('isolation audit requires exactly two GT variants')
    from ..recording.replay import ReplaySession
    from ..runtime.launcher import replay
    from .exports import load_runtime_export
    root=Path(out).absolute()
    if root.exists() and any(root.iterdir()):raise ValueError('GT audit requires empty output directory')
    root.mkdir(parents=True,exist_ok=True)
    imported=audit_runtime_imports()
    if imported['violations']:raise ValueError('runtime imports offline evaluation')
    # Semantic GT is read separately and never inserted into launcher config.
    gts=[load_offline_gt(path) for path in gt_paths]
    if gts[0]['input_sha256']!=gts[1]['input_sha256'] or gts[0]['input_sha256']!=sha256_file(Path(recording_path)/'manifest.json'):
        raise ValueError('GT variants must describe identical recording input')
    if [o['raw_label'] for o in gts[0]['objects']]==[o['raw_label'] for o in gts[1]['objects']]:raise ValueError('GT variants must have different semantic labels')
    seed_session=root/'session-template.json';ReplaySession.open(seed_session,recording_path,start_ns=1_000_000_000)
    runs=[];hashes=[]
    for index,gt_path in enumerate(gt_paths):
        output=root/f'variant-{index}';output.mkdir()
        shutil.copyfile(seed_session,output/'replay-session.json')
        ReplaySession.open(output/'replay-session.json',recording_path,start_ns=1_000_000_000)
        result=replay(recording_path,config_path,out=output)
        if result['outcome']!='completed':raise ValueError('GT isolation replay did not complete: '+str(result))
        summary,objects,nav,hierarchy=load_runtime_export(output/'export-manifest.json')
        current,semantic_hashes=runtime_output_hashes(output)
        hashes.append(semantic_hashes)
        runs.append(dict(output=str(output),gt_sha256=sha256_file(gt_path),runtime_hashes=current,compared_hashes=semantic_hashes,object_ids=sorted(objects.objects),
            event_ids=[event['event_id'] for event in summary['events']],aliases=dict(objects.aliases),clock_domain=nav.clock_domain))
    report=dict(schema_version=1,profile='fixture_cpu_no_models',canonical_outputs_equal=hashes[0]==hashes[1],raw_bytes_equal=runs[0]['runtime_hashes']==runs[1]['runtime_hashes'],excluded_fields=['hierarchy.revision'],
        semantic_gt_equal=False,preserved_identity_and_evidence=True,compared_outputs=['objects.json','nav.json','hierarchy.json'],
        normalization='only hierarchy root publication revision excluded; canonical/object/map/region/latest revisions, IDs, aliases, source keys, geometry and all evidence retained; same cloned validated replay session',runtime_import_audit=imported,runs=runs,native_runtime_validated=False)
    (root/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report
