from pathlib import Path
import json
import pytest


def test_actual_replay_unchanged_under_different_offline_semantic_gt(tmp_path):
    from neusymnav.evaluation.gt_isolation import audit_gt_isolation
    repo=Path(__file__).resolve().parents[1];fixture=repo/'tests/fixtures/package'
    report=audit_gt_isolation(fixture/'recording',fixture/'config.yaml',
        [repo/'tests/fixtures/evaluation/semantic-a.json',repo/'tests/fixtures/evaluation/semantic-b.json'],out=tmp_path/'isolation')
    assert report['canonical_outputs_equal'] is True
    assert report['semantic_gt_equal'] is False
    assert report['excluded_fields']==['hierarchy.revision']
    assert report['runs'][0]['runtime_hashes']['objects.json']==report['runs'][1]['runtime_hashes']['objects.json']
    assert report['runs'][0]['runtime_hashes']['nav.json']==report['runs'][1]['runtime_hashes']['nav.json']
    assert report['compared_outputs']==['objects.json','nav.json','hierarchy.json']
    assert report['preserved_identity_and_evidence'] is True
    assert report['runs'][0]['object_ids']==['0aa4a5c2-aff5-5f7f-9d6e-4ccf6d090e17']
    assert report['runs'][0]['event_ids']==report['runs'][1]['event_ids']
    assert report['runtime_import_audit']['violations']==[]
    assert report['native_runtime_validated'] is False


def test_runtime_import_audit_follows_relative_and_absolute_evaluator_imports(tmp_path):
    from neusymnav.evaluation.gt_isolation import audit_runtime_imports
    (tmp_path/'runtime').mkdir();(tmp_path/'runtime/a.py').write_text('from ..evaluation import metrics\n')
    (tmp_path/'runtime/b.py').write_text('import neusymnav.evaluation.metrics\n')
    result=audit_runtime_imports(tmp_path)
    assert len(result['violations'])==2


def test_runtime_rejects_semantic_gt_in_configuration(tmp_path):
    from neusymnav.runtime.configuration import load_config
    fixture=Path(__file__).parent/'fixtures/package';value=json.loads((fixture/'config.yaml').read_text())
    value['semantic_gt']='offline-only.json';path=tmp_path/'config.json';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='unknown'):load_config(path)


@pytest.mark.parametrize('kind',['identity','edge','provenance'])
def test_gt_comparison_does_not_normalize_identity_or_edge_changes(tmp_path,kind):
    from neusymnav.evaluation.gt_isolation import runtime_output_hashes
    for name in ['objects.json','nav.json']:(tmp_path/name).write_text('{}')
    hierarchy=dict(payload=dict(fields=dict(revision=1,nodes={'object-id':'preserve'},edges={'provenance':'preserve'})))
    path=tmp_path/'hierarchy.json';path.write_text(json.dumps(hierarchy));raw,canonical=runtime_output_hashes(tmp_path)
    hierarchy['payload']['fields']['revision']=9;path.write_text(json.dumps(hierarchy))
    assert runtime_output_hashes(tmp_path)[1]==canonical
    if kind=='identity':hierarchy['payload']['fields']['nodes']={'different-object-id':'preserve'}
    elif kind=='edge':hierarchy['payload']['fields']['edges']['target']='different'
    else:hierarchy['payload']['fields']['edges']['provenance']='different'
    path.write_text(json.dumps(hierarchy))
    assert runtime_output_hashes(tmp_path)[1]!=canonical


def test_actual_runtime_subprocess_never_imports_evaluator_or_opens_gt(tmp_path):
    import os,subprocess,sys
    fixture=Path(__file__).parent/'fixtures/package'
    denied=Path(__file__).parent/'fixtures/evaluation'
    program='''
import importlib.abc,json,pathlib,sys
blocked=pathlib.Path(sys.argv[4]).resolve()
class RuntimeBoundary(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='neusymnav.evaluation' or fullname.startswith('neusymnav.evaluation.'):
   raise AssertionError('runtime imported evaluator: '+fullname)
sys.meta_path.insert(0,RuntimeBoundary())
def audit(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)):
  candidate=pathlib.Path(args[0]).resolve()
  if candidate==blocked or blocked in candidate.parents:raise AssertionError('runtime read offline GT')
sys.addaudithook(audit)
from neusymnav.runtime.launcher import replay
result=replay(sys.argv[1],sys.argv[2],out=sys.argv[3])
assert result['outcome']=='completed' and len(result['object_ids'])==1
print(json.dumps(dict(outcome=result['outcome'],blocked_gt_read=False,evaluator_imported=False)))
'''
    result=subprocess.run([sys.executable,'-c',program,str(fixture/'recording'),str(fixture/'config.yaml'),str(tmp_path/'runtime'),str(denied)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==dict(outcome='completed',blocked_gt_read=False,evaluator_imported=False)
