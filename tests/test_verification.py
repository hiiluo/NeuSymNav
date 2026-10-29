from dataclasses import replace
import pytest
from test_projection import scene, batch
from test_object_identity import owner, commit
from neusymnav.verification import VerificationOwner


def verifier(o, clock=None, **kw):
    return VerificationOwner(o, clock_domain='host:boot1',
        now_ns=(lambda: 2_000_000_000) if clock is None else lambda: clock[0], **kw)


def test_committed_unique_detected_views_only(tmp_path):
    o=owner(tmp_path); v=verifier(o)
    result=commit(o,scene()); v.consume(result); v.consume(result)
    oid=next(iter(result.snapshot.objects)); state=v.snapshot().objects[oid]
    assert (state.detected_count,state.independent_views,state.status)==(1,1,'candidate')
    best=v.best_views(oid)[0]
    assert best.quality==pytest.approx(.9)
    assert best.crop_ref and best.event_id in result.committed_event_ids
    assert best.source.frame_index==0 and best.clock_domain=='host:boot1'
    assert state.graph_lifecycle=='candidate'
    v.close(); o.close()


def test_tracking_and_refinement_never_add_detector_votes(tmp_path):
    from neusymnav.perception.projector import Projector
    o=owner(tmp_path); v=verifier(o)
    for i,kind in enumerate(('detected','tracked','refined','detected')):
        source=scene(i); b=batch(source)
        projected=tuple(replace(p,evidence_kind=kind) for p in Projector(min_points=1).project(source,b))
        v.consume(o.commit(source,b,projected))
    s=next(iter(v.snapshot().objects.values()))
    assert (s.detected_count,s.independent_views,s.status)==(2,1,'tracked')
    assert v.snapshot().view_count==4
    v.close(); o.close()


def test_complete_empty_batch_delivers_negatives_and_expires_at_snapshot(tmp_path):
    clock=[2_000_000_000]; o=owner(tmp_path); v=verifier(o,clock)
    v.consume(commit(o,scene()))
    source=scene(10,depth=3.); empty=commit(o,source,batch(source,()))
    v.consume(empty); v.consume(empty)
    snapshot=v.snapshot(); s=next(iter(snapshot.objects.values()))
    assert snapshot.complete_empty_batch_count==1 and snapshot.batch_count==2
    assert (s.detected_count,s.negative_views,s.negative_history_count)==(1,1,1)
    clock[0]=2_750_000_000
    assert next(iter(v.snapshot().objects.values())).negative_views==1
    clock[0]=2_750_000_001
    s=next(iter(v.snapshot().objects.values()))
    assert s.negative_views==0 and s.negative_history_count==1
    v.close(); o.close()


@pytest.mark.parametrize('completion,saturated', [('partial',False),('failed',False),('unknown',False),('complete',True)])
def test_noncomplete_and_saturated_cannot_create_negatives(tmp_path,completion,saturated):
    o=owner(tmp_path); v=verifier(o); v.consume(commit(o,scene()))
    source=scene(10,depth=3.)
    v.consume(commit(o,source,batch(source,(),completion=completion,cap_reached=saturated)))
    s=next(iter(v.snapshot().objects.values()))
    assert s.negative_views==s.negative_history_count==0
    assert v.snapshot().batch_count==2
    v.close(); o.close()


@pytest.mark.parametrize('variant',['occluded','invalid','touching'])
def test_occluded_invalid_or_mask_touching_no_negatives(tmp_path,variant):
    import numpy as np
    o=owner(tmp_path); v=verifier(o); v.consume(commit(o,scene()))
    source=scene(10,depth=2. if variant=='occluded' else 3.)
    if variant=='invalid':
        valid=source.valid_depth.copy(); valid[15,15]=False
        source=replace(source,valid_depth=valid)
    b=batch(source,((12,12,13,13),) if variant=='touching' else ())
    v.consume(commit(o,source,b))
    assert next(iter(v.snapshot().objects.values())).negative_history_count==0
    v.close(); o.close()


