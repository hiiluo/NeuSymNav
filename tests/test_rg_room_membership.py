from dataclasses import replace

import pytest

from test_rg_evidence import inputs
from neusymnav.contracts.hydra_graph import NativeNodeRef
from neusymnav.reasoninggraph.room_membership import CertifiedRoom, RoomSample, resolve_memberships


def setup_data():
    _, _, token = inputs()
    room = NativeNodeRef(token.native, 'R(0)', 4)
    geometry = CertifiedRoom(token, room, 'floor-0', ((0, 0), (2, 0), (2, 2), (0, 2)), 'survey-v1')
    sample = RoomSample(token, (1, 1, 1), 'floor-0')
    return token, geometry, sample


def test_assigned_only_with_exact_certified_containment():
    token, geometry, sample = setup_data()
    result = resolve_memberships(token, [sample], [geometry], geometry_complete=True)[0]
    assert (result.status, result.room, result.reason) == ('assigned', geometry.room, 'inside_certified_room')
    assert result.source == token.source


def test_missing_geometry_floor_and_pose_are_pending():
    token, geometry, sample = setup_data()
    assert resolve_memberships(token, [sample], [])[0].status == 'pending'
    assert resolve_memberships(token, [replace(sample, floor_id=None)], [geometry], geometry_complete=True)[0].status == 'pending'
    assert resolve_memberships(token, [replace(sample, position=None)], [geometry], geometry_complete=True)[0].status == 'pending'
    assert resolve_memberships(token, [replace(sample, floor_id='other')], [geometry], geometry_complete=True)[0].status == 'pending'


def test_boundary_and_competing_rooms_are_ambiguous():
    token, geometry, sample = setup_data()
    assert resolve_memberships(token, [replace(sample, position=(0, 1, 1))], [geometry], geometry_complete=True)[0].status == 'ambiguous'
    other = replace(geometry, room=NativeNodeRef(token.native, 'R(1)', 4))
    result = resolve_memberships(token, [sample], [other, geometry], geometry_complete=True)[0]
    assert result.status == 'ambiguous'
    assert result.candidates == (geometry.room, other.room)


def test_outside_is_pending_and_stale_geometry_cannot_assign():
    token, geometry, sample = setup_data()
    assert resolve_memberships(token, [replace(sample, position=(3, 1, 1))], [geometry], geometry_complete=True)[0].status == 'pending'
    stale = replace(token, sidecar_revision=token.sidecar_revision + 1)
    assert resolve_memberships(stale, [sample], [geometry], geometry_complete=True)[0].status == 'pending'


def test_invalid_geometry_duplicate_sources_and_caps_rejected():
    token, geometry, sample = setup_data()
    with pytest.raises(ValueError):
        replace(geometry, polygon=((0, 0), (1, 1), (0, 1), (1, 0)))
    with pytest.raises(ValueError):
        resolve_memberships(token, [sample, sample], [geometry])
    with pytest.raises(ValueError):
        resolve_memberships(token, [sample], [geometry], max_samples=0)


def test_retained_source_can_be_reassigned_with_corrected_pose_at_new_token():
    token, geometry, sample = setup_data()
    newer = replace(token, native=replace(token.native, graph_revision=8, input_prefix_sha256='a'*64),
                    sidecar_revision=token.sidecar_revision + 1)
    new_room = replace(geometry, token=newer, room=NativeNodeRef(newer.native, 'R(1)', 4))
    corrected = RoomSample(newer, (1, 1, 1), 'floor-0', source=sample.token.source)
    result = resolve_memberships(newer, [corrected], [new_room], geometry_complete=True)[0]
    assert result.source == sample.token.source
    assert result.room == new_room.room


def test_partial_or_mixed_revision_geometry_never_assigns():
    token, geometry, sample = setup_data()
    assert resolve_memberships(token, [sample], [geometry], geometry_complete=False)[0].status == 'pending'
    old = replace(token, sidecar_revision=token.sidecar_revision + 1)
    other = replace(geometry, token=old, room=NativeNodeRef(old.native, 'R(1)', 4))
    assert resolve_memberships(token, [sample], [geometry, other], geometry_complete=True)[0].status == 'pending'
