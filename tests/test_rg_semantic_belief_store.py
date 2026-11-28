from dataclasses import replace
from neusymnav.contracts.hydra_lineage import NativeObjectBatch, NativeObjectEvent
from neusymnav.reasoninggraph.association_receipts import lineage_digest
from neusymnav.reasoninggraph.native_lineage import NativeObjectLineage
from neusymnav.reasoninggraph.semantic_belief_store import SemanticBeliefStore
from test_rg_semantic_beliefs import accumulator, receipt


def setup():
    vote = receipt()
    graph = vote.source_token
    native = replace(graph.native, graph_revision=1, input_prefix_sha256='1' * 64,
                     source_sha256='a' * 40, build_sha256='b' * 64, config_sha256='c' * 64)
    first = replace(graph, native=native)
    ref = replace(vote.evidence, input_prefix_sha256=native.input_prefix_sha256)
    return first, replace(vote, source_token=first, evidence=ref)


def next_frame(token, revision):
    return replace(token, native=replace(token.native, graph_revision=revision, input_prefix_sha256=f'{revision:064x}'),
                   source=replace(token.source, frame_index=token.source.frame_index + revision - 1),
                   capture_monotonic_ns=token.capture_monotonic_ns + revision - 1)


def apply(store, owner, token, objects, events=(), receipts=()):
    batch = NativeObjectBatch(token.native, token.capture_monotonic_ns, 1, events)
    view = owner.apply(token.native, batch, objects)
    assert view is not None
    receipts = tuple(replace(r, evidence=replace(r.evidence, native_lineage_sha256=lineage_digest(view)))
                     for r in receipts)
    return store.apply_revision(token, view, receipts, revision_complete=True, journal=batch)


def event(operation, source, target=None):
    return NativeObjectEvent('frontend', operation, source, target)


def test_retirement_alias_preserves_votes_without_resurrection_and_seals(tmp_path):
    store = SemanticBeliefStore(accumulator().taxonomy)
    owner = NativeObjectLineage()
    one, vote = setup()
    old = vote.canonical_object.native_id
    new = 'O(3)'
    assert apply(store, owner, one, [old], (event('create', old),), (vote,))
    assert store.read(one.native).belief(old).observation_count == 1
    two = next_frame(one, 2)
    assert apply(store, owner, two, [new], (event('delete', old), event('create', new)))
    assert store.read(two.native).belief(old) is None
    three = next_frame(one, 3)
    assert apply(store, owner, three, [new], (event('reconcile', old, new),))
    result = store.read(three.native)
    assert result.belief(old) == result.belief(new)
    assert result.belief(new).probability('chair') == 1
    assert store.read(one.native) is None
    path = tmp_path / 'belief.json'
    checksum = store.seal(path, three.native)
    copy = SemanticBeliefStore(accumulator().taxonomy)
    assert copy.restore(path, three, checksum, lineage=owner.read(three.native))
    assert copy.read(three.native).belief(new) == result.belief(new)
    path.write_bytes(path.read_bytes() + b' ')
    assert not copy.restore(path, three, checksum, lineage=owner.read(three.native))


def test_unverified_merge_invalidates_existing_votes_and_gap_stays_unavailable():
    store = SemanticBeliefStore(accumulator().taxonomy)
    owner = NativeObjectLineage()
    one, vote = setup()
    old, new = vote.canonical_object.native_id, 'O(3)'
    assert apply(store, owner, one, [old, new], (event('create', old), event('create', new)), (vote,))
    two = next_frame(one, 2)
    assert apply(store, owner, two, [new], (event('merge', old, new),))
    assert store.read(two.native).belief(new).status == 'unavailable'
    four = next_frame(one, 4)
    assert not store.apply_revision(four, None, (), revision_complete=False, journal=None)
    assert store.read(four.native) is None


def test_incremental_quota_does_not_replace_previous_publication():
    store = SemanticBeliefStore(accumulator().taxonomy, max_receipts=1)
    owner = NativeObjectLineage()
    first, vote = setup()
    raw = vote.canonical_object.native_id
    assert apply(store, owner, first, [raw], (event('create', raw),), (vote,))
    assert apply(store, owner, first, [raw], (event('create', raw),), (vote,))
    two = next_frame(first, 2)
    second = replace(vote, source_token=two, evidence=replace(vote.evidence, source=two.source,
                     capture_monotonic_ns=two.capture_monotonic_ns, input_prefix_sha256=two.native.input_prefix_sha256))
    assert not apply(store, owner, two, [raw], receipts=(second,))
    assert store.read(two.native) is None
    assert store.read(first.native).belief(raw).observation_count == 1
    assert apply(store, owner, two, [raw])
    assert store.read(two.native).belief(raw).observation_count == 1


def test_new_children_are_empty_until_owner_supplies_proven_continuity():
    store = SemanticBeliefStore(accumulator().taxonomy)
    owner = NativeObjectLineage()
    first, vote = setup()
    raw = vote.canonical_object.native_id
    assert apply(store, owner, first, [raw], (event('create', raw),), (vote,))
    two = next_frame(first, 2)
    children = ('O(3)', 'O(4)')
    assert apply(store, owner, two, children, (event('delete', raw), *(event('create', k) for k in children)))
    view = store.read(two.native)
    assert all(view.belief(child).observation_count == 0 for child in children)
    assert view.belief(raw) is None
    three = next_frame(first, 3)
    assert apply(store, owner, three, children, (event('reconcile', raw, children[1]),))
    proved = store.read(three.native)
    assert proved.belief(children[1]).observation_count == 1
    assert proved.belief(children[0]).observation_count == 0
