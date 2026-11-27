from dataclasses import replace

from test_rg_query import setup_query
from neusymnav.reasoninggraph.reasoner import TaskReasoner, ReasoningBudget


def run(outputs, *, instruction='find chair', mutate=None):
    token, a, b, room, ospec, rspec, current, _, query = setup_query()
    calls = []
    def complete(stage, payload):
        calls.append(stage)
        if mutate:
            mutate(current, stage)
        return outputs[len(calls)-1]
    reasoner = TaskReasoner(complete, model_id='fixture-model', prompt_id='fixture-v1')
    result = reasoner.propose(query, token, instruction, [1, 0], ospec, ReasoningBudget())
    return result, calls, a


def test_grounded_proposal_and_order():
    result, calls, a = run(['{"kind":"object"}', '{"id":"O(1)"}'])
    assert calls == ['parse', 'select']
    assert result.status == 'proposed' and result.ref == a
    assert result.trace == ('parse:object', 'select:grounded')


def test_untrusted_or_unsupported_outputs_abstain():
    for outputs in ([ '{"kind":"object","kind":"room"}' ],
                    ['{"kind":"relation"}'], ['{"kind":"ambiguous"}'],
                    ['{"kind":"object"}', '{"id":"foreign"}'],
                    ['{"kind":"object"}', '{"id":"O(1)","action":"stop"}']):
        result, _, _ = run(outputs)
        assert result.status == 'insufficient_evidence' and result.ref is None


def test_stale_during_completion_and_transport_failure_abstain():
    result, calls, _ = run(['{"kind":"object"}'], mutate=lambda current, stage: current.__setitem__(0, False))
    assert result.status == 'insufficient_evidence' and calls == ['parse']
    result, _, _ = run([])
    assert result.status == 'insufficient_evidence'


def test_deadline_and_call_budget_stop_without_completion():
    token, a, b, room, ospec, rspec, current, _, query = setup_query()
    calls = []
    reasoner = TaskReasoner(lambda *args: calls.append(args), model_id='m', prompt_id='p', clock=lambda: 10.)
    result = reasoner.propose(query, token, 'find chair', [1, 0], ospec, ReasoningBudget(deadline=9.))
    assert result.status == 'insufficient_evidence' and not calls
    result = reasoner.propose(query, token, 'find chair', [1, 0], ospec, ReasoningBudget(max_calls=1))
    assert result.status == 'insufficient_evidence' and not calls


def test_late_result_and_wrong_revision_are_discarded():
    token, a, b, room, ospec, _, _, _, query = setup_query()
    now = [0.]
    def late(stage, payload):
        now[0] = 2.
        return '{"kind":"object"}'
    reasoner = TaskReasoner(late, model_id='m', prompt_id='p', clock=lambda: now[0])
    assert reasoner.propose(query, token, 'find chair', [1, 0], ospec, ReasoningBudget(deadline=1.)).status == 'insufficient_evidence'
    assert reasoner.propose(query, replace(token, sidecar_revision=1), 'find chair', [1, 0], ospec, ReasoningBudget()).status == 'insufficient_evidence'


def test_unsupported_relation_cannot_be_flattened_to_single_object():
    result, calls, _ = run(['{"kind":"object"}', '{"id":"O(1)"}'],
                           instruction='find chair next to nonexistent table')
    assert result.status == 'insufficient_evidence' and not calls


def test_reasoner_ranks_the_exact_view_instead_of_accepting_caller_scores():
    token, a, b, _, ospec, _, _, _, query = setup_query()
    ranked = []

    def complete(stage, payload):
        if stage == 'parse':
            return '{"kind":"object"}'
        ranked.extend(payload['ranked_candidates'])
        return '{"id":"O(1)"}'

    reasoner = TaskReasoner(complete, model_id='m', prompt_id='p')
    result = reasoner.propose(query, token, 'find chair', [1, 0], ospec, ReasoningBudget())
    assert result.status == 'proposed'
    assert ranked == [(a.native_id, 1.0, 2), (b.native_id, 0.0, 1)]
