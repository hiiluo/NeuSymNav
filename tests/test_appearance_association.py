"""Owner appearance regressions; fixtures exercise real SQLite and projection."""
from dataclasses import replace
import json
import numpy as np
import pytest
from test_projection import scene, batch
from test_object_identity import owner, commit
from neusymnav.contracts.observations import AppearanceBatch, AppearanceFeature
from neusymnav.perception.projector import Projector


def feature(vector, space='space:v1'):
    return AppearanceFeature(space, np.array(vector, dtype=float))


def attach(o, source, vector, detection='0', space='space:v1'):
    return o.attach_appearance(AppearanceBatch(source.key, source.geometry_hash,
        {detection: feature(vector, space)}))


def inline(o, source, vector, kind='detected'):
    b=batch(source)
    observations=tuple(replace(p, appearance=feature(vector), evidence_kind=kind)
        for p in Projector(min_points=1).project(source,b))
    return o.commit(source,b,observations)


def vector(o):
    return next(iter(o.snapshot().objects.values())).appearance.vector


def test_unique_detected_votes_are_normalized_aggregated_and_recovered(tmp_path):
    with owner(tmp_path) as o:
        inline(o,scene(),[3,0]); inline(o,scene(1),[0,4])
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
        assert attach(o,scene(1),[0,4]).committed_event_ids==()
        inline(o,scene(2),[0,1],kind='tracked')
        inline(o,scene(3),[0,1],kind='refined')
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
    with owner(tmp_path) as o:
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
        assert attach(o,scene(),[3,0]).committed_event_ids==()


def test_async_aggregate_updates_future_identity_scoring(tmp_path):
    with owner(tmp_path,appearance_mode='openclip') as o:
        source=scene(); b=batch(source,((12,12,20,20),(12,12,20,20)))
        first=commit(o,source,b); ids=list(first.snapshot.objects)
        o.attach_appearance(AppearanceBatch(source.key,source.geometry_hash,
            {'0':feature([1,0]),'1':feature([0,1])}))
        result=inline(o,scene(1),[1,0])
        assert len(result.snapshot.objects)==2
        view=o.ledger.committed_views(result.committed_event_ids)[0]
        assert view['object_id']==ids[0]
        with pytest.raises(ValueError,match='simultaneous'):
            o.merge(*ids)


def test_missing_features_preserve_geometry_ambiguity_in_both_profiles(tmp_path):
    for mode in ('off','openclip'):
        with owner(tmp_path/mode,appearance_mode=mode) as o:
            source=scene(); commit(o,source,batch(source,((12,12,20,20),(12,12,20,20))))
            result=commit(o,scene(1))
            assert len(result.snapshot.objects)==2
            assert o.ledger.committed_views(result.committed_event_ids)[0]['object_id'] is None
            attach(o,scene(1),[1,0])
            assert all(obj.appearance is None for obj in o.snapshot().objects.values())


def test_async_rollback_keeps_engine_snapshot_and_spec_unchanged(tmp_path):
    with owner(tmp_path) as o:
        commit(o,scene()); revision=o.snapshot().revision
        o.ledger.connection.execute("CREATE TRIGGER fail_feature BEFORE INSERT ON appearances BEGIN SELECT RAISE(ABORT,'injected'); END")
        with pytest.raises(Exception,match='injected'): attach(o,scene(),[1,0])
        assert o.snapshot().revision==revision
        assert o.ledger.get('appearance_spec') is None
        assert next(iter(o._engine._tracks.values())).visual_embedding is None
        o.ledger.connection.execute('DROP TRIGGER fail_feature')
        attach(o,scene(),[1,0]); commit(o,scene(1)); attach(o,scene(1),[0,1])
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])


def test_profile_is_pinned_and_legacy_off_ledger_keeps_all_evidence(tmp_path):
    with owner(tmp_path) as o:
        inline(o,scene(),[1,0]); config=o.ledger.get('config')
        checkpoint=json.loads(o.ledger.get('checkpoint'))
        for state in checkpoint['engine'].values(): state.pop('visual_weight',None)
        o.ledger.set('checkpoint',json.dumps(checkpoint))
        o.ledger.connection.execute("DELETE FROM metadata WHERE key='appearance_profile'")
    with pytest.raises(ValueError,match='appearance.*profile'):
        owner(tmp_path,appearance_mode='openclip')
    with owner(tmp_path) as o:
        assert o.ledger.get('config')==config
        assert len(o.ledger.committed_views())==len(o.ledger.appearance_records())==1
        inline(o,scene(1),[0,1])
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
    with pytest.raises(ValueError,match='appearance.*profile'):
        owner(tmp_path,appearance_mode='openclip')


