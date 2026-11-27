from dataclasses import replace

import pytest

from test_rg_evidence import inputs
from neusymnav.contracts.hydra_graph import NativeNodeRef
from neusymnav.contracts.observations import FrameKey
from neusymnav.contracts.reasoninggraph import FeatureSpec
from neusymnav.reasoninggraph.room_features import RoomFeatureStore, rank_rooms


def test_room_reassignment_reclusters_exact_native_geometry():
    _, _, token = inputs()
    spec = FeatureSpec('room-test', '1' * 64, '2' * 64, 2, 'room')
    store = RoomFeatureStore(token, spec, clusters=2)
    later = replace(token, native=replace(token.native, graph_revision=8, input_prefix_sha256='a'*64),
                    source=FrameKey('ep', 'rgbd', 6), capture_monotonic_ns=101)
    assert store.observe_room_view(token, [1., 0.])
    assert store.observe_room_view(later, [0., 1.])
    assert not store.observe_room_view(later, [0., 1.])
    room = NativeNodeRef(later.native, 'R(0)', 4)
    other = NativeNodeRef(later.native, 'R(1)', 4)
    combined = store.recluster(later, {token.source: room})
    assert combined.pending == 1
    assert rank_rooms(combined, [1., 0.], spec)[0].support == 1
    split = store.recluster(later, {token.source: other, later.source: room})
    assert split.pending == 0
    assert rank_rooms(split, [1., 0.], spec)[0].ref == other
    stale = NativeNodeRef(token.native, 'R(0)', 4)
    with pytest.raises(ValueError, match='exact room revision'):
        store.recluster(later, {token.source: stale})


def test_room_cluster_and_prompt_scoring_is_deterministic():
    _, _, token = inputs()
    spec = FeatureSpec('room-test', '1' * 64, '2' * 64, 2, 'room')
    store = RoomFeatureStore(token, spec, clusters=2)
    for i, vector in enumerate(([1., 0.], [0., 1.], [0., 1.])):
        shot = replace(token, native=replace(token.native, graph_revision=7+i, input_prefix_sha256=str(3+i)*64),
                       source=FrameKey('ep', 'rgbd', i+5), capture_monotonic_ns=100+i)
        assert store.observe_room_view(shot, vector)
    token = shot
    ref = NativeNodeRef(token.native, 'R(0)', 4)
    members = {FrameKey('ep', 'rgbd', i+5): ref for i in range(3)}
    view = store.recluster(token, members)
    assert view == store.recluster(token, dict(reversed(tuple(members.items()))))
    assert rank_rooms(view, [1., 0.], spec)[0].score == .5
    assert rank_rooms(view, [1., 0.], spec, scoring='max')[0].score == 1.
    with pytest.raises(ValueError, match='different feature space'):
        rank_rooms(view, [1., 0.], replace(spec, model_sha256='3'*64))
