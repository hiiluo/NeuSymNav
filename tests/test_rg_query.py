from dataclasses import replace

import pytest

from test_rg_relation_store import fixture, sample
from neusymnav.contracts.hydra_graph import NativeNodeRef
from neusymnav.contracts.reasoninggraph import FeatureSpec
from neusymnav.reasoninggraph.object_features import ObjectFeature, ObjectFeatureView
from neusymnav.reasoninggraph.room_features import RoomFeature, RoomFeatureView
from neusymnav.reasoninggraph.relation_store import RelationStore
from neusymnav.reasoninggraph.query import RevisionQuery


def setup_query():
    token, a, b, relspec = fixture()
    room = NativeNodeRef(token.native, 'R(0)', 4)
    ospec = FeatureSpec('object', '1'*64, '2'*64, 2, 'object')
    rspec = FeatureSpec('room', '1'*64, '2'*64, 2, 'room')
    objects = ObjectFeatureView(token, ospec, (ObjectFeature(b, (0., 1.), 1), ObjectFeature(a, (1., 0.), 2)))
    rooms = RoomFeatureView(token, rspec, (RoomFeature(room, ((1., 0.),), 1),), 2)
    current = [True]
    relations = RelationStore(token, {a, b}, lambda _: current[0])
    assert relations.apply_pair('ev1', a, b, sample(relspec, a, b, [1, 2]), token)
    return token, a, b, room, ospec, rspec, current, relations, RevisionQuery(token, objects, rooms, relations, lambda _: current[0])


def test_ranking_and_relation_support_are_revision_bound():
    token, a, b, room, ospec, rspec, current, _, query = setup_query()
    assert query.objects(token, [1, 0], ospec).items[0].ref == a
    assert query.rooms(token, [1, 0], rspec).pending == 2
    result = query.relations(token, a, b)
    assert result[0].event_ids == ('ev1',) and result[0].count == 1
    assert not hasattr(result[0], 'verdict')
    assert query.relations(token, b, a) == ()
    with pytest.raises(ValueError, match='stale'):
        query.objects(replace(token, sidecar_revision=1), [1, 0], ospec)
    current[0] = False
    with pytest.raises(ValueError, match='stale'):
        query.relations(token, a, b)


def test_subgraph_is_bounded_directional_and_deterministic():
    token, a, b, room, _, _, _, _, query = setup_query()
    subgraph = query.retrieve_subgraph(token, [a], max_nodes=2, max_edges=1)
    assert subgraph.nodes == (a, b)
    assert [(e.subject, e.object) for e in subgraph.edges] == [(a, b)]
    assert query.retrieve_subgraph(token, [a], max_nodes=1, max_edges=1).edges == ()
    foreign = NativeNodeRef(replace(token.native, graph_revision=8), 'O(3)', 2)
    with pytest.raises(ValueError):
        query.retrieve_subgraph(token, [foreign], max_nodes=2, max_edges=1)
    with pytest.raises(ValueError):
        query.retrieve_subgraph(token, [a], max_nodes=0, max_edges=1)


def test_rejects_mismatched_feature_view_and_relation_store():
    token, a, b, room, _, _, _, relations, query = setup_query()
    wrong = replace(query.object_view, token=replace(token, sidecar_revision=1))
    with pytest.raises(ValueError, match='token'):
        RevisionQuery(token, wrong, query.room_view, relations, lambda _: True)


def test_graph_support_keeps_native_objects_without_embeddings_and_skips_token_decoding(monkeypatch):
    from neusymnav.reasoninggraph import relation_store

    token, a, b, _, _, _, _, relations, query = setup_query()
    empty = replace(query.object_view, objects=())
    result = RevisionQuery(token, empty, query.room_view, relations, lambda _: True)

    def unexpected_decode(*_args):
        pytest.fail('metadata query decoded a token payload')

    monkeypatch.setattr(relation_store, 'decode_tokens', unexpected_decode)
    subgraph = result.retrieve_subgraph(token, [a], max_nodes=2, max_edges=1)
    assert subgraph.nodes == (a, b)
    assert subgraph.edges[0].event_ids == ('ev1',)
