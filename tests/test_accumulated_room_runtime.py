"""Room history is independent of the fresh local control map."""
from dataclasses import replace
from threading import Event
from types import MappingProxyType
import time
import numpy as np
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.mapping.overview import OverviewTiles
from neusymnav.regions.backend import RegionBackend
from neusymnav.regions._types import Polygon2D,RegionObservation
from test_runtime_scheduling import pipeline,source,nav_for,wait_for


class HistoryMapper:
    robot=RobotGeometry('robot',.1,1.234,.05)
    def __init__(self,incomplete=()):self.incomplete=set(incomplete);self.current=None
    def update(self,obs):
        self.current=nav_for(obs,obs.key.frame_index+1)
        return self.current
    def room_input_tiles(self):
        nav=self.current
        tiles={(0,0):np.zeros((16,16),np.int8)}
        if nav.revision>1:tiles[(0,1)]=np.zeros((16,16),np.int8)
        return OverviewTiles(nav,(-.5,-.5),.1,16,MappingProxyType(tiles),nav.revision not in self.incomplete)


class Client:
    def __init__(self,entered=None,release=None):self.calls=[];self.entered=entered;self.release=release
    def integrate(self,grid,**kwargs):
        self.calls.append(grid)
        if len(self.calls)==1 and self.entered is not None:
            self.entered.set();assert self.release.wait(3)
        x,y=grid.origin_xy;h,w=grid.values.shape;res=grid.resolution_m
        polygon=Polygon2D(((x,y),(x+w*res,y),(x+w*res,y+h*res),(x,y+h*res)))
        obs=RegionObservation(0,polygon,1.,grid.source_map_revision,(x+w*res/2,y+h*res/2),w*h*res*res)
        return {'status':'success','branch':'fixture'},(obs,)
    def reset(self):return {'status':'reset'}
    def close(self):pass


def _wait_for_publication_with_virtual_time(p, clock, predicate):
    # An earlier publication can finish after the region result is ready and
    # consume the one cadence tick. Advance on every poll, as a running clock
    # would, until the desired source-bound publication is observed.
    deadline = time.monotonic() + 5.
    while time.monotonic() < deadline:
        result = p.snapshot()
        if result is not None and predicate(result):
            return
        clock[0] += 100_000_000
        p._wake.set()
        # Yield to the graph owner after each virtual cadence tick. Advancing
        # virtual time in a tight 5 ms polling loop starved this worker on CI.
        time.sleep(.01)
    raise AssertionError('timed out waiting for a coalesced hierarchy publication')


def test_blocked_room_worker_does_not_block_or_replace_local_navigation(tmp_path):
    entered=Event();release=Event();mapper=HistoryMapper();client=Client(entered,release)
    backend=RegionBackend(floor_id='f',client=client,reset_on_geometry_change=True)
    clock=[1_000_000_000]
    p,_,_=pipeline(tmp_path,mapper=mapper,region_factory=lambda:backend,clock=lambda:clock[0])
    try:
        p.submit(source(0));assert entered.wait(2)
        for i in range(1,5):
            p.submit(source(i));wait_for(lambda:p._latest_nav.revision==i+1)
            assert p._latest_nav.states.shape==(10,10)
        assert client.calls[0].values.shape==(16,16)
        release.set();wait_for(lambda:p._regions is not None and p._regions.source_map_revision==5)
        _wait_for_publication_with_virtual_time(p,clock,lambda snapshot:snapshot.map_revision==5)
        hierarchy,room_nav=p.snapshot_bundle()
        assert room_nav.states.shape==(16,32) and p._latest_nav.states.shape==(10,10)
        assert room_nav is not p._latest_nav and room_nav.source==p._latest_nav.source
        assert np.all(room_nav.clearance==1.234)
        floor=hierarchy.nodes['floor:f']
        assert floor.attributes['geometry_input_scope']=='accumulated_measured_occupancy_v1'
        assert p.telemetry()['regions']['last_input_shape']==[16,32]
    finally:release.set();assert p.close(3)['clean_shutdown']


def test_incomplete_room_history_retains_exact_accepted_pair_without_aging_tracks(tmp_path):
    mapper=HistoryMapper(incomplete=(2,));backend=RegionBackend(floor_id='f',client=Client(),reset_on_geometry_change=True)
    clock=[1_000_000_000]
    p,_,_=pipeline(tmp_path,mapper=mapper,region_factory=lambda:backend,clock=lambda:clock[0])
    try:
        p.submit(source(0));wait_for(lambda:p._regions is not None and not p._regions.stale)
        accepted=p._accepted_nav;index=backend.processor.tracker.accepted_update_index
        p.submit(source(1));wait_for(lambda:p._regions.stale)
        assert p._latest_nav.revision==2 and p._accepted_nav is accepted
        assert p._regions.source_map_revision==accepted.revision
        assert backend.processor.tracker.accepted_update_index==index
        _wait_for_publication_with_virtual_time(p,clock,lambda snapshot:snapshot.statuses['regions']=='unavailable')
        assert 'incomplete' in p.telemetry()['regions']['last_rejection_reason']
        p.submit(source(2));wait_for(lambda:not p._regions.stale and p._regions.source_map_revision==3)
        assert backend.processor.tracker.accepted_update_index==index+1
        assert p._accepted_nav.states.shape==(16,32)
    finally:assert p.close(3)['clean_shutdown']


