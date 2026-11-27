import numpy as np

from test_rg_native_lineage import A, B, C, batch, create, token
from neusymnav.contracts.hydra_lineage import NativeObjectEvent
from neusymnav.reasoninggraph.native_lineage import NativeObjectLineage
from neusymnav.reasoninggraph.relation_encoder import RelFeatureSpec, pack_tokens
from neusymnav.reasoninggraph.cumulative_relations import CumulativeRelations


def _fixture_store(view, current, **limits):
    return CumulativeRelations(view, current, lambda sample: True, **limits)


def asset(a, b, value):
    spec = RelFeatureSpec('1'*64, '2'*64, '3'*64, '4'*64, 'cut', 'tile', 1, 1)
    return pack_tokens(spec, np.array([[value]], dtype='<f2'), subject=a, object_id=b)


def test_merge_preserves_unique_history_and_direction():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B), create(C)), [A, B, C])
    store = _fixture_store(one, lambda v: owner.read(v.token) is v)
    assert store.add('a', one, asset(A, C, 1))
    assert store.add('a', one, asset(A, C, 1))
    assert store.add('b', one, asset(B, C, 5))
    assert store.add('reverse', one, asset(C, B, 9))
    two = owner.apply(token(2), batch(2, NativeObjectEvent('frontend', 'merge', A, B)), [B, C])
    assert store.advance(two)
    pools = store.read(two)
    assert len(pools) == 2
    assert pools[0].count == 2 and pools[0].mean.tolist() == [[3.0]]
    assert pools[0].subject == two.objects[B] and pools[0].object == two.objects[C]
    assert not pools[0].mean.flags.writeable
    assert pools[0].samples[0].origin == one.token
    assert pools[0].samples[0].asset.subject == A
    assert store.read(one) is None


def test_merge_cannot_bypass_per_edge_budget():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B), create(C)), [A, B, C])
    store = _fixture_store(one, lambda v: owner.read(v.token) is v, max_refs_per_edge=1)
    assert store.add('a', one, asset(A, C, 1))
    assert store.add('b', one, asset(B, C, 5))
    two = owner.apply(token(2), batch(2, NativeObjectEvent('frontend', 'merge', A, B)), [B, C])
    assert not store.advance(two)
    assert store.read(two) is None


def test_gap_revokes_and_deleted_or_self_edges_disappear():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B), create(C)), [A, B, C])
    store = _fixture_store(one, lambda v: owner.read(v.token) is v)
    assert store.add('self', one, asset(A, B, 1))
    assert store.add('orphan', one, asset(C, B, 2))
    two = owner.apply(token(2), batch(2, NativeObjectEvent('frontend', 'merge', A, B),
                                      NativeObjectEvent('frontend', 'delete', C)), [B])
    assert store.advance(two)
    assert store.read(two) == ()
    owner.apply(token(3), batch(3), [B])
    four = owner.apply(token(4), batch(4), [B])
    assert not store.advance(four)
    assert store.read(four) is None


def test_duplicate_id_conflict_and_marker_spec_separation():
    from dataclasses import replace
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B)), [A, B])
    store = _fixture_store(one, lambda v: owner.read(v.token) is v, max_events=3)
    original = asset(A, B, 1)
    assert store.add('a', one, original)
    assert not store.add('a', one, asset(A, B, 2))
    assert store.add('b', one, original, marker_scheme='other')
    spec = replace(original.spec, tile_layout='other')
    other = pack_tokens(spec, np.array([[3]], dtype='<f2'), subject=A, object_id=B)
    assert store.add('c', one, other)
    assert not store.add('d', one, original)
    assert len(store.read(one)) == 3


def test_invalid_asset_stale_view_and_byte_budget_are_rejected():
    from dataclasses import replace
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B)), [A, B])
    store = _fixture_store(one, lambda v: owner.read(v.token) is v, max_bytes=1)
    assert not store.add('a', one, asset(A, B, 1))
    store = _fixture_store(one, lambda v: owner.read(v.token) is v)
    bad = replace(asset(A, B, 1), payload=b'bad')
    assert not store.add('a', one, bad)
    two = owner.apply(token(2), batch(2), [A, B])
    assert not store.add('a', one, asset(A, B, 1))
    assert store.advance(two)
    assert store.read(two) == ()


