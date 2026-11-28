from tools.psg_nav.render_belief_annotations import evaluate_case


def test_offline_ground_truth_changes_matches_without_filtering_ranks():
    case = dict(scene='s', uid='u', revision=3, target_category='chair', owners={
        'O(0)': dict(deterministic_category='chair', receipts=[
            dict(revision=1, detection_id='a', category='chair')]),
        'O(1)': dict(deterministic_category='chair', receipts=[
            dict(revision=2, detection_id='b', category='chair'),
            dict(revision=3, detection_id='c', category='sofa')]),
    })
    taxonomy = dict(categories=['chair', 'sofa'], aliases={})
    visible = [('hm3d:1', 'chair'), ('hm3d:2', 'wall')]
    rows = evaluate_case(case, {(2, 'b'): 'hm3d:1', (3, 'c'): 'hm3d:1'}, visible, taxonomy)
    assert rows[0]['native_id'] == 'O(1)'
    assert rows[0]['retrieval_ranks'] == {'deterministic': 2, 'probabilistic': 2}
    assert rows[1]['status'] == 'out_of_domain'
    assert rows[2]['native_id'] == 'O(0)' and rows[2]['status'] == 'unresolved'
