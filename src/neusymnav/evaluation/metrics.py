"""Explicit support and measured-only runtime summaries for offline evaluation."""
from __future__ import annotations
import math


RUNTIME_METRICS = (
    'capture_to_result_ms','capture_to_commit_ms','admitted_fraction','accepted_fraction',
    'stale_fraction','replaced_fraction','control_depth_age_ms','control_stop_reasons',
    'actual_input_resolution_hw','health_state','rss_peak_bytes','vram_peak_bytes',
    'raw_completeness','export_completeness','explored_free_area_m2','distance_m',
    'no_progress_intervals','object_id_switches','object_merges',
    'room_membership_assigned','room_membership_ambiguous',
)


def unavailable(reason='not measured by supplied runtime exports'):
    return dict(value=None,support=0,reason=reason)


def measured(value, *, support=1, source):
    return dict(value=value,support=support,reason=None,source=source)


def ratio(numerator, denominator, *, denominator_name):
    if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in (numerator,denominator)) or numerator>denominator:
        raise ValueError('ratio requires finite 0 <= numerator <= denominator')
    return dict(value=numerator/denominator if denominator else None,numerator=numerator,
                denominator=denominator,denominator_name=denominator_name,support=denominator,
                reason=None if denominator else 'no support')


def runtime_metrics(summary=None, *, nav=None, hierarchy=None):
    result={name:unavailable() for name in RUNTIME_METRICS}
    if summary is None:return result
    telemetry=summary.get('runtime',{}).get('metrics',{})
    submitted=telemetry.get('submitted');offered=telemetry.get('offered');accepted=telemetry.get('durable_accepted')
    if type(submitted) is int and type(offered) is int and submitted>=offered>=0:
        result['admitted_fraction']=ratio(offered,submitted,denominator_name='submitted inputs (all modalities)')
    if type(offered) is int and type(accepted) is int and offered>=accepted>=0:
        result['accepted_fraction']=ratio(accepted,offered,denominator_name='offered semantic keyframes')
    # A final age is a snapshot, not a cadence/p95/control age measurement.
    health=telemetry.get('health')
    if isinstance(health,dict):result['health_state']=measured(health,source='summary.runtime.metrics.health (final snapshot)')
    certificate=summary.get('recording_certificate')
    if isinstance(certificate,dict) and type(certificate.get('complete')) is bool:
        result['raw_completeness']=measured(certificate['complete'],source='summary.recording_certificate')
    result['export_completeness']=measured(summary.get('hierarchy_available') is True,
        source='validated manifest contains coherent objects/map/hierarchy snapshots; canonical ledger is not exported, event summary completeness reported separately')
    if nav is not None:
        import numpy as np
        result['explored_free_area_m2']=measured(float(np.count_nonzero(nav.states==0)*nav.resolution_m**2),
            source='nav.json observed FREE cells within final exported snapshot; not whole explored world')
    if hierarchy is not None:
        memberships=[node.attributes.get('membership_status','unavailable') for node in hierarchy.nodes.values() if node.kind=='object']
        for status,name in [('assigned','room_membership_assigned'),('ambiguous','room_membership_ambiguous')]:
            result[name]=ratio(sum(m==status for m in memberships),len(memberships),denominator_name='exported object memberships')
    return result


def evaluate_labels(pairs, taxonomy):
    """Raw string equality and frozen-taxonomy equality use identical support.

    Unknown canonical categories do not count as a correct unknown/unknown pair.
    Geometry matching must precede this function; it never chooses matches.
    """
    pairs=list(pairs)
    if any(not isinstance(p,str) or not isinstance(g,str) for p,g in pairs):raise ValueError('labels must be strings')
    canonical=[(taxonomy.canonicalize(p),taxonomy.canonicalize(g)) for p,g in pairs]
    return dict(exact=ratio(sum(p==g for p,g in pairs),len(pairs),denominator_name='geometrically matched labeled objects'),
        canonical=ratio(sum(p is not None and p==g for p,g in canonical),len(pairs),denominator_name='geometrically matched labeled objects including unknown'),
        canonical_known_pairs=sum(p is not None and g is not None for p,g in canonical))


def aabb_iou(first,second):
    """Volume IoU of canonical metre-space AABBs; zero-volume boxes unsupported."""
    import numpy as np
    first=np.asarray(first,dtype=float);second=np.asarray(second,dtype=float)
    if any(x.shape!=(2,3) or not np.isfinite(x).all() or np.any(x[1]<=x[0]) for x in (first,second)):
        raise ValueError('3D bounds require finite ordered positive volume')
    overlap=np.maximum(0,np.minimum(first[1],second[1])-np.maximum(first[0],second[0]))
    intersection=float(np.prod(overlap));union=float(np.prod(first[1]-first[0])+np.prod(second[1]-second[0])-intersection)
    return intersection/union


def aabb_xy_iou(first,second):
    """Explicit XY footprint diagnostic, distinct from 3D geometry accuracy."""
    import numpy as np
    values=[np.asarray(x,dtype=float) for x in (first,second)]
    if any(x.shape!=(2,3) or not np.isfinite(x).all() or np.any(x[1]<x[0]) or np.any(x[1,:2]<=x[0,:2]) for x in values):
        raise ValueError('XY footprint requires finite ordered bounds and positive area')
    first,second=values
    intersection=float(np.prod(np.maximum(0,np.minimum(first[1,:2],second[1,:2])-np.maximum(first[0,:2],second[0,:2]))))
    union=float(np.prod(first[1,:2]-first[0,:2])+np.prod(second[1,:2]-second[0,:2])-intersection)
    return intersection/union


def evaluate_objects(objects, ground_truth, taxonomy):
    from .instance_metrics import evaluate_instances
    predictions={key:state for key,state in objects.objects.items() if state.lifecycle!='retired'}
    gt={item['gt_id']:item for item in ground_truth['objects']}
    predicted_ids=tuple(sorted(predictions));visible=tuple(ground_truth['visible_object_ids']);scope=tuple(sorted(gt))
    # Zero-volume runtime bounds cannot support volume IoU. Exclude from matched
    # geometry, but preserve them as unmatched predictions in the denominator.
    scores=[]
    for key in predicted_ids:
        row=[]
        for target in visible:
            try:row.append((aabb_iou if ground_truth['geometry_metric']=='aabb_volume_iou_v1' else aabb_xy_iou)(predictions[key].bounds,gt[target]['bounds']))
            except ValueError:row.append(0.)
        scores.append(row)
    instance=evaluate_instances(predicted_ids,visible,scope,scores,minimum_score=.25)
    pairs=[(predictions[m.predicted_id].raw_label,gt[m.ground_truth_id]['raw_label']) for m in instance.matching.matches
           if predictions[m.predicted_id].raw_label is not None and gt[m.ground_truth_id]['raw_label'] is not None]
    def encode(metric):
        from dataclasses import asdict
        return dict(asdict(metric),support=metric.denominator)
    return dict(label=dict(evaluate_labels(pairs,taxonomy),support=len(pairs)),
        geometry=dict(precision=encode(instance.precision),observed_recall=encode(instance.observed_recall),
            object_scope_coverage=encode(instance.coverage),support=len(visible),gt_scope_objects=len(scope),
            predictions=len(predicted_ids),matched_objects=len(instance.matching.matches),metric=ground_truth['geometry_metric']+' >=0.25, label-independent maximum-weight matching'),
        identity=unavailable('export contains no frame-level predicted/visible identity observations; final IDs are not IDF1 support'))


def empty_quality(reason='no offline GT supplied'):
    return {name:unavailable(reason) for name in ('label','geometry','identity')}