def test_consumer_rechecks_time_after_slow_disk(tmp_path,monkeypatch):
    clock=[2_000_000_000]; o=owner(tmp_path); v=verifier(o,clock)
    v.consume(commit(o,scene()))
    source=scene(10,depth=3.); result=commit(o,source,batch(source,()))
    assert len(o.ledger.negative_records())==1
    read=o.assets.read
    def slow_read(ref):
        clock[0]=2_750_000_001
        return read(ref)
    monkeypatch.setattr(o.assets,'read',slow_read)
    v.consume(result)
    s=next(iter(v.snapshot().objects.values()))
    assert s.negative_history_count==1 and s.accepted_negative_history_count==s.negative_views==0
    assert v.snapshot().rejection_reasons['historical_or_expired']==1
    v.close(); o.close()


@pytest.mark.parametrize('clock_ns,domain',[(1_999_999_999,'host:boot1'),(2_000_000_000,'host:boot2'),(2_000_000_000,'replay:run')])
def test_consumer_future_domain_and_replay_suppress_negatives(tmp_path,clock_ns,domain):
    o=owner(tmp_path); v=VerificationOwner(o,clock_domain=domain,now_ns=lambda:clock_ns)
    v.consume(commit(o,scene()))
    source=scene(10,depth=3.); v.consume(commit(o,source,batch(source,())))
    s=next(iter(v.snapshot().objects.values()))
    assert s.negative_views==s.accepted_negative_history_count==0
    assert s.negative_history_count==1
    v.close(); o.close()


def test_explicit_replay_recovers_missing_positives_but_never_revives_negatives(tmp_path):
    o=owner(tmp_path); first=commit(o,scene())
    source=scene(10,depth=3.); commit(o,source,batch(source,()))
    v=verifier(o)
    assert v.snapshot().replay_required
    v.replay(); v.replay()
    s=next(iter(v.snapshot().objects.values()))
    assert s.detected_count==1 and s.negative_history_count==1 and s.negative_views==0
    assert not v.snapshot().replay_required
    v.close(); o.close()
    o=owner(tmp_path); v=verifier(o); v.replay(); v.consume(first)
    s=next(iter(v.snapshot().objects.values()))
    assert s.detected_count==1 and s.negative_views==0
    v.close(); o.close()


def test_alias_retargets_counts_selection_and_best_views(tmp_path):
    o=owner(tmp_path); v=verifier(o)
    a=commit(o,scene()); v.consume(a); aid=next(iter(a.snapshot.objects))
    b=commit(o,scene(1,shift=3.)); v.consume(b); bid=next(k for k in b.snapshot.objects if k!=aid)
    merged=o.merge(aid,bid); v.consume(merged)
    oid=v.resolve_id(bid); snapshot=v.snapshot()
    assert len(snapshot.objects)==1 and snapshot.objects[oid].detected_count==2
    assert {view.object_id for view in v.best_views(aid)}=={oid}
    assert len(v.best_views(bid))==2
    v.close(); o.close()
    o=owner(tmp_path); v=verifier(o); v.replay()
    assert next(iter(v.snapshot().objects.values())).detected_count==2
    v.close(); o.close()


def test_negative_stale_object_revision_kept_only_as_history(tmp_path):
    o=owner(tmp_path); v=verifier(o); v.consume(commit(o,scene()))
    source=scene(10,depth=3.); negative=commit(o,source,batch(source,()))
    # Delay verification until a newer object geometry has been committed.
    newer=commit(o,scene(11,stamp=2_000_000_000)); v.consume(newer); v.consume(negative)
    s=next(iter(v.snapshot().objects.values()))
    assert s.negative_views==s.accepted_negative_history_count==0
    assert v.snapshot().rejection_reasons['stale_object_revision']==1
    v.close(); o.close()


