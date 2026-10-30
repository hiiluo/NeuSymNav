"""Offline quality report; never imported by the live pipeline."""
from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path

from .quality_dataset import load_quality_pair


def unavailable(reason):
    return dict(available=False, value=None, support=0, reason=reason)


def _markdown(report):
    lines = ['# Object quality evaluation', '',
        f"Evidence: **{report['evidence_kind']}**. These are offline annotation scores, not runtime acceptance.", '',
        '## Detection', '', '| Metric | Value |', '|---|---:|']
    detection = report['detection']
    for key in ('tp','fp','fn','precision','recall','f1'):
        lines.append(f"| {key} | {detection['operating_point'].get(key)} |")
    for family in ('bbox_ap','mask_ap'):
        for key in ('ap50','ap75','ap50_95'):
            lines.append(f"| {family}.{key} | {detection[family].get(key)} |")
    for title,key in [('Association','association'),('Geometry','geometry')]:
        lines += ['',f'## {title}','', '```json', json.dumps(report[key],ensure_ascii=False,indent=2), '```']
    lines += ['', '## Limitations', '']
    lines += ['- '+item for item in report['limitations']]
    return '\n'.join(lines)+'\n'


def evaluate_quality(gt_path, prediction_path, *, out, confidence_threshold=0.25,
                     iou_threshold=0.5, geometry_iou_threshold=0.25,
                     point_tolerance_m=0.05, revisit_gap_frames=2):
    from .detection_quality import evaluate_detection
    from .association_quality import evaluate_association
    from .geometry_quality import evaluate_geometry
    from .tracking_quality import evaluate_tracking
    pair = load_quality_pair(gt_path, prediction_path)
    root = Path(out)
    if root.exists() and any(root.iterdir()): raise ValueError('quality report requires empty output directory')
    frames = pair['frames']; gt = pair['gt']; pred = pair['predictions']
    detection_frames = []
    for frame in frames:
        row = dict(frame_id=frame['frame_id'])
        for side in ('gt','pred'):
            row[side] = []
            for obj in frame[side]:
                item = {k:v for k,v in obj.items() if k != 'identity'}
                if 'mask' in item: item['mask'] = item['mask'].tolist()
                row[side].append(item)
        detection_frames.append(row)
    detection = evaluate_detection(detection_frames, iou_threshold=iou_threshold,
                                   confidence_threshold=confidence_threshold)
    detection['prediction_scope'] = dict(score_floor=pred['score_floor'],
        max_detections=pred['max_detections'],
        ap_scope='AP over supplied predictions only; upstream filtering cannot be undone',
        frame_status_counts=dict(Counter(frame['status'] for frame in frames)))
    assoc_frames = []
    for index, frame in enumerate(frames):
        observations = []
        for obj in frame['pred']:
            if obj['score'] < confidence_threshold: continue
            item = {k:v for k,v in obj.items() if k != 'mask'}
            # Detector IDs are frame-local; track identity remains unchanged.
            item['id'] = json.dumps([index,obj['id']],separators=(',',':'))
            observations.append(item)
        assoc_frames.append(dict(frame_id=frame['frame_id'],
            gt=[{k:v for k,v in obj.items() if k!='mask'} for obj in frame['gt']], pred=observations))
    if pred['identity_semantics'] == 'none':
        association = dict(online=unavailable('prediction input has no identity history'),
            final_canonicalized=unavailable('prediction input has no identity history'))
    else:
        association = evaluate_association(assoc_frames, iou_threshold=iou_threshold,
            revisit_gap_frames=revisit_gap_frames, final_aliases=pred.get('final_aliases'))
        if pred['identity_semantics'] == 'final_canonical_only':
            if pred.get('final_aliases') is None:
                association['final_canonicalized'] = association['online']
            association['online'] = unavailable('ledger IDs rewritten by merge; original online IDs unavailable')
    association['confidence_threshold'] = confidence_threshold
    if pred['identity_semantics'] == 'none':
        tracking = dict(online=unavailable('prediction input has no identity history'),
            final_canonicalized=unavailable('prediction input has no identity history'))
    else:
        tracking = evaluate_tracking(assoc_frames, final_aliases=pred.get('final_aliases'))
        if pred['identity_semantics'] == 'final_canonical_only':
            if pred.get('final_aliases') is None:
                tracking['final_canonicalized'] = tracking['online']
            tracking['online'] = unavailable('ledger IDs rewritten by merge; original online IDs unavailable')
    association['tracking'] = tracking
    association.pop('hota',None); association.pop('assa',None)
    geometry = unavailable('supply both observed-support geometry_objects and geometry_scope')
    if 'geometry_objects' in gt or 'geometry_objects' in pred:
        if not all('geometry_objects' in doc and isinstance(doc.get('geometry_scope'),str) and doc['geometry_scope'].strip() for doc in (gt,pred)):
            raise ValueError('both geometry inputs require explicit geometry_objects and geometry_scope')
        if gt['geometry_scope'] != pred['geometry_scope']: raise ValueError('geometry scope mismatch')
        geometry = dict(available=True, **evaluate_geometry(pred['geometry_objects'],gt['geometry_objects'],
            iou_threshold=geometry_iou_threshold, point_tolerance_m=point_tolerance_m))
        geometry['geometry_scope'] = gt['geometry_scope']
        if 'scope_gt_ids' in gt:
            scope = gt['scope_gt_ids']
            if not isinstance(scope,list) or any(not isinstance(x,str) or not x for x in scope) or len(set(scope)) != len(scope):
                raise ValueError('scope_gt_ids must be unique nonempty strings')
            if not {o['id'] for o in gt['geometry_objects']} <= set(scope): raise ValueError('observed GT not contained in scope')
            geometry['volume']['object_scope_coverage'] = dict(
                value=geometry['volume']['tp']/len(scope) if scope else None,
                numerator=geometry['volume']['tp'], denominator=len(scope),
                denominator_name='declared scene-scope GT objects')
    report = dict(schema_version=1, evidence_kind=gt['provenance']['kind'], binding=gt['binding'],
        provenance=dict(ground_truth=gt['provenance'],predictions=pred['provenance']), input_hashes=pair['input_hashes'],
        evaluated_frames=len(frames), detection=detection, geometry=geometry, association=association,
        native_runtime_validated=False, limitations=[
            'Synthetic annotations test evaluator correctness, not model accuracy.' if gt['provenance']['kind']=='synthetic' else 'Accuracy depends on independent annotation quality and declared visibility scope.',
            'Box/mask AP uses the non-crowd/non-ignore 101-point subset; not full official COCO evaluation.',
            'AP is limited to supplied confidence floor and detection cap; empty/missing/failed predictions remain in frame scope.',
            'Association is conditional on selected annotated frame sequence; pairwise metrics use geometrically matched observations only.',
            'Revisit gaps count absent annotated frames, not elapsed seconds or all sensor frames.',
            'HOTA/AssA follow the TrackEval sequence algorithm with class-agnostic bbox IoU; this is a declared object-memory adaptation, not an official benchmark submission.',
            'No quality acceptance threshold, runtime acceptance, or causal model improvement is inferred.'])
    root.mkdir(parents=True,exist_ok=True)
    encoded = json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    (root/'report.json').write_text(encoded)
    (root/'report.md').write_text(_markdown(report))
    return report
