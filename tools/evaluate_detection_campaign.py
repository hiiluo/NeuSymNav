#!/usr/bin/env python3
"""Offline PR/AP and diagnostic calibration; never imported by the online matcher.

Reuses the project's class-aware score-ranked matching and101point AP protocol.
Native NumPy masks avoid expanding every raster to Python bool lists. Threshold
selection is explicitly in-sample diagnostic evidence, not held-out validation.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from neusymnav.evaluation.quality_dataset import load_quality_pair
from neusymnav.evaluation.detection_quality import _normalize, _overlaps, _ranked, _match, _point, _ap

DEFAULT_THRESHOLDS=(.01,.025,.05,.075,.1,.15,.2,.25,.3,.4,.5,.6,.7,.8,.9)

def analyze(frames, *, thresholds=DEFAULT_THRESHOLDS):
    if (not thresholds or any(type(t) not in (int,float) or not np.isfinite(t) or not 0<=t<=1 for t in thresholds)):
        raise ValueError('nonempty finite thresholds in [0,1] required')
    thresholds=sorted(set(float(t) for t in thresholds))
    # Normalize every non-mask field through the same public evaluator boundary.
    stripped=[dict(frame_id=f['frame_id'],**{kind:[{k:v for k,v in o.items() if k in {'id','label','bbox','score'}} for o in f[kind]] for kind in ('gt','pred')}) for f in frames]
    normalized=_normalize(stripped)
    masks_complete=True
    for source,target in zip(frames,normalized):
        shape=None
        for kind in ('gt','pred'):
            for original,obj in zip(source[kind],target[kind]):
                if 'mask' not in original:
                    masks_complete=False
                    continue
                mask=np.asarray(original['mask'])
                if mask.dtype!=np.bool_ or mask.ndim!=2 or not mask.size or not mask.any():
                    raise ValueError('nonempty boolean2D masks required')
                if shape is not None and shape!=mask.shape:raise ValueError('same-source mask shape mismatch')
                shape=mask.shape;obj['mask']=mask
    labels=sorted({o['label'] for f in normalized for kind in ('gt','pred') for o in f[kind]})
    overlaps=_overlaps(normalized,'bbox')
    counts={label:sum(o['label']==label for f in normalized for o in f['gt']) for label in labels}
    ranked={label:_ranked(normalized,label) for label in labels}
    flags={label:_match(ranked[label],{f['frame_id']:sorted((o for o in f['gt'] if o['label']==label),key=lambda o:o['id']) for f in normalized},overlaps,.5) for label in labels}
    per_class={label:[] for label in labels};global_pr=[]
    for threshold in thresholds:
        total_tp=total_pred=0
        for label in labels:
            eligible=[flag for (_,obj),flag in zip(ranked[label],flags[label]) if obj['score']>=threshold]
            point=_point(sum(eligible),len(eligible),counts[label])
            per_class[label].append(dict(threshold=threshold,**point))
            total_tp+=point['tp'];total_pred+=point['predictions']
        global_pr.append(dict(threshold=threshold,**_point(total_tp,total_pred,sum(counts.values()))))
    # Equal F1 selects higher precision then higher threshold deterministically.
    def best(rows):return max(rows,key=lambda r:(r['f1'] if r['f1'] is not None else -1,r['precision'] if r['precision'] is not None else -1,r['threshold']))
    chosen=best(global_pr);choices={}
    for label,rows in per_class.items():
        candidate=best(rows)
        enough=counts[label]>=10 and candidate['tp']>=3
        choices[label]=dict(threshold=candidate['threshold'] if enough else chosen['threshold'],
            reason='diagnostic_best_f1_with_support' if enough else 'insufficient_gt_or_tp_support',
            ground_truth=counts[label],tp_at_candidate=candidate['tp'])
    calibrated=[]
    for f in normalized:
        calibrated.append(dict(frame_id=f['frame_id'],gt=f['gt'],pred=[o for o in f['pred'] if o['score']>=choices[o['label']]['threshold']]))
    tp=pred=0
    for label in labels:
        row=next(r for r in per_class[label] if r['threshold']==choices[label]['threshold'])
        tp+=row['tp'];pred+=row['predictions']
    return dict(schema_version='detection-campaign-v1',
        protocol='class-aware bboxIoU>=.5; score-ranked greedy; COCO-style101point subset AP; allsupplied GT/frames',
        support=dict(frames=len(frames),ground_truth=sum(counts.values()),predictions=sum(len(f['pred']) for f in normalized)),
        bbox_ap=_ap(normalized,labels,overlaps),
        mask_ap=_ap(normalized,labels,_overlaps(normalized,'mask') if masks_complete else None),
        global_pr=global_pr,per_class_pr=per_class,
        calibration=dict(scope='diagnostic_in_sample_not_held_out',objective='F1 at bboxIoU.5; precision then higherthreshold tiebreak',
            global_threshold=chosen['threshold'],global_point=chosen,per_class=choices,
            per_class_point=_point(tp,pred,sum(counts.values()))))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ground-truth',type=Path,required=True)
    parser.add_argument('--predictions',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.out.exists():raise FileExistsError(args.out)
    pair=load_quality_pair(args.ground_truth,args.predictions)
    report=analyze(pair['frames'])
    report.update(input_hashes=pair['input_hashes'],binding=pair['gt']['binding'],
        source_prediction_limits=dict(score_floor=pair['predictions']['score_floor'],max_detections=pair['predictions']['max_detections']),
        tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.out.mkdir(parents=True)
    (args.out/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    with (args.out/'pr.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=['class','threshold','tp','fp','fn','ground_truth','predictions','precision','recall','f1'])
        writer.writeheader()
        writer.writerows(dict({'class':'__all__'},**row) for row in report['global_pr'])
        for label,rows in report['per_class_pr'].items():writer.writerows(dict({'class':label},**row) for row in rows)
    print(json.dumps(dict(support=report['support'],bbox_ap=report['bbox_ap']['ap50_95'],mask_ap=report['mask_ap']['ap50_95'],calibration=report['calibration']['global_point'])))
    return 0

if __name__=='__main__':raise SystemExit(main())
