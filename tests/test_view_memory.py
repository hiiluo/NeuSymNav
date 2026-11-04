import numpy as np
import pytest
from neusymnav.contracts import FrameKey
from neusymnav.verification.view_memory import ViewEvidence, ViewMemory


def view(event, obj='a', pos=(0, 0, 0), frame=1, score=.5):
    pose = np.eye(4); pose[:3, 3] = pos
    return ViewEvidence(episode_id='ep', object_id=obj, event_id=event,
        source=FrameKey('ep', 'cam', frame), capture_monotonic_ns=frame,
        clock_domain='clock', object_revision=1, geometry_hash='a'*64,
        calibration_id='cal', feature_space_id=None, camera_pose_world=pose,
        K=np.eye(3), object_centroid_world=np.array([1., 1., 0.]),
        mask_fraction=.1, depth_support=.8, crop_ref='b'*64, mask_ref='c'*64,
        source_ref='d'*64, detector_score=score,
        quality_components={'mask_fraction': .1, 'depth_support': .8},
        quality_version='quality:v1')


def test_immutable_evidence_and_correlated_views():
    v = view('one'); m = ViewMemory('ep')
    assert m.offer(v)
    assert not m.offer(v)
    assert not m.offer(view('two', pos=(.01, 0, 0), frame=2))
    assert len(m.snapshot().views['a']) == 1
    with pytest.raises(ValueError): v.camera_pose_world.setflags(write=True)
    with pytest.raises(TypeError): v.quality_components['x'] = 1


def test_alias_replay_reset_and_global_bounds():
    events = [view(str(i), obj=str(i), frame=i+1) for i in range(30)]
    def replay():
        m = ViewMemory('ep', max_objects=4, max_bytes=10000)
        for item in events: m.offer(item)
        return m
    a, b = replay(), replay()
    assert list(a.snapshot().views) == list(b.snapshot().views)
    assert a.snapshot().charged_bytes <= 10000
    assert len(a.snapshot().views) <= 4
    ids = list(a.snapshot().views)
    a.remap({ids[0]: ids[1]})
    assert ids[0] not in a.snapshot().views
    a.reset('new')
    assert not a.snapshot().views
    with pytest.raises(ValueError): a.offer(events[0])


def test_invalid_geometry_rejected():
    with pytest.raises(ValueError): view('bad', pos=(1, 1, 0))


def test_real_owner_adapter_preserves_source_and_fails_closed(tmp_path):
    from test_object_identity import owner, commit
    from test_projection import scene
    from neusymnav.verification.view_memory import read_committed_views
    o=owner(tmp_path)
    try:
        source=scene(); result=commit(o, source)
        evidence=read_committed_views(o,result)
        assert len(evidence)==1
        item=evidence[0]
        assert item.source==source.key and item.geometry_hash==source.geometry_hash
        assert item.feature_space_id is None and item.depth_support>0
        assert item.object_id in result.snapshot.objects
        assert np.array_equal(item.camera_pose_world,source.T_world_camera)
        o.assets.path(item.mask_ref).write_bytes(b'corrupt')
        assert read_committed_views(o,result)==()
    finally:
        o.close()


def test_diverse_views_and_alias_merge_do_not_double_count():
    m=ViewMemory('ep')
    assert m.offer(view('a', obj='old', pos=(0,0,0), frame=1))
    assert m.offer(view('b', obj='new', pos=(2,0,0), frame=2))
    m.remap({'old':'new'})
    assert {v.event_id for v in m.snapshot().views['new']} == {'a','b'}
    assert not m.offer(view('a', obj='old', pos=(0,0,0), frame=1))
    with pytest.raises(ValueError): m.remap({'new':'old'})
    assert {v.event_id for v in m.snapshot().views['new']} == {'a','b'}


def test_long_stream_stays_bounded():
    m=ViewMemory('ep', max_objects=8, max_bytes=24000)
    for i in range(2000):
        m.offer(view(str(i), obj=str(i), frame=i+1))
        snapshot=m.snapshot()
        assert snapshot.charged_bytes <= 24000
        assert len(snapshot.views) <= 8
        assert len(snapshot.recent_trace) <= 32
    assert snapshot.eviction_counters


def test_replay_after_eviction_is_idempotent_and_same_frame_events_supported():
    m=ViewMemory('ep', max_objects=8, max_bytes=24000)
    events=[view(str(i), obj=str(i), frame=i+1) for i in range(2100)]
    for e in events: m.offer(e)
    before=m.snapshot()
    for e in events: assert not m.offer(e)
    after=m.snapshot()
    assert before.views==after.views
    assert before.evidence_revision==after.evidence_revision
    assert before.eviction_counters==after.eviction_counters
    assert before.recent_trace==after.recent_trace
    n=ViewMemory('ep')
    assert n.offer(view('a',obj='a',frame=1))
    assert n.offer(view('b',obj='b',frame=1))
    assert not n.offer(view('a',obj='a',frame=1))


def test_remap_is_idempotent_and_ignores_unrelated_aliases():
    m=ViewMemory('ep'); m.offer(view('a',obj='old'))
    aliases={f'unrelated{i}':f'target{i}' for i in range(2000)}
    aliases['old']='new'
    m.remap(aliases)
    before=m.snapshot(); m.remap(aliases); after=m.snapshot()
    assert before.evidence_revision==after.evidence_revision
    assert before.eviction_counters==after.eviction_counters
    assert before.views==after.views and before.aliases==after.aliases
    assert set(after.views)=={'new'} and after.aliases['old']=='new'


def test_adapter_reuses_source_and_batch_for_multi_detection(tmp_path):
    from test_object_identity import owner, commit
    from test_projection import scene, batch
    from neusymnav.verification.view_memory import read_committed_views
    o=owner(tmp_path)
    try:
        source=scene(); result=commit(o,source,batch(source,((2,2,8,8),(20,20,27,27))))
        read=o.assets.read; calls=[]
        def tracked(ref): calls.append(ref); return read(ref)
        o.assets.read=tracked
        evidence=read_committed_views(o,result)
        assert len(evidence)==2
        rows=[dict(o.ledger.connection.execute('SELECT data FROM views WHERE event_id=?',(v.event_id,)).fetchone()) for v in evidence]
        import json
        source_ref=json.loads(rows[0]['data'])['source_asset']; batch_ref=json.loads(rows[0]['data'])['batch_asset']
        assert calls.count(source_ref)==1 and calls.count(batch_ref)==1
    finally: o.close()


def test_adapter_rejects_wrong_domain_and_batch_mask(tmp_path):
    import json
    from test_object_identity import owner, commit
    from test_projection import scene
    from neusymnav.verification.view_memory import read_committed_views
    o=owner(tmp_path)
    try:
        result=commit(o,scene()); event=o.ledger.connection.execute('SELECT event_id FROM views').fetchone()[0]
        row=o.ledger.connection.execute('SELECT data FROM views WHERE event_id=?',(event,)).fetchone()
        data=json.loads(row['data']); data['clock_domain']='forged'
        o.ledger.connection.execute('UPDATE views SET data=? WHERE event_id=?',(json.dumps(data),event))
        assert read_committed_views(o,result)==()
        data['clock_domain']='host:boot1'
        data['batch_asset']=data['source_asset']
        o.ledger.connection.execute('UPDATE views SET data=? WHERE event_id=?',(json.dumps(data),event))
        assert read_committed_views(o,result)==()
    finally: o.close()
