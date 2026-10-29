import json
from pathlib import Path
import subprocess
import sys

SCRIPT=Path(__file__).resolve().parents[1]/'tools/check_github_payload.py'


def check(tmp_path, files):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    for name,content in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
    subprocess.run(['git','-C',str(tmp_path),'add','-f','.'],check=True)
    r=subprocess.run([sys.executable,str(SCRIPT),'--root',str(tmp_path)],capture_output=True,text=True)
    return r


def test_source_only_index_passes(tmp_path):
    r=check(tmp_path,{'src/package.py':'print(1)\n','runtime/environments/host.lock.txt':'numpy==1.26.4\n'})
    assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)['ready']


def test_force_added_runtime_and_native_closure_reject(tmp_path):
    r=check(tmp_path,{'.runtime/file':'x','native/dude/upstream/file.cpp':'x'})
    assert r.returncode==1
    x=json.loads(r.stdout)
    assert {v['path'] for v in x['findings']}=={'.runtime/file','native/dude/upstream/file.cpp'}


def test_secret_report_never_echoes_secret_value(tmp_path):
    secret='ghp_'+'x'*36
    r=check(tmp_path,{'credentials.txt':secret})
    assert r.returncode==1
    assert secret not in r.stdout+r.stderr
    assert json.loads(r.stdout)['findings'][0]['kind']=='github_token'


def test_index_secret_still_rejects_after_working_file_cleaned(tmp_path):
    secret='ghp_'+'y'*36
    check(tmp_path,{'credentials.txt':secret})
    (tmp_path/'credentials.txt').write_text('clean working tree bytes')
    r=subprocess.run([sys.executable,str(SCRIPT),'--root',str(tmp_path)],capture_output=True,text=True)
    assert r.returncode==1
    assert secret not in r.stdout+r.stderr
    assert json.loads(r.stdout)['findings'][0]['kind']=='github_token'
