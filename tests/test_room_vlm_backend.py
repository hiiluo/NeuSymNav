import hashlib
import json
from types import SimpleNamespace

from test_room_persistent_backend import make_config, make_request
from neusymnav.rooms.vlm_backend import RoomVlmBackend, build_vlm_prompt, adapt_vlm_reply


def view(request, data=b'jpeg'):
    return SimpleNamespace(view_id=hashlib.sha256(data).hexdigest(), jpeg=data,
        room_id=request.key.room_id, frame_index=3, graph_revision=request.key.graph_revision,
        manifest=lambda: {'frame_index': 3})


def test_prompt_binds_images_and_reply_support(tmp_path):
    request = make_request()
    v = view(request)
    prompt, grammar = build_vlm_prompt(request, (v,), lambda text: [1], 3072)
    assert v.view_id not in prompt.prompt_text
    assert 'v1' in grammar.grammar_text
    changed, _ = build_vlm_prompt(request, (view(request, b'other jpeg'),), lambda text: [1], 3072)
    assert changed.prompt_text == prompt.prompt_text
    assert changed.prompt_sha256 != prompt.prompt_sha256
    raw = json.dumps({'l':'bathroom','o':[], 'v':['v1']})
    result = adapt_vlm_reply(raw, request, (v,), model_hash='a'*64, prompt_hash=prompt.prompt_sha256)
    assert result.status == 'proposed'
    assert result.supporting_view_ids == (v.view_id,)
    other = raw.replace('v1', 'v2')
    assert adapt_vlm_reply(other, request, (v,), model_hash='a'*64, prompt_hash=prompt.prompt_sha256).status == 'invalid_output'


def test_invalid_view_is_rejected_before_server(tmp_path):
    request = make_request()
    backend = RoomVlmBackend(make_config(tmp_path))
    v = view(request)
    v.jpeg = b'changed'
    assert backend.infer(request, views=(v,)).status == 'insufficient_evidence'
    assert backend.last_metrics['launched'] is False


def test_completion_transports_images_and_projector_verified(tmp_path, monkeypatch):
    request = make_request()
    v = view(request)
    projector = tmp_path / 'mmproj.gguf'
    projector.write_bytes(b'projector')
    config = make_config(tmp_path, mmproj_path=str(projector),
        mmproj_sha256=hashlib.sha256(projector.read_bytes()).hexdigest())
    backend = RoomVlmBackend(config)
    seen = []
    monkeypatch.setattr(backend, '_existing_or_start', lambda *args: (SimpleNamespace(pid=1, poll=lambda: None), 'http://127.0.0.1:1', False))
    def http(method, url, body, *args, **kwargs):
        seen.append((url, body))
        if url.endswith('/tokenize'):
            return {'tokens':[1, 2]}
        return {'choices':[{'message':{'content':json.dumps({'l':'bathroom','o':[], 'v':['v1']})}, 'finish_reason':'stop'}], 'usage':{'prompt_tokens':99}}
    monkeypatch.setattr(backend, '_http_deadlined', http)
    result = backend.infer(request, views=(v,))
    assert result.status == 'proposed'
    body = seen[-1][1]
    assert body['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert backend.last_metrics['native_usage']['prompt_tokens'] == 99
    assets, signatures = backend._verify_assets(backend._generation, __import__('time').monotonic() + 1)
    assert assets['mmproj'] == projector
    projector.write_bytes(b'changed')
    assert backend._asset_signature_changes(signatures) == 'mmproj'


def test_projector_hash_mismatch_fails_closed(tmp_path):
    projector = tmp_path / 'mmproj.gguf'
    projector.write_bytes(b'bad')
    backend = RoomVlmBackend(make_config(tmp_path, mmproj_path=str(projector), mmproj_sha256='0'*64))
    import pytest
    from neusymnav.rooms.persistent_backend import _BackendUnavailable
    import time
    with pytest.raises(_BackendUnavailable, match='mmproj_hash_mismatch'):
        backend._verify_assets(backend._generation, time.monotonic() + 1)


def test_visual_evidence_only_bypasses_objectless_gate(tmp_path):
    backend = RoomVlmBackend(make_config(tmp_path))
    backend._views_local.views = (object(),)
    for reason, expected in [('no_semantic_objects', None), ('geometry_stale', 'geometry_stale'),
                             ('ambiguous_room_membership', 'ambiguous_room_membership'),
                             ('context_object_cap_exceeded', 'context_object_cap_exceeded')]:
        assert backend._inference_block_reason(SimpleNamespace(inference_block_reason=reason)) == expected