def test_verifier_response_after_revision_or_alias_is_rejected(tmp_path):
    from neusymnav.verification import VerifierResult
    o=owner(tmp_path); v=verifier(o)
    first=commit(o,scene()); v.consume(first); oid=next(iter(first.snapshot.objects))
    request=v.request(oid)
    v.consume(commit(o,scene(1)))
    with pytest.raises(ValueError,match='stale|pending'):
        v.apply_result(VerifierResult(request.id,'episode',oid,request.source_revision,'confirmed'))
    request=v.request(oid)
    other=commit(o,scene(2,shift=3.)); v.consume(other)
    bid=next(k for k in other.snapshot.objects if k!=oid)
    v.consume(o.merge(oid,bid))
    with pytest.raises(ValueError,match='stale|pending|retired'):
        v.apply_result(VerifierResult(request.id,'episode',oid,request.source_revision,'confirmed'))
    v.close(); o.close()


def test_verification_failure_does_not_rollback_accepted_objects_and_replay_is_explicit(tmp_path,monkeypatch):
    o=owner(tmp_path); v=verifier(o); result=commit(o,scene())
    read=o.assets.read
    def broken_disk(ref):
        raise OSError('verification read failed')
    monkeypatch.setattr(o.assets,'read',broken_disk)
    with pytest.raises(OSError,match='verification read failed'):
        v.consume(result)
    assert len(o.snapshot().objects)==1 and len(o.ledger.committed_views())==1
    s=v.snapshot()
    assert s.replay_required and s.batch_count==0 and s.view_count==0
    monkeypatch.setattr(o.assets,'read',read)
    v.replay(); v.consume(result)
    assert not v.snapshot().replay_required and v.snapshot().view_count==1
    v.close(); o.close()


def test_quality_is_source_mask_occupancy_and_measured_depth_fraction(tmp_path):
    import json
    from pathlib import Path
    import numpy as np
    from neusymnav.contracts.observations import Detection,DetectionBatch
    o=owner(tmp_path); v=verifier(o)
    source=scene(); valid=source.valid_depth.copy(); valid[12:16,12:20]=False
    source=replace(source,valid_depth=valid)
    # Half-box mask: rows12..19, cols12..19, two holes in right half.
    mask=np.zeros((32,32),bool); mask[12:20,12:20]=True; mask[14:16,18:20]=False
    detection=Detection('0','chair','chair',.8,mask)
    b=DetectionBatch.from_observation(source,(detection,),vocabulary_id='v1')
    v.consume(commit(o,source,b))
    view=v.best_views()[0]
    assert view.mask_quality==pytest.approx(60/64)
    assert view.depth_quality==pytest.approx(32/60)
    assert view.quality==pytest.approx(.4)
    expected=json.loads((Path(__file__).parent/'fixtures/verification/source-oracle-v1.json').read_text())['quality']
    for key,value in expected.items():
        assert getattr(view,key)==pytest.approx(value)
    v.close(); o.close()


def test_gallery_pairwise_baseline_and_bounded_memory_regression():
    import math
    from neusymnav.verification import BestView,BestViewSelector
    from neusymnav.contracts.observations import FrameKey
    def view(i,x,q):
        return BestView('object',str(i),FrameKey('episode','rgbd',i),'0',i,'clock',
            'a'*64,1,(x,0.,0.),q,q,1.,1.,'b'*64,'c'*64,'d'*64,(0,0,1,1))
    gallery=BestViewSelector('object')
    gallery.offer(view(0,0.,.5)); gallery.offer(view(1,.5,.8))
    assert len(gallery.offer(view(2,.25,.6)))==2  # Stronger second neighbor survives.
    best=gallery.offer(view(3,.25,.9))
    assert len(best)==1 and best[0].event_id=='3'
    for i in range(4,1004):
        best=gallery.offer(view(i,float(i),.7))
    assert len(best)==3
    assert all(math.dist(a.camera_position_world,b.camera_position_world)>=.3
        for i,a in enumerate(best) for b in best[i+1:])
    assert len(vars(gallery))==2  # no history-sized event cache in this standalone selector


