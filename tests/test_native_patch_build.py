import importlib.util
from pathlib import Path
import hashlib,json
import pytest
spec=importlib.util.spec_from_file_location('nativebuild',Path(__file__).parents[1]/'tools/build_native.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def fixture(tmp_path):
    root=tmp_path/'original';root.mkdir();f=root/'sample.cpp';f.write_text('before\n')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.16)\n')
    (root/'source-closure.json').write_text(json.dumps(dict(schema_version=1,files=[dict(path='sample.cpp',source_sha256=sha(f),vendored_sha256=sha(f))])))
    patch=tmp_path/'fix.patch';patch.write_text('--- a/sample.cpp\n+++ b/sample.cpp\n@@ -1 +1 @@\n-before\n+after\n')
    recipe=tmp_path/'fix.json';recipe.write_text(json.dumps(dict(schema_version=1,patch='fix.patch',patch_sha256=sha(patch),files=[dict(path='sample.cpp',before_sha256=sha(f),after_sha256=hashlib.sha256(b'after\n').hexdigest())])))
    return root,recipe

def test_patch_staging_preserves_verified_original_and_pins_local_modification(tmp_path):
    root,recipe=fixture(tmp_path)
    stage,provenance=m.stage_patched_closure(root,recipe,tmp_path/'stage')
    assert (root/'sample.cpp').read_text()=='before\n'
    assert (stage/'sample.cpp').read_text()=='after\n'
    assert m.verify_source_closure(stage)['file_count']==1
    assert provenance['patch_set_sha256']==sha(recipe)

@pytest.mark.parametrize('mutation',['patchhash','filehash','escape'])
def test_patch_mismatch_or_escape_rejected_before_original_changes(tmp_path,mutation):
    root,recipe=fixture(tmp_path);d=json.loads(recipe.read_text())
    if mutation=='patchhash':d['patch_sha256']='0'*64
    elif mutation=='filehash':d['files'][0]['after_sha256']='0'*64
    else:d['files'][0]['path']='../sample.cpp'
    recipe.write_text(json.dumps(d))
    with pytest.raises((ValueError,RuntimeError)):m.stage_patched_closure(root,recipe,tmp_path/'stage')
    assert (root/'sample.cpp').read_text()=='before\n'

def test_patched_cli_requires_fresh_output_before_any_baseline_write(tmp_path,monkeypatch):
    import sys
    baseline=tmp_path/'canonical-baseline'
    monkeypatch.setattr(m,'RUN_ROOT',baseline)
    monkeypatch.setattr(sys,'argv',['build_native.py','--dependency-prefix',str(tmp_path),'--patch-set',str(tmp_path/'patch.json')])
    with pytest.raises(SystemExit,match='--output-dir'):
        m.main()
    assert not baseline.exists()

@pytest.mark.parametrize('extra',['cmake','undeclared'])
def test_patch_cannot_hide_build_recipe_or_undeclared_file_changes(tmp_path,extra):
    root,recipe=fixture(tmp_path);d=json.loads(recipe.read_text());patch=tmp_path/'fix.patch'
    if extra=='cmake':
        addition='--- a/CMakeLists.txt\n+++ b/CMakeLists.txt\n@@ -1 +1 @@\n-cmake_minimum_required(VERSION 3.16)\n+cmake_minimum_required(VERSION 3.20)\n'
    else:
        addition='--- /dev/null\n+++ b/undeclared.cpp\n@@ -0,0 +1 @@\n+surprise\n'
    patch.write_text(patch.read_text()+addition);d['patch_sha256']=sha(patch);recipe.write_text(json.dumps(d))
    with pytest.raises((ValueError,RuntimeError)):
        m.stage_patched_closure(root,recipe,tmp_path/'stage')
