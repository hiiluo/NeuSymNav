import pytest

from neusymnav.evaluation.room_quality import RoomSupportSnapshot, evaluate_room_geometry


def prediction(assignments, *, domain='place_points'):
    support = {key: (float(i), 0.0, 0.0) for i, key in enumerate(assignments)}
    return RoomSupportSnapshot(
        episode_id='ep', run_id='run', graph_revision=7,
        frame_convention='canonical_z_up_m_v1', observed_support=support,
        support_domain=domain, room_assignments=assignments,
        unassigned=tuple(key for key, room in assignments.items() if room is None),
        source_hashes={'graph': 'a' * 64, 'recording': 'b' * 64},
    )


def annotation(labels, *, domain='place_points', annotated=True):
    return {'schema_version': 1, 'annotation_version': 'human-room-v1',
            'support_domain': domain, 'annotated': annotated,
            'assignments': labels, 'provenance': 'manual independent annotation',
            'episode_id': 'ep', 'run_id': 'run', 'graph_revision': 7,
            'graph_sha256': 'a' * 64}


def test_room_partition_scores_are_invariant_to_native_or_gt_label_permutation():
    pred = prediction({'p1': 'R(0)', 'p2': 'R(0)', 'p3': 'R(1)', 'p4': 'R(1)'})
    gt = annotation({'p1': 'bedroom-A', 'p2': 'bedroom-A',
                     'p3': 'bedroom-B', 'p4': 'bedroom-B'})
    report = evaluate_room_geometry(pred, gt, protocol='room-point-partition-v1')
    assert report.status == 'available'
    assert report.metrics['adjusted_rand_index'] == 1.0
    assert report.metrics['pairwise_f1'] == 1.0
    assert report.metrics['purity'] == 1.0
    assert report.metrics['best_match_mean_iou'] == 1.0


def test_merge_split_and_partial_observed_support_are_reported_separately():
    pred = prediction({'p1': 'R(0)', 'p2': 'R(0)', 'p3': 'R(0)', 'p4': None})
    gt = annotation({'p1': 'A', 'p2': 'A', 'p3': 'B', 'p4': 'B'})
    report = evaluate_room_geometry(pred, gt, protocol='room-point-partition-v1')
    assert report.support_count == 3
    assert report.annotation_coverage == 0.75
    assert report.metrics['merge_count'] == 1
    assert report.metrics['split_count'] == 0
    assert report.metrics['boundary_f1_020m'] is None
    assert report.unavailable['boundary_f1_020m'] == 'point support does not define a room boundary'


@pytest.mark.parametrize('gt,reason', [
    (None, 'annotation_missing'),
    (annotation({'p1': 'A'}, annotated=False), 'annotation_not_complete'),
    (annotation({'q1': 'A'}), 'no_common_annotated_support'),
    (annotation({'p1': 'A'}, domain='surface_points'), 'support_domain_mismatch'),
    ({**annotation({'p1': 'A'}), 'graph_revision': 6}, 'annotation_graph_revision_mismatch'),
    ({**annotation({'p1': 'A'}), 'graph_sha256': 'c' * 64}, 'annotation_graph_hash_mismatch'),
])
def test_unavailable_room_evaluation_is_typed_not_zero(gt, reason):
    report = evaluate_room_geometry(prediction({'p1': 'R(0)'}), gt,
                                    protocol='room-point-partition-v1')
    assert report.status == 'unavailable'
    assert report.metrics['adjusted_rand_index'] is None
    assert report.reasons == (reason,)


def test_snapshot_rejects_unknown_assignments_and_hashless_source():
    with pytest.raises(ValueError, match='observed support'):
        RoomSupportSnapshot('ep', 'run', 1, 'canonical_z_up_m_v1',
            {'p1': (0., 0., 0.)}, 'place_points', {'p2': 'R(0)'}, (), {'graph': 'a' * 64})
    with pytest.raises(ValueError, match='SHA'):
        prediction({'p1': 'R(0)'}).__class__('ep', 'run', 1, 'canonical_z_up_m_v1',
            {'p1': (0., 0., 0.)}, 'place_points', {'p1': 'R(0)'}, (), {'graph': 'bad'})
