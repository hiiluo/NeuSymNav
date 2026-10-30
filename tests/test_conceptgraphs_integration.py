import json
from pathlib import Path

import pytest

from test_object_identity import owner, commit
from test_projection import scene
from neusymnav.objects.association_recipe import AssociationRecipe
from neusymnav.runtime.configuration import load_config


CG = AssociationRecipe(mode='conceptgraphs')


def test_owner_recipe_restart_and_mismatch(tmp_path):
    with owner(tmp_path, association_recipe=CG) as o:
        first = commit(o, scene())
        assert json.loads(o.ledger.get('association_recipe')) == CG.durable_dict()
        assert json.loads(o.ledger.get('appearance_profile'))['scoring'] == 'conceptgraphs-directional-cosine:v1'
        assert o._engine.association_recipe == CG
    with owner(tmp_path, association_recipe=CG) as o:
        assert commit(o, scene()).committed_event_ids == ()
        assert o.snapshot().revision == first.snapshot.revision
    for recipe in (AssociationRecipe(), AssociationRecipe(mode='conceptgraphs', nn_distance_m=.04)):
        with pytest.raises(ValueError, match='association recipe mismatch'):
            owner(tmp_path, association_recipe=recipe)


def test_legacy_unpinned_ledger_remains_compatible(tmp_path):
    with owner(tmp_path) as o:
        commit(o, scene())
        o.ledger.connection.execute("DELETE FROM metadata WHERE key='association_recipe'")
    with pytest.raises(ValueError, match='association recipe mismatch'):
        owner(tmp_path, association_recipe=CG)
    with owner(tmp_path) as o:
        assert len(o.snapshot().objects) == 1


def test_batch_diagnostics_online_endpoints_survive_merge(tmp_path):
    with owner(tmp_path, association_recipe=CG) as o:
        commit(o, scene())
        commit(o, scene(1, shift=3.))
        records = o.ledger.batch_records()
        original = [r['association']['online_object_ids'] for r in records]
        ids = list(o.snapshot().objects)
        assert len(ids) == 2
        assert all(r['association']['diagnostics']['new_ids'] == 1 for r in records)
        o.merge(*ids)
        assert [r['association']['online_object_ids'] for r in o.ledger.batch_records()] == original
        assert len({r['object_id'] for r in o.ledger.committed_views()}) == 1


def test_config_accepts_explicit_recipe_and_rejects_invalid(tmp_path):
    base = json.loads(Path('configs/p10/demo-yoloe26m-640x480-long-gpu-00861.json').read_text())
    path = tmp_path/'profile.json'
    base['association'] = {'mode': 'conceptgraphs'}
    path.write_text(json.dumps(base))
    assert load_config(path).data['association'] == {'mode': 'conceptgraphs'}
    base['association']['nn_distance_m'] = -1
    path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match='association'):
        load_config(path)
    base['association'] = None
    path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match='association'):
        load_config(path)


def test_failed_commit_does_not_publish_diagnostics_or_state(tmp_path):
    with owner(tmp_path, association_recipe=CG) as o:
        commit(o, scene())
        before = o.snapshot()
        o.ledger.connection.execute("CREATE TRIGGER fail_batch BEFORE INSERT ON batches BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with pytest.raises(Exception, match='injected'):
            commit(o, scene(1))
        assert o.snapshot() is before
        assert len(o.ledger.batch_records()) == 1


def test_launcher_replay_forwards_recipe_to_durable_owner(tmp_path):
    import sqlite3
    from neusymnav.runtime.launcher import replay
    fixture = Path(__file__).parent/'fixtures'/'launcher'
    value = json.loads((fixture/'config.yaml').read_text())
    value['association'] = {'mode': 'conceptgraphs'}
    value['fixture']['detections']['path'] = str((fixture/'batches.json').resolve())
    profile = tmp_path/'config.json'
    profile.write_text(json.dumps(value))
    out = tmp_path/'output'
    result = replay(fixture/'recording', profile, out=out)
    assert result['outcome'] == 'completed', result
    with sqlite3.connect(out/'objects'/'objects.sqlite3') as conn:
        stored = conn.execute("SELECT value FROM metadata WHERE key='association_recipe'").fetchone()[0]
        assert json.loads(stored)['mode'] == 'conceptgraphs'
        data = json.loads(conn.execute('SELECT data FROM batches').fetchone()[0])
        assert data['association']['diagnostics']['recipe_id'] == CG.durable_dict()['recipe_id']
