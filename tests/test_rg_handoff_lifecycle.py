"""Controlled host handoff: synthetic transport, not native merge telemetry."""
from dataclasses import replace
import json

import pytest

from test_hydra_session import frame, worker
from test_rg_evidence import inputs
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.contracts.hydra_graph import NativeNodeRef
from neusymnav.contracts.reasoninggraph import FeatureSpec
from neusymnav.reasoninggraph.object_features import ObjectFeature, ObjectFeatureView
from neusymnav.reasoninggraph.room_features import RoomFeatureView
from neusymnav.reasoninggraph.relation_store import RelationStore
from neusymnav.reasoninggraph.query import RevisionQuery


# Same ordered backend merge shape as the native owner test. This is a synthetic
# worker: the C++ test checks its own events, but exports no batch to this test.
WORKER = '''
import hashlib
prefix = b''
step = 0
for line in sys.stdin:
 msg = json.loads(line)
 if msg['type'] == 'close':
  print(json.dumps({'type':'closed'}), flush=True); break
 step += 1
 prefix = hashlib.sha256(prefix + msg['frame'].encode()).digest()
 ids = [['O(0)', 'O(1)', 'O(2)'], ['O(2)'], []][step-1]
 events = [[dict(owner='frontend', operation='create', source=x, target=None) for x in ids],
           [dict(owner='backend', operation='merge', source='O(0)', target='O(1)'),
            dict(owner='backend', operation='merge', source='O(1)', target='O(2)')],
           []][step-1]
 # Third revision deliberately violates projected continuity.
 reply = dict(type='result', request_id=msg['request_id'], accepted=True,
  graph_summary=dict(schema_version=1, graph_revision=step, input_prefix_sha256=prefix.hex(),
                     nodes=[dict(native_id=x, layer_id=2) for x in ids]),
  native_metadata=dict(config_sha256='a'*64, source_sha256='b'*40,
                       build_sha256='c'*64, native_binding_sha256='c'*64, room_stability=None),
  object_event_journal=dict(input_prefix_sha256=prefix.hex(), native=dict(
   schema_version=1, status='complete', epoch=1, step=step,
   timestamp_ns=100+msg['frame_index'], events=events)))
 print(json.dumps(reply), flush=True)
'''


def test_synthetic_accepted_lifecycle_handoff_and_query_revocation(tmp_path):
    command = worker(tmp_path, WORKER)
    script = tmp_path / 'fake_worker.py'
    script.write_text(script.read_text().replace('"protocol":1', '"protocol":1,"config_sha256":"a"*64,"source_sha256":"b"*40'))
    journal = tmp_path / 'journal.jsonl'
    session = HydraSession('ep', command=command, journal_path=journal, object_event_journal=True)
    try:
        assert session.offer(frame(0)).status == 'queued'
        assert session.wait_for_revision(1, 3)
        first = session.current_read_token()
        first_view = session.object_lineage(first)
        identities = dict(first_view.objects)
        assert set(identities) == {'O(0)', 'O(1)', 'O(2)'}
        assert session.offer(frame(1)).status == 'queued'
        assert session.wait_for_revision(2, 3)
        native = session.current_read_token()
        batch = session.object_event_batch(native)
        view = session.object_lineage(native)
        assert [(e.source, e.target) for e in batch.events] == [('O(0)', 'O(1)'), ('O(1)', 'O(2)')]
        assert view.resolve(identities['O(0)']) == view.resolve(identities['O(1)']) == identities['O(2)']
        assert session.object_lineage(first) is None
        # Explicit fixture adapter: query has native refs, not a canonical-ID API.
        _, _, template = inputs()
        token = replace(template, native=native)
        ref = NativeNodeRef(native, view.resolve(identities['O(0)']).native_id, 2)
        spec = FeatureSpec('object', '1'*64, '2'*64, 2, 'object')
        room_spec = FeatureSpec('room', '1'*64, '2'*64, 2, 'room')
        current = lambda value: session.current_read_token() == value and session.object_lineage(value) is not None
        relations = RelationStore(token, {ref}, current)
        query = RevisionQuery(token, ObjectFeatureView(token, spec, (ObjectFeature(ref, (1., 0.), 1),)),
                              RoomFeatureView(token, room_spec, (), 0), relations, current)
        assert query.objects(token, [1, 0], spec).items[0].ref == ref
        assert query.retrieve_subgraph(token, [ref], max_nodes=1, max_edges=0).nodes == (ref,)
        assert session.offer(frame(2)).status == 'queued'
        assert session.wait_for_revision(3, 3)
        assert session.object_lineage(session.current_read_token()) is None
        with pytest.raises(ValueError, match='stale'):
            query.objects(token, [1, 0], spec)
    finally:
        assert session.close(3)['complete']
    accepted = [row for row in map(json.loads, journal.read_text().splitlines()) if row.get('event') == 'accepted']
    assert len(accepted) == 3
    assert all('object_event_journal' in row for row in accepted)
