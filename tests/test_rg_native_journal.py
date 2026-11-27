import json
from pathlib import Path

import pytest

from neusymnav.backends.hydra.session import HydraSession
from test_hydra_session import frame, worker


WORKER = """
import hashlib
from os import environ
prefix = b''
step = 0
for line in sys.stdin:
    msg = json.loads(line)
    if msg["type"] == "close":
        print(json.dumps({"type":"closed"}), flush=True)
        break
    step += 1
    prefix = hashlib.sha256(prefix + msg["frame"].encode()).digest()
    reply = dict(type="result", request_id=msg["request_id"], accepted=True,
                 graph_summary=dict(schema_version=1, graph_revision=step,
                                    input_prefix_sha256=prefix.hex(),
                                    nodes=[dict(native_id="O(0)", layer_id=2)]),
                 native_metadata=dict(config_sha256="a"*64, source_sha256="b"*40,
                                      build_sha256="c"*64, native_binding_sha256="c"*64,
                                      room_stability=None))
    if environ.get("NEUSYMNAV_HYDRA_OBJECT_JOURNAL") == "1":
        reply["object_event_journal"] = dict(input_prefix_sha256=prefix.hex(), native=dict(
            schema_version=1, status="complete", epoch=1, step=step,
            timestamp_ns=100 + msg["frame_index"] + OFFSET,
            events=[dict(owner="frontend", operation="create", source="O(0)", target=None)] if step == 1 else []))
    print(json.dumps(reply), flush=True)
"""


@pytest.mark.parametrize('enabled,offset,observed', [(True, 0, True), (True, 1, False), (False, 0, False)])
def test_exact_durable_journal_is_optional_and_stale_tokens_are_revoked(tmp_path, enabled, offset, observed):
    path = tmp_path / 'journal.jsonl'
    command = worker(tmp_path, WORKER.replace('OFFSET', str(offset)))
    script = Path(command[1])
    script.write_text(script.read_text().replace('"protocol":1', '"protocol":1,"config_sha256":"a"*64,"source_sha256":"b"*40'))
    session = HydraSession('ep', command=command, journal_path=path, object_event_journal=enabled)
    try:
        assert session.offer(frame()).status == 'queued'
        assert session.wait_for_revision(1, 3)
        token = session.current_read_token()
        batch = session.object_event_batch(token)
        assert (batch is not None) is observed
        view = session.object_lineage(token)
        assert (view is not None) is observed
        if enabled:
            recorded = next(row for row in map(json.loads, path.read_text().splitlines())
                            if row.get('event') == 'accepted')
            assert ('object_event_journal' in recorded) is observed
        if observed:
            assert batch.events[0].source == 'O(0)'
            assert batch.graph_revision == token.graph_revision
            assert view.objects['O(0)'].run_id == token.run_id
        assert session.offer(frame(1)).status == 'queued'
        assert session.wait_for_revision(2, 3)
        assert session.object_event_batch(token) is None
        assert session.object_lineage(token) is None
        if observed:
            assert session.object_lineage(session.current_read_token()).objects == view.objects
    finally:
        assert session.close(3)['complete']
    records = [row for row in map(json.loads, path.read_text().splitlines())
               if row.get('event') == 'accepted']
    assert len(records) == 2
    assert any('object_event_journal' in row for row in records) is observed


def test_corrupt_middle_batch_revokes_continuity_without_stopping_graph(tmp_path):
    command = worker(tmp_path, WORKER.replace('OFFSET', 'int(step == 2)'))
    script = Path(command[1])
    script.write_text(script.read_text().replace('"protocol":1', '"protocol":1,"config_sha256":"a"*64,"source_sha256":"b"*40'))
    session = HydraSession('ep', command=command, journal_path=tmp_path / 'journal.jsonl',
                           object_event_journal=True)
    try:
        for revision in (1, 2, 3):
            assert session.offer(frame(revision - 1)).status == 'queued'
            assert session.wait_for_revision(revision, 3)
            token = session.current_read_token()
            assert (session.object_event_batch(token) is not None) == (revision == 1)
            assert (session.object_lineage(token) is not None) == (revision == 1)
    finally:
        assert session.close(3)['complete']