def test_restart_and_explicit_replay_never_reissue_previously_current_negative(tmp_path):
    o=owner(tmp_path); v=verifier(o); v.consume(commit(o,scene()))
    source=scene(10,depth=3.); result=commit(o,source,batch(source,())); v.consume(result)
    assert next(iter(v.snapshot().objects.values())).negative_views==1
    v.close()
    # Same boot/time does not make restored history a new live proof.
    v=verifier(o); v.replay(); v.consume(result)
    s=next(iter(v.snapshot().objects.values()))
    assert s.negative_views==0 and s.accepted_negative_history_count==1
    v.close(); o.close()


def test_verification_and_gallery_match_pinned_source_oracles(tmp_path):
    import json
    from pathlib import Path
    from neusymnav.perception.projector import Projector
    from neusymnav.verification import BestView,BestViewSelector
    fixture=json.loads((Path(__file__).parent/'fixtures/verification/source-oracle-v1.json').read_text())
    o=owner(tmp_path); v=verifier(o)
    for case,expected in zip(fixture['verification_trace'],fixture['verification_outputs']):
        source=scene(case['frame'],shift=case['x']); offset=round(20*case['x'])
        b=batch(source,((12-offset,12,20-offset,20),))
        projected=tuple(replace(p,evidence_kind=case['kind']) for p in Projector(min_points=1).project(source,b))
        v.consume(o.commit(source,b,projected))
        assert len(v.snapshot().objects)==1
        state=next(iter(v.snapshot().objects.values()))
        for name,value in expected.items():
            actual=getattr(state,name)
            assert actual==pytest.approx(value) if isinstance(value,float) else actual==value
    # Source qualification remains distinct from object association lifecycle.
    assert state.status=='verified' and state.graph_lifecycle=='active'
    assert state.independent_views==3 and state.detected_count==5
    v.close(); o.close()
    gallery=BestViewSelector('object')
    for frame,x,q in fixture['gallery_trace']:
        gallery.offer(BestView('object',str(frame),__import__('neusymnav.contracts.observations',fromlist=['FrameKey']).FrameKey(
            'episode','rgbd',frame),'0',frame,'clock','a'*64,1,(x,0.,0.),q,q,1.,1.,'b'*64,'c'*64,'d'*64,(0,0,1,1)))
    assert [view.source.frame_index for view in gallery.snapshot()]==fixture['gallery_frames']


def test_process_death_in_verification_preserves_object_commit_and_replays_once(tmp_path):
    import signal
    import subprocess
    import sys
    from neusymnav.contracts.serialization import dumps
    if sys.platform!='linux':
        pytest.skip('Linux SIGXFSZ transaction-death injection')
    source=scene(); inputs=tmp_path/'inputs.jsonl'
    inputs.write_text(dumps(source)+'\n'+dumps(batch(source))+'\n')
    child='''
import resource,signal,sys
from pathlib import Path
from neusymnav.contracts.serialization import loads
from neusymnav.objects.store import ObjectOwner
from neusymnav.perception.projector import Projector
from neusymnav.verification import VerificationOwner
source,batch=[loads(line) for line in Path(sys.argv[2]).read_text().splitlines()]
o=ObjectOwner(sys.argv[1],episode_id='episode',primary_sensor_id='rgbd',floor_id='f0',
    detector_profile_id='fixture-v1',vocabulary_id='v1',clock_domain='host:boot1',now_ns=lambda:2_000_000_000)
result=o.commit(source,batch,Projector(min_points=1).project(source,batch))
v=VerificationOwner(o,clock_domain='host:boot1',now_ns=lambda:2_000_000_000)
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
resource.setrlimit(resource.RLIMIT_FSIZE,(1024,1024))
signal.signal(signal.SIGXFSZ,signal.SIG_DFL)
v.consume(result)
'''
    root=tmp_path/'ledger'
    result=subprocess.run([sys.executable,'-c',child,str(root),str(inputs)],capture_output=True,timeout=10)
    assert result.returncode==-signal.SIGXFSZ, result.stderr.decode()
    o=owner(root); assert len(o.snapshot().objects)==1
    v=verifier(o); v.replay(); v.replay()
    snapshot=v.snapshot()
    assert not snapshot.replay_required and snapshot.view_count==1 and snapshot.batch_count==1
    assert next(iter(snapshot.objects.values())).detected_count==1
    v.close(); o.close()


