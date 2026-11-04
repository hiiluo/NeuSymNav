from neusymnav.evaluation.active_perception import oracle_frame, promotion


def test_oracles_change_only_valid_matched_fields_and_preserve_misses():
    gt = [{'id': 'g1', 'label': 'chair', 'box': [0, 0, 10, 10]}, {'id': 'g2', 'label': 'table', 'box': [20, 20, 30, 30]}]
    pred = [{'id': 'p1', 'label': 'table', 'box': [0, 0, 10, 10], 'mask': 'original'}, {'id': 'fp', 'label': 'lamp', 'box': [40, 40, 50, 50], 'mask': 'fp'}]
    result = oracle_frame(gt, pred)
    assert result['matches'] == 1
    assert result['fn'] == 1 and result['unmatched_predictions'] == 1
    assert result['label'][0]['label'] == 'chair' and result['label'][0]['mask'] == 'original'
    assert result['identity'][0]['id'] == 'oracle:g1'
    assert result['identity'][1] == pred[1] and result['label'][1] == pred[1]
    assert pred[0]['label'] == 'table'


def test_promotion_refuses_missing_exhaustive_support():
    assert promotion([])['status'] == 'unavailable'


def test_promotion_requires_heldout_pairs_and_all_gates():
    row = {'scene': 's', 'start': 'a', 'exhaustive': True, 'b_ids': 5, 'r_ids': 7, 'c_ids': 6, 'b_precision': .9, 'r_precision': .89, 'b_false_merges': 0, 'r_false_merges': 0, 'b_free': 100, 'r_free': 90, 'reobserve_fraction': .2, 'b_p95': 1, 'r_p95': 1.1, 'safety_ok': True, 'resources_ok': True}
    assert promotion([row])['status'] == 'unavailable'


def test_one_to_one_split_merge_occlusion_and_partial_scope():
    gt = [{'id': 'a', 'label': 'x', 'box': [0, 0, 10, 10]}, {'id': 'b', 'label': 'x', 'box': [0, 0, 10, 10]}]
    pred = [{'id': 'merged', 'label': 'x', 'box': [0, 0, 10, 10]}, {'id': 'split', 'label': 'x', 'box': [30, 30, 40, 40]}]
    result = oracle_frame(gt, pred)
    assert result['matches'] == 1 and result['fn'] == 1 and result['unmatched_predictions'] == 1
    assert result['identity'][1] == pred[1]
    assert oracle_frame([], pred)['unmatched_predictions'] == 2
    assert oracle_frame(gt, [])['fn'] == 2


def test_nine_pairs_are_not_heldout_unless_explicit():
    rows = [{'scene': str(i // 3), 'start': str(i % 3), 'exhaustive': True, 'b_ids': 5, 'r_ids': 7, 'c_ids': 6, 'b_precision': .9, 'r_precision': .89, 'b_false_merges': 0, 'r_false_merges': 0, 'b_free': 100, 'r_free': 90, 'reobserve_fraction': .2, 'b_p95': 1, 'r_p95': 1.1, 'safety_ok': True, 'resources_ok': True} for i in range(9)]
    assert promotion(rows)['status'] == 'unavailable'


def test_promotion_applies_each_gate_to_heldout_pairs():
    rows = [{'scene': str(i // 3), 'start': str(i % 3), 'exhaustive': True, 'heldout': True, 'b_ids': 5, 'r_ids': 7, 'c_ids': 6, 'b_precision': .9, 'r_precision': .89, 'b_false_merges': 0, 'r_false_merges': 0, 'b_free': 100, 'r_free': 90, 'reobserve_fraction': .2, 'b_p95': 1, 'r_p95': 1.1, 'safety_ok': True, 'resources_ok': True} for i in range(9)]
    assert promotion(rows)['status'] == 'passed'
    rows[0]['r_free'] = 89
    assert promotion(rows)['gates']['free_area'] is False
    rows[0]['r_p95'] = float('nan')
    assert promotion(rows)['status'] == 'unavailable'
