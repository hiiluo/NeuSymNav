from uuid import uuid4
import numpy as np
from neusymnav.contracts import FrameKey
from neusymnav.contracts.graphs import ObjectSnapshot, ObjectState
from neusymnav.verification.view_memory import ViewEvidence, ViewMemorySummary
from neusymnav.verification.reobserve import ReobserveScheduler


def fixture(now=1_000_000_000, support=.8):
    oid=str(uuid4()); key=FrameKey('ep','rgb',1)
    obj=ObjectState(oid,'floor',np.array([0.,0.,2.]),np.array([[-.1,-.1,1.9],[.1,.1,2.1]]),'candidate',(),1,key,now,now,'clock')
    snap=ObjectSnapshot('ep',1,key,{oid:obj},{})
    pose=np.eye(4); pose[0,3]=1
    view=ViewEvidence('ep',oid,'event',key,now,'clock',1,'a'*64,'cal',None,pose,np.eye(3),obj.centroid,.1,support,'a'*64,'b'*64,'c'*64,.8,{},'v1')
    summary=ViewMemorySummary('ep',1,1,'v1',{oid:(view,)},{},0,{},())
    return oid,snap,summary


def test_admission_requires_depth_and_activation_time_credit():
    oid,snap,summary=fixture(support=0)
    s=ReobserveScheduler('ep','clock'); s.reset('ep',0); s.update(summary,snap,1_000_000_000)
    assert s.queued()==()
    oid,snap,summary=fixture()
    s.update(summary,snap,1_000_000_000)
    request=s.queued()[0]
    assert s.activate(request.id,1_000_000_000).state=='active'
    s.tick(1_250_000_000)
    assert s.active is None
    assert s.status()['terminal_history'][-1]['state']=='expired'


def test_request_does_not_recur_without_new_support_after_expiry():
    _,snap,summary=fixture(); s=ReobserveScheduler('ep','clock',request_ttl_ns=1_000_000_000)
    s.update(summary,snap,1_000_000_000); assert len(s.queued())==1
    s.update(summary,snap,2_000_000_000); assert not s.queued()


def test_long_tick_charges_all_active_wall_time():
    _,snap,summary=fixture(); s=ReobserveScheduler('ep','clock')
    s.update(summary,snap,1_000_000_000); r=s.queued()[0]; s.activate(r.id,1_000_000_000)
    s.tick(9_000_000_000)
    assert s.active is None and s.status()['active_time_ns']==8_000_000_000


def test_future_and_stale_evidence_do_not_schedule():
    _,snap,summary=fixture(); s=ReobserveScheduler('ep','clock')
    s.update(summary,snap,0); assert not s.queued()
    s.update(summary,snap,32_000_000_000); assert not s.queued()


def test_queue_limit_and_bounded_history():
    s=ReobserveScheduler('ep','clock',max_queue=1,request_ttl_ns=1)
    for i in range(150):
        _,snap,summary=fixture(now=1_000_000_000+i*2)
        s.update(summary,snap,1_000_000_000+i*2)
        assert len(s.queued())<=1
        s.tick(1_000_000_001+i*2)
    assert len(s.status()['terminal_history'])==128
    assert s.status()['tracked_objects']==150


def test_only_new_independent_captured_view_satisfies():
    from dataclasses import replace
    oid,snap,summary=fixture(); s=ReobserveScheduler('ep','clock')
    s.update(summary,snap,1_000_000_000); r=s.queued()[0]; s.activate(r.id,1_000_000_000)
    v=summary.views[oid][0]
    pose=np.eye(4); pose[0,3]=-1
    new=replace(v,event_id='new',source=FrameKey('ep','rgb',2),capture_monotonic_ns=1_100_000_000,camera_pose_world=pose)
    updated=replace(summary,evidence_revision=2,views={oid:(v,new)})
    s.update(updated,snap,1_050_000_000); assert s.active is not None
    s.update(updated,snap,1_100_000_000); assert s.active is None
    assert s.status()['terminal_history'][-1]['state']=='satisfied'


def test_move_and_alias_cancel_existing_request():
    from dataclasses import replace
    oid,snap,summary=fixture(); s=ReobserveScheduler('ep','clock')
    s.update(summary,snap,1_000_000_000)
    moved=replace(snap.objects[oid],centroid=np.array([.2,0.,2.]),bounds=np.array([[.1,-.1,1.9],[.3,.1,2.1]]),revision=2)
    newer=replace(snap,revision=2,objects={oid:moved})
    s.update(replace(summary,object_revision=2),newer,1_000_000_001)
    assert s.status()['terminal_history'][-1]['cancel_reason']=='object_moved'
    new_id=str(uuid4()); renamed=replace(moved,object_id=new_id,revision=3)
    alias=replace(newer,revision=3,objects={new_id:renamed},aliases={oid:new_id})
    s.update(replace(summary,object_revision=3,views={new_id:tuple(replace(v,object_id=new_id) for v in summary.views[oid])}),alias,1_000_000_002)
    assert all(r.object_id==new_id for r in s.queued())


def test_clock_replay_rejected_and_reset_clears_pending():
    import pytest
    _,snap,summary=fixture(); s=ReobserveScheduler('ep','clock')
    s.update(summary,snap,1_000_000_000)
    with pytest.raises(ValueError): s.tick(1)
    s.reset('other',2_000_000_000); assert not s.queued() and not s.status()['terminal_history']
