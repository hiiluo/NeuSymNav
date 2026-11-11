"""The measurement harness must never be more permissive than production."""
import importlib.util
import json
from pathlib import Path
import pytest
from neusymnav.rooms.requests import make_room_label_request
from test_room_context import candidate, query, support

@pytest.mark.parametrize('finish,status,reason', [('stop','proposed','toilet anchor'),
    ('length','invalid_output','generation_truncated')])
def test_kv_probe_rejects_even_complete_json_when_runtime_reports_length(finish,status,reason):
    path=Path(__file__).parents[1]/'tools/room_slm_response_policy.py'
    spec=importlib.util.spec_from_file_location('room_slm_kv_policy',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    req=make_room_label_request(query([candidate('O(0)','toilet')]),{},support())[0]
    raw=json.dumps({'label':'bathroom','alternatives':[],'supporting_object_ids':['O(0)'],
        'status':'proposed','reason':'toilet anchor'})
    proposal=module.adapt_completion({'message':{'content':raw},'finish_reason':finish},req,
        model_hash='d'*64,prompt_hash='e'*64)
    assert proposal.status==status and proposal.reason==reason
    if finish=='length':assert proposal.supporting_object_ids==() and proposal.label=='unknown'
