from dataclasses import replace
from math import log

import pytest

from neusymnav.contracts.observations import Taxonomy
from neusymnav.reasoninggraph.association_receipts import confirm_evidence
from neusymnav.reasoninggraph.semantic_beliefs import SemanticVoteAccumulator
from test_psg_confirmation_receipts import fixture


def receipt():
    geometry, token, lineage, proof = fixture()
    return confirm_evidence(token, geometry, proof, lineage, raw_label='chair', score=.8)


def variant(original, detection, category, score=.2, raw_label=None):
    return replace(original, category=category, raw_label=raw_label or category, raw_score=score,
                   evidence=replace(original.evidence, detection_id=detection))


def accumulator():
    return SemanticVoteAccumulator(Taxonomy('taxonomy', ('chair', 'sofa', 'table'),
                                            {'couch': 'sofa'}, 'fixture'))


def test_unavailable_single_and_empty_category():
    vote = receipt()
    store = accumulator()
    empty = store.belief(vote.canonical_object)
    assert empty.status == 'unavailable'
    assert empty.probability('chair') is None
    assert empty.entropy_nats is None and empty.observation_count == 0
    assert store.apply(vote)
    single = store.belief(vote.canonical_object)
    assert single.status == 'available' and single.entropy_nats == 0
    assert single.probability('chair') == 1 and single.probability('table') == 0
    with pytest.raises(ValueError):
        single.probability('unknown')


def test_votes_are_unweighted_and_ties_use_category_order():
    vote = receipt()
    store = accumulator()
    assert store.apply(variant(vote, 'b', 'sofa', score=.99, raw_label='couch'))
    assert store.apply(vote)
    assert store.belief(vote.canonical_object).top_hypotheses == (('chair', .5), ('sofa', .5))
    assert store.apply(variant(vote, 'c', 'chair', score=.01))
    result = store.belief(vote.canonical_object, top_k=1)
    assert result.counts == (('chair', 2), ('sofa', 1))
    assert result.top_hypotheses == (('chair', 2 / 3),)
    assert sum(p for _, p in result.distribution) == pytest.approx(1)
    assert result.entropy_nats == pytest.approx(-(2 / 3 * log(2 / 3) + 1 / 3 * log(1 / 3)))


def test_duplicate_conflict_and_invalid_votes_are_atomic():
    vote = receipt()
    store = accumulator()
    assert store.apply(vote)
    before = store.belief(vote.canonical_object)
    assert not store.apply(vote)
    with pytest.raises(ValueError, match='conflict'):
        store.apply(replace(vote, raw_score=.7))
    for bad in (variant(vote, 'b', 'unknown'), variant(vote, 'c', 'chair', raw_label='unknown'),
                variant(vote, 'd', 'chair', score=float('nan'))):
        with pytest.raises(ValueError):
            store.apply(bad)
    assert store.belief(vote.canonical_object) == before
    with pytest.raises(ValueError):
        store.belief(vote.canonical_object, top_k=0)
