"""Hand-computed offline identity oracles; no runtime/GT coupling."""
import copy
import pytest


def evaluate(frames, **kwargs):
    from neusymnav.evaluation.association_quality import evaluate_association
    return evaluate_association(frames, **kwargs)


def frame(index, identities=('p',), gt_ids=('g',)):
    return dict(frame_id=str(index),
        gt=[dict(id=g, label='chair', bbox=[i*20, 0, i*20+10, 10]) for i, g in enumerate(gt_ids)],
        pred=[dict(id=f'{index}-{i}', identity=p, label='wrong label', score=.8,
                   bbox=[i*20, 0, i*20+10, 10]) for i, p in enumerate(identities)])


def test_same_identity_geometry_matches_without_using_semantic_labels():
    result = evaluate([frame(0), frame(1), frame(2)])
    online = result['online']
    assert result['available'] is True
    assert online['idf1']['value'] == 1
    assert (online['idf1']['idtp'], online['idf1']['idfp'], online['idf1']['idfn']) == (3, 0, 0)
    assert online['pairwise_precision']['value'] == online['pairwise_recall']['value'] == 1
    assert online['pairwise_recall']['denominator'] == 3
    assert online['id_switches']['value'] == online['fragments']['value'] == 0
    assert result['final_canonicalized']['available'] is False
    assert result['hota']['value'] is None and result['assa']['value'] is None


def test_identity_split_penalizes_end_to_end_and_pairwise_recall():
    result = evaluate([frame(0), frame(1), frame(2, ('q',))])['online']
    assert result['idf1']['value'] == pytest.approx(2/3)
    assert result['pairwise_precision']['value'] == 1
    assert result['pairwise_recall']['value'] == pytest.approx(1/3)
    assert result['split_pairs']['value'] == 2
    assert result['false_merge_pairs']['value'] == 0
    assert result['id_switches']['value'] == 1
    assert result['id_switches']['support'] == 2


def test_false_merge_across_distinct_gt_tracks():
    result = evaluate([frame(0), frame(1, ('p',), ('other',))])['online']
    assert result['idf1']['value'] == .5
    assert result['pairwise_precision']['value'] == 0
    assert result['pairwise_recall']['value'] is None
    assert result['false_merge_pairs']['value'] == 1
    assert result['split_pairs']['value'] == 0


def test_misses_and_false_positives_remain_in_idf1_not_pairwise_support():
    result = evaluate([frame(0), frame(1, (), ('g',)), frame(2, ('fp',), ())])
    assert result['online']['idf1']['value'] == .5
    assert result['online']['idf1']['idtp'] == 1
    assert result['online']['idf1']['idfp'] == result['online']['idf1']['idfn'] == 1
    assert result['online']['pairwise_recall']['support'] == 0
    assert result['support']['matched_observations'] == 1


def test_duplicate_rate_uses_all_prediction_observations():
    first = frame(0)
    first['pred'].append(dict(id='duplicate', identity='q', label='chair', score=.9, bbox=[0,0,10,10]))
    result = evaluate([first])
    assert result['duplicate_rate']['numerator'] == 1
    assert result['duplicate_rate']['denominator'] == 2
    assert result['duplicate_rate']['value'] == .5
    assert result['online']['idf1']['value'] == pytest.approx(2/3)


def test_fragment_requires_continuously_visible_gt_and_counts_recovery_once():
    result = evaluate([frame(0), frame(1, ()), frame(2, ()), frame(3), frame(4)])['online']
    assert result['fragments']['value'] == 1
    assert result['id_switches']['value'] == 0
    absent = evaluate([frame(0), frame(1, (), ()), frame(2)])['online']
    assert absent['fragments']['value'] == absent['id_switches']['value'] == 0


@pytest.mark.parametrize('reappears_as,recovered', [('p', 1), ('new', 0), (None, 0)])
def test_revisit_recovery_tests_first_reappearance_not_later_success(reappears_as, recovered):
    frames = [frame(0), frame(1, (), ()), frame(2, (), ()),
              frame(3, () if reappears_as is None else (reappears_as,)), frame(4)]
    result = evaluate(frames)['online']
    assert result['revisit_recovery']['numerator'] == recovered
    assert result['revisit_recovery']['denominator'] == 1
    # Occlusion itself is not a switch or fragment; a first-reappearance miss
    # has no preceding match in that visibility episode.
    assert result['fragments']['value'] == 0


def test_revisit_gap_counts_absent_annotated_frames_not_numeric_frame_ids():
    frames = [frame(100), frame(10000, (), ()), frame(90000)]
    assert evaluate(frames)['online']['revisit_recovery']['value'] is None
    assert evaluate(frames, revisit_gap_frames=1)['online']['revisit_recovery']['value'] == 1


def test_switch_after_visible_miss_is_counted_but_after_absence_is_reset():
    result = evaluate([frame(0), frame(1, ()), frame(2, ('q',))])['online']
    assert result['id_switches']['value'] == result['fragments']['value'] == 1
    result = evaluate([frame(0), frame(1, (), ()), frame(2, ('q',))])['online']
    assert result['id_switches']['value'] == 0


def test_aliases_are_final_only_transitive_and_allow_unseen_terminal():
    frames = [frame(0), frame(1, ('q',))]
    result = evaluate(frames, final_aliases={'p': 'middle', 'middle': 'canonical', 'q': 'canonical'})
    assert result['online']['idf1']['value'] == .5
    assert result['online']['id_switches']['value'] == 1
    assert result['final_canonicalized']['idf1']['value'] == 1
    assert result['final_canonicalized']['id_switches']['value'] == 0
    assert frames[0]['pred'][0]['identity'] == 'p'


