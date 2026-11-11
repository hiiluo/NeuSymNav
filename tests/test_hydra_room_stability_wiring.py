import json
import sys
from pathlib import Path
from test_hydra_session import frame,wait_until
from neusymnav.backends.hydra.session import HydraSession


def command(tmp_path, *, changed=False, forge=False):
    ready={'type':'ready','protocol':1,'config_sha256':'a'*64,'source_sha256':'e'*40}
    meta={'config_sha256':'a'*64,'source_sha256':'e'*40,'build_sha256':'b'*64,'native_binding_sha256':'c'*64,'room_stability':{'enabled':True,'version':'neusymnav-room-stability-v1','library_sha256':'d'*64,'policy_sha256':'f'*64}}
    body='''
for line in sys.stdin:
 msg=json.loads(line)
 if msg['type']=='close': break
 value=dict(meta)
 if changed and msg['frame_index']>0:value['build_sha256']='9'*64
 if forge:value['config_sha256']='0'*64
 print(json.dumps({'type':'result','request_id':msg['request_id'],'accepted':True,'native_metadata':value,'room_stability_diagnostics':{'enabled':True,'action':'held_pending','pending_count':1}}),flush=True)
'''
    path=tmp_path/'worker.py';path.write_text('import json,sys\nmeta='+repr(meta)+'\nchanged='+repr(changed)+'\nforge='+repr(forge)+'\nprint(json.dumps('+repr(ready)+'),flush=True)\n'+body)
    return (sys.executable,str(path))


def test_live_snapshot_pins_effective_build_and_detaches_stability_metadata(tmp_path):
    session=HydraSession('ep',command=command(tmp_path),journal_path=tmp_path/'j.jsonl')
    try:
        session.offer(frame());assert session.wait_for_revision(1,2.)
        snapshot=session.snapshot();assert snapshot.build_sha256=='b'*64
        assert snapshot.room_stability['last_decision']['action']=='held_pending'
        snapshot.room_stability['last_decision']['pending_count']=99
        assert session.snapshot().room_stability['last_decision']['pending_count']==1
    finally:session.close(2.)
    accepted=[json.loads(line) for line in (tmp_path/'j.jsonl').read_text().splitlines()
              if json.loads(line).get('event')=='accepted']
    assert accepted[0]['room_stability_diagnostics']['pending_count']==1
    assert accepted[0]['native_metadata']['build_sha256']=='b'*64


def test_build_cannot_change_within_one_episode(tmp_path):
    session=HydraSession('ep',command=command(tmp_path,changed=True),journal_path=tmp_path/'j.jsonl')
    try:
        session.offer(frame());assert session.wait_for_revision(1,2.)
        session.offer(frame(1));assert not session.wait_for_revision(2,2.)
        assert session.snapshot().stale and session.snapshot().graph_revision==1
        assert session.snapshot().build_sha256=='b'*64
    finally:session.close(2.)


def test_frame_metadata_cannot_rebind_ready_config(tmp_path):
    session=HydraSession('ep',command=command(tmp_path,forge=True),journal_path=tmp_path/'j.jsonl')
    try:
        session.offer(frame());assert not session.wait_for_revision(1,2.)
        assert session.snapshot().stale and session.snapshot().graph_revision==0
    finally:session.close(2.)
