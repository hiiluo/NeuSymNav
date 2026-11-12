"""Exact-wire and queue-bound checks for Hydra frame serialization reuse."""
from dataclasses import replace
import hashlib
import json
import time

import pytest

from neusymnav.backends.hydra import session as session_module
from neusymnav.contracts.serialization import dumps
from test_hydra_session import frame, wait_until, worker


def _quoted_frame(index=0, *, marker='quote" backslash\\ café'):
    return replace(frame(index), vocabulary_id=marker)


def _legacy_request(value, request_id):
    payload=dumps(value).encode('utf-8')
    return json.dumps({'type':'frame','request_id':request_id,
        'frame_index':value.source_key.frame_index,'frame':payload.decode('utf-8')},
        separators=(',',':')).encode('utf-8')+b'\n'


def _frame_buffers(value):
    payload=dumps(value).encode('utf-8')
    literal=json.dumps(payload.decode('utf-8'),separators=(',',':'),allow_nan=False).encode('utf-8')
    request=_legacy_request(value,'0'*32)
    return payload,literal,request


def _accepted_worker(tmp_path):
    request_path=tmp_path/'request.jsonl'
    body=f'''\nimport hashlib
for line in sys.stdin:
 msg=json.loads(line)
 if msg["type"] == "close":
  print(json.dumps({{"type":"closed","accepted":1}}),flush=True)
  break
 payload=msg["frame"].encode("utf-8")
 prefix=hashlib.sha256(payload).hexdigest()
 open({str(request_path)!r},"ab").write(line.encode("utf-8"))
 summary={{"schema_version":1,"graph_revision":1,"input_prefix_sha256":prefix,
  "layer_counts":{{}},"nodes":[],"edges":[]}}
 print(json.dumps({{"type":"result","request_id":msg["request_id"],"accepted":True,
  "graph_summary":summary}}),flush=True)
'''
    return worker(tmp_path,body),request_path


def test_request_builder_preserves_legacy_json_bytes_for_escaped_frame():
    value=_quoted_frame(7)
    request_id='a'*32
    payload,literal,_=_frame_buffers(value)
    request=session_module._frame_request(value.source_key.frame_index,request_id,literal)
    expected=json.dumps({'type':'frame','request_id':request_id,
        'frame_index':value.source_key.frame_index,'frame':payload.decode('utf-8')},
        separators=(',',':')).encode('utf-8')+b'\n'
    assert request==expected
    assert session_module._frame_request_size(value.source_key.frame_index,literal)==len(expected)


