import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tools.psg_nav.score_beliefs import score


def row(instance, status='matched', **changes):
    value = dict(scene='s', episode='e', revision=1, instance=instance,
                 gt_category='chair', status=status, native_id=instance if status == 'matched' else None,
                 deterministic_category=None, probabilities=None)
    value.update(changes)
    return value


def payload(rows):
    return dict(schema_version=1, categories=['chair', 'table', 'sofa'], rows=rows)


def test_metrics_and_missing_denominators():
    result = score(payload([
        row('1', probabilities={'chair': .5, 'table': .5}, deterministic_category='table'),
        row('2', probabilities={'chair': 0, 'sofa': 1}, deterministic_category='chair'),
        row('3', 'unmatched'),
    ]))
    assert result['counts']['eligible_visible'] == 3
    assert result['counts']['available'] == 2
    assert result['belief']['top1']['all_visible'] == pytest.approx(1 / 3)
    assert result['belief']['top1']['available'] == .5
    assert result['belief']['top3']['available'] == 1
    assert result['belief']['nll']['raw_mean'] is None
    assert result['belief']['nll']['raw_infinite'] is True
    assert result['belief']['nll']['zero_truth_count'] == 1
    assert result['belief']['nll']['clipped_mean'] == pytest.approx((-math.log(.5)-math.log(1e-12))/2)
    assert result['belief']['brier'] == pytest.approx((.5 + 2)/2)
    assert sum(x['count'] for x in result['belief']['ece']['bins']) == 2
    assert result['belief']['ece']['value'] == pytest.approx(.75)
    assert result['deterministic']['correct'] == 1
    assert result['deterministic']['coverage'] == pytest.approx(2/3)
    assert result['retrieval']['available'] is False


def test_validation_and_unavailable_json():
    for invalid in [
        payload([row('1'), row('1')]),
        payload([row('1', probabilities={'chair': .7})]),
        payload([row('1', probabilities={'chair': float('nan')})]),
        payload([row('1', native_id='n'), row('2', native_id='n')]),
        payload([row('1', gt_category='alien')]),
    ]:
        with pytest.raises(ValueError):
            score(invalid)
    result = score(payload([]))
    assert result['belief']['nll']['raw_mean'] is None
    json.dumps(result, allow_nan=False)


def test_retrieval_and_cli(tmp_path):
    data = payload([row('1', target_category='chair', retrieval_ranks={'probabilistic': 1, 'deterministic': None}),
                    row('2', 'unmatched', target_category='chair', retrieval_ranks={'probabilistic': None, 'deterministic': None})])
    result = score(data)
    assert result['retrieval']['methods']['probabilistic']['recall_at_1']['all_visible'] == .5
    assert result['retrieval']['methods']['probabilistic']['recall_at_3']['all_visible'] == .5
    input_path, output_path = tmp_path/'input.json', tmp_path/'output.json'
    input_path.write_text(json.dumps(data))
    proc = subprocess.run([sys.executable, 'tools/psg_nav/score_beliefs.py', str(input_path), '--out', str(output_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(output_path.read_text()) == result


def test_raw_nll_does_not_clip_small_positive_truth_mass():
    result = score(payload([row('1', probabilities={'chair': 1e-15, 'table': 1 - 1e-15})]))
    assert result['belief']['nll']['raw_mean'] == pytest.approx(-math.log(1e-15))
    assert result['belief']['nll']['clipped_mean'] == pytest.approx(-math.log(1e-12))


def test_malformed_categories_and_status_are_rejected():
    data = payload([row('1', status=[])])
    with pytest.raises(ValueError):
        score(data)
    data = payload([row('1', deterministic_category=[])])
    with pytest.raises(ValueError):
        score(data)


def test_persistence_checks_ordered_observation_prefixes():
    first = row('1', observation_count=1, observation_keys=['frame1'])
    second = row('1', revision=2, observation_count=2, observation_keys=['frame1', 'frame2'])
    result = score(payload([second, first]))
    assert result['persistence']['available'] is True
    assert result['persistence']['comparisons'] == 1
    assert result['persistence']['prefix_violations'] == 0
    second['observation_keys'] = ['frame2', 'frame3']
    assert score(payload([first, second]))['persistence']['prefix_violations'] == 1
    second['observation_keys'] = ['frame1', 'frame1']
    with pytest.raises(ValueError):
        score(payload([first, second]))


def test_retrieval_targets_only_eligible_category_and_reports_coverage():
    rows = [row('1', target_category='chair', retrieval_ranks={'prob': 1}), row('2')]
    result = score(payload(rows))['retrieval']['methods']['prob']
    assert result['eligible_visible'] == 2
    assert result['coverage'] == .5
    assert result['recall_at_1']['all_visible'] == .5
    assert result['recall_at_1']['recorded'] == 1
    rows[0]['target_category'] = 'table'
    with pytest.raises(ValueError):
        score(payload(rows))
