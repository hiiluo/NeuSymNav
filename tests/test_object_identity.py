import numpy as np
import pytest
from test_projection import scene, batch


def owner(path,**kw):
    from neusymnav.objects.store import ObjectOwner
    return ObjectOwner(path,episode_id='episode',primary_sensor_id='rgbd',floor_id='f0',
        detector_profile_id='fixture-v1',vocabulary_id='v1',clock_domain='host:boot1',
        now_ns=lambda: 2_000_000_000,**kw)


def commit(o,obs,b=None):
    from neusymnav.perception.projector import Projector
    b=batch(obs) if b is None else b
    return o.commit(obs,b,Projector(min_points=1).project(obs,b))


def test_near_same_label_instances_are_distinct_and_cannot_merge(tmp_path):
    o=owner(tmp_path); obs=scene(); b=batch(obs,((10,12,14,20),(15,12,19,20)))
    result=commit(o,obs,b); ids=list(result.snapshot.objects)
    assert len(ids)==2
    with pytest.raises(ValueError,match='simultaneous'): o.merge(*ids)
    assert len(o.snapshot().objects)==2
    o.close()


def test_repeat_restart_and_monotonic_last_seen(tmp_path):
    o=owner(tmp_path); obs=scene(2); first=commit(o,obs)
    id_=next(iter(first.snapshot.objects)); refs=first.snapshot.objects[id_].evidence_refs
    assert commit(o,obs).committed_event_ids==()
    o.close(); o=owner(tmp_path)
    assert commit(o,obs).committed_event_ids==()
    assert o.snapshot().objects[id_].evidence_refs==refs
    assert o.dispatch_watermark==2
    result=commit(o,scene(1))
    assert result.snapshot.objects[id_].last_seen_ns==obs.capture_monotonic_ns
    o.close()


def test_ambiguous_equal_geometry_does_not_force_match(tmp_path):
    o=owner(tmp_path); obs=scene()
    # Two distinct masks on a planar cloud very close together.
    b=batch(obs,((12,12,20,20),(12,12,20,20)))
    commit(o,obs,b)
    result=commit(o,scene(1))
    assert len(result.snapshot.objects)==2
    views=o.ledger.committed_views(result.committed_event_ids)
    assert views[0]['object_id'] is None
    o.close()


def test_merge_retargets_old_evidence_and_aliases(tmp_path):
    o=owner(tmp_path); a=commit(o,scene()); aid=next(iter(a.snapshot.objects))
    b=commit(o,scene(1,shift=3.)); bid=next(k for k in b.snapshot.objects if k!=aid)
    survivor=o.merge(aid,bid).snapshot
    assert len(survivor.objects)==1
    assert o.resolve_id(aid)==o.resolve_id(bid)
    assert {v['object_id'] for v in o.ledger.committed_views()}=={o.resolve_id(aid)}
    assert len(next(iter(survivor.objects.values())).evidence_refs)==2
    o.close(); o=owner(tmp_path)
    assert o.resolve_id(aid)==o.resolve_id(bid); o.close()


def test_appearance_attach_is_durable_idempotent_and_checks_space(tmp_path):
    from neusymnav.contracts.observations import AppearanceBatch,AppearanceFeature
    o=owner(tmp_path); obs=scene(); initial=commit(o,obs)
    feature=AppearanceFeature('checkpoint:preprocess-v1',np.array([1.,2.]))
    attachment=AppearanceBatch(obs.key,obs.geometry_hash,{'0':feature})
    attached=o.attach_appearance(attachment)
    assert len(attached.committed_event_ids)==1
    assert len(o.snapshot().objects)==1
    assert o.attach_appearance(attachment).committed_event_ids==()
    o.close(); o=owner(tmp_path)
    assert o.attach_appearance(attachment).committed_event_ids==()
    obs2=scene(1); commit(o,obs2)
    with pytest.raises(ValueError,match='space/dimension'):
        o.attach_appearance(AppearanceBatch(obs2.key,obs2.geometry_hash,
            {'0':AppearanceFeature('different',np.array([1.,2.]))}))
    with pytest.raises(ValueError,match='committed'):
        o.attach_appearance(AppearanceBatch(obs2.key,obs2.geometry_hash,{'invented':feature}))
    assert o.snapshot().revision==attached.snapshot.revision+1
    o.close()


def test_voxel_per_frame_vote_cap_and_candidate_lifecycle():
    from neusymnav.objects.fusion import VoxelCloud
    from neusymnav.objects.association import AssociationEngine,AssociationObservation
    cloud=VoxelCloud(max_voxels=2,max_weight=3)
    cloud.integrate(np.zeros((100,3)))
    assert cloud.max_observation_weight==1
    for i in range(10): cloud.integrate(np.array([[0.,0.,0.],[1.,1.,1.],[2.,2.,2.]]))
    assert cloud.point_count==2 and cloud.max_observation_weight==3
    engine=AssociationEngine('e')
    obs=AssociationObservation('e',0,'d','f','detected','chair',.9,np.array([[0.,0.,1.]]),(0.,0.,0.))
    id_=engine.ingest((obs,),now_s=0).object_ids[0]
    assert engine.advance_time(16).tracks[id_].status=='dormant'
    assert not engine.advance_time(60).tracks


