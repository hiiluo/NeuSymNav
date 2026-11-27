from dataclasses import replace

import pytest

from neusymnav.contracts.hydra_graph import HydraReadToken
from neusymnav.contracts.hydra_lineage import NativeObjectBatch, NativeObjectEvent
from neusymnav.reasoninggraph.native_lineage import NativeObjectLineage


A, B, C = ('O(0)', 'O(1)', 'O(2)')


def token(revision, *, run='r'):
    return HydraReadToken('ep', run, revision, str(revision) * 64, source_sha256='a'*40,
                          build_sha256='b'*64, config_sha256='c'*64)


def batch(revision, *events, epoch=1):
    return NativeObjectBatch(token(revision), 99 + revision, epoch, events)


def create(raw):
    return NativeObjectEvent('frontend', 'create', raw)


def test_native_lineage_tracks_chains_once_and_retires_on_delete():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B), create(C)), [A, B, C])
    before = dict(one.objects)
    two_batch = batch(2, NativeObjectEvent('frontend', 'merge', A, B),
                      NativeObjectEvent('frontend', 'merge', B, C))
    two = owner.apply(token(2), two_batch, [C])
    assert owner.apply(token(2), two_batch, [C]) is two
    assert two.resolve(before[A]) == two.resolve(before[B]) == before[C]
    assert two.resolve(before[C]) == before[C]
    gone = owner.apply(token(3), batch(3, NativeObjectEvent('frontend', 'delete', C)), [])
    assert not gone.objects
    assert gone.resolve(before[A]) is gone.resolve(before[C]) is None
    assert owner.read(token(2)) is None


def test_backend_remap_and_frontend_alias_interaction_fail_closed():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B), create(C)), [A, B, C])
    before = dict(one.objects)
    two = owner.apply(token(2), batch(2, NativeObjectEvent('backend', 'merge', A, B),
                                     NativeObjectEvent('backend', 'merge', B, C)), [C])
    assert two.resolve(before[A]) == before[C]
    assert owner.apply(token(3), batch(3, NativeObjectEvent('frontend', 'delete', C)), []) is None
    assert owner.read(token(2)) is None
    assert owner.apply(token(3), batch(3), [C]) is None


@pytest.mark.parametrize('later,events,projection', [
    (token(3), batch(3), [A]),
    (token(2), batch(2, epoch=2), [A]),
    (token(2), batch(2), [A,B]),
    (token(2, run='other'), batch(2), [A]),
    (token(2), batch(2, create(A)), [A]),
    (token(2), replace(batch(2), token=replace(token(2), input_prefix_sha256='f'*64)), [A]),
])
def test_lineage_revokes_on_gap_reuse_reset_or_projection_mismatch(later, events, projection):
    owner = NativeObjectLineage()
    assert owner.apply(token(1), batch(1, create(A)), [A])
    assert owner.apply(later, events, projection) is None
    assert owner.read(token(1)) is None


def test_first_publication_rejects_same_prefix_from_a_different_build():
    original = batch(1, create(A))
    other = replace(token(1), build_sha256='d'*64)
    assert original.token.input_prefix_sha256 == other.input_prefix_sha256
    assert NativeObjectLineage().apply(other, original, [A]) is None