def test_alias_retargeted_historical_attachment_weights_survivor(tmp_path):
    with owner(tmp_path) as o:
        a=scene(); first=inline(o,a,[1,0]); aid=next(iter(first.snapshot.objects))
        b=scene(1,shift=3); second=commit(o,b); bid=next(k for k in second.snapshot.objects if k!=aid)
        o.merge(aid,bid); attach(o,b,[0,1])
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
        assert {r['object_id'] for r in o.ledger.appearance_records()}=={o.resolve_id(aid)}
    with owner(tmp_path) as o: np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])


def test_feature_space_hash_and_dimension_rejections_precede_mutation(tmp_path):
    with owner(tmp_path) as o:
        inline(o,scene(),[1,0]); commit(o,scene(1)); revision=o.snapshot().revision
        for vector_,space in (([1,0],'other'),([1,0,0],'space:v1')):
            with pytest.raises(ValueError,match='space/dimension'):
                attach(o,scene(1),vector_,space=space)
        for source,hash_ in ((scene(2).key,scene(1).geometry_hash),(scene(1).key,'f'*64)):
            with pytest.raises(ValueError,match='committed'):
                o.attach_appearance(AppearanceBatch(source,hash_,{'0':feature([1,0])}))
        assert o.snapshot().revision==revision
        assert len(o.ledger.appearance_records())==1


def test_cancelled_aggregate_is_unavailable_and_later_vote_recovers(tmp_path):
    with owner(tmp_path,appearance_mode='openclip') as o:
        inline(o,scene(),[1,0]); inline(o,scene(1),[-1,0])
        assert next(iter(o.snapshot().objects.values())).appearance is None
    with owner(tmp_path,appearance_mode='openclip') as o:
        inline(o,scene(2),[0,1])
        np.testing.assert_allclose(vector(o),[0,1])
        assert next(iter(o._engine._tracks.values())).visual_weight==3


def test_merge_uses_event_counts_instead_of_equal_object_weights(tmp_path):
    with owner(tmp_path) as o:
        a=inline(o,scene(),[1,0]); aid=next(iter(a.snapshot.objects))
        inline(o,scene(1),[1,0]); inline(o,scene(2),[1,0])
        b=inline(o,scene(3,shift=3),[0,1]); bid=next(k for k in b.snapshot.objects if k!=aid)
        o.merge(aid,bid)
        np.testing.assert_allclose(vector(o),[3/10**.5,1/10**.5])
        assert next(iter(o._engine._tracks.values())).visual_weight==4


def test_more_than_twenty_votes_use_source_event_count_without_saturation(tmp_path):
    with owner(tmp_path) as o:
        for i in range(25): inline(o,scene(i,stamp=1_000_000_000+i),[1,0])
        inline(o,scene(25,stamp=1_000_000_025),[0,1])
        np.testing.assert_allclose(vector(o),[25/626**.5,1/626**.5])
        assert next(iter(o._engine._tracks.values())).visual_weight==26


def test_profile_restart_cannot_switch_and_no_feature_label_terms(tmp_path):
    with owner(tmp_path,appearance_mode='openclip') as o: commit(o,scene())
    with pytest.raises(ValueError,match='appearance profile'):
        owner(tmp_path,appearance_mode='off')
    with owner(tmp_path,appearance_mode='openclip') as o:
        b=batch(scene(1)); changed=replace(b,detections=tuple(replace(d,raw_label='desk',category='desk') for d in b.detections))
        assert len(commit(o,scene(1),changed).snapshot.objects)==1


def test_inline_incompatible_space_does_not_commit_batch_or_identity(tmp_path):
    with owner(tmp_path) as o:
        inline(o,scene(),[1,0]); revision=o.snapshot().revision
        source=scene(1,shift=3); b=batch(source)
        observations=tuple(replace(p,appearance=feature([1,0],'wrong'))
            for p in Projector(min_points=1).project(source,b))
        with pytest.raises(ValueError,match='space/dimension'): o.commit(source,b,observations)
        assert o.snapshot().revision==revision and len(o.snapshot().objects)==1
        assert len(o.ledger.batch_records())==1


