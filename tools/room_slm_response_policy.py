"""Benchmark host policy matching production rejection of truncated generations."""
from dataclasses import replace
from neusymnav.rooms.labels import adapt_model_reply


def adapt_completion(choice, request, *, model_hash, prompt_hash):
    proposal = adapt_model_reply(choice['message']['content'], request,
        model_hash=model_hash, prompt_hash=prompt_hash)
    if choice.get('finish_reason') == 'length':
        return replace(proposal, label='unknown', alternatives=(),
            supporting_object_ids=(), status='invalid_output', reason='generation_truncated')
    return proposal
