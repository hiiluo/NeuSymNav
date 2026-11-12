from types import SimpleNamespace

import pytest

from neusymnav.rooms.context import build_room_context
from test_hydra_scene_graph_query import _projection, _query
from test_hydra_object_evidence import ref as evidence_ref
from neusymnav.contracts.hydra_evidence import EvidencePage
from neusymnav.backends.hydra.labels import HydraLabelRasterizer
from test_hydra_scene_graph_query import _taxonomy

ROOM_ID = 'hydra:run-1:4:R(0)'


def query(objects):
    unique = {item.native_id: item for item in objects}
    nodes = [dict(native_id=item.native_id, layer_id=2, name=item.category,
        position=[1., 2., .5], parent_native_id='p(0)') for item in unique.values()]
    nodes.extend([
        dict(native_id='p(0)', layer_id=3, name='place', position=[1., 2., 0.], parent_native_id='R(0)'),
        dict(native_id='R(0)', layer_id=4, name='room', position=[1., 2., 0.], parent_native_id='B(0)'),
        dict(native_id='B(0)', layer_id=5, name='building', position=[1., 2., 0.], parent_native_id=None),
    ])
    projection = _projection(revision=9, nodes=nodes)
    labels = HydraLabelRasterizer(_taxonomy()).class_to_label
    semantic = {item.native_id: labels[item.category] for item in unique.values()}
    return _query(projection=projection, semantic_labels=semantic)


def candidate(native_id, category='chair', room=ROOM_ID, membership='assigned'):
    return SimpleNamespace(native_id=native_id, category=category, room_id=room,
        membership_status=membership, graph_revision=9, semantic_id=3,
        graph_status='available', input_prefix_sha256='a'*64)


def support(**kwargs):
    return {'episode_id':'episode-1','run_id':'run-1','geometry_revision':9,
        'geometry_hash':'b'*64,'status':'available',**kwargs}


def test_room_context_counts_distinct_native_objects_and_pins_geometry():
    obj = candidate('O(0)')
    context = build_room_context(query([obj, obj]), evidence={}, room_support=support(), room_id=ROOM_ID)
    assert context.distinct_object_count == 1
    assert context.objects[0].native_id == 'O(0)'
    assert context.objects[0].association_status == 'not_recorded'
    assert context.geometry_revision == 9
    assert context.geometry_hash == 'b'*64
    assert context.truncated is False


def test_context_changes_for_evidence_or_geometry_but_not_duplicate_frames():
    obj = candidate('O(0)')
    base = build_room_context(query([obj]), evidence={}, room_support=support(), room_id=ROOM_ID)
    geometry = build_room_context(query([obj]), evidence={},
        room_support=support(geometry_hash='c'*64), room_id=ROOM_ID)
    ref = evidence_ref(frame=1)
    with_evidence = build_room_context(query([obj]),
        evidence={'O(0)':EvidencePage('available',(ref,ref),None)},
        room_support=support(), room_id=ROOM_ID)
    assert base.input_evidence_hash != geometry.input_evidence_hash
    assert base.input_evidence_hash != with_evidence.input_evidence_hash
    assert with_evidence.objects[0].evidence_count == 1


def test_context_distinguishes_ambiguous_membership_and_truncates_deterministically():
    objects = [candidate(f'O({i:03})') for i in range(70)]
    ambiguous = evidence_ref(frame=1, link_status='ambiguous')
    evidence = {'O(000)':EvidencePage('available',(ambiguous,),None)}
    context = build_room_context(query(objects), evidence=evidence,
        room_support=support(), room_id=ROOM_ID)
    assert context.objects[0].association_status == 'ambiguous'
    assert context.distinct_object_count == 70
    assert context.total_object_count == 70
    assert len(context.objects) == 64
    assert context.truncated is True


def test_context_rejects_stale_query_or_foreign_evidence_revision():
    with pytest.raises(ValueError, match='revision'):
        build_room_context(query([candidate('O(0)')]), evidence={},
            room_support=support(geometry_revision=8), room_id=ROOM_ID)
