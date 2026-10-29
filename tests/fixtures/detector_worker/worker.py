"""Explicit external protocol stub; never selected by production defaults."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src'))
from neusymnav.contracts import Detection, DetectionBatch, FrameKey, from_dict, to_dict
import numpy as np

mode=os.environ.get('NEUSYMNAV_DETECTOR_STUB_MODE','success')
def read():
    h=sys.stdin.buffer.read(4)
    if not h: raise EOFError()
    n=int.from_bytes(h,'big')
    data=b''
    while len(data)<n:
        data += sys.stdin.buffer.read(n-len(data))
    return json.loads(data)
def send(data):
    encoded=json.dumps(data,separators=(',',':')).encode()
    payload=len(encoded).to_bytes(4,'big')+encoded
    if mode=='partial':
        for i in range(0,len(payload),7):
            sys.stdout.buffer.write(payload[i:i+7]); sys.stdout.buffer.flush()
    else:
        sys.stdout.buffer.write(payload);sys.stdout.buffer.flush()
r=read()
recipe=r['recipe']
digest=hashlib.sha256(json.dumps(recipe,sort_keys=True,separators=(',',':')).encode()).hexdigest()
send(dict(ok=True,wire_version=1,recipe_sha256=digest,
          runtime=dict(python='3.12.test',numpy='test',torch='test',ultralytics='test',clip='test')))
if mode=='no_read':
    time.sleep(60)
while True:
    try:r=read()
    except EOFError:break
    if mode=='timeout':time.sleep(60)
    if mode=='child':
        pid=os.fork()
        if pid==0:
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            time.sleep(60)
            os._exit(0)
        print('CHILD_PID='+str(pid),file=sys.stderr,flush=True)
        time.sleep(60)
    if mode=='huge_header':
        sys.stdout.buffer.write((2**32-1).to_bytes(4,'big'));sys.stdout.buffer.flush();time.sleep(60)
    if mode=='truncated':
        sys.stdout.buffer.write((100).to_bytes(4,'big')+b'{}');sys.stdout.buffer.flush();break
    obs=from_dict(r['observation'])
    vocab=json.loads(Path(recipe['taxonomy_path']).read_text())['vocabulary_id']
    detections=()
    if mode in ('detection','wrong_mask'):
        shape=obs.depth_m.shape if mode=='detection' else (1,1)
        d=Detection('0','chair','chair',.9,np.ones(shape,bool))
        batch=DetectionBatch(obs.key,obs.geometry_hash,vocab,(d,),'complete',False)
    else:
        batch=DetectionBatch.from_observation(obs,(),vocabulary_id=vocab)
    data=to_dict(batch)
    if mode=='wrong_source':data['payload']['fields']['source']['fields']['frame_index']+=1
    if mode=='wrong_geometry':data['payload']['fields']['geometry_hash']='a'*64
    if mode=='wrong_vocab':data['payload']['fields']['vocabulary_id']='other'
    response=dict(ok=True,wire_version=True if mode=='bool_version' else 1,batch=data)
    if mode=='gt_field':response['semantic_gt']=[]
    send(response)
