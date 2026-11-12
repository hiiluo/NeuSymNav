import pytest

from neusymnav.contracts.room_semantics import RoomLabelProposal, validate_room_label
from neusymnav.rooms.context import RoomContext, RoomObjectContext


def context(*, geometry_revision=5, geometry_status='available', objects=None):
    rows = tuple(RoomObjectContext(item, 'chair', 3, 'assigned', 'not_recorded', 0, ())
                 for item in (objects if objects is not None else ('O(1)',)))
    return RoomContext('ep','run','R(0)',geometry_revision,'a'*64,geometry_status,
        'assigned','b'*64,rows,len(rows),len(rows),False,
        {'graph':'c'*64})


def proposal(ctx, **kwargs):
    defaults = dict(room_id=ctx.room_id, geometry_revision=ctx.geometry_revision,
        input_evidence_hash=ctx.input_evidence_hash, label='kitchen', alternatives=('dining_room',),
        supporting_object_ids=('O(1)',), status='proposed', reason=None,
        model_sha256=None, prompt_sha256=None)
    defaults.update(kwargs)
    return RoomLabelProposal(**defaults)


def test_valid_label_preserves_room_identity_and_supporting_ids():
    ctx = context()
    result = validate_room_label(proposal(ctx), ctx)
    assert result.status == 'available'
    assert result.label == 'kitchen'
    assert result.room_id == ctx.room_id
    assert result.geometry_revision == ctx.geometry_revision
    assert result.supporting_object_ids == ('O(1)',)


def test_stale_room_revision_or_context_hash_is_rejected():
    ctx = context()
    assert validate_room_label(proposal(ctx, geometry_revision=4), ctx).status == 'stale'
    assert validate_room_label(proposal(ctx, input_evidence_hash='d'*64), ctx).status == 'stale'


def test_supporting_object_ids_must_be_in_bounded_context():
    ctx = context(objects=['O(1)'])
    result = validate_room_label(proposal(ctx, supporting_object_ids=('O(2)',)), ctx)
    assert result.status == 'invalid'
    assert result.reason == 'supporting_object_not_in_context'


def test_unknown_and_insufficient_evidence_are_valid_abstentions():
    empty = context(geometry_status='unavailable')
    assert validate_room_label(proposal(empty, label='unknown', status='unknown',
        reason='no_model', alternatives=(), supporting_object_ids=()), empty).status == 'unknown'
    assert validate_room_label(proposal(empty), empty).status == 'insufficient_evidence'


def test_invalid_output_proposal_maps_to_invalid_result_without_raising():
    ctx = context()
    result = validate_room_label(proposal(ctx, status='invalid_output',
        reason='malformed_json'), ctx)
    assert result.status == 'invalid'
    assert result.reason == 'malformed_json'


def test_proposed_label_requires_nonempty_support_from_assigned_members():
    ctx = context()
    result = validate_room_label(proposal(ctx, supporting_object_ids=()), ctx)
    assert result.status == 'invalid'
    assert result.reason == 'proposed_label_requires_assigned_support'


def test_proposed_label_cannot_use_ambiguous_membership_as_support():
    row = RoomObjectContext('O(1)', 'chair', 3, 'ambiguous', 'not_recorded', 0, ())
    ctx = RoomContext('ep','run','R(0)',5,'a'*64,'available','ambiguous','b'*64,
        (row,),1,1,False,{'graph':'c'*64})
    result = validate_room_label(proposal(ctx, supporting_object_ids=('O(1)',)), ctx)
    assert result.status == 'invalid'
    assert result.reason == 'supporting_object_membership_not_assigned'


def test_noncanonical_labels_bad_json_and_unpinned_backend_are_rejected():
    ctx = context()
    with pytest.raises(ValueError, match='label'):
        proposal(ctx, label='kitchenette')
    invalid = validate_room_label({'free_text':'kitchen'}, ctx)
    assert invalid.status == 'invalid'
    with pytest.raises(ValueError, match='both'):
        proposal(ctx, model_sha256='d'*64)


@pytest.mark.parametrize('status', ['unknown', 'insufficient_evidence'])
@pytest.mark.parametrize('claim', ['alternative', 'support'])
def test_abstention_cannot_leak_room_or_support_claims(status, claim):
    ctx = context()
    result = validate_room_label(proposal(ctx, label='unknown', status=status,
        alternatives=('bedroom',) if claim == 'alternative' else (),
        supporting_object_ids=('O(1)',) if claim == 'support' else (),
        reason='insufficient discriminating evidence'), ctx)
    assert result.status == 'invalid'
    assert result.reason == 'abstention_must_be_unknown_without_claims'


def test_insufficient_evidence_cannot_publish_a_room_type():
    ctx = context()
    result = validate_room_label(proposal(ctx, label='kitchen',
        status='insufficient_evidence', alternatives=(), supporting_object_ids=(),
        reason='insufficient evidence'), ctx)
    assert result.status == 'invalid'
