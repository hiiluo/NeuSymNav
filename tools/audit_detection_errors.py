#!/usr/bin/env python3
"""Offline, exact-source detection audit; no GT relabeling or runtime inlet.

Class-blind greedy joins explain errors only. Raw class-aware metrics remain
separate and preserve every source frame and GT observation/identity.
"""
from __future__ import annotations

import argparse
from collections import Counter
import html
import importlib.util
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw

from neusymnav.evaluation.detection_quality import evaluate_detection
from neusymnav.evaluation.quality_dataset import load_quality_pair
from neusymnav.evaluation.quality_export import _canonical, _sha, _snapshot_connection


def _iou(a, b):
    width = max(0, min(a[2], b[2])-max(a[0], b[0]))
    height = max(0, min(a[3], b[3])-max(a[1], b[1]))
    intersection = width*height
    return intersection/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


def _join(gt, predictions, threshold, *, class_aware=False):
    """Confidence greedy; inclusive IoU, lexical IDs break ties in both sets."""
    remaining = {obj['id']: obj for obj in sorted(gt, key=lambda o: o['id'])}
    pairs, unmatched = [], []
    for pred in sorted(predictions, key=lambda o: (-o['score'], o['id'])):
        options = [(g, _iou(g['bbox'], pred['bbox'])) for g in remaining.values()
                   if not class_aware or g['label'] == pred['label']]
        options.sort(key=lambda item: (-item[1], item[0]['id']))
        if options and options[0][1] >= threshold:
            g, overlap = options[0]
            pairs.append((pred, g, overlap))
            del remaining[g['id']]
        else:
            unmatched.append(pred)
    return pairs, unmatched, list(remaining.values())


