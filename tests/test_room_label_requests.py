from dataclasses import replace

from neusymnav.contracts import dumps, loads
from neusymnav.contracts.room_label_publication import RoomLabelPublication
from neusymnav.rooms.requests import RoomLabelRequestKey, make_room_label_request
from test_room_context import ROOM_ID, candidate, query, support


def test_request_uses_native_room_and_exact_run_revision_context_identity():
    request, = make_room_label_request(query([candidate('O(0)', 'toilet')]), {},
        support(), world_epoch='world-1')
    key = request.key
    assert key.room_id == ROOM_ID
    assert key.episode_id == 'episode-1'
    assert key.run_id == 'run-1'
    assert key.graph_revision == 9
    assert key.input_prefix_sha256 == 'a' * 64
    assert key.geometry_hash == 'b' * 64
    assert key.context_hash == request.context.input_evidence_hash
    assert key.world_epoch == 'world-1'
    assert request.request_id == make_room_label_request(query([candidate('O(0)', 'toilet')]),
        {}, support(), world_epoch='world-1')[0].request_id


def test_request_relations_are_only_native_parent_edges_from_same_projection():
    request, = make_room_label_request(query([candidate('O(0)', 'toilet')]), {}, support())
    assert {(r.subject_native_id, r.relation, r.object_native_id) for r in request.relations} == {
        ('O(0)', 'parent', 'p(0)'), ('p(0)', 'parent', 'R(0)'), ('R(0)', 'parent', 'B(0)')}


def test_request_marks_missing_geometry_and_truncated_context_as_host_abstentions():
    missing_geometry, = make_room_label_request(query([candidate('O(0)')]), {}, None)
    assert missing_geometry.inference_block_reason == 'room_geometry_unavailable'

    truncated, = make_room_label_request(query([candidate(f'O({i:03})') for i in range(70)]),
        {}, support())
    assert truncated.context.truncated is True
    assert truncated.inference_block_reason == 'context_object_cap_exceeded'


def test_empty_native_room_still_gets_a_request_that_abstains():
    request, = make_room_label_request(query([]), {}, support())
    assert request.context.objects == ()
    assert request.inference_block_reason == 'no_semantic_objects'


def test_request_and_publication_contracts_round_trip_deterministically():
    request, = make_room_label_request(query([candidate('O(0)', 'toilet')]), {}, support())
    assert loads(dumps(request)) == request
    from neusymnav.contracts.room_semantics import RoomLabelResult
    result = RoomLabelResult(request.key.room_id, request.key.graph_revision,
        request.key.context_hash, 'unknown', (), (), 'insufficient_evidence', 'sparse',
        None, None)
    publication = RoomLabelPublication(request.key, result, 'f' * 64, 'e' * 64,
        '1' * 64, '2' * 64, 10, 20, 'monotonic:test-clock', 'history')
    assert loads(dumps(publication)) == publication


def test_full_request_key_prevents_cross_run_or_revision_publication_attachment():
    request, = make_room_label_request(query([candidate('O(0)', 'toilet')]), {}, support())
    key = request.key
    other_run = replace(key, run_id='run-2')
    other_revision = replace(key, graph_revision=10)
    assert key != other_run
    assert key != other_revision
    assert key.matches_current(other_run) is False
    assert key.matches_current(other_revision) is False


def test_publication_rejects_result_bound_to_another_run_or_context():
    request, = make_room_label_request(query([candidate('O(0)', 'toilet')]), {}, support())
    from neusymnav.contracts.room_semantics import RoomLabelResult
    result = RoomLabelResult(request.key.room_id, request.key.graph_revision,
        request.key.context_hash, 'bathroom', (), ('O(0)',), 'available', None,
        'd' * 64, 'e' * 64)
    publication = RoomLabelPublication(request.key, result, 'f' * 64, 'e' * 64,
        '1' * 64, '2' * 64, 10, 20, 'monotonic:test-clock', 'current')
    assert publication.matches_current(request.key)
    assert not publication.matches_current(replace(request.key, run_id='run-2'))
    assert not publication.matches_current(replace(request.key, graph_revision=10))
