from dataclasses import replace
import numpy as np
import pytest
from test_projection import scene,batch
from test_object_identity import owner,commit


def test_empty_batch_has_durable_sources_and_no_duplicate(tmp_path):
    o=owner(tmp_path); obs=scene(); result=commit(o,obs,batch(obs,()))
    assert result.snapshot.revision==1 and len(result.committed_event_ids)==1
    record=o.ledger.batch_records()[0]
    assert record['completion']=='complete' and record['source_asset']
    assert record['batch_asset'] and o.assets.read(record['source_asset'])
    o.close(); o=owner(tmp_path)
    assert commit(o,obs,batch(obs,())).committed_event_ids==()
    assert len(o.ledger.batch_records())==1; o.close()


def test_failed_sql_transaction_does_not_publish_trial(tmp_path):
    o=owner(tmp_path); obs=scene()
    o.ledger.connection.execute("CREATE TRIGGER fail_commit BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(Exception,match='injected'): commit(o,obs)
    assert o.snapshot().revision==0 and not o.snapshot().objects
    assert o.ledger.batch_records()==()
    o.ledger.connection.execute('DROP TRIGGER fail_commit')
    assert len(commit(o,obs).snapshot.objects)==1; o.close()


def test_conflicting_repeat_rejected_and_single_owner(tmp_path):
    o=owner(tmp_path); obs=scene(); commit(o,obs)
    with pytest.raises(ValueError,match='conflicting'): commit(o,replace(obs,rgb=np.ones_like(obs.rgb)))
    with pytest.raises(RuntimeError,match='owner'): owner(tmp_path)
    o.close()


@pytest.mark.parametrize('completion,cap', [('partial',False),('complete',True),('failed',False)])
def test_incomplete_or_saturated_batch_cannot_vote_negative(tmp_path,completion,cap):
    o=owner(tmp_path); commit(o,scene())
    obs=scene(10,depth=3.)
    commit(o,obs,batch(obs,(),completion=completion,cap_reached=cap))
    assert o.ledger.negative_records()==(); o.close()


def test_negative_requires_measured_clear_depth_and_current_clock(tmp_path):
    o=owner(tmp_path); first=commit(o,scene())
    obs=scene(10,depth=3.); result=commit(o,obs,batch(obs,()))
    negatives=o.ledger.negative_records()
    assert len(negatives)==1
    assert negatives[0]['object_revision']==first.snapshot.revision
    assert negatives[0]['geometry_hash']==obs.geometry_hash
    # Older source is durable history and must never produce a current negative.
    old=scene(11,depth=3.,stamp=100)
    commit(o,old,batch(old,()))
    assert len(o.ledger.negative_records())==1
    o.close()


def test_recovery_detects_corrupt_asset_and_unknown_schema(tmp_path):
    o=owner(tmp_path); commit(o,scene())
    ref=o.ledger.batch_records()[0]['source_asset']; path=o.assets.path(ref); o.close()
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='checksum'): owner(tmp_path)


def test_masks_without_projectable_geometry_remain_durable_and_clock_is_pinned(tmp_path):
    o=owner(tmp_path); obs=scene(); obs=replace(obs,valid_depth=np.zeros_like(obs.valid_depth))
    result=commit(o,obs)
    assert not result.snapshot.objects
    refs=o.ledger.batch_records()[0]['detections']['0']
    assert o.assets.read(refs['mask_asset']) and o.assets.read(refs['crop_asset'])
    with pytest.raises(ValueError,match='clock'):
        wrong=replace(scene(1),clock_domain='different-host')
        commit(o,wrong)
    assert o.snapshot().revision==1; o.close()


def test_unknown_sqlite_schema_requires_migration(tmp_path):
    o=owner(tmp_path); o.ledger.connection.execute('PRAGMA user_version=99'); o.close()
    with pytest.raises(ValueError,match='migration'): owner(tmp_path)


def test_reopen_rejects_changed_profile_and_preserves_checkpoint(tmp_path):
    from neusymnav.objects.store import ObjectOwner
    o=owner(tmp_path); initial=commit(o,scene()); o.close()
    with pytest.raises(ValueError,match='configuration mismatch'):
        ObjectOwner(tmp_path,episode_id='episode',primary_sensor_id='rgbd',floor_id='f0',
            detector_profile_id='changed',vocabulary_id='v1',clock_domain='host:boot1')
    o=owner(tmp_path)
    assert o.snapshot().revision==initial.snapshot.revision; o.close()


