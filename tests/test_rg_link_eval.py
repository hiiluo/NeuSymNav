import pytest

from tools.reasoninggraph.score_links import score_links


def report():
    def frame(revision, links):
        return dict(revision=revision, native_endpoints=['O(0)', 'O(1)'],
                    links=[dict(detection_id=f'det-{i}', status='geometric_candidate' if node else 'no_support',
                                endpoint=None if node is None else {'native_id': node})
                           for i, node in enumerate(links)])
    return dict(schema_version=1, records=[frame(1, ['O(0)', 'O(1)', 'O(0)', None]),
                                           frame(2, ['O(0)'])])


def test_score_keeps_revision_scope_and_unknown_links_in_bounds():
    labels = [
        dict(revision=1, detection_id='det-0', status='matched', native_id='O(0)'),
        dict(revision=1, detection_id='det-1', status='no_endpoint', native_id=None),
        dict(revision=1, detection_id='det-2', status='unresolved', native_id=None),
        dict(revision=1, detection_id='det-3', status='matched', native_id='O(1)'),
        dict(revision=2, detection_id='det-0', status='matched', native_id='O(1)'),
    ]
    result = score_links(report(), labels)
    assert result['proposed'] == 4
    assert result['correct_proposed'] == 1
    assert result['false_proposed'] == 2
    assert result['unresolved_proposed'] == 1
    assert result['false_link_rate_adjudicated'] == pytest.approx(2/3)
    assert result['false_link_rate_bounds'] == [.5, .75]
    assert result['correct_match_coverage'] == pytest.approx(1/3)


def test_score_rejects_duplicate_or_foreign_annotations():
    label = dict(revision=1, detection_id='det-0', status='matched', native_id='O(0)')
    with pytest.raises(ValueError, match='duplicate'):
        score_links(report(), [label, label])
    with pytest.raises(ValueError, match='not in native revision'):
        score_links(report(), [{**label, 'native_id': 'O(99)'}])
    with pytest.raises(ValueError, match='unknown detection'):
        score_links(report(), [{**label, 'revision': 99}])
    assert score_links(report(), [])['false_link_rate_adjudicated'] is None