def test_incomplete_startup_publishes_empty_stale_then_recovers(tmp_path):
    mapper=HistoryMapper(incomplete=(1,));backend=RegionBackend(floor_id='f',client=Client())
    p,_,_=pipeline(tmp_path,mapper=mapper,region_factory=lambda:backend)
    try:
        p.submit(source(0));wait_for(lambda:p.snapshot() is not None)
        assert p._regions.stale and not p._regions.regions and backend.accepted_nav is None
        assert p.snapshot().statuses['regions']=='unavailable'
        assert p._accepted_region_scope=='room_input_unavailable'
        assert p.snapshot().nodes['floor:f'].attributes.get('geometry_input_scope')!='accumulated_measured_occupancy_v1'
        p.submit(source(1));wait_for(lambda:p._regions is not None and not p._regions.stale)
        assert backend.accepted_nav.revision==2
    finally:assert p.close(3)['clean_shutdown']


def test_reset_ack_failure_never_changes_canonical_geometry():
    from test_regions import nav
    class ResetClient(Client):
        good=False
        def reset(self):return {'status':'reset' if self.good else 'wrong'}
    client=ResetClient();backend=RegionBackend(floor_id='f',client=client,reset_on_geometry_change=True)
    first=backend.update(nav());accepted=backend.accepted_nav;tracks=backend.processor.tracker.accepted_update_index
    second=backend.update(replace(nav(2),origin_xy=(0.,0.)))
    assert second.stale and second.regions is not None and second.source_map_revision==1
    assert backend.accepted_nav is accepted and backend.processor.tracker.accepted_update_index==tracks
    assert len(client.calls)==1
    client.good=True;third=backend.update(replace(nav(3),origin_xy=(0.,0.)))
    assert not third.stale and backend.diagnostics()['native_resets']==1


def test_historical_place_routes_disappear_when_measured_cell_is_corrected():
    from neusymnav.hierarchy.places import PlaceBuilder
    from neusymnav.mapping.room_map import RoomMapEvidence,build_room_map
    robot=HistoryMapper.robot
    def frame(i):
        n=nav_for(source(i),i+1);states=np.zeros((20,40),np.int8)
        return replace(n,origin_xy=(0.,0.),states=states,floor_support=states==0,clearance=np.full(states.shape,2.))
    places=PlaceBuilder(robot)
    for i,xy in enumerate(((.55,.55),(1.55,.55))):
        n=frame(i);places.update(n,xy,pose_source=n.source,capture_monotonic_ns=n.capture_monotonic_ns,clock_domain=n.clock_domain)
    n=replace(frame(2),origin_xy=(2.,0.))
    raw={(0,k):np.zeros((16,16),np.int8) for k in range(3)}
    full=build_room_map(RoomMapEvidence(OverviewTiles(n,(0.,0.),.1,16,raw),robot),n)
    before=places.snapshot_for(full)
    assert len(before.places)==2 and len(before.edges)==1
    assert not places.snapshot_for(n).places  # local window alone has lost those visits
    raw[(0,0)][5,5]=100;n4=replace(n,revision=4,source=replace(n.source,frame_index=3))
    corrected=build_room_map(RoomMapEvidence(OverviewTiles(n4,(0.,0.),.1,16,raw),robot),n4)
    after=places.snapshot_for(corrected)
    assert len(after.places)==1 and not after.edges
    assert full.states[5,5]==0 and corrected.states[5,5]==100


def test_publication_captures_input_scope_with_the_same_map_generation():
    from test_canonical_publication_cadence import fixture
    from neusymnav.contracts import RegionSnapshot
    from neusymnav.hierarchy.composer import HierarchyComposer
    p,_,_=fixture();p.region_factory=object();p._accepted_nav=p._latest_nav
    p._regions=RegionSnapshot('episode',0,p._latest_nav.revision,'f',{},True)
    p._accepted_region_scope='room_input_unavailable'
    actual=HierarchyComposer()
    class InterleavingComposer:
        def compose(self,*args,**kwargs):
            p._accepted_region_scope='accumulated_measured_occupancy_v1'
            return actual.compose(*args,**kwargs)
    p._composer=InterleavingComposer();p._publish()
    assert p.snapshot().nodes['floor:f'].attributes.get('geometry_input_scope')!='accumulated_measured_occupancy_v1'


def test_frozen_clock_can_coalesce_final_map_after_an_earlier_publication():
    from test_canonical_publication_cadence import fixture
    from neusymnav.contracts import RegionSnapshot
    p,clock,published=fixture();p.region_factory=object()
    p._latest_nav=p._accepted_nav=nav_for(source(0),1)
    p._regions=RegionSnapshot('episode',1,1,'f',{},False)
    p._publish()
    clock[0]+=100_000_000
    p._publish()  # an earlier in-flight generation consumes the only tick
    p._latest_nav=p._accepted_nav=nav_for(source(1),2)
    p._regions=RegionSnapshot('episode',2,2,'f',{},False)
    p._publish()
    assert published[-1].map_revision==1
    clock[0]+=100_000_000
    p._publish()
    assert published[-1].map_revision==2