def test_worker_prefix_and_sorted_journal_bytes_match_legacy_oracles(tmp_path):
    value=_quoted_frame(3);payload,_,_=_frame_buffers(value)
    command,request_path=_accepted_worker(tmp_path)
    journal=tmp_path/'journal.jsonl'
    session=session_module.HydraSession('ep',command=command,journal_path=journal)
    try:
        assert session.offer(value).status=='queued'
        assert session.wait_for_revision(1,2.)
        assert session.snapshot().input_prefix_sha256==hashlib.sha256(payload).hexdigest()
        assert session.close(2.)['complete']
    finally:
        if session.process.poll() is None:session.close(.1)
    request=json.loads(request_path.read_text().splitlines()[0])
    assert request['frame']==payload.decode('utf-8')
    records=journal.read_bytes().splitlines(keepends=True)
    started=next(line for line in records if json.loads(line)['event']=='started')
    event=json.loads(started)
    assert event['selected_frame']==payload.decode('utf-8')
    legacy=json.dumps(event,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')+b'\n'
    assert started==legacy
    run_id=event.pop('run_id')
    literal=json.dumps(payload.decode('utf-8'),separators=(',',':'),allow_nan=False).encode('utf-8')
    assert session_module._journal_line(run_id,{**event,'selected_frame':None},literal)==legacy


def test_payload_encoding_is_reused_by_offer_worker_and_journal(tmp_path,monkeypatch):
    value=_quoted_frame(0,marker='wide-'+('x'*64_000))
    payload_text=dumps(value)
    command,_=_accepted_worker(tmp_path)
    calls=[];original=session_module.json.dumps

    def spy(value,*args,**kwargs):
        if isinstance(value,str) and value==payload_text:
            calls.append('literal')
        elif isinstance(value,dict) and any(item==payload_text for item in value.values()):
            calls.append('large_frame_object')
        return original(value,*args,**kwargs)

    monkeypatch.setattr(session_module.json,'dumps',spy)
    session=session_module.HydraSession('ep',command=command,journal_path=tmp_path/'journal.jsonl')
    try:
        assert session.offer(value).status=='queued'
        assert session.wait_for_revision(1,2.)
        assert session.close(2.)['complete']
    finally:
        if session.process.poll() is None:session.close(.1)
    assert calls==[]  # payload/literal codec must not encode the full large string again


def test_queue_bytes_charge_both_retained_serialized_buffers(tmp_path,monkeypatch):
    value=_quoted_frame(0)
    payload,literal,request=_frame_buffers(value)
    charge=len(payload)+len(literal)
    monkeypatch.setattr(session_module,'MAX_QUEUE_BYTES',charge)
    command,_=_accepted_worker(tmp_path)
    session=session_module.HydraSession('ep',command=command,journal_path=tmp_path/'journal.jsonl')
    try:
        with session._condition:
            admission=session.offer(value)
            stats=session.stats
            assert admission.status=='queued'
            assert admission.payload_bytes==len(request)
            assert stats['pending_bytes']==charge
            assert stats['queue_bytes']==charge
            assert stats['queue_bytes_scope']=='serialized payload plus escaped frame literal; excludes frame object and transient request'
    finally:
        assert session.close(2.)['complete']


def test_queue_cap_rejects_payload_when_combined_buffer_charge_exceeds_limit(tmp_path,monkeypatch):
    value=_quoted_frame(0)
    payload,literal,_=_frame_buffers(value)
    monkeypatch.setattr(session_module,'MAX_QUEUE_BYTES',len(payload)+len(literal)-1)
    command,_=_accepted_worker(tmp_path)
    session=session_module.HydraSession('ep',command=command,journal_path=tmp_path/'journal.jsonl')
    try:
        with session._condition:
            result=session.offer(value)
            assert result.status=='payload_too_large'
            assert session.stats['queue_bytes']==0
    finally:
        assert session.close(2.)['complete']


def test_replacing_pending_frame_releases_its_old_buffer_charge(tmp_path,monkeypatch):
    inflight=frame(0)
    old_pending=_quoted_frame(1,marker='old-'+('o'*4000))
    replacement=_quoted_frame(2,marker='new-'+('n'*1000))
    in_payload,in_literal,_=_frame_buffers(inflight)
    old_payload,old_literal,old_request=_frame_buffers(old_pending)
    new_payload,new_literal,new_request=_frame_buffers(replacement)
    inflight_charge=len(in_payload)+len(in_literal)
    old_charge=len(old_payload)+len(old_literal)
    new_charge=len(new_payload)+len(new_literal)
    assert new_charge<old_charge
    monkeypatch.setattr(session_module,'MAX_QUEUE_BYTES',inflight_charge+old_charge)
    command,_=_accepted_worker(tmp_path)
    session=session_module.HydraSession('ep',command=command,journal_path=tmp_path/'journal.jsonl')
    try:
        with session._condition:
            session._in_flight=True
            session._in_flight_bytes=inflight_charge
            session._pending=(old_pending,old_payload,len(old_request),time.monotonic(),old_literal)
            session._last_offered=old_pending
            admission=session.offer(replacement)
            stats=session.stats
            assert admission.status=='replaced'
            assert admission.payload_bytes==len(new_request)
            assert stats['pending_bytes']==new_charge
            assert stats['in_flight_bytes']==inflight_charge
            assert stats['queue_bytes']==inflight_charge+new_charge
    finally:
        assert session.close(2.)['complete']


def test_journal_quota_still_fails_closed_before_worker_acceptance(tmp_path):
    command,_=_accepted_worker(tmp_path)
    session=session_module.HydraSession('ep',command=command,journal_path=tmp_path/'quota.jsonl',
        artifact_quota_bytes=128)
    try:
        assert session.offer(_quoted_frame()).status=='queued'
        assert wait_until(lambda:session.snapshot().failure_reason=='artifact_quota_exceeded')
        assert session.snapshot().graph_revision==0
        assert session.close(.2)['complete'] is False
    finally:
        if session.process.poll() is None:session.close(.1)


def test_partial_pipe_writes_reuse_original_buffer_without_suffix_copies(monkeypatch):
    from types import SimpleNamespace
    payload=b'frame-payload-'*1000
    received=bytearray()
    owner=object.__new__(session_module.HydraSession)
    owner.process=SimpleNamespace(stdin=SimpleNamespace(fileno=lambda:17))
    monkeypatch.setattr(session_module.select,'select',lambda *args:([],[17],[]))
    def partial_write(fd,remaining):
        assert fd==17
        assert isinstance(remaining,memoryview)
        assert remaining.obj is payload
        count=min(101,len(remaining))
        received.extend(remaining[:count])
        return count
    monkeypatch.setattr(session_module.os,'write',partial_write)
    owner._write(payload,1.)
    assert bytes(received)==payload
