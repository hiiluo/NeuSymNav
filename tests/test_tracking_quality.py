"""Analytic HOTA oracles catch identity, support and threshold mistakes."""
import copy
from collections import Counter
from fractions import Fraction
from itertools import permutations
import math
import random

import pytest


def evaluate(frames, **kwargs):
    from neusymnav.evaluation.tracking_quality import evaluate_tracking
    return evaluate_tracking(frames, **kwargs)


def frame(index, tracks=('p',), gt_ids=('g',)):
    return dict(frame_id=str(index),
        gt=[dict(id=g, label='chair', bbox=[i*20, 0, i*20+10, 10])
            for i, g in enumerate(gt_ids)],
        pred=[dict(id=f'{index}-{i}', identity=p, label='wrong', score=0.,
                   bbox=[i*20, 0, i*20+10, 10]) for i, p in enumerate(tracks)])


def test_perfect_tracks_ignore_labels_and_confidence_and_keep_all_thresholds():
    result = evaluate([frame(0), frame(1)], final_aliases={})
    online = result['online']
    assert online['available'] is True
    assert online['mean'] == dict(hota=1., assa=1., deta=1., loca=1.)
    assert online['support']['gt_observations'] == 2
    assert online['support']['predicted_observations'] == 2
    assert len(online['per_alpha']) == 19
    for index, row in enumerate(online['per_alpha'], 1):
        assert row['alpha'] == pytest.approx(index*.05)
        assert (row['tp'], row['fp'], row['fn']) == (2, 0, 0)
    assert result['final_canonicalized'] == online


@pytest.mark.parametrize('frames,deta,assa,hota,counts', [
    ([frame(0), frame(1, ())], .5, .5, .5, (1, 0, 1)),
    ([frame(0), frame(1, ('q',))], 1., .5, math.sqrt(.5), (2, 0, 0)),
    ([frame(0), frame(1, gt_ids=('h',))], 1., .5, math.sqrt(.5), (2, 0, 0)),
    ([frame(0), frame(1, gt_ids=())], .5, .5, .5, (1, 1, 0)),
    ([frame(0, ('p','extra')), frame(1)], 2/3, 1., math.sqrt(2/3), (2, 1, 0)),
])
def test_misses_splits_merges_and_false_positives_include_all_track_observations(
        frames, deta, assa, hota, counts):
    result = evaluate(frames)['online']
    assert result['mean']['deta'] == pytest.approx(deta)
    assert result['mean']['assa'] == pytest.approx(assa)
    assert result['mean']['hota'] == pytest.approx(hota)
    for row in result['per_alpha']:
        assert (row['tp'], row['fp'], row['fn']) == counts


def test_association_is_weighted_by_matched_detections_not_number_of_tracks():
    frames = [frame(0, ('p','r'), ('g','h')), frame(1, ('p','r'), ('g','h')),
              frame(2, ('q',))]
    result = evaluate(frames)['online']['mean']
    assert result['assa'] == pytest.approx(11/15)
    assert result['hota'] == pytest.approx(math.sqrt(11/15))


def test_localization_thresholds_and_mean_hota_are_not_sqrt_of_mean_components():
    first = frame(0)
    first['gt'][0]['bbox'] = [0, 0, 3, 2]
    first['pred'][0]['bbox'] = [1, 0, 4, 2]  # IoU = .5.
    result = evaluate([first])['online']
    assert result['mean']['hota'] == pytest.approx(10/19)
    assert result['mean']['loca'] == pytest.approx((10*.5+9)/19)
    for index, row in enumerate(result['per_alpha']):
        assert (row['tp'], row['fp'], row['fn']) == ((1,0,0) if index < 10 else (0,1,1))
        assert row['loca'] == (.5 if index < 10 else 1.)