def test_seal_restore_requires_authenticated_history_and_preserves_committed_data(tmp_path):
    import hashlib
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B), create(C)), [A, B, C])
    archive = {one.token: one}
    source = _fixture_store(one, lambda v: owner.read(v.token) is v)
    target = _fixture_store(one, lambda v: owner.read(v.token) is v)
    assert source.add('old', one, asset(A, C, 1))
    two = owner.apply(token(2), batch(2, NativeObjectEvent('frontend', 'merge', A, B)), [B, C])
    archive[two.token] = two
    assert source.advance(two)
    assert source.add('new', two, asset(B, C, 5))
    path = tmp_path / 'relations.json'
    digest = source.seal(path, two)
    assert source.seal(path, two) == digest
    assert not target.restore(path, two, digest, lambda _: None)
    assert target.restore(path, two, digest, archive.get)
    pool = target.read(two)[0]
    assert pool.count == 2 and pool.mean.tolist() == [[3.0]]
    assert pool.samples[0].asset.subject == A
    assert target.restore(path, two, digest, archive.get)
    assert not target.restore(path, two, '0'*64, archive.get)
    path.write_bytes(path.read_bytes() + b' ')
    assert not target.restore(path, two, hashlib.sha256(path.read_bytes()).hexdigest(), archive.get)
    assert target.read(two)[0].count == 2


def test_restore_rejects_other_revision_and_does_not_erase_competing_sample(tmp_path):
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B)), [A, B])
    archive = {one.token: one}
    source = _fixture_store(one, lambda v: owner.read(v.token) is v)
    target = _fixture_store(one, lambda v: owner.read(v.token) is v)
    assert source.add('source', one, asset(A, B, 1))
    assert target.add('target', one, asset(A, B, 2))
    path = tmp_path / 'manifest'
    digest = source.seal(path, one)
    assert not target.restore(path, one, digest, archive.get)
    assert target.read(one)[0].samples[0].event_id == 'target'
    two = owner.apply(token(2), batch(2), [A, B])
    archive[two.token] = two
    assert target.advance(two)
    assert not target.restore(path, two, digest, archive.get)
    assert target.read(two)[0].samples[0].event_id == 'target'


def test_restore_rejects_rehashed_payload_from_unauthenticated_endpoint(tmp_path):
    import base64
    import hashlib
    import json
    from dataclasses import asdict
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B)), [A, B])
    source = _fixture_store(one, lambda v: owner.read(v.token) is v)
    target = _fixture_store(one, lambda v: owner.read(v.token) is v)
    assert source.add('one', one, asset(A, B, 1))
    path = tmp_path / 'manifest'
    source.seal(path, one)
    document = json.loads(path.read_bytes())
    replacement = asset(A, C, 3)
    document['samples'][0].update(subject=A, object=C, spec=asdict(replacement.spec),
                                  payload=base64.b64encode(replacement.payload).decode(),
                                  sha256=replacement.sha256)
    raw = json.dumps(document, sort_keys=True, separators=(',', ':')).encode()
    path.write_bytes(raw)
    assert not target.restore(path, one, hashlib.sha256(raw).hexdigest(), lambda _: one)
    assert target.read(one) == ()


def test_malformed_lineage_view_fails_closed():
    from types import MappingProxyType
    from neusymnav.reasoninggraph.native_lineage import ObjectLineageView
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A)), [A])
    store = _fixture_store(one, lambda v: True)
    broken = ObjectLineageView(None, 1, MappingProxyType({}), MappingProxyType({}))
    assert not store.advance(broken)
    assert store.read(one) is None


def test_refs_are_bounded_across_marker_groups():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B)), [A, B])
    store = _fixture_store(one, lambda v: owner.read(v.token) is v, max_refs_per_edge=1)
    assert store.add('a', one, asset(A, B, 1), marker_scheme='first')
    assert not store.add('b', one, asset(A, B, 1), marker_scheme='second')


def test_samples_need_exact_external_source_evidence():
    owner = NativeObjectLineage()
    one = owner.apply(token(1), batch(1, create(A), create(B)), [A, B])
    original = asset(A, B, 1)
    store = CumulativeRelations(one, lambda v: owner.read(v.token) is v,
        lambda sample: sample.origin == one.token and sample.asset == original and sample.event_id == 'valid')
    assert not store.add('other', one, original)
    assert store.add('valid', one, original)
    two = owner.apply(token(2), batch(2), [A, B])
    assert store.advance(two)
    assert not store.add('later', two, original)
