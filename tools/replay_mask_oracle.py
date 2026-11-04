#!/usr/bin/env python3
"""Offline scoped mask/proposal oracle; always re-encode changed crops."""
import argparse
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from neusymnav.contracts import Detection
from neusymnav.evaluation.active_perception import oracle_frame, evaluate_retained
from neusymnav.evaluation.graph_admission import replay_owner
from neusymnav.perception.appearance_client import AppearanceWorkerEncoder, attach_features
from neusymnav.perception.projector import Projector
from neusymnav.runtime.configuration import file_sha256


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('gt','predictions','ledger','baseline','config','out'):
        p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args()
    gt,pred,base=(json.loads(path.read_text()) for path in (a.gt,a.predictions,a.baseline))
    evaluate_retained(gt,pred,base)  # exact binding before opening encoder
    gframes={f['frame_id']:f for f in gt['frames']}
    config=json.loads(a.config.read_text())
    worker=config['worker'];paths=config['workers']['appearance']
    for entry in (paths['python'],paths['script']):
        if file_sha256(entry['path'])!=entry['sha256']:raise ValueError('encoder executable/script pin mismatch')
    encoder=AppearanceWorkerEncoder(paths['python']['path'],worker['checkpoint_path'],
        checkpoint_sha256=worker['checkpoint_sha256'],checkpoint_format=worker['checkpoint_format'],
        preprocessing_id=worker['preprocessing_id'],model_name=worker['model_name'],
        timeout_s=worker['timeout_s'],startup_timeout_s=worker['startup_timeout_s'],
        max_request_bytes=worker.get('max_request_bytes',32*1024**2),
        _worker_command=[paths['python']['path'],paths['script']['path'],'--worker'])
    projector=Projector();counts=dict(replaced=0,added=0,retained_unmatched=0,projected=0,reencoded=0)
    def mask_oracle(obs,batch,items,frame):
        g=gframes[frame['frame_id']]['objects'];d=frame['objects']
        matches=oracle_frame([dict(id=o['id'],label=o['label'],box=o['bbox']) for o in g],
                             [dict(id=o['id'],label=o['label'],box=o['bbox']) for o in d])['pairs']
        by_gt={j:d[i]['id'] for i,j in matches}
        if len(g)>256:raise ValueError('scoped mask oracle frame exceeds proposal cap')
        original={x.detection_id:x for x in batch.detections}
        edited=dict(original)
        counts['retained_unmatched']+=len(edited)-len(matches)
        for j,obj in enumerate(g):
            ref=obj['mask'];path=(a.gt.parent/ref['path']).resolve()
            if path.stat().st_size>8*1024**2:raise ValueError('mask exceeds byte cap')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('GT mask checksum mismatch')
            mask=np.load(io.BytesIO(raw),allow_pickle=False)
            if mask.dtype!=np.bool_ or mask.shape!=obs.depth_m.shape:raise ValueError('GT mask shape/type mismatch')
            if j in by_gt:
                did=by_gt[j];edited[did]=replace(original[did],mask=mask);counts['replaced']+=1
            else:
                did=f'oracle-mask:{j}'
                if did in edited:raise ValueError('oracle detection ID collision')
                # Keep labels un-oracled for proposals that had no detection.
                edited[did]=Detection(did,'unknown',None,.25,mask);counts['added']+=1
        # Partial GT cannot authorize a negative-visibility conclusion.
        oracle=replace(batch,detections=tuple(edited.values()),completion='partial')
        projected=projector.project(obs,oracle)
        if projected:
            features=encoder.encode(obs,oracle)
            selected={item.detection_id:features.features[item.detection_id] for item in projected}
            if any(v.space_id!=base['feature_space'] for v in selected.values()):
                raise ValueError('oracle encoder feature space differs from baseline')
            projected=attach_features(projected,replace(features,features=selected))
            counts['reencoded']+=len(selected)
        counts['projected']+=len(projected)
        return oracle,projected
    try:
        replay=replay_owner(a.ledger,a.predictions,a.out,batch_oracle=mask_oracle)
    finally:encoder.close()
    if replay['ledger_logical_sha256']!=base['ledger_logical_sha256']:
        raise ValueError('oracle and baseline ledger differ')
    report=dict(counts=counts,diagnostic=evaluate_retained(gt,pred,replay),
                feature_space=base['feature_space'],
                limitations=['Partial GT proposals only; unmatched original detections retained.',
                    'Oracle-added proposals use unknown label and fixed .25 score; admission comparison is not isolated.',
                    'All projected crops re-encoded with same RGB/recipe; negative evidence disabled on partial masks.',
                    'Not a deployable result, no precision or native motion claim.'])
    (a.out/'mask-oracle-report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