def test_global_alignment_can_prefer_temporal_identity_over_largest_frame_iou():
    frames = [frame(index, ('p','q'), ('g','h')) for index in range(6)]
    for item in frames:
        item['gt'][1]['bbox'] = [2,0,12,10]
        item['pred'][1]['bbox'] = [2,0,12,10]
    frames[-1]['pred'][0]['bbox'], frames[-1]['pred'][1]['bbox'] = [2,0,12,10], [0,0,10,10]
    result = evaluate(frames)['online']
    # Global alignment keeps p->g and q->h on frame 6 despite IoU 2/3,
    # whereas pure frame IoU would exchange them at IoU 1.
    assert result['mean']['hota'] == pytest.approx(121/133)
    for index, row in enumerate(result['per_alpha']):
        if index < 13:
            assert (row['tp'], row['fp'], row['fn']) == (12,0,0)
            assert row['assa'] == row['deta'] == row['hota'] == 1.
            assert row['loca'] == pytest.approx(17/18)
        else:
            # Filtering happens after a single Hungarian solution: it does
            # not reassign the last-frame pairs to recover their perfect IoUs.
            assert (row['tp'], row['fp'], row['fn']) == (10,2,2)
            assert row['assa'] == pytest.approx(5/7)
            assert row['hota'] == pytest.approx(5/7)


def _fraction_iou(first, second):
    width = max(0, min(first[2], second[2])-max(first[0], second[0]))
    height = max(0, min(first[3], second[3])-max(first[1], second[1]))
    area = lambda box: (box[2]-box[0])*(box[3]-box[1])
    return Fraction(width*height, area(first)+area(second)-width*height)


def _exhaustive_oracle(frames):
    """Exact rational soft alignment and exhaustive assignment, never scipy."""
    gt_count, pred_count, potential = Counter(), Counter(), Counter()
    similarities = []
    for item in frames:
        gt_count.update(g['id'] for g in item['gt'])
        pred_count.update(p['identity'] for p in item['pred'])
        sim = [[_fraction_iou(g['bbox'], p['bbox']) for p in item['pred']] for g in item['gt']]
        similarities.append(sim)
        for i, g in enumerate(item['gt']):
            for j, p in enumerate(item['pred']):
                union = sum(sim[i])+sum(row[j] for row in sim)-sim[i][j]
                if union:
                    potential[g['id'],p['identity']] += sim[i][j]/union
    choices = []
    for item, sim in zip(frames, similarities):
        scored = []
        for candidate in permutations(range(2)):
            score = 0
            for i, j in enumerate(candidate):
                g, p = item['gt'][i]['id'], item['pred'][j]['identity']
                count = potential[g,p]
                score += count/(gt_count[g]+pred_count[p]-count)*sim[i][j]
            scored.append((score, candidate))
        scored.sort(reverse=True)
        if abs(float(scored[0][0]-scored[1][0])) < 1e-12:
            return None  # A tie's arbitrary optimum may change threshold support.
        choices.append(scored[0][1])
    results = []
    for step in range(1,20):
        matches, total_iou = Counter(), Fraction(0)
        for item, sim, choice in zip(frames, similarities, choices):
            for i, j in enumerate(choice):
                if float(sim[i][j]) >= step*.05-2.220446049250313e-16:
                    matches[item['gt'][i]['id'],item['pred'][j]['identity']] += 1
                    total_iou += sim[i][j]
        tp = sum(matches.values())
        fp = fn = len(frames)*2-tp
        assa = sum(Fraction(n*n,gt_count[g]+pred_count[p]-n) for (g,p),n in matches.items())/max(1,tp)
        deta = Fraction(tp,tp+fp+fn)
        results.append(dict(tp=tp,fp=fp,fn=fn,assa=float(assa),deta=float(deta),
            hota=math.sqrt(float(assa*deta)),loca=float(total_iou/tp) if tp else 1.))
    return results


def test_small_random_boxes_agree_with_exact_rational_exhaustive_assignment_oracle():
    rng = random.Random(3948)
    compared = 0
    for trial in range(40):
        frames = [frame(index, ('p','q'), ('g','h')) for index in range(3)]
        for item in frames:
            for detection in item['gt']+item['pred']:
                x, y = rng.randrange(9), rng.randrange(9)
                detection['bbox'] = [x,y,x+rng.randrange(5,15),y+rng.randrange(5,15)]
        expected = _exhaustive_oracle(frames)
        if expected is None:
            continue
        actual = evaluate(frames)['online']['per_alpha']
        for got, wanted in zip(actual, expected):
            for name, value in wanted.items():
                assert got[name] == pytest.approx(value), (trial,name,got,wanted)
        compared += 1
    assert compared >= 30


