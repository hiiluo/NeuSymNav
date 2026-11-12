import sys
import time
import json

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.backends.hydra.input_adapter import HydraInputAdapter
from neusymnav.contracts import DetectionBatch
from neusymnav.contracts.hydra_graph import HydraCalibration
from neusymnav.backends.hydra.session import HydraSession, replay_selected_prefix


def frame(index=0, episode='ep'):
    obs = observation()
    from dataclasses import replace
    from neusymnav.contracts import FrameKey
    obs = replace(obs, key=FrameKey(episode, 'rgbd', index),
                  capture_monotonic_ns=100 + index)
    cal = HydraCalibration('calibration:v1', 'calibration:v1', 'rgbd', 'camera', obs.K,
        np.eye(4), 0, 'canonical_z_up_v1',
        'optical_x_right_y_down_z_forward_v1', 'metric_axial_v1', 'fixture')
    batch = DetectionBatch.from_observation(obs, (), vocabulary_id='taxonomy:v1')
    return HydraInputAdapter.convert(obs, batch, cal, np.zeros((2, 3), np.int32),
        detector_profile_id='detector:v1', labelspace_id='labelspace:v1',
        labelspace_hash='0'*64)


def worker(tmp_path, body, *, delay_ready=0):
    script = tmp_path / 'fake_worker.py'
    source = ('import json,sys,time\n' + f'time.sleep({delay_ready})\n' +
              'print(json.dumps({"type":"ready","protocol":1}),flush=True)\n' +
              body + '\n')
    script.write_text(source)
    return (sys.executable, str(script))


def wait_until(predicate, timeout=2.):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return True
        time.sleep(.01)
    return predicate()


def test_offer_is_nonblocking_latest_pending_wins_and_only_accepted_advances_revision(tmp_path):
    body = '''
for line in sys.stdin:
 msg=json.loads(line)
 if msg["type"] == "close": break
 time.sleep(.3)
 accepted=msg["frame_index"] != 1
 print(json.dumps({"type":"result","request_id":msg["request_id"],"accepted":accepted}),flush=True)
'''
    session = HydraSession('ep', command=worker(tmp_path, body), journal_path=tmp_path/'journal.jsonl')
    start=time.monotonic(); one=session.offer(frame(0),now_monotonic_ns=101,now_domain='host:boot1'); elapsed=time.monotonic()-start
    assert elapsed < .1 and one.status == 'queued'
    assert wait_until(lambda: session.stats['started'] == 1)
    assert session.offer(frame(1)).status == 'queued'
    assert session.offer(frame(2)).status == 'replaced'
    assert wait_until(lambda: session.stats['accepted'] == 2)
    snap=session.snapshot()
    assert snap.graph_revision == 2 and snap.last_source_key.frame_index == 2
    assert session.stats['replaced'] == 1
    assert session.stats['worker_rss_bytes'] is not None
    assert session.stats['source_age_p50_ms'] == pytest.approx(.000001)
    assert session.close(1.)['complete']
    journal = [json.loads(line) for line in (tmp_path/'journal.jsonl').read_text().splitlines()]
    assert any(event.get('event') == 'accepted' and event.get('source', {}).get('frame_index') == 2
               for event in journal)
    assert any(inner.get('event') == 'replaced' and inner.get('replaced_source', {}).get('frame_index') == 1
               for event in journal for inner in event.get('events', []))


def test_step_false_does_not_advance_graph_revision(tmp_path):
    body='''
for line in sys.stdin:
 msg=json.loads(line)
 if msg["type"] == "close": break
 print(json.dumps({"type":"result","request_id":msg["request_id"],"accepted":False}),flush=True)
'''
    session=HydraSession('ep',command=worker(tmp_path,body),journal_path=tmp_path/'journal.jsonl')
    assert session.offer(frame()).status == 'queued'
    assert wait_until(lambda: session.stats['step_rejected'] == 1)
    assert session.snapshot().graph_revision == 0
    assert session.close(1.)['complete']


def test_configured_fps_limit_is_counted_and_does_not_replace_pending(tmp_path):
    body='''
for line in sys.stdin:
 msg=json.loads(line)
 if msg["type"] == "close": break
 print(json.dumps({"type":"result","request_id":msg["request_id"],"accepted":True}),flush=True)
'''
    session=HydraSession('ep',command=worker(tmp_path,body),journal_path=tmp_path/'journal.jsonl',fps_limit_hz=.1)
    assert session.offer(frame(0)).status == 'queued'
    assert session.offer(frame(1)).status == 'fps_limited'
    assert wait_until(lambda: session.stats['accepted'] == 1)
    assert session.stats['fps_limited'] == 1
    assert session.snapshot().last_source_key.frame_index == 0
    assert session.close(1.)['complete']


