"""Native-oracle coverage for request-specific room-output GBNF."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from dataclasses import replace

import pytest

from neusymnav.rooms.output_grammar import (
    MAX_OUTPUT_GRAMMAR_BYTES,
    OUTPUT_GRAMMAR_POLICY_VERSION,
    RoomOutputGrammar,
    build_room_output_grammar,
)
from neusymnav.rooms.requests import make_room_label_request
from test_room_context import candidate, query, support


NATIVE_VALID = 'Input string is valid according to the grammar.'
NATIVE_INVALID = 'Input string is invalid according to the grammar.'


def make_request(ids=('O(0)',), *, ambiguous=()):
    request = make_room_label_request(query([candidate(native_id) for native_id in ids]),
        {}, support())[0]
    ambiguous = set(ambiguous)
    if not ambiguous:
        return request
    rows = tuple(replace(row, membership_status=(
        'ambiguous' if row.native_id in ambiguous else row.membership_status))
        for row in request.context.objects)
    context = replace(request.context, input_evidence_hash='f' * 64,
        membership_status='ambiguous', objects=rows)
    key = replace(request.key, context_hash=context.input_evidence_hash)
    return replace(request, key=key, context=context)


def reply(*, label='bathroom', alternatives=(), supporting=('O(0)',),
          status='proposed', reason='evidence is sufficient', ensure_ascii=True):
    return json.dumps({
        'label': label,
        'alternatives': list(alternatives),
        'supporting_object_ids': list(supporting),
        'status': status,
        'reason': reason,
    }, ensure_ascii=ensure_ascii, separators=(',', ':'))


@pytest.fixture
def native_accepts(tmp_path):
    binary = os.environ.get('ROOM_SLM_NATIVE_VALIDATOR')
    if not binary:
        pytest.skip('ROOM_SLM_NATIVE_VALIDATOR is not configured')
    validator = Path(binary)
    if not validator.is_file():
        pytest.fail(f'ROOM_SLM_NATIVE_VALIDATOR does not exist: {validator}')

    def accepts(grammar_text: str, output: str) -> bool:
        grammar_path = tmp_path / 'request.gbnf'
        input_path = tmp_path / 'output.json'
        grammar_path.write_text(grammar_text, encoding='utf-8')
        input_path.write_text(output, encoding='utf-8')
        result = subprocess.run([str(validator), str(grammar_path), str(input_path)],
            check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        first_stdout_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ''
        assert first_stdout_line in {NATIVE_VALID, NATIVE_INVALID}, result.stdout
        return first_stdout_line == NATIVE_VALID

    return accepts


def test_output_grammar_is_frozen_deterministic_and_changes_with_support_context():
    request = make_request(('O(0)', 'O(1)'))
    first = build_room_output_grammar(request)
    second = build_room_output_grammar(request)

    assert isinstance(first, RoomOutputGrammar)
    assert first == second
    assert first.policy_version == OUTPUT_GRAMMAR_POLICY_VERSION
    assert first.grammar_sha256 == hashlib.sha256(first.grammar_text.encode('utf-8')).hexdigest()
    assert first.allowed_support_ids == ('O(0)', 'O(1)')
    assert build_room_output_grammar(make_request(('O(0)', 'O(2)'))).grammar_sha256 != first.grammar_sha256
    with pytest.raises((AttributeError, TypeError)):
        first.grammar_text = 'changed'


def test_native_grammar_accepts_consistent_proposals_and_both_abstention_statuses(
        native_accepts):
    grammar = build_room_output_grammar(make_request(('O(0)', 'O(1)', 'O(2)'))).grammar_text

    assert native_accepts(grammar, reply(alternatives=('bedroom', 'kitchen'),
        supporting=('O(0)', 'O(2)')))
    assert native_accepts(grammar, reply(alternatives=('unknown',), supporting=('O(1)',)))
    assert native_accepts(grammar, reply(label='unknown', alternatives=(), supporting=(),
        status='unknown', reason='not enough evidence'))
    assert native_accepts(grammar, reply(label='unknown', alternatives=(), supporting=(),
        status='insufficient_evidence', reason='not enough evidence'))


@pytest.mark.parametrize('output', [
    reply(alternatives=('bathroom',)),  # primary label repeated
    reply(alternatives=('kitchen', 'bedroom')),  # not canonical sorted order
    reply(alternatives=('bedroom', 'bedroom')),  # duplicate alternative
    reply(supporting=('O(0)', 'O(0)')),  # duplicate support
    reply(supporting=('O(9)',)),  # not assigned to this request
    reply(supporting=('O(0), O(1)',)),  # fabricated combined ID
    reply(supporting=()),  # proposed without evidence
    reply(label='unknown'),  # proposed status cannot claim unknown
    reply(status='unknown'),  # abstention needs unknown label and no support
    reply(label='unknown', supporting=(), status='proposed'),
    reply(label='unknown', alternatives=('bedroom',), supporting=(), status='unknown'),
    reply(label='bathroom', supporting=(), status='insufficient_evidence'),
    reply(label='unknown', supporting=('O(0)',), status='unknown'),
])
def test_native_grammar_rejects_inconsistent_proposals(native_accepts, output):
    grammar = build_room_output_grammar(make_request(('O(0)', 'O(1)'))).grammar_text
    assert not native_accepts(grammar, output)


def test_native_grammar_support_is_enum_of_assigned_ids_only(native_accepts):
    request = make_request(('O(0)', 'O(1)'), ambiguous=('O(1)',))
    grammar = build_room_output_grammar(request)

    assert grammar.allowed_support_ids == ('O(0)',)
    assert native_accepts(grammar.grammar_text, reply(supporting=('O(0)',)))
    assert not native_accepts(grammar.grammar_text, reply(supporting=('O(1)',)))


def test_zero_eligible_ids_compile_abstention_only(native_accepts):
    grammar = build_room_output_grammar(make_request(('O(0)',), ambiguous=('O(0)',)))

    assert grammar.allowed_support_ids == ()
    assert native_accepts(grammar.grammar_text, reply(label='unknown', supporting=(),
        status='unknown'))
    assert not native_accepts(grammar.grammar_text, reply(supporting=('O(0)',)))


def test_native_grammar_bounds_reason_and_requires_nonspace_printable_first_character(
        native_accepts):
    grammar = build_room_output_grammar(make_request()).grammar_text

    assert native_accepts(grammar, reply(reason='x' * 256))
    assert not native_accepts(grammar, reply(reason='x' * 257))
    assert not native_accepts(grammar, reply(reason=''))
    assert not native_accepts(grammar, reply(reason=' starts with space'))
    assert not native_accepts(grammar, reply(reason='\nstarts with newline'))
    assert native_accepts(grammar, reply(reason='x then escaped\nnewline'))
    assert native_accepts(grammar, reply(reason='x with "quote", \\ slash, and\nnewline'))
    assert native_accepts(grammar, reply(reason='x includes café and 雪', ensure_ascii=False))


@pytest.mark.parametrize('output', [
    '{"label":"bathroom"',
    reply() + ' trailing',
    reply().replace('"reason":', '"extra":1,"reason":'),
    reply().replace('"label":"bathroom",', '"status":"proposed","label":"bathroom",'),
])
def test_native_grammar_rejects_malformed_extra_or_noncanonical_json(native_accepts, output):
    grammar = build_room_output_grammar(make_request()).grammar_text
    assert not native_accepts(grammar, output)


def test_native_grammar_escapes_untrusted_native_id_literals(native_accepts):
    special_id = 'O("quoted")\\tail\n雪'
    grammar = build_room_output_grammar(make_request((special_id,)))
    output = reply(supporting=(special_id,))

    assert grammar.allowed_support_ids == (special_id,)
    assert native_accepts(grammar.grammar_text, output)
    assert not native_accepts(grammar.grammar_text, reply(supporting=('O(0)',)))


def test_64_object_request_compiles_with_bounded_size_and_runtime(native_accepts):
    request = make_request(tuple(f'O({index:02d})' for index in range(64)))
    start = time.perf_counter()
    grammar = build_room_output_grammar(request)
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0
    assert len(grammar.allowed_support_ids) == 64
    assert len(grammar.grammar_text.encode('utf-8')) <= MAX_OUTPUT_GRAMMAR_BYTES
    assert native_accepts(grammar.grammar_text, reply(supporting=tuple(
        f'O({index:02d})' for index in range(8))))
    assert not native_accepts(grammar.grammar_text, reply(supporting=tuple(
        f'O({index:02d})' for index in range(9))))


def test_compiler_rejects_contexts_beyond_the_64_object_bound():
    request = make_request(tuple(f'O({index:02d})' for index in range(64)))
    row = request.context.objects[0]
    context = request.context
    context = type(context)(context.episode_id, context.run_id, context.room_id,
        context.geometry_revision, context.geometry_hash, context.geometry_status,
        context.membership_status, 'a' * 64, context.objects + (row,),
        65, 65, False, context.source_hashes)
    key = type(request.key)(request.key.episode_id, request.key.run_id, request.key.room_id,
        request.key.graph_revision, request.key.input_prefix_sha256, request.key.geometry_hash,
        context.input_evidence_hash, request.key.world_epoch)
    too_many = type(request)(key, context, request.relations, request.source_manifest)

    with pytest.raises(ValueError, match='64'):
        build_room_output_grammar(too_many)


def test_compiler_fails_closed_on_empty_assigned_native_id():
    request = make_request()
    empty_row = replace(request.context.objects[0], native_id='')
    context = replace(request.context, input_evidence_hash='a' * 64,
        objects=(empty_row,))
    key = replace(request.key, context_hash=context.input_evidence_hash)
    malformed = replace(request, key=key, context=context)

    with pytest.raises(ValueError, match='nonempty'):
        build_room_output_grammar(malformed)

