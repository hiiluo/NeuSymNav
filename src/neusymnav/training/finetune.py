"""Partial-annotation YOLOE training, isolated from online runtime imports.

Requires the explicitly selected local torch/Ultralytics environment. No data,
models or packages are downloaded. Spatial ignore and unsupported class channels
have zero classification gradient; mask ignore is applied before crop/reduction.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.nn import functional as F
from ultralytics.utils.loss import v8SegmentationLoss
from ultralytics.utils.ops import crop_mask
from ultralytics.utils.tal import make_anchors


def metric_eligibility(box_fraction, mask_fraction, box_iou, mask_iou, same_class):
    """Keep possible TPs per metric, otherwise require evaluated spatial support."""
    same_class=np.asarray(same_class,bool)
    box_possible=((np.asarray(box_iou)>=.5)&same_class).any(1)
    mask_possible=((np.asarray(mask_iou)>=.5)&same_class).any(1)
    return (np.asarray(box_fraction)>=.5)|box_possible, (np.asarray(mask_fraction)>=.5)|mask_possible


class PartialBCE(nn.Module):
    def __init__(self):
        super().__init__()
        self.valid = None
        self.classes = None

    def forward(self, logits, targets):
        if self.valid is None or self.classes is None:
            raise ValueError('partial supervision weights were not bound')
        # Assigned positives are evidence even when an anchor falls outside a
        # non-rectangular instance. Unknown anchors supply no negative labels.
        weight = (self.valid[..., None] | (targets > 0)) & self.classes[None, None, :]
        return F.binary_cross_entropy_with_logits(logits, targets, reduction='none') * weight


def masked_mask_loss(gt, coefficients, proto, boxes, valid):
    logits = torch.einsum('in,nhw->ihw', coefficients, proto)
    if valid.shape != logits.shape[-2:]:
        raise ValueError('mask validity must match prototype resolution')
    loss = F.binary_cross_entropy_with_logits(logits, gt, reduction='none')
    support = crop_mask(valid[None].expand_as(loss).float(), boxes)
    denominator = support.sum((1, 2)).clamp_min(1)
    return (crop_mask(loss * valid, boxes).sum((1, 2)) / denominator).sum()


class PartialSegmentationLoss(v8SegmentationLoss):
    def __init__(self, model, supervised_class_ids):
        super().__init__(model)
        self.bce = PartialBCE()
        self.bce.classes = torch.zeros(self.nc, dtype=torch.bool, device=self.device)
        self.bce.classes[list(supervised_class_ids)] = True
        self._valid = None

    def loss(self, preds, batch):
        if isinstance(preds['proto'], tuple):
            raise ValueError('auxiliary semantic head needs a separate ignore-aware loss')
        return super().loss(preds, batch)

    def get_assigned_targets_and_loss(self, preds, batch):
        valid = batch['valid_pixels'].to(self.device).bool()
        anchors, strides = make_anchors(preds['feats'], self.stride, 0.5)
        pixels = (anchors * strides).long()
        y = pixels[:, 1].clamp(0, valid.shape[1]-1)
        x = pixels[:, 0].clamp(0, valid.shape[2]-1)
        self.bce.valid = valid[:, y, x]
        self._valid = valid
        return super().get_assigned_targets_and_loss(preds, batch)

    def calculate_segmentation_loss(self, fg_mask, masks, target_gt_idx,
                                    target_bboxes, batch_idx, proto, pred_masks, imgsz):
        _, _, height, width = proto.shape
        boxes = target_bboxes / imgsz[[1, 0, 1, 0]]
        boxes = boxes * torch.tensor([width, height, width, height], device=proto.device)
        # PIL NEAREST (used for ID rasters) and torch nearest-exact agree on
        # source-pixel centers; torch legacy nearest samples different pixels.
        valid = F.interpolate(self._valid[:, None].float(), (height, width), mode='nearest-exact')[:, 0].bool()
        total = (proto * 0).sum() + (pred_masks * 0).sum()
        for i in range(len(proto)):
            fg = fg_mask[i]
            if not fg.any():
                continue
            indices = target_gt_idx[i, fg]
            if self.overlap:
                gt = (masks[i][None] == (indices+1)[:, None, None]).float()
            else:
                gt = masks[batch_idx.view(-1) == i][indices]
            present = gt.flatten(1).any(1)
            if present.any():
                total = total + masked_mask_loss(gt[present], pred_masks[i, fg][present], proto[i], boxes[i, fg][present], valid[i])
        return total / fg_mask.sum().clamp_min(1)


class BitmapDataset(torch.utils.data.Dataset):
    def __init__(self, root, split, size=640):
        self.root = Path(root)
        self.rows = [json.loads(line) for line in (self.root/'manifest.jsonl').read_text().splitlines()
                     if line.strip() and json.loads(line)['split'] == split]
        if not self.rows:
            raise ValueError('empty split')
        self.size = size

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with Image.open(row['image']) as im:
            image = im.convert('RGB')
            width, height = image.size
            ratio = self.size/max(width, height)
            nw, nh = round(width*ratio), round(height*ratio)
            left, top = (self.size-nw)//2, (self.size-nh)//2
            canvas = Image.new('RGB', (self.size, self.size), (114,114,114))
            canvas.paste(image.resize((nw,nh), Image.Resampling.BILINEAR), (left,top))
        with Image.open(self.root/row['instance_mask']) as im:
            ids = np.array(im.resize((nw,nh), Image.Resampling.NEAREST))
        with Image.open(self.root/row['ignore_mask']) as im:
            valid = np.array(im.resize((nw,nh), Image.Resampling.NEAREST)) == 0
        full_ids = np.zeros((self.size,self.size), np.int32)
        full_valid = np.zeros((self.size,self.size), bool)
        full_ids[top:top+nh,left:left+nw] = ids
        full_valid[top:top+nh,left:left+nw] = valid
        masks = np.zeros_like(full_ids)
        classes, boxes = [], []
        for obj in row['objects']:
            ys, xs = np.where(full_ids == obj['id'])
            if not len(xs):
                continue
            # Keep exact bitmap IDs aligned after resize; no polygon conversion.
            new_id = len(classes)+1
            masks[full_ids == obj['id']] = new_id
            classes.append(obj['class_id'])
            x1,y1,x2,y2 = xs.min(),ys.min(),xs.max()+1,ys.max()+1
            boxes.append([(x1+x2)/2/self.size,(y1+y2)/2/self.size,
                          (x2-x1)/self.size,(y2-y1)/self.size])
        # Keep full-resolution validity for anchor classification. Mask targets
        # use the standard stride4 grid; no costly prototype upsampling required.
        down = np.array(Image.fromarray(masks).resize((self.size//4,self.size//4), Image.Resampling.NEAREST))
        return dict(img=torch.from_numpy(np.asarray(canvas).copy().transpose(2,0,1)).float()/255,
                    masks=torch.from_numpy(down.astype(np.int64)),
                    valid_pixels=torch.from_numpy(full_valid),
                    cls=torch.tensor(classes,dtype=torch.float32).reshape(-1,1),
                    bboxes=torch.tensor(boxes,dtype=torch.float32).reshape(-1,4),
                    image=row['image'])


def collate(items):
    return dict(img=torch.stack([x['img'] for x in items]),
                masks=torch.stack([x['masks'] for x in items]),
                valid_pixels=torch.stack([x['valid_pixels'] for x in items]),
                cls=torch.cat([x['cls'] for x in items]),
                bboxes=torch.cat([x['bboxes'] for x in items]),
                batch_idx=torch.cat([torch.full((len(x['cls']),),i) for i,x in enumerate(items)]))
