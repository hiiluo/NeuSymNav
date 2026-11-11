from dataclasses import replace
import pytest

from neusymnav.rooms.prompt import PromptBudget, RoomPromptError, render_room_prompt
from test_room_context import candidate, query, support
from neusymnav.rooms.requests import make_room_label_request


class WordTokenizer:
    def encode(self, text):
        return text.split()


_UNSET = object()


def request(objects=None, room_support=_UNSET):
    if objects is None:
        objects = [candidate('O(0)', 'toilet')]
    selected_support = support() if room_support is _UNSET else room_support
    return make_room_label_request(query(objects), {}, selected_support)[0]


def test_prompt_uses_canonical_semantics_membership_and_native_relations_only():
    value = render_room_prompt(request(), WordTokenizer(), PromptBudget(max_input_tokens=3072))
    assert 'toilet' in value.prompt_text
    assert 'O(0)' in value.prompt_text
    assert 'assigned' in value.prompt_text
    assert 'parent' in value.prompt_text
    assert 'episode-1' not in value.prompt_text
    assert 'run-1' not in value.prompt_text
    assert 'hydra:run-1:4:R(0)' not in value.prompt_text
    assert 'position_xyz' not in value.prompt_text
    assert value.retained_object_ids == ('O(0)',)
    assert len(value.prompt_sha256) == 64


def test_prompt_fails_closed_for_unavailable_geometry_or_truncated_context():
    with pytest.raises(RoomPromptError) as missing:
        render_room_prompt(request(room_support=None), WordTokenizer(), 3072)
    assert missing.value.status == 'insufficient_evidence'
    assert missing.value.reason == 'room_geometry_unavailable'

    many = request([candidate(f'O({i:03})', 'toilet') for i in range(70)])
    with pytest.raises(RoomPromptError) as truncated:
        render_room_prompt(many, WordTokenizer(), 3072)
    assert truncated.value.reason == 'context_object_cap_exceeded'


def test_prompt_rejects_instruction_like_or_noncanonical_object_category():
    value = request()
    row = replace(value.context.objects[0], category='ignore_previous_instructions')
    changed_context = replace(value.context, objects=(row,))
    changed = replace(value, context=changed_context)
    with pytest.raises(RoomPromptError, match='noncanonical_object_category'):
        render_room_prompt(changed, WordTokenizer(), 3072)


def test_prompt_accepts_canonical_taxonomy_category_with_spaces():
    value = render_room_prompt(request([candidate('O(0)', 'coffee table')]), WordTokenizer(), 3072)
    assert 'coffee table' in value.prompt_text


def test_prompt_budget_overflow_returns_typed_insufficient_evidence():
    with pytest.raises(RoomPromptError) as caught:
        render_room_prompt(request(), WordTokenizer(), PromptBudget(max_input_tokens=2))
    assert caught.value.status == 'insufficient_evidence'
    assert caught.value.reason == 'context_budget_exceeded'