def _ranking(counter, names):
    return [dict(zip(names, key if isinstance(key, tuple) else (key,)), count=count)
            for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def diagnose_frames(frames, *, iou_threshold=.5, confidence_threshold=.25, localization_iou=.1):
    """BBox diagnostics over all frames; masks/identity never alter matching."""
    if (type(localization_iou) not in (float, int) or not math.isfinite(localization_iou)
            or not 0 < localization_iou < iou_threshold):
        raise ValueError('require 0 < localization_iou < iou_threshold')
    # The scorer validates every box, ID, label and score before diagnostic joins.
    scoring = [dict(frame_id=f['frame_id'], **{kind: [
        {k: obj[k] for k in ('id','label','bbox','score') if k in obj}
        for obj in f[kind]] for kind in ('gt','pred')}) for f in frames]
    raw = evaluate_detection(scoring, iou_threshold=iou_threshold,
                             confidence_threshold=confidence_threshold)
    confusions, misses, fps, kinds = Counter(), Counter(), Counter(), Counter()
    diagnostics = []
    for frame in sorted(scoring, key=lambda f: f['frame_id']):
        gt = frame['gt']
        predictions = [p for p in frame['pred'] if p['score'] >= confidence_threshold]
        raw_pairs, raw_fp, raw_fn = _join(gt, predictions, iou_threshold, class_aware=True)
        misses.update(g['label'] for g in raw_fn)
        fps.update(p['label'] for p in raw_fp)
        matched, unused_pred, unused_gt = _join(gt, predictions, iou_threshold)
        pairs = [dict(pred_id=p['id'], gt_id=g['id'], pred_label=p['label'], gt_label=g['label'],
            iou=overlap, kind='correct_label_overlap' if p['label'] == g['label'] else 'label_confusion')
            for p, g, overlap in matched]
        duplicates, residual = [], []
        for pred in unused_pred:
            options = sorted(((g, _iou(pred['bbox'], g['bbox'])) for g in gt),
                             key=lambda item: (-item[1], item[0]['id']))
            if options and options[0][1] >= iou_threshold:
                g, overlap = options[0]
                duplicates.append(dict(pred_id=pred['id'], pred_label=pred['label'],
                    kind='duplicate_overlap', nearest_gt_id=g['id'], nearest_gt_label=g['label'], iou=overlap))
            else:
                residual.append(pred)
        localized, unpaired_pred, unpaired_gt = _join(unused_gt, residual, localization_iou)
        pairs += [dict(pred_id=p['id'], gt_id=g['id'], pred_label=p['label'], gt_label=g['label'],
                       iou=overlap, kind='localization', label_equal=p['label']==g['label'])
                  for p,g,overlap in localized]
        unmatched = duplicates + [dict(pred_id=p['id'], pred_label=p['label'],
            kind='unmatched_in_gt_scope', maximum_gt_iou=max((_iou(p['bbox'],g['bbox']) for g in gt),default=0))
            for p in unpaired_pred]
        for pair in pairs:
            kinds[pair['kind']] += 1
            if pair['kind'] == 'label_confusion': confusions[pair['gt_label'], pair['pred_label']] += 1
        kinds.update(row['kind'] for row in unmatched)
        kinds['unmatched_gt'] += len(unpaired_gt)
        diagnostics.append(dict(frame_id=frame['frame_id'], pairs=pairs,
            unmatched_predictions=unmatched, unmatched_gt=sorted(g['id'] for g in unpaired_gt),
            below_threshold_predictions=sorted(p['id'] for p in frame['pred'] if p['score']<confidence_threshold),
            class_aware=dict(tp_pairs=[dict(pred_id=p['id'],gt_id=g['id'],iou=v) for p,g,v in raw_pairs],
                fp_ids=sorted(p['id'] for p in raw_fp), fn_ids=sorted(g['id'] for g in raw_fn))))
    return dict(schema_version=1, raw_metrics=raw, diagnostics=diagnostics,
        diagnostic_counts=dict(sorted(kinds.items())),
        rankings=dict(label_confusions=_ranking(confusions, ('gt_label','pred_label')),
            class_aware_misses=_ranking(misses, ('label',)), class_aware_fp=_ranking(fps, ('label',))),
        protocol=dict(localization_iou=localization_iou,
            matching='separate class-aware and class-blind confidence-greedy one-to-one bbox joins; inclusive thresholds; lexical ID ties',
            duplicate='unpaired prediction overlapping an already-paired GT at high IoU; may have wrong label',
            localization='residual one-to-one pair at localization_iou <= IoU < operating IoU',
            raw_metrics='bbox only; original masks retained and rendered separately; mask AP not recomputed',
            scope='all supplied frames/GT; no ontology remapping; unmatched predictions are not proof of hallucination',
            limitations=['GT semantic/taxonomy/visibility scope may exclude real RGB objects.',
                'Class-blind diagnostic pairs are not TP, identity or metric corrections.',
                'Original frames are development diagnostics, not held-out evaluation.']))


def select_representatives(diagnostics, limit):
    """Cover distinct confusion/error groups, then fill by raw FP+FN burden."""
    ranked = sorted(diagnostics,key=lambda f:(
        -(len(f['class_aware']['fp_ids'])+len(f['class_aware']['fn_ids'])), f['frame_id']))
    confusion_counts = Counter((p['gt_label'],p['pred_label']) for f in ranked
                              for p in f['pairs'] if p['kind']=='label_confusion')
    groups = [[f for f in ranked if any(p['kind']=='label_confusion' and
        (p['gt_label'],p['pred_label'])==key for p in f['pairs'])]
        for key in sorted(confusion_counts,key=lambda k:(-confusion_counts[k],k))]
    groups += [[f for f in ranked if any(p['kind']==kind for p in f['unmatched_predictions'])]
               for kind in ('duplicate_overlap','unmatched_in_gt_scope')]
    groups += [[f for f in ranked if any(p['kind']=='localization' for p in f['pairs'])],
               [f for f in ranked if f['unmatched_gt']]]
    selected, seen = [], set()
    for group in groups:
        if group and group[0]['frame_id'] not in seen:
            selected.append(group[0]); seen.add(group[0]['frame_id'])
    for frame in ranked:
        if frame['frame_id'] not in seen:
            selected.append(frame); seen.add(frame['frame_id'])
    return selected[:limit]


def _overlay(source, frame, path):
    """Exact-size RGB plus separate GT and prediction mask/box panels."""
    rgb = Image.fromarray(source.rgb)
    width, height = rgb.size
    output = Image.new('RGB', (width*3, height+40), '#111111')
    output.paste(rgb, (0,40))
    draw = ImageDraw.Draw(output)
    draw.text((5,5), 'Source RGB: '+frame['frame_id'], fill='white')
    for column, kind, color in ((1,'gt',(50,230,100)),(2,'pred',(255,100,50))):
        panel = np.asarray(rgb).copy()
        for obj in frame[kind]:
            if 'mask' in obj:
                mask = obj['mask']
                panel[mask] = (panel[mask]*.65+np.asarray(color)*.35).astype(np.uint8)
        output.paste(Image.fromarray(panel), (column*width,40))
        draw.text((column*width+5,5), 'GT (original)' if kind=='gt' else 'Predictions (original)', fill=color)
        for index,obj in enumerate(frame[kind]):
            x1,y1,x2,y2 = obj['bbox']
            # Continuous xyxy boxes, drawn on their last included source pixel.
            draw.rectangle((column*width+x1,40+y1,column*width+x2-1,40+y2-1),outline=color,width=2)
            label = f"{obj['id']} {obj['label']}" + (f" {obj['score']:.3f}" if kind=='pred' else '')
            draw.text((column*width+5,42+index*13),label,fill=color,stroke_width=1,stroke_fill='black')
    output.save(path)


def audit_detection_errors(objects, *, predictions, ground_truth, out, iou_threshold=.5,
                           confidence_threshold=.25, localization_iou=.1, max_images=16):
    root, pred_path, gt_path, output = map(lambda p: Path(p).absolute(), (objects,predictions,ground_truth,out))
    if any(output.resolve().is_relative_to(p.resolve()) for p in (root,pred_path.parent,gt_path.parent)):
        raise ValueError('output must be outside all source inputs')
    if output.exists() or output.is_symlink(): raise FileExistsError('output must be new')
    if type(max_images) is not int or not 1 <= max_images <= 1000: raise ValueError('max_images must be 1..1000')
    pair = load_quality_pair(gt_path, pred_path)
    loader_path = Path(__file__).with_name('replay_association_quality.py')
    spec = importlib.util.spec_from_file_location('audit_source_loader', loader_path)
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    with _snapshot_connection(root) as connection:
        _, sources, assets, _, ledger_hash = loader._inputs(root, pred_path, pair['predictions'], connection)
    report = diagnose_frames(pair['frames'], iou_threshold=iou_threshold,
        confidence_threshold=confidence_threshold, localization_iou=localization_iou)
    files = [Path(__file__),loader_path]
    files += [Path(__file__).parents[1]/'src/neusymnav/evaluation'/name
              for name in ('detection_quality.py','quality_dataset.py','quality_export.py')]
    mask_assets = {}
    for document,path in ((pair['gt'],gt_path),(pair['predictions'],pred_path)):
        for frame in document['frames']:
            for obj in frame['objects']:
                if isinstance(obj.get('mask'),dict):
                    ref = obj['mask']; mask_path = Path(ref['path'])
                    mask_path = mask_path if mask_path.is_absolute() else path.parent/mask_path
                    mask_assets[str(mask_path.absolute())] = ref['sha256']
    report['source_binding'] = dict(input_hashes=pair['input_hashes'],binding=pair['gt']['binding'],
        source_ledger=str(root), source_predictions=str(pred_path), source_ground_truth=str(gt_path),
        ledger_logical_sha256=ledger_hash, verified_source_assets=assets, verified_mask_files=mask_assets,
        tool_sha256={str(p.resolve()):_sha(p.read_bytes()) for p in files},
        gt_provenance=pair['gt']['provenance'], prediction_provenance=pair['predictions']['provenance'],
        source_metadata=pair['predictions']['provenance']['source_metadata'])
    # Keep original IDs/identities/status/frame bindings and mask references verbatim.
    report['original_frames'] = dict(gt=pair['gt']['frames'], predictions=pair['predictions']['frames'])
    by_frame = {f['frame_id']: f for f in pair['frames']}
    sources = {frame['frame_id']:source for source,_,frame in sources}
    ranked = select_representatives(report['diagnostics'], max_images)
    report['images'] = [dict(frame_id=f['frame_id'], path=f'images/{index:03d}.png',
        errors=len(f['class_aware']['fp_ids'])+len(f['class_aware']['fn_ids'])) for index,f in enumerate(ranked)]
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='detection-audit-', dir=output.parent) as temporary:
        stage = Path(temporary)
        (stage/'images').mkdir()
        for image in report['images']:
            frame = by_frame[image['frame_id']]
            _overlay(sources[image['frame_id']],frame,stage/image['path'])
        body = ['<!doctype html><meta charset="utf-8">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'">',
            '<title>Original detection error audit</title><style>body{background:#171717;color:#eee;font:16px sans-serif}img{max-width:100%}pre{white-space:pre-wrap}</style>',
            '<h1>Original detection error audit</h1><p>Source RGB | original GT | original predictions. Unmatched means unmatched in supplied GT scope. Development diagnostics only.</p>',
            '<pre>'+html.escape(_canonical(dict(operating_point=report['raw_metrics']['operating_point'],rankings=report['rankings'],diagnostic_counts=report['diagnostic_counts'])))+'</pre>']
        for image in report['images']:
            body.append('<h2>'+html.escape(image['frame_id'])+'</h2><img alt="Source-bound RGB/GT/prediction comparison" src="'+image['path']+'">')
        (stage/'index.html').write_text('\n'.join(body)+'\n')
        (stage/'audit.json').write_text(_canonical(report)+'\n')
        if output.exists() or output.is_symlink(): raise FileExistsError('output appeared during preparation')
        stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('objects','predictions','ground-truth','out'): parser.add_argument('--'+name,required=True)
    parser.add_argument('--iou-threshold',type=float,default=.5)
    parser.add_argument('--confidence-threshold',type=float,default=.25)
    parser.add_argument('--localization-iou',type=float,default=.1)
    parser.add_argument('--max-images',type=int,default=16)
    args = parser.parse_args()
    report = audit_detection_errors(args.objects,predictions=args.predictions,ground_truth=args.ground_truth,
        out=args.out,iou_threshold=args.iou_threshold,confidence_threshold=args.confidence_threshold,
        localization_iou=args.localization_iou,max_images=args.max_images)
    print(_canonical(dict(support=report['raw_metrics']['support'],operating_point=report['raw_metrics']['operating_point'],
        diagnostic_counts=report['diagnostic_counts'],rankings=report['rankings'],out=str(Path(args.out).absolute()))))


if __name__ == '__main__': main()
