import copy
import pytest
from tools.reasoninggraph.score_semantics import score, digest
from tools.reasoninggraph.compare_arms import compare


def fixtures():
    manifest = {'schema_version': 1, 'samples': [
        {'id': str(i), 'scene': 's', 'subject': str(i), 'object': 'b', 'predicate': 'left', 'input_sha256': str(i)*64} for i in range(1, 6)]}
    oracle = {'manifest_sha256': digest(manifest), 'labels': [{'id': str(i), 'label': label} for i, label in enumerate(['positive', 'positive', 'negative', 'unknown', 'positive'], 1)]}
    arm = {'manifest_sha256': digest(manifest), 'arm': 'a', 'predictions': [{'id': str(i), 'input_sha256': str(i)*64, 'prediction': p} for i, p in enumerate(['positive', 'abstain', 'positive', 'negative', 'error'], 1)]}
    return manifest, oracle, arm


def test_fixed_denominators_and_unknown():
    m, o, a = fixtures()
    result = score(m, o, a)
    assert result['counts'] == {'total': 5, 'known': 4, 'unknown_reference': 1, 'answered_known': 2, 'abstain': 1, 'unknown_prediction': 0, 'error': 1, 'missing': 0, 'tp': 1, 'fp': 1, 'fn': 0, 'tn': 0}
    assert result['metrics']['coverage'] == .5
    assert result['metrics']['conditional_accuracy'] == .5
    assert result['metrics']['end_to_end_recall'] == 1/3


def test_missing_is_counted_and_unknown_not_negative():
    m, o, a = fixtures(); a['predictions'].pop()
    result = score(m, o, a)
    assert result['counts']['missing'] == 1
    assert result['metrics']['end_to_end_recall'] == 1/3


def test_reject_leak_and_bad_identity():
    m, o, a = fixtures(); m['samples'][0]['label'] = 'positive'
    with pytest.raises(ValueError): score(m, o, a)
    m, o, a = fixtures(); a['predictions'][0]['input_sha256'] = 'x'*64
    with pytest.raises(ValueError): score(m, o, a)


def test_paired_comparison_rejects_mismatch():
    m, o, a = fixtures(); b = copy.deepcopy(a); b['arm'] = 'b'; b['predictions'][0]['prediction'] = 'negative'
    result = compare(m, o, a, b)
    assert result['paired']['correct_delta_b_minus_a'] == -0.25
    b['manifest_sha256'] = 'bad'
    with pytest.raises(ValueError): compare(m, o, a, b)


def test_prediction_unknown_is_distinct_from_abstention():
    m, o, a = fixtures(); a['predictions'][1]['prediction'] = 'unknown'
    result = score(m, o, a)
    assert result['counts']['unknown_prediction'] == 1
    assert result['counts']['abstain'] == 0
    assert result['metrics']['end_to_end_recall'] == 1/3