def test_negative_suppressed_for_invalid_occluded_touching_and_replay(tmp_path):
    o=owner(tmp_path); commit(o,scene())
    source=scene(1,depth=3.,stamp=1_800_000_000)
    values=source.valid_depth.copy(); values[15,15]=False
    source=replace(source,valid_depth=values)
    commit(o,source,batch(source,()))
    source=scene(2,depth=2.,stamp=1_900_000_000); commit(o,source,batch(source,()))
    source=scene(3,depth=3.,stamp=2_000_000_000)
    commit(o,source,batch(source,((12,12,13,13),)))
    assert o.ledger.negative_records()==(); o.close()
    from neusymnav.objects.store import ObjectOwner
    o=ObjectOwner(tmp_path/'replay',episode_id='episode',primary_sensor_id='rgbd',floor_id='f0',
        detector_profile_id='fixture-v1',vocabulary_id='v1',clock_domain='replay:run1',
        now_ns=lambda:2_000_000_000)
    source=replace(scene(),clock_domain='replay:run1'); commit(o,source)
    source=replace(scene(10,depth=3.),clock_domain='replay:run1'); commit(o,source,batch(source,()))
    assert o.ledger.negative_records()==(); o.close()


def test_asset_reference_contains_exact_projected_payload(tmp_path):
    from neusymnav.contracts.serialization import loads
    from neusymnav.perception.projector import Projector
    o=owner(tmp_path); obs=scene(); b=batch(obs); projected=Projector(min_points=1).project(obs,b)
    result=o.commit(obs,b,projected)
    view=o.ledger.committed_views(result.committed_event_ids)[0]
    restored=loads(o.assets.read(view['observation_asset']).decode())
    np.testing.assert_array_equal(restored.points_world,projected[0].points_world)
    o.close()


def test_process_death_during_asset_write_allows_identical_frame_retry(tmp_path):
    import signal
    import subprocess
    import sys
    from neusymnav.contracts.serialization import dumps

    if sys.platform != 'linux':
        pytest.skip('Linux SIGXFSZ process-death injection')
    source=scene()
    inputs=tmp_path/'inputs.jsonl'
    inputs.write_text(dumps(source)+'\n'+dumps(batch(source))+'\n')
    root=tmp_path/'ledger'
    child='''
import resource, signal, sys
from pathlib import Path
from neusymnav.contracts.serialization import loads
from neusymnav.objects.store import ObjectOwner
from neusymnav.perception.projector import Projector
source, batch = [loads(line) for line in Path(sys.argv[2]).read_text().splitlines()]
owner = ObjectOwner(sys.argv[1], episode_id='episode', primary_sensor_id='rgbd',
    floor_id='f0', detector_profile_id='fixture-v1', vocabulary_id='v1',
    clock_domain='host:boot1', now_ns=lambda: 2_000_000_000)
projected = Projector(min_points=1).project(source, batch)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))
signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
owner.commit(source, batch, projected)
'''
    result=subprocess.run([sys.executable,'-c',child,str(root),str(inputs)],
        capture_output=True,timeout=10)
    assert result.returncode == -signal.SIGXFSZ, result.stderr.decode()
    with owner(root) as recovered:
        assert recovered.snapshot().revision == 0
        assert recovered.ledger.batch_records() == ()
        accepted=commit(recovered,source)
        assert len(accepted.snapshot.objects) == 1
        assert len(recovered.ledger.batch_records()) == 1
        assert commit(recovered,source).committed_event_ids == ()


def test_reused_asset_fences_directory_before_returning(tmp_path, monkeypatch):
    import os
    import stat
    from neusymnav.objects.assets import AssetStore

    store=AssetStore(tmp_path)
    payload=b'already complete, possibly published by an interrupted writer'
    ref=store.put(payload)
    barriers=[]
    real_fsync=os.fsync

    def record_barrier(fd):
        barriers.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(os,'fsync',record_barrier)
    assert store.put(payload) == ref
    assert True in barriers
