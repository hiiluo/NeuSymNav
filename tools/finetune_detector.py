#!/usr/bin/env python3
"""Explicit local YOLOE head adaptation with partial-annotation supervision.

Run with .runtime/detector26/bin/python and PYTHONPATH=src. Test metrics are
computed only after validation selection is written. This tool never promotes
runtime defaults. Checkpoints retain the promptable YOLOE architecture.
"""
from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('YOLO_CONFIG_DIR',str(Path(__file__).resolve().parents[1]/'.runtime/cache/ultralytics'))

import numpy as np
from PIL import Image
import torch
from ultralytics import YOLOE, __version__ as ultra_version
from ultralytics.utils import DEFAULT_CFG_DICT

from neusymnav.perception.yoloe import LocalMobileCLIPPromptProvider
from neusymnav.training.finetune import BitmapDataset, PartialSegmentationLoss, collate, metric_eligibility
from neusymnav.evaluation.detection_quality import _ap, _overlaps, _normalize


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def state_sha(modules):
    digest=hashlib.sha256()
    for module in modules:
        for name,value in module.state_dict().items():
            digest.update(name.encode());digest.update(value.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def load_model(checkpoint, encoder, names, device):
    wrapper = YOLOE(str(checkpoint))
    wrapper.model.to(device)
    provider = LocalMobileCLIPPromptProvider(encoder)
    # Runtime provider intentionally uses inference_mode. Training needs an
    # ordinary detached tensor because autograd saves text features for cv4.
    wrapper.set_classes(names, provider(wrapper, names).clone().detach())
    del provider
    return wrapper


def save_checkpoint(model, path, epoch, names, recipe):
    saved=copy.deepcopy(model).cpu().float().eval()
    saved.args=dict(DEFAULT_CFG_DICT)
    saved.names=dict(enumerate(names))
    torch.save(dict(model=saved,ema=None,epoch=epoch,version=ultra_version,
                    date=datetime.now(timezone.utc).isoformat(),license='AGPL-3.0',
                    train_args=dict(DEFAULT_CFG_DICT),neusymnav_recipe=recipe),path)
    del saved


def evaluate(checkpoint, encoder, names, rows, dataset_root, device, output):
    """Full-resolution bitmap subset AP with explicit spatial/class ignore.

    Same-class possible TPs are retained independently for each metric.
    Other predictions need >=50% evaluated box/mask area. Unknown class channels are
    outside this dataset's support. This is partial-annotation subset AP, not COCO.
    """
    model=load_model(checkpoint,encoder,names,device)
    frames=[];mask_frames=[];mask_overlaps={}
    counts=dict(unsupported=0,ignored_box=0,ignored_mask=0,box_predictions=0,mask_predictions=0,gt=0)
    allowed=set(rows[0]['supervised_class_ids'])
    started=time.monotonic()
    for index,row in enumerate(rows):
        fid=f"{row['scene']}:{row.get('camera','00')}:{row.get('frame',index)}"
        with Image.open(dataset_root/row['instance_mask']) as im: ids=np.array(im)
        with Image.open(dataset_root/row['ignore_mask']) as im: valid=np.array(im)==0
        result=model.predict(row['image'],device=device,imgsz=640,conf=.05,max_det=100,
                             retina_masks=True,verbose=False)[0]
        gt=[];gt_masks=[]
        for obj in row['objects']:
            m=ids==obj['id'];ys,xs=np.where(m)
            if not len(xs):raise ValueError('manifest object has no mask')
            gt.append(dict(id=str(obj['id']),label=names[obj['class_id']],
                           bbox=[float(xs.min()),float(ys.min()),float(xs.max()+1),float(ys.max()+1)]))
            gt_masks.append(m)
        pred=[];pred_masks=[];box_fractions=[];mask_fractions=[]
        boxes=result.boxes.xyxy.detach().cpu().numpy()
        classes=result.boxes.cls.detach().cpu().numpy().astype(int)
        scores=result.boxes.conf.detach().cpu().numpy()
        raw_masks=(np.zeros((0,*ids.shape),bool) if result.masks is None else
                   result.masks.data.detach().cpu().numpy()>.5)
        if len(raw_masks)!=len(boxes) or tuple(raw_masks.shape[1:])!=ids.shape:
            raise ValueError('inference masks must be exact original image shape')
        for j,(box,cls,score,mask) in enumerate(zip(boxes,classes,scores,raw_masks)):
            if cls not in allowed:counts['unsupported']+=1;continue
            if box[2]<=box[0] or box[3]<=box[1]:continue
            x1,y1=np.floor(box[:2]).astype(int);x2,y2=np.ceil(box[2:]).astype(int)
            roi=valid[max(0,y1):min(ids.shape[0],y2),max(0,x1):min(ids.shape[1],x2)]
            box_fractions.append(float(roi.mean()) if roi.size else 0.)
            mask_fractions.append(np.count_nonzero(mask&valid)/max(np.count_nonzero(mask),1))
            pred.append(dict(id=str(j),label=names[cls],score=float(score),bbox=[float(v) for v in box]))
            pred_masks.append(mask&valid)
        # Compute exact full-resolution intersections on device, discard masks
        # after each frame rather than keeping gigabytes of Python bool lists.
        ious=np.zeros((len(pred),len(gt)),np.float32)
        if pred_masks and gt_masks:
            g=torch.from_numpy(np.stack(gt_masks).reshape(len(gt_masks),-1).astype(np.float32)).to(device)
            p=torch.from_numpy(np.stack(pred_masks).reshape(len(pred_masks),-1).astype(np.float32)).to(device)
            intersections=(p@g.T).cpu().numpy()
            unions=p.sum(1).cpu().numpy()[:,None]+g.sum(1).cpu().numpy()[None,:]-intersections
            ious=intersections/np.maximum(unions,1)
            del p,g
            for pi,pp in enumerate(pred):
                for gi,gg in enumerate(gt):
                    if pp['label']==gg['label']:mask_overlaps[fid,pp['id'],gg['id']]=float(ious[pi,gi])
        raw=_normalize([dict(frame_id=fid,gt=gt,pred=pred)])
        ov=_overlaps(raw,'bbox')
        box_ious=np.array([[ov.get((fid,p['id'],g['id']),0.) for g in gt] for p in pred]).reshape(len(pred),len(gt))
        same=np.array([[p['label']==g['label'] for g in gt] for p in pred]).reshape(len(pred),len(gt))
        kb,km=metric_eligibility(box_fractions,mask_fractions,box_ious,ious,same)
        bp=[p for p,k in zip(pred,kb) if k];mp=[p for p,k in zip(pred,km) if k]
        frames.append(dict(frame_id=fid,gt=gt,pred=bp));mask_frames.append(dict(frame_id=fid,gt=gt,pred=mp))
        counts['gt']+=len(gt);counts['box_predictions']+=len(bp);counts['mask_predictions']+=len(mp)
        counts['ignored_box']+=len(pred)-len(bp);counts['ignored_mask']+=len(pred)-len(mp)
        if index%50==0:print(json.dumps(dict(stage='evaluate',checkpoint=str(checkpoint),frame=index,total=len(rows))),flush=True)
        del result
    normalized=_normalize(frames)
    normalized_masks=_normalize(mask_frames)
    labels=sorted({r['label'] for ff in (normalized,normalized_masks) for f in ff for kind in ('gt','pred') for r in f[kind]})
    report=dict(checkpoint=str(checkpoint),checkpoint_sha256=sha(checkpoint),frames=len(rows),
                support=counts,bbox=_ap(normalized,labels,_overlaps(normalized,'bbox')),
                mask=_ap(normalized_masks,labels,mask_overlaps),wall_seconds=time.monotonic()-started,
                protocol=dict(confidence_floor=.05,max_det=100,resolution='original bitmap',
                              ignored_prediction='per metric: no same-class IoU>=.5 potential and <50% box/mask evaluated area',
                              scope='25 mapped classes with explicit spatial void; not official COCO AP',
                              selection='validation only; test after selection'))
    write(output,report)
    del model;gc.collect();torch.cuda.empty_cache()
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',type=Path,required=True)
    ap.add_argument('--checkpoint',type=Path,required=True)
    ap.add_argument('--encoder',type=Path,required=True)
    ap.add_argument('--taxonomy',type=Path,default=Path('configs/taxonomy-v1.json'))
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--epochs',type=int,default=6)
    ap.add_argument('--batch',type=int,default=2)
    ap.add_argument('--lr',type=float,default=1e-4)
    ap.add_argument('--device',default='cuda:0')
    ap.add_argument('--head-mode',choices=('all','detection'),default='all')
    ap.add_argument('--smoke',action='store_true')
    args=ap.parse_args()
    if args.out.exists():raise FileExistsError(args.out)
    args.out.mkdir(parents=True)
    torch.set_num_threads(2);random.seed(0);np.random.seed(0);torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False
    rows=[json.loads(x) for x in (args.dataset/'manifest.jsonl').read_text().splitlines()]
    names=json.loads(args.taxonomy.read_text())['categories']
    class_ids=sorted({o['class_id'] for r in rows if r['split']=='train' for o in r['objects']})
    recipe=dict(seed=0,epochs=args.epochs,batch=args.batch,lr=args.lr,
                dataset_manifest_sha256=sha(args.dataset/'manifest.jsonl'),
                taxonomy_sha256=sha(args.taxonomy),base_sha256=sha(args.checkpoint),encoder_sha256=sha(args.encoder),
                ultralytics=ultra_version,torch=torch.__version__,train_class_ids=class_ids,
                head_mode=args.head_mode,
                trainable='last head excluding reprta/savpe/dfl; detection mode also freezes proto/cv5',
                ignore_loss='partial-anchor/class BCE and valid-pixel mask BCE',
                test_policy='conversion QC permitted before selection; test metrics only after selection')
    write(args.out/'recipe.json',recipe)
    wrapper=load_model(args.checkpoint,args.encoder,names,args.device)
    model=wrapper.model
    for p in model.parameters():p.requires_grad_(False)
    for name,p in model.model[-1].named_parameters():
        allowed=(not name.startswith(('reprta.','savpe.','dfl.')) and
                 (args.head_mode=='all' or name.startswith(('cv2.','cv3.','cv4.'))))
        if allowed:p.requires_grad_(True)
    model.args=SimpleNamespace(**dict(DEFAULT_CFG_DICT,overlap_mask=True))
    criterion=PartialSegmentationLoss(model,class_ids)
    optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=args.lr,weight_decay=1e-4)
    loader=torch.utils.data.DataLoader(BitmapDataset(args.dataset,'train'),batch_size=args.batch,
                                     shuffle=True,num_workers=2,collate_fn=collate,pin_memory=True)
    # Before/after data-independent parameter proof for frozen backbone.
    frozen_before=state_sha(model.model[:-1])
    mask_before=state_sha([model.model[-1].proto,model.model[-1].cv5])
    history=[];candidates=[args.checkpoint]
    for epoch in range(1,(1 if args.smoke else args.epochs)+1):
        model.eval();model.model[-1].train()
        if args.head_mode=='detection':
            # Frozen mask branch includes BatchNorm buffers, not just weights.
            model.model[-1].proto.eval();model.model[-1].cv5.eval()
        totals=[];start=time.monotonic()
        for step,batch in enumerate(loader):
            batch={k:v.to(args.device,non_blocking=True) for k,v in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            preds=model(batch['img'])
            values,_=criterion(preds,batch)
            loss=values.sum()/len(batch['img'])
            if not torch.isfinite(loss):raise ValueError('non-finite training loss')
            loss.backward();norm=torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],10.)
            if not torch.isfinite(norm):raise ValueError('non-finite gradients')
            optimizer.step();totals.append(float(loss.detach()))
            if step%50==0:print(json.dumps(dict(stage='train',epoch=epoch,step=step,loss=totals[-1])),flush=True)
            if args.smoke:break
        target=args.out/f'epoch-{epoch:02d}.pt'
        save_checkpoint(model,target,epoch,names,recipe);candidates.append(target)
        history.append(dict(epoch=epoch,mean_loss=float(np.mean(totals)),steps=len(totals),wall_seconds=time.monotonic()-start,checkpoint=str(target)))
        write(args.out/'history.json',history)
        if args.smoke:break
    frozen_after=state_sha(model.model[:-1])
    if frozen_before!=frozen_after:raise ValueError('frozen backbone changed')
    mask_unchanged=mask_before==state_sha([model.model[-1].proto,model.model[-1].cv5])
    if args.head_mode=='detection' and not mask_unchanged:raise ValueError('frozen mask branch changed')
    write(args.out/'training-complete.json',dict(epochs=len(history),backbone_unchanged=True,mask_branch_unchanged=mask_unchanged))
    del criterion,optimizer,model,wrapper,loader;gc.collect();torch.cuda.empty_cache()
    if args.smoke:
        print(json.dumps(dict(smoke='forward_backward_and_checkpoint',checkpoint=str(candidates[-1]))));return
    val=[r for r in rows if r['split']=='val'];reports=[]
    for i,path in enumerate(candidates):
        reports.append(evaluate(path,args.encoder,names,val,args.dataset,args.device,args.out/f'val-{i:02d}.json'))
    # Base is a candidate so worsening all adapted models cannot force promotion.
    best=max(range(len(reports)),key=lambda i:reports[i]['mask']['ap50_95'])
    selection=dict(candidate_index=best,checkpoint=str(candidates[best]),checkpoint_sha256=sha(candidates[best]),
                   criterion='maximum validation mask subset AP50:95; first candidate wins ties',
                   value=reports[best]['mask']['ap50_95'],training_performed=True)
    write(args.out/'selection.json',selection)
    test=[r for r in rows if r['split']=='test']
    evaluate(args.checkpoint,args.encoder,names,test,args.dataset,args.device,args.out/'test-base.json')
    evaluate(candidates[best],args.encoder,names,test,args.dataset,args.device,args.out/'test-selected.json')
    print(json.dumps(selection),flush=True)


if __name__=='__main__':main()