@pytest.mark.parametrize('variant',['clear','occluded','invalid','touching','incomplete','saturated'])
def test_negative_geometry_matches_pinned_source_oracle(tmp_path,variant):
    import json
    from pathlib import Path
    from neusymnav.objects.negative_evidence import negative_visibility
    expected=json.loads((Path(__file__).parent/'fixtures/verification/source-oracle-v1.json').read_text())['negative_cases'][variant]
    o=owner(tmp_path); first=commit(o,scene())
    source=scene(10,depth=2. if variant=='occluded' else 3.)
    if variant=='invalid':
        valid=source.valid_depth.copy(); valid[15,15]=False
        source=replace(source,valid_depth=valid)
    b=batch(source,((12,12,13,13),) if variant=='touching' else (),
        completion='partial' if variant=='incomplete' else 'complete',cap_reached=variant=='saturated')
    proofs=negative_visibility(source,b,first.snapshot,current=True)
    assert [dict(projected_bbox_xyxy=p['projected_bbox_xyxy'],object_revision=p['object_revision'],
        camera_position_world=p['camera_position']) for p in proofs]==expected
    o.close()


@pytest.mark.parametrize('decision',['timeout','failed'])
def test_async_failure_cooldown_is_durable_and_never_promotes(tmp_path,decision):
    from neusymnav.verification import VerifierResult
    clock=[2_000_000_000]; o=owner(tmp_path); v=verifier(o,clock)
    first=commit(o,scene()); v.consume(first); oid=next(iter(first.snapshot.objects))
    request=v.request(oid)
    assert request.source_revision==first.snapshot.objects[oid].revision
    state=v.apply_result(VerifierResult(request.id,'episode',oid,request.source_revision,decision))
    assert state.status=='unknown' and v.request(oid) is None
    v.close(); v=verifier(o,clock)
    assert v.snapshot().objects[oid].status=='unknown' and v.request(oid) is None
    clock[0]=request.deadline_ns+30_000_000_000
    retry=v.request(oid)
    assert retry is not None and retry.id!=request.id
    with pytest.raises(ValueError,match='pending'):
        v.apply_result(VerifierResult(request.id,'episode',oid,request.source_revision,'confirmed'))
    state=v.apply_result(VerifierResult(retry.id,'episode',oid,retry.source_revision,'confirmed','chair'))
    assert state.status!='verified' and state.detected_count==1
    v.close(); o.close()


def test_async_late_confirmation_expires_and_new_negative_invalidates_request(tmp_path):
    from neusymnav.verification import VerifierResult
    clock=[2_000_000_000]; o=owner(tmp_path); v=verifier(o,clock)
    first=commit(o,scene()); v.consume(first); oid=next(iter(first.snapshot.objects))
    request=v.request(oid); clock[0]=request.deadline_ns+1
    state=v.apply_result(VerifierResult(request.id,'episode',oid,request.source_revision,'confirmed'))
    assert state.status=='unknown'
    clock[0]+=30_000_000_000; request=v.request(oid)
    source=scene(10,stamp=2_000_000_000,depth=3.)
    negative=commit(o,source,batch(source,())); v.consume(negative)
    assert o.snapshot().objects[oid].revision==request.source_revision
    with pytest.raises(ValueError,match='pending|stale'):
        v.apply_result(VerifierResult(request.id,'episode',oid,request.source_revision,'confirmed'))
    v.close(); o.close()


