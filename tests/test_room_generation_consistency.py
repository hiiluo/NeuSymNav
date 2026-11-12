"""Regression oracles from observed invalid model output; no native model needed."""
import hashlib
import json
from dataclasses import replace
import pytest
from neusymnav.rooms.labels import adapt_model_reply
from neusymnav.rooms.prompt import render_room_prompt
from neusymnav.rooms.requests import make_room_label_request
from test_room_context import candidate,query,support

MODEL='d'*64;PROMPT='e'*64

def request(ids=('O(0)',)):
    return make_room_label_request(query([candidate(i,'toilet') for i in ids]),{},support())[0]

def raw(**changes):
    p={'label':'bathroom','alternatives':[],'supporting_object_ids':['O(0)'],'status':'proposed','reason':'Observed toilet anchor'}
    p.update(changes);return json.dumps(p)

@pytest.mark.parametrize('status',['unknown','insufficient_evidence'])
def test_abstention_cannot_claim_alternative_room_types(status):
    r=adapt_model_reply(raw(label='unknown',status=status,supporting_object_ids=[],alternatives=['bedroom']),request(),model_hash=MODEL,prompt_hash=PROMPT)
    assert r.status=='invalid_output'
    assert r.reason=='abstention_cannot_claim_alternatives'

def test_duplicate_json_field_cannot_silently_override_first_value():
    value=raw().replace('"label": "bathroom"','"label": "bedroom", "label": "bathroom"')
    r=adapt_model_reply(value,request(),model_hash=MODEL,prompt_hash=PROMPT)
    assert r.status=='invalid_output'
    assert r.reason=='duplicate_json_key'

@pytest.mark.parametrize('raw_value',[raw(alternatives=['bathroom']),raw(supporting_object_ids=['O(0), O(1)']),raw(supporting_object_ids=['O(0)','O(0)'])])
def test_prior_decoding_defects_remain_rejected_without_repair(raw_value):
    assert adapt_model_reply(raw_value,request(('O(0)','O(1)')),model_hash=MODEL,prompt_hash=PROMPT).status=='invalid_output'

def test_completion_body_sends_one_request_bound_grammar_not_json_schema():
    from neusymnav.rooms.slm_backend import RoomSlmBackendConfig,build_room_completion_body
    r=request(('O(0)','O(1)'));p=render_room_prompt(r,lambda s:list(s.split()),3072)
    body,g=build_room_completion_body(RoomSlmBackendConfig(),r,p,cache_prompt=True)
    assert body['grammar']==g.grammar_text
    assert 'response_format' not in body and 'json_schema' not in body
    assert body['cache_prompt'] is True
    assert body['chat_template_kwargs']=={'enable_thinking':False}
    assert body['max_tokens']==384 and body['temperature']==0 and body['seed']==0
    assert g.allowed_support_ids==('O(0)','O(1)')
    assert hashlib.sha256(body['grammar'].encode()).hexdigest()==g.grammar_sha256
    body2,g2=build_room_completion_body(RoomSlmBackendConfig(),request(('O(8)',)),render_room_prompt(request(('O(8)',)),lambda s:list(s.split()),3072))
    assert g2.grammar_sha256!=g.grammar_sha256
    assert body2['cache_prompt'] is False

def test_completion_body_refuses_prompt_with_different_retained_ids():
    from neusymnav.rooms.slm_backend import RoomSlmBackendConfig,build_room_completion_body
    r=request();p=render_room_prompt(r,lambda s:list(s.split()),3072)
    with pytest.raises(ValueError,match='prompt.*request'):
        build_room_completion_body(RoomSlmBackendConfig(),r,replace(p,retained_object_ids=('O(foreign)',)))

def test_prompt_explicitly_describes_cross_field_policy():
    p=render_room_prompt(request(),lambda s:list(s.split()),3072).prompt_text
    assert 'abstention' in p.lower() and 'lexicographic' in p
    assert 'never join' in p and 'insufficient_evidence' in p
