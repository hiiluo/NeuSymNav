"""Navigation churn must respect graph cadence without losing final state."""
from dataclasses import replace
from threading import RLock
from types import SimpleNamespace

from neusymnav.contracts import ObjectSnapshot, RegionSnapshot
from neusymnav.runtime.coordinator import Pipeline
from test_runtime_scheduling import source, nav_for, DOMAIN


def fixture():
    clock=[1_000_000_000];published=[]
    p=Pipeline.__new__(Pipeline)
    p._lock=RLock();p._objects=ObjectSnapshot('episode',1,source().key,{},{})
    p._latest_nav=nav_for(source(),1);p._accepted_nav=None;p._regions=None
    p.region_factory=None;p.floor_id='f';p._captured=source().key;p._processed=source().key
    p._verification=None;p._latest_depth=None;p._publication_revisions=None
    p.now_ns=lambda:clock[0];p.clock_domain=DOMAIN;p._closing=False
    p.mapper=None;p._place_status='unavailable_no_measured_pose';p.publisher=None;p._counts={'missing':0}
    p.measurements=SimpleNamespace(publication=published.append)
    p.health=SimpleNamespace(snapshot=lambda:{'failed':{}})
    return p,clock,published


def test_nav_and_region_churn_coalesces_to_latest_coherent_pair_at_100ms():
    p,clock,published=fixture();p.region_factory=object()
    for i,offset in enumerate([0,10_000_000,20_000_000,99_999_999,100_000_000]):
        clock[0]=1_000_000_000+offset
        p._latest_nav=p._accepted_nav=nav_for(source(i,stamp=clock[0]),i+1)
        p._regions=RegionSnapshot('episode',i+1,i+1,'f',{},False)
        p._publish()
    assert [h.map_revision for h in published]==[1,5]
    hierarchy,nav=p.snapshot_bundle()
    assert hierarchy is published[-1] and hierarchy.map_revision==nav.revision==5
    assert hierarchy.latest_nav_revision==5


def test_new_object_revision_bypasses_map_cadence_and_close_flushes_latest():
    p,clock,published=fixture();p._publish()
    clock[0]+=1
    p._objects=replace(p._objects,revision=2)
    p._publish()
    assert [h.object_revision for h in published]==[1,2]
    p._latest_nav=nav_for(source(1),2);p._publish()
    assert len(published)==2
    p._closing=True;p._publish()
    assert published[-1].map_revision==2 and len(published)==3


def test_close_waits_for_final_region_and_flushes_on_graph_owner(tmp_path):
    from threading import Event, get_ident
    from test_runtime_scheduling import pipeline, wait_for
    entered=Event();release=Event();compositions=[]
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Regions:
        def update(self,nav):
            if nav.revision==2:entered.set();assert release.wait(3)
            return RegionSnapshot('episode',nav.revision,nav.revision,'f',{},False)
        def close(self):pass
    class Observer:
        stop_requested=Event()
        def publication(self,h):compositions.append((h,get_ident()))
        def __getattr__(self,name):return lambda *a,**kw:None
    p,_,_=pipeline(tmp_path,mapper=Mapper(),region_factory=Regions,measurements=Observer())
    try:
        p.submit(source());wait_for(lambda:p.snapshot() is not None)
        p.submit(source(1,modality='depth_only'));assert entered.wait(1)
        first=p.close(.05)
        assert not first['clean_shutdown'] and p._threads['graph'].is_alive()
        release.set();final=p.close(2)
        assert final['clean_shutdown']
        hierarchy,nav=p.snapshot_bundle()
        assert hierarchy.map_revision==nav.revision==p._accepted_nav.revision==2
        assert all(tid==p._threads['graph'].ident for _,tid in compositions)
    finally:release.set();p.close(2)


def test_region_finishing_between_publish_and_exit_check_is_flushed(tmp_path):
    from threading import Event
    from test_runtime_scheduling import pipeline, wait_for
    entered=Event();release=Event();after_publish=Event();check_exit=Event()
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    class Regions:
        def update(self,nav):
            if nav.revision==2:entered.set();assert release.wait(3)
            return RegionSnapshot('episode',nav.revision,nav.revision,'f',{},False)
        def close(self):pass
    p,_,_=pipeline(tmp_path,mapper=Mapper(),region_factory=Regions)
    original=p._publish;fenced=[False]
    def switch_after_publish(verifier=None):
        original(verifier)
        if p._closing and not fenced[0]:
            fenced[0]=True;after_publish.set();assert check_exit.wait(3)
    p._publish=switch_after_publish
    try:
        p.submit(source());wait_for(lambda:p.snapshot() is not None)
        p.submit(source(1,modality='depth_only'));assert entered.wait(1)
        assert not p.close(.05)['clean_shutdown'];assert after_publish.wait(1)
        release.set();wait_for(lambda:p._worker_done.get('region',False))
        check_exit.set();assert p.close(2)['clean_shutdown']
        assert p.snapshot().map_revision==p._accepted_nav.revision==2
    finally:release.set();check_exit.set();p.close(2)


def test_region_worker_without_mapper_closes_cleanly(tmp_path):
    from test_runtime_scheduling import pipeline
    class Regions:
        def close(self):pass
    p,_,_=pipeline(tmp_path,region_factory=Regions)
    assert p.close(2)['clean_shutdown']