def test_expire_marks_unknown_and_snapshot_keeps_immutable_revision_provenance(tmp_path):
    clock=[2_000_000_000]; o=owner(tmp_path); v=verifier(o,clock)
    result=commit(o,scene()); v.consume(result); oid=next(iter(result.snapshot.objects))
    original=v.snapshot(); request=v.request(oid)
    assert original.object_revision==result.snapshot.revision
    assert original.objects[oid].object_revision==result.snapshot.objects[oid].revision
    with pytest.raises(TypeError):
        original.objects[oid]=original.objects[oid]
    clock[0]=request.deadline_ns+1; v.expire()
    assert v.snapshot().objects[oid].status=='unknown'
    assert original.objects[oid].status=='candidate'
    v.close(); o.close()


def test_verification_has_one_writer_and_run_local_db_without_object_side_effects(tmp_path):
    import hashlib
    o=owner(tmp_path/'object'); result=commit(o,scene())
    # Check canonical DB/WAL bytes. SQLite readers legitimately update read-lock
    # metadata in -shm; that transient coordination is not an object-ledger write.
    paths=[p for p in (tmp_path/'object').glob('objects.sqlite3*') if p.suffix!='.sqlite3-shm']
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    root=tmp_path/'run'/'verification'; v=verifier(o,root=root); v.consume(result)
    with pytest.raises(BlockingIOError):
        verifier(o,root=root)
    assert (root/'verification.sqlite3').is_file()
    assert {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}==before
    v.close()
    with pytest.raises(ValueError,match='mismatch'):
        VerificationOwner(o,clock_domain='host:other-boot',root=root)
    v=verifier(o,root=root); assert not v.snapshot().replay_required
    v.close(); o.close()


@pytest.mark.parametrize('delay_at', ['positive_sql', 'history_sql', 'final_sql', 'gallery'])
def test_negative_credit_expires_after_snapshot_io(tmp_path, monkeypatch, delay_at):
    clock = [2_000_000_000]
    o = owner(tmp_path)
    v = verifier(o, clock)
    try:
        v.consume(commit(o, scene()))
        obs = scene(10, depth=3.)
        v.consume(commit(o, obs, batch(obs, ())))
        assert next(iter(v.snapshot().objects.values())).negative_views == 1
        if delay_at == 'gallery':
            original = v.best_views
            def slow_gallery(oid=None):
                result = original(oid)
                clock[0] = 2_750_000_001
                return result
            monkeypatch.setattr(v, 'best_views', slow_gallery)
        else:
            marker = {'positive_sql': 'coalesce(sum(independent)',
                      'history_sql': 'coalesce(sum(accepted)',
                      'final_sql': 'SELECT reason,count(*) FROM negatives WHERE accepted=0'}[delay_at]
            def trace(sql):
                if marker in sql:
                    clock[0] = 2_750_000_001
            v._db.set_trace_callback(trace)
        state = next(iter(v.snapshot().objects.values()))
        assert state.negative_views == 0
        assert state.negative_history_count == 1
    finally:
        v.close()
        o.close()


def test_negative_credit_rechecks_after_later_object_gallery(tmp_path, monkeypatch):
    clock = [2_000_000_000]
    o = owner(tmp_path)
    v = verifier(o, clock)
    try:
        first = commit(o, scene())
        oid = next(iter(first.snapshot.objects))
        v.consume(first)
        obs = scene(10, depth=3.)
        v.consume(commit(o, obs, batch(obs, ())))
        v.consume(commit(o, scene(11, shift=3., stamp=2_000_000_000)))
        assert len(v.snapshot().objects) == 2
        assert v.snapshot().objects[oid].negative_views == 1
        original = v.best_views
        seen = []
        def slow_later_gallery(object_id=None):
            result = original(object_id)
            seen.append(object_id)
            if len(seen) == 2:
                clock[0] = 2_750_000_001
            return result
        monkeypatch.setattr(v, 'best_views', slow_later_gallery)
        result = v.snapshot()
        assert seen[0] == oid
        assert result.objects[oid].negative_views == 0
        assert result.objects[oid].negative_history_count == 1
    finally:
        v.close()
        o.close()
