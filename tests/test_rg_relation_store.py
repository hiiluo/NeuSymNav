from dataclasses import replace
import numpy as np
import pytest

from test_rg_evidence import inputs
from neusymnav.contracts.hydra_graph import NativeNodeRef
from neusymnav.reasoninggraph.relation_encoder import RelFeatureSpec, pack_tokens
from neusymnav.reasoninggraph.relation_store import RelationStore


def fixture():
    _, node, token = inputs()
    a = node.ref
    b = NativeNodeRef(token.native, 'O(2)', 2)
    spec = RelFeatureSpec('1'*64, '2'*64, '3'*64, '4'*64, 'cut', 'tile', 1, 2)
    return token, a, b, spec


def sample(spec, a, b, values):
    return pack_tokens(spec, np.array([values], dtype='<f2'), subject=a.native_id, object_id=b.native_id)


def test_direction_mean_dedup_and_scope():
    token, a, b, spec = fixture()
    store = RelationStore(token, {a, b}, lambda native: native == token.native)
    x = sample(spec, a, b, [1, 3])
    assert store.apply_pair('one', a, b, x, token)
    assert store.apply_pair('one', a, b, x, token)
    assert store.apply_pair('two', a, b, sample(spec, a, b, [3, 5]), token)
    assert store.apply_pair('reverse', b, a, sample(spec, b, a, [7, 9]), token)
    view = store.read(token)
    assert len(view) == 2
    assert view[0].count == 2
    assert np.array_equal(view[0].mean, [[2, 4]])
    assert not view[0].mean.flags.writeable
    assert not store.apply_pair('one', a, b, sample(spec, a, b, [8, 8]), token)
    assert not store.apply_pair('bad', a, a, x, token)
    assert not store.apply_pair('stale', a, b, x, replace(token, sidecar_revision=1))


def test_caps_integrity_and_sealed_manifest(tmp_path):
    token, a, b, spec = fixture()
    current = [True]
    store = RelationStore(token, {a, b}, lambda _: current[0], max_events=1)
    x = sample(spec, a, b, [1, 3])
    assert store.apply_pair('one', a, b, x, token)
    assert not store.apply_pair('two', a, b, x, token)
    path = tmp_path / 'manifest.json'
    sha = store.seal(path, token)
    restored = RelationStore(token, {a, b}, lambda _: current[0], max_events=1)
    assert restored.restore(path, token, sha)
    assert restored.read(token)[0].count == 1
    path.write_bytes(path.read_bytes() + b' ')
    assert not restored.restore(path, token, sha)
    current[0] = False
    assert restored.read(token) is None
    assert not restored.apply_pair('one', a, b, x, token)


def test_layouts_remain_separate_and_unregistered_endpoints_rejected():
    token, a, b, spec = fixture()
    c = NativeNodeRef(token.native, 'O(3)', 2)
    store = RelationStore(token, {a, b}, lambda _: True, max_edges=2, max_refs_per_edge=1)
    x = sample(spec, a, b, [1, 2])
    assert store.apply_pair('x', a, b, x, token)
    assert not store.apply_pair('y', a, b, x, token)
    assert store.apply_pair('z', a, b, sample(replace(spec, tile_layout='different'), a, b, [3, 4]), token)
    assert not store.apply_pair('third', b, a, sample(spec, b, a, [1, 2]), token)
    assert not store.apply_pair('orphan', a, c, sample(spec, a, c, [1, 2]), token)
    assert len(store.read(token)) == 2


def test_restore_rejects_rehashed_corruption_without_mutating_store(tmp_path):
    import hashlib
    import json
    token, a, b, spec = fixture()
    store = RelationStore(token, {a, b}, lambda _: True)
    assert store.apply_pair('x', a, b, sample(spec, a, b, [1, 2]), token)
    path = tmp_path / 'view'
    store.seal(path, token)
    document = json.loads(path.read_bytes())
    document['events'][0]['payload'] = 'AAAAAA=='
    payload = json.dumps(document).encode()
    path.write_bytes(payload)
    assert not store.restore(path, token, hashlib.sha256(payload).hexdigest())
    assert store.read(token)[0].count == 1


def test_restore_preserves_evidence_already_committed_for_this_revision(tmp_path):
    token, a, b, spec = fixture()
    source = RelationStore(token, {a, b}, lambda _: True)
    target = RelationStore(token, {a, b}, lambda _: True)
    assert source.apply_pair('one', a, b, sample(spec, a, b, [1, 2]), token)
    assert target.apply_pair('two', a, b, sample(spec, a, b, [3, 4]), token)
    path = tmp_path / 'manifest.json'
    checksum = source.seal(path, token)
    assert source.restore(path, token, checksum)
    assert not target.restore(path, token, checksum)
    assert target.read(token)[0].event_ids == ('two',)