def test_alias_collision_preserves_simultaneous_prediction_and_gt_counts():
    frames = [frame(0, ('p', 'q'), ('g', 'h')), frame(1, ('p', 'q'), ('g', 'h'))]
    result = evaluate(frames, final_aliases={'q': 'p'})
    assert result['online']['idf1']['value'] == 1
    final = result['final_canonicalized']
    assert final['idf1']['value'] == .5
    assert (final['idf1']['idtp'], final['idf1']['idfp'], final['idf1']['idfn']) == (2,2,2)
    assert final['pairwise_precision']['value'] == pytest.approx(1/3)
    assert final['false_merge_pairs']['value'] == 4


@pytest.mark.parametrize('aliases', [{'unused':'unused'}, {'unused':'x','x':'unused'}, {'p':2}, []])
def test_alias_cycles_and_invalid_types_fail_even_when_unused(aliases):
    with pytest.raises(ValueError, match='alias'):
        evaluate([frame(0)], final_aliases=aliases)


def test_detection_only_identity_is_unavailable_without_fabricated_ids():
    first = frame(0)
    del first['pred'][0]['identity']
    result = evaluate([first], final_aliases={})
    assert result['available'] is False
    assert result['online']['available'] is False
    assert result['final_canonicalized']['available'] is False
    assert result['support']['matched_observations'] == 1
    assert result['duplicate_rate']['value'] == 0
    assert 'identity' in result['reason']


def test_no_support_is_unavailable_ratio_not_perfect_score():
    result = evaluate([], final_aliases={})
    assert result['online']['idf1']['value'] is None
    assert result['online']['pairwise_precision']['value'] is None
    assert result['duplicate_rate']['value'] is None
    assert result['online']['revisit_recovery']['denominator'] == 0


@pytest.mark.parametrize('field,value', [('bbox',[0,0,0,1]), ('bbox',[0,0,float('nan'),1]),
                                      ('bbox',[0,0,10**1000,1]),
                                      ('bbox',[0,0,True,1]), ('score',float('inf')),
                                      ('score',10**1000),
                                      ('score',-.1), ('score',1.1), ('score',True),
                                      ('id',''), ('identity',2), ('label',None)])
def test_invalid_prediction_values_rejected(field, value):
    first = frame(0)
    first['pred'][0][field] = value
    with pytest.raises(ValueError): evaluate([first])


@pytest.mark.parametrize('kind', ['frame', 'gt', 'observation', 'identity'])
def test_duplicate_ids_rejected_in_the_appropriate_scope(kind):
    first = frame(0)
    frames = [first]
    if kind == 'frame': frames.append(copy.deepcopy(first))
    elif kind == 'gt': first['gt'].append(copy.deepcopy(first['gt'][0]))
    elif kind == 'observation':
        second = frame(1)
        second['pred'][0]['id'] = first['pred'][0]['id']
        frames.append(second)
    else:
        first['pred'].append(dict(first['pred'][0], id='new-observation'))
    with pytest.raises(ValueError, match='unique'): evaluate(frames)


@pytest.mark.parametrize('kwargs', [dict(iou_threshold=0), dict(iou_threshold=1.1),
                                  dict(iou_threshold=True), dict(revisit_gap_frames=0),
                                  dict(revisit_gap_frames=1.5), dict(revisit_gap_frames=True)])
def test_protocol_options_rejected_when_invalid(kwargs):
    with pytest.raises(ValueError): evaluate([frame(0)], **kwargs)


def test_iou_threshold_really_filters_geometry_matches():
    first = frame(0)
    first['pred'][0]['bbox'] = [5,0,15,10]  # IoU = 1/3
    assert evaluate([first])['online']['idf1']['value'] == 0
    assert evaluate([first], iou_threshold=.3)['online']['idf1']['value'] == 1
from neusymnav.evaluation.association_quality import evaluate_association


def test_standard_idf1_keeps_all_spatially_eligible_track_pairs():
    boxes = [[0,0,10,10], [2,0,12,10]]
    frames = [dict(frame_id=str(index),
        gt=[dict(id=gt, label='chair', bbox=boxes[i]) for i, gt in enumerate(('g','h'))],
        pred=[dict(id=f'{index}-{track}', identity=track, label='other', score=.9,
                   bbox=boxes[i if index == 0 else 1-i]) for i, track in enumerate(('p','q'))])
        for index in range(2)]
    result = evaluate_association(frames)['online']
    assert result['idf1']['idtp'] == 4
    assert result['idf1']['idfp'] == result['idf1']['idfn'] == 0
    assert result['idf1']['value'] == 1
    # Conditional local diagnostics still observe both geometry-selected swaps.
    assert result['id_switches']['value'] == 2
    assert result['split_pairs']['value'] == 2


def test_final_alias_counts_at_most_one_track_gt_opportunity_per_frame():
    frames = [dict(frame_id=str(index),
        gt=[dict(id='g', label='chair', bbox=[0,0,10,10])],
        pred=[dict(id=f'{index}-{track}', identity=track, label='chair', score=.9,
                   bbox=[0,0,10,10]) for track in ('p','q')]) for index in range(2)]
    result = evaluate_association(frames, final_aliases={'q':'p'})['final_canonicalized']['idf1']
    assert result['idtp'] == 2
    assert result['idfp'] == 2 and result['idfn'] == 0
    assert result['value'] == 2/3