def test_hungarian_and_ambiguity_match_independent_source_trace():
    import json
    from pathlib import Path
    from neusymnav.objects.association import AssociationEngine,AssociationObservation
    fixture=json.loads((Path(__file__).parent/'fixtures/objects/parity-v1.json').read_text())['association_trace']
    def cloud(x):
        return np.array([[x+dx,dy,1+dz] for dx in (-.03,.03) for dy in (-.03,.03) for dz in (-.03,.03)])
    def obs(frame,id_,x):
        return AssociationObservation('parity',frame,str(id_),'floor','detected','chair',.9,cloud(x),(0.,0.,0.))
    engine=AssociationEngine('parity',association_mode='geometry')
    first=engine.ingest((obs(0,0,0.),obs(0,1,.5)),now_s=1.)
    second=engine.ingest((obs(1,0,.5),obs(1,1,0.)),now_s=2.)
    assert len(first.tracks)==fixture['first_count']
    assert len(second.tracks)==fixture['second_count']
    assert [first.object_ids.index(i) for i in second.object_ids]==fixture['second_matches_first_indices']
    assert engine.can_merge(*first.object_ids)==fixture['can_merge_simultaneous']
    assert sorted(t.point_count for t in second.tracks.values())==fixture['point_counts']
    amb=AssociationEngine('parity',association_mode='geometry')
    amb.ingest((obs(0,0,0.),obs(0,1,0.)),now_s=1.)
    result=amb.ingest((obs(1,0,0.),),now_s=2.)
    assert list(result.ambiguous_indices)==fixture['ambiguous_indices']
    assert list(result.object_ids)==fixture['ambiguous_assigned']


def test_inline_feature_is_same_durable_unique_attachment(tmp_path):
    from dataclasses import replace
    from neusymnav.contracts.observations import AppearanceBatch,AppearanceFeature
    from neusymnav.perception.projector import Projector
    o=owner(tmp_path); obs=scene(); b=batch(obs)
    feature=AppearanceFeature('s1',np.array([1.,0.]))
    projected=tuple(replace(p,appearance=feature) for p in Projector(min_points=1).project(obs,b))
    result=o.commit(obs,b,projected)
    assert o.attach_appearance(AppearanceBatch(obs.key,obs.geometry_hash,{'0':feature})).committed_event_ids==()
    assert len(o.ledger.appearance_records())==1
    o.close()


def test_ambiguous_detection_can_keep_appearance_without_new_identity(tmp_path):
    from neusymnav.contracts.observations import AppearanceBatch,AppearanceFeature
    o=owner(tmp_path); obs=scene(); commit(o,obs,batch(obs,((12,12,20,20),(12,12,20,20))))
    obs=scene(1); commit(o,obs)
    result=o.attach_appearance(AppearanceBatch(obs.key,obs.geometry_hash,
        {'0':AppearanceFeature('s1',np.array([1.,0.]))}))
    assert len(result.snapshot.objects)==2
    assert o.ledger.appearance_records()[0]['object_id'] is None
    o.close()


def test_owner_hot_event_cache_is_bounded_and_ids_use_new_namespace(tmp_path):
    o=owner(tmp_path)
    for i in range(258):
        commit(o,scene(i,stamp=1_000_000_000+i))
    assert len(o._engine._events)<=256
    assert len(o.ledger.committed_views())==258
    from uuid import uuid5,NAMESPACE_URL
    old_id=str(uuid5(NAMESPACE_URL,repr(('episode',0,'0','detected'))))
    assert next(iter(o.snapshot().objects))!=old_id
    o.close()


def test_feature_space_is_pinned_across_distinct_objects_and_restart(tmp_path):
    from neusymnav.contracts.observations import AppearanceBatch,AppearanceFeature
    o=owner(tmp_path); a=scene(); commit(o,a)
    o.attach_appearance(AppearanceBatch(a.key,a.geometry_hash,
        {'0':AppearanceFeature('space1',np.array([1.,0.]))}))
    b=scene(1,shift=3.); commit(o,b); revision=o.snapshot().revision; o.close()
    o=owner(tmp_path)
    with pytest.raises(ValueError,match='space/dimension'):
        o.attach_appearance(AppearanceBatch(b.key,b.geometry_hash,
            {'0':AppearanceFeature('space2',np.array([1.,0.]))}))
    assert o.snapshot().revision==revision; o.close()