def test_feature_score_is_source_weight_subset_and_hard_gates_remain():
    from neusymnav.objects.association import AssociationEngine,AssociationObservation,_ScoreGeometry
    points=np.array([[x,y,z] for x in (-.03,.03) for y in (-.03,.03) for z in (.97,1.03)])
    def obs(frame=0,vector_=None,**kw):
        return AssociationObservation('e',frame,'0',kw.get('floor','f'),'detected',kw.get('label','chair'),.9,
            points+np.array([kw.get('shift',0),0,0]),(0,0,0),visual_embedding=vector_)
    engine=AssociationEngine('e',association_mode='geometry_appearance')
    object_id=engine.ingest((obs(vector_=np.array([1.,0.])),),now_s=1).object_ids[0]
    track=engine._tracks[object_id]; shape=_ScoreGeometry.from_points(track.points_world)
    # Exact identical cube geometry: overlap=geometry=bboxIoU=1.
    for embedding,want in ((None,1.),(np.array([0.,1.]),.75),(np.array([1.,0.]),1.)):
        item=obs(1,embedding,label='unrelated')
        assert engine._score(item,track,None,_ScoreGeometry.from_points(item.points_world),shape)==pytest.approx(want)
    for item,wall in ((obs(1,np.array([1.,0.]),floor='other'),None),
                      (obs(1,np.array([1.,0.]),shift=2),None),
                      (obs(1,np.array([1.,0.])),lambda a,b:True)):
        assert engine._score(item,track,wall,_ScoreGeometry.from_points(item.points_world),shape) is None


def test_recovery_rejects_checkpoint_feature_dimension_drift(tmp_path):
    with owner(tmp_path) as o:
        inline(o,scene(),[1,0]); saved=json.loads(o.ledger.get('checkpoint'))
        next(iter(saved['engine'].values()))['visual_embedding']=[1.,0.,0.]
        o.ledger.set('checkpoint',json.dumps(saved))
    with pytest.raises(ValueError,match='space/dimension'): owner(tmp_path)


def test_aggregate_and_visual_geometry_scores_match_independent_source_ast_oracle():
    from pathlib import Path
    from neusymnav.objects.appearance import fuse_visual
    from neusymnav.objects.association import AssociationEngine,AssociationObservation,_ScoreGeometry
    fixture=json.loads((Path(__file__).parent/'fixtures/regressions/appearance-parity-oracle.json').read_text())
    np.testing.assert_allclose(fixture['near_cancel_source_output'],[0.,.75])
    value=None; count=0
    for item,want in zip(fixture['aggregation_inputs'],fixture['aggregation_outputs']):
        value,count=fuse_visual(value,count,np.array(item),1)
        np.testing.assert_allclose(value,want,atol=1e-14)
    points=np.array([[x,y,z] for x in (-.03,.03) for y in (-.03,.03) for z in (.97,1.03)])
    engine=AssociationEngine('e',association_mode='geometry_appearance')
    first=AssociationObservation('e',0,'0','f','detected','chair',.9,points,(0,0,0),visual_embedding=np.array([1.,0.]))
    object_id=engine.ingest((first,),now_s=1).object_ids[0]; track=engine._tracks[object_id]
    for case in fixture['score_cases']:
        obs=AssociationObservation('e',1,'0','f','detected','unrelated',.9,
            points+np.array([case['shift'],0,0]),(0,0,0),visual_embedding=case['visual'])
        actual=engine._score(obs,track,None,_ScoreGeometry.from_points(obs.points_world),_ScoreGeometry.from_points(track.points_world))
        if case['geometry_appearance'] is None: assert actual is None
        else: assert actual==pytest.approx(case['geometry_appearance'],abs=1e-12)


@pytest.mark.parametrize('epsilon,available',[(1.5e-12,False),(4e-12,True)])
def test_near_cancellation_guard_uses_average_source_normalization_scale(epsilon,available):
    from neusymnav.objects.appearance import fuse_visual
    value,count=fuse_visual(np.array([1.,0.]),1,np.array([-1.,epsilon]),1)
    assert count==2
    if available: np.testing.assert_allclose(value,[0,1])
    else: assert value is None


def test_large_finite_feature_vectors_normalize_without_corrupt_checkpoint(tmp_path):
    with owner(tmp_path) as o:
        inline(o,scene(),[1e300,0]); commit(o,scene(1)); attach(o,scene(1),[0,1e300])
        np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
    with owner(tmp_path) as o: np.testing.assert_allclose(vector(o),[2**-.5,2**-.5])