def test_journal_artifact_quota_fails_closed_before_native_acceptance(tmp_path):
    body='for line in sys.stdin: time.sleep(30)'
    session=HydraSession('ep',command=worker(tmp_path,body),journal_path=tmp_path/'journal.jsonl',
                         artifact_quota_bytes=128)
    assert session.offer(frame()).status == 'queued'
    assert wait_until(lambda: session.snapshot().failure_reason == 'artifact_quota_exceeded')
    assert session.snapshot().graph_revision == 0
    assert session.close(.2)['complete'] is False


def test_restart_replays_only_exactly_accepted_selected_input_prefix(tmp_path):
    accepts='''
for line in sys.stdin:
 msg=json.loads(line)
 if msg["type"] == "close": break
 print(json.dumps({"type":"result","request_id":msg["request_id"],"accepted":True}),flush=True)
'''
    journal=tmp_path/'first.jsonl'
    first=HydraSession('ep',command=worker(tmp_path,accepts),journal_path=journal)
    assert first.offer(frame(0)).status == 'queued'
    assert first.wait_for_revision(1,1.)
    assert first.close(1.)['complete']
    recovered=replay_selected_prefix(journal,command=worker(tmp_path,accepts),
        journal_output_path=tmp_path/'replay.jsonl',timeout_s=2.)
    assert recovered.snapshot().graph_revision == 1
    assert recovered.snapshot().last_source_key.frame_index == 0
    assert recovered.snapshot().input_prefix_sha256 == first.snapshot().input_prefix_sha256
    assert recovered.close(1.)['complete']


@pytest.mark.parametrize('mode', ['malformed', 'oversized', 'crash', 'sleep'])
def test_bad_or_slow_worker_fails_closed_without_fake_acceptance(tmp_path, mode):
    if mode == 'malformed': body='for line in sys.stdin:\n print("not-json",flush=True); break'
    elif mode == 'oversized': body='for line in sys.stdin:\n sys.stdout.write("x"*(32*1024*1024+1)+"\\n"); sys.stdout.flush(); break'
    elif mode == 'crash': body='for line in sys.stdin: raise SystemExit(7)'
    else: body='for line in sys.stdin: time.sleep(30)'
    session=HydraSession('ep', command=worker(tmp_path,body), worker_timeout_s=.2,
                         journal_path=tmp_path/'journal.jsonl')
    session.offer(frame())
    assert wait_until(lambda: session.snapshot().failure_reason is not None, timeout=2.)
    snap=session.snapshot()
    assert snap.graph_revision == 0 and snap.replay_required
    result=session.close(.2)
    assert result['complete'] is False


def test_wrong_episode_replayed_frame_and_payload_cap_are_rejected(tmp_path):
    body='for line in sys.stdin:\n msg=json.loads(line)\n if msg["type"]=="close": break\n time.sleep(1)'
    session=HydraSession('ep',command=worker(tmp_path,body),journal_path=tmp_path/'journal.jsonl')
    assert session.offer(frame(0,'other')).status == 'wrong_episode'
    assert session.offer(frame(0)).status == 'queued'
    assert session.offer(frame(0)).status == 'replayed_frame'
    huge=frame(1)
    huge=__import__('dataclasses').replace(huge,rgb=np.zeros((1600,1600,3),np.uint8),
        depth_m=np.ones((1600,1600),np.float32),valid_depth=np.ones((1600,1600),bool),
        labels=np.zeros((1600,1600),np.int32))
    assert session.offer(huge).status == 'payload_too_large'
    assert session.close(.1)['complete'] is False


def test_snapshot_retains_last_accepted_native_graph_summary(tmp_path):
    import hashlib
    from neusymnav.contracts.serialization import dumps
    source=frame();digest=hashlib.sha256(dumps(source).encode()).hexdigest()
    body=f'''\nfor line in sys.stdin:\n msg=json.loads(line)\n if msg["type"]=="close": break\n print(json.dumps({{"type":"result","request_id":msg["request_id"],"accepted":True,"graph_summary":{{"schema_version":1,"graph_revision":1,"input_prefix_sha256":"{digest}","layer_counts":{{"5":1}},"nodes":[{{"native_id":"R(1)","layer_id":5,"name":"room","position":[0,0,0],"parent_native_id":None}}],"edges":[]}}}}),flush=True)\n'''
    session=HydraSession('ep',command=worker(tmp_path,body),journal_path=tmp_path/'journal.jsonl')
    try:
        assert session.offer(source).status=='queued'
        assert session.wait_for_revision(1,2.)
        assert session.snapshot().graph_summary['nodes'][0]['native_id']=='R(1)'
    finally:session.close(2.)