def test_alpha_boundary_accepts_one_float_epsilon_below_threshold():
    first = frame(0)
    first['gt'][0]['bbox'] = [0, 0, 1, 1]
    first['pred'][0]['bbox'] = [0, 0, math.nextafter(.5, 0), 1]
    result = evaluate([first])['online']
    assert result['per_alpha'][9]['tp'] == 1
    first['pred'][0]['bbox'][2] = .5-1e-12
    assert evaluate([first])['online']['per_alpha'][9]['tp'] == 0


@pytest.mark.parametrize('tracks,gt_ids,counts', [((), ('g',), (0,0,1)),
                                                (('p',), (), (0,1,0))])
def test_one_sided_support_scores_zero_but_loca_uses_reference_empty_match_value(tracks, gt_ids, counts):
    result = evaluate([frame(0, tracks, gt_ids)])['online']
    assert result['available'] is True
    assert result['mean'] == dict(hota=0., assa=0., deta=0., loca=1.)
    assert (result['per_alpha'][0]['tp'], result['per_alpha'][0]['fp'],
            result['per_alpha'][0]['fn']) == counts


@pytest.mark.parametrize('frames', [[], [frame(0, (), ())]])
def test_both_sides_empty_are_unavailable_and_document_reference_difference(frames):
    result = evaluate(frames, final_aliases={})
    assert result['online']['available'] is False
    assert result['online']['mean']['hota'] is None
    assert 'support' in result['online']['reason']
    assert 'empty' in result['online']['protocol']['empty_sequence_policy']


def test_missing_identity_never_fabricates_tracks_but_retains_detection_support():
    first = frame(0)
    del first['pred'][0]['identity']
    result = evaluate([first], final_aliases={})
    for side in result.values():
        assert side['available'] is False
        assert 'identity' in side['reason']
        assert side['support']['predicted_observations'] == 1


def test_aliases_only_affect_final_result_and_resolve_transitively_without_mutation():
    frames = [frame(0), frame(1, ('q',))]
    original = copy.deepcopy(frames)
    result = evaluate(frames, final_aliases={'p':'middle', 'middle':'new', 'q':'new'})
    assert result['online']['mean']['assa'] == .5
    assert result['final_canonicalized']['mean']['hota'] == 1.
    assert result['final_canonicalized']['support']['unique_predicted_ids'] == 1
    assert frames == original
    assert evaluate(frames)['final_canonicalized']['available'] is False


def test_same_frame_alias_collision_is_unavailable_without_discarding_online_predictions():
    result = evaluate([frame(0, ('p','q'), ('g','h'))], final_aliases={'q':'p'})
    assert result['online']['mean']['hota'] == 1.
    final = result['final_canonicalized']
    assert final['available'] is False
    assert 'within' in final['reason']
    assert final['support']['predicted_observations'] == 2


@pytest.mark.parametrize('aliases', [{'unused':'unused'}, {'unused':'x', 'x':'unused'}, {'p':2}, []])
def test_invalid_aliases_rejected_even_if_unused(aliases):
    with pytest.raises(ValueError, match='alias'):
        evaluate([frame(0)], final_aliases=aliases)


@pytest.mark.parametrize('kind', ['frame', 'gt', 'observation', 'identity'])
def test_duplicate_input_identifiers_are_rejected_in_their_declared_scope(kind):
    first = frame(0)
    frames = [first]
    if kind == 'frame':
        frames.append(copy.deepcopy(first))
    elif kind == 'gt':
        first['gt'].append(copy.deepcopy(first['gt'][0]))
    elif kind == 'observation':
        second = frame(1)
        second['pred'][0]['id'] = first['pred'][0]['id']
        frames.append(second)
    else:
        first['pred'].append(dict(first['pred'][0], id='another'))
    with pytest.raises(ValueError, match='unique'):
        evaluate(frames)


@pytest.mark.parametrize('field,value', [('bbox',[0,0,0,1]), ('bbox',[0,0,float('nan'),1]),
    ('score',float('inf')), ('score',True), ('score',-1), ('id',''), ('identity',2), ('label',None)])
def test_invalid_observations_use_association_input_validation(field, value):
    first = frame(0)
    first['pred'][0][field] = value
    with pytest.raises(ValueError):
        evaluate([first])
