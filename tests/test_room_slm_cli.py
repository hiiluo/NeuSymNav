import json
from pathlib import Path

from neusymnav.rooms.requests import make_room_label_request
from test_room_context import candidate, query, support
from tools.infer_room_labels import main


def test_cli_writes_same_context_rule_and_typed_unavailable_model_record(tmp_path):
    request, = make_room_label_request(query([candidate('O(0)', 'toilet')]), {}, support())
    request_path = tmp_path / 'request.json'
    request_path.write_text(request.to_json())
    config_path = Path(__file__).parents[1] / 'configs' / 'room-label-slm.experimental.json'
    output_path = tmp_path / 'prediction.json'
    assert main(['--request-json',str(request_path),'--config',str(config_path),
        '--out',str(output_path)]) == 0
    result = json.loads(output_path.read_text())
    assert result['request_id'] == request.request_id
    assert result['rule']['proposal']['payload']['fields']['status'] == 'proposed'
    assert result['model']['proposal']['payload']['fields']['status'] == 'unavailable'
    assert result['model']['proposal']['payload']['fields']['reason'] == 'model_runtime_disabled'
    assert result['model']['metrics']['launched'] is False
    assert result['rule']['request_id'] == result['model']['request_id']
