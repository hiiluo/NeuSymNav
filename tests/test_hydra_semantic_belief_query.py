from dataclasses import replace
from types import MappingProxyType

import pytest

from neusymnav.contracts.hydra_graph import NativeNodeRef
from neusymnav.reasoninggraph.native_lineage import CanonicalObjectId, ObjectLineageView
from neusymnav.reasoninggraph.semantic_belief_store import SemanticBeliefView
from test_hydra_scene_graph_query import _query, _taxonomy
from test_rg_semantic_beliefs import receipt


def fixture():
    query = _query()
    token = query.read_token
    objects = MappingProxyType({raw: CanonicalObjectId(token.episode_id, token.run_id, 1, raw)
                                for raw in ('O(0)', 'O(1)', 'O(2)')})
    lineage = ObjectLineageView(token, 1, objects, MappingProxyType({'O(10)': 'O(0)'}))
    r = receipt()
    view = SemanticBeliefView(replace(r.source_token, native=token,
        source=replace(r.source_token.source, episode_id=token.episode_id)), lineage, _taxonomy(),
        MappingProxyType({'O(0)': (r, replace(r, category='table')), 'O(1)': (r,)}))
    active = [view]
    query._belief_reader = lambda expected: active[0] if expected == token else None
    return query, token, active


def test_probability_alias_missing_and_cursor_are_exact():
    query, token, current = fixture()
    alias = NativeNodeRef(token, 'O(10)', 2)
    result = query.object_belief(alias, expected_token=token)
    assert result.status == 'available' and result.token == token
    assert result.value.observation_count == 2
    assert query.category_probability(alias, 'sofa', expected_token=token).value == 0
    assert query.object_belief(query.node_ref('O(2)'), expected_token=token).status == 'unavailable'
    page = query.objects_by_probability('chair', expected_token=token, limit=1).value
    assert page.items[0].ref.native_id == 'O(1)'
    assert query.objects_by_probability('chair', expected_token=token, limit=1,
                                        cursor=page.next_cursor).value.items[0].ref.native_id == 'O(0)'
    with pytest.raises(ValueError):
        query.objects_by_probability('table', expected_token=token, limit=1, cursor=page.next_cursor)
    assert query.belief_evidence(alias, expected_token=token, limit=1).value.next_cursor
    assert query.object_belief(alias, expected_token=replace(token, graph_revision=8)).status == 'stale'
    current[0] = None
    assert query.object_belief(alias, expected_token=token).status == 'unavailable'


def test_room_subgraph_and_uncertainty_keep_native_topology():
    query, token, _ = fixture()
    room = query.node_ref('R(0)')
    assert query.object_belief(room, expected_token=token).status == 'unavailable'
    context = query.probabilistic_room_context(room, expected_token=token).value
    assert [item.ref.native_id for item in context.items] == ['O(0)']
    assert query.uncertain_objects(expected_token=token).value.items[0].ref.native_id == 'O(0)'
    ref = query.node_ref('O(0)')
    result = query.probabilistic_subgraph((ref,), expected_token=token, max_nodes=2)
    assert result.value.graph == query.subgraph((ref,), max_nodes=2).value
    assert result.value.objects[0].ref == ref
