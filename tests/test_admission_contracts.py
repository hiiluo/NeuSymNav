from dataclasses import replace
import pytest
import numpy as np
from neusymnav.contracts import AdmissionDecision, AdmissionSnapshot, dumps, loads
from neusymnav.objects.admission import AdmissionPolicy


def test_contract_roundtrip_and_immutable():
    decision = AdmissionDecision('id', 'candidate', 'unavailable', ('missing',), (), {'count': 0})
    snapshot = AdmissionSnapshot('episode', 1, 1, 'object-admission:v1', 'a'*64, {'id': decision})
    assert loads(dumps(snapshot)) == snapshot
    with pytest.raises(TypeError): snapshot.decisions['id'] = decision
    with pytest.raises(ValueError): replace(snapshot, policy_hash='bad')
    with pytest.raises(ValueError): replace(snapshot, policy_version='v2')
    with pytest.raises(ValueError): replace(snapshot, object_revision=-1)
    with pytest.raises(ValueError): replace(decision, quality={'nan': float('nan')})
    with pytest.raises(ValueError): replace(decision, quality={'nested': [np.array([float('nan')])]})


@pytest.mark.parametrize('kwargs', [{'baseline_m': float('inf')}, {'min_depth_fraction': 1.1}, {'max_views': 0}, {'version': 'v2'}])
def test_policy_validation(kwargs):
    with pytest.raises(ValueError): AdmissionPolicy(**kwargs)
