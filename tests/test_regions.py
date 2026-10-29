"""Synthetic contract/IPC tests; native parity is opt-in in tests/native."""
from dataclasses import replace
import os
import time
import numpy as np
import pytest
from neusymnav.contracts import NavSnapshot, FrameKey
from neusymnav.regions import RegionBackend, DuDeWorkerClient, DuDeConfig, RegionGrid
from neusymnav.regions.pipeline import RegionUpdateProcessor
from neusymnav.regions._types import RegionObservation, Polygon2D


def nav(revision=1, states=None):
    states=np.zeros((10,10), np.int8) if states is None else np.array(states,np.int8)
    return NavSnapshot('e',revision,FrameKey('e','depth',revision),100,'clock',.5,(-1.,-2.),states,
        np.ones(states.shape,bool),np.full(states.shape,2.),'robot',0.,'calibration','a'*64)


def obs(raw=0, x=0., width=4., rev=1, adjacency=()):
    return RegionObservation(raw,Polygon2D(((x,0.),(x+width,0.),(x+width,4.),(x,4.))),float(rev),rev,(x+width/2,2.),width*4,adjacent_raw_ids=adjacency)


def worker(tmp_path, body):
    p=tmp_path/'worker';p.write_text('#!/usr/bin/env python3\n'+body);p.chmod(0o755);return p


def test_grid_copy_preserves_unknown_free_and_origin():
    n=nav(states=[[-1,0,100]])
    g=RegionGrid.from_nav(n)
    assert g.origin_xy==n.origin_xy and g.resolution_m==n.resolution_m
    assert g.values.tolist()==[[-1,0,100]] and not g.values.flags.writeable
    assert g.preprocessing_policy=='extended_unknown_boundary'


def test_source_guard_tracker_stable_and_reject_does_not_age():
    p=RegionUpdateProcessor()
    a=p.update([obs()],free_cells=90,unknown_cells=10,expected_cells=100)
    assert a.accepted and a.current_regions[0].persistent_id==1
    b=p.update([],free_cells=90,unknown_cells=10,expected_cells=100)
    assert not b.accepted and p.tracker.accepted_update_index==1
    assert p.tracker.snapshot()[0].miss_count==0
    c=p.update([obs(x=.1,rev=3)],free_cells=90,unknown_cells=10,expected_cells=100)
    assert c.current_regions[0].persistent_id==1


def test_timeout_poison_and_reap(tmp_path):
    binary=worker(tmp_path,'import time\ntime.sleep(20)\n')
    c=DuDeWorkerClient(binary,DuDeConfig(timeout_s=.05))
    with pytest.raises(ValueError,match='deadline'):c.integrate(RegionGrid.from_nav(nav()))
    assert c._proc.poll() is not None
    with pytest.raises(ValueError,match='error state'):c.integrate(RegionGrid.from_nav(nav(2)))
    c.close()


class SyntheticClient:
    def __init__(self, sequence):self.sequence=iter(sequence)
    def integrate(self, grid, **kwargs):
        item=next(self.sequence)
        if isinstance(item,Exception):raise item
        return {'status':'success'},tuple(item)
    def close(self):pass


def test_backend_split_merge_lineage_and_pinned_stale_map():
    b=RegionBackend(floor_id='f',client=SyntheticClient([[obs()], [obs(width=2,rev=2),obs(1,2.,2.,2)], [obs(rev=3)], ValueError('crash')]))
    first=b.update(nav())
    second=b.update(nav(2)); ids=set(second.regions)
    assert len(ids)==2 and first.regions.keys()<=ids
    assert all(next(iter(first.regions)) in r.predecessor_ids for r in second.regions.values())
    third=b.update(nav(3))
    assert set(next(iter(third.regions.values())).predecessor_ids)==ids
    stale=b.update(nav(4))
    assert stale.stale and stale.source_map_revision==3 and stale.revision==third.revision
    assert b.accepted_nav.revision==3 and b.inflight_nav is None


def test_no_observed_free_never_calls_worker():
    b=RegionBackend(floor_id='f',client=SyntheticClient([]))
    r=b.update(nav(states=[[-1,100]]))
    assert r.stale and not r.regions and b.accepted_nav is None


def test_unmodified_source_guard_tracker_parity_fixture():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/regions/source-parity-v1.json').read_text())
    p=RegionUpdateProcessor()
    for step in fixture['steps']:
        observations=[RegionObservation(o['raw_id'],Polygon2D(tuple(map(tuple,o['polygon']))),o['timestamp_s'],o['revision'],tuple(o['centroid_xy']),o['area_m2']) for o in step['inputs']]
        r=p.update(observations,free_cells=step['free'],unknown_cells=step['unknown'],expected_cells=100)
        assert (r.accepted,r.reason)==(step['accepted'],step['reason'])
        assert [x.persistent_id for x in r.current_regions]==step['ids']
        assert [[x.persistent_id,x.miss_count,x.last_source_grid_revision] for x in r.retained_tracks]==step['retained']
        assert p.tracker.accepted_update_index==step['accepted_update_index']


def wire_body(response_mutation=''):
    return '''import sys,json
for line in sys.stdin:
 q=json.loads(line)
 if q['op']!='integrate':break
 r={'protocol_version':1,'protocol_status':'ok','request_id':q['request_id'],'input_revision':q['revision'],'status':'success','branch':'synthetic','frame_id':q['frame_id'],'units':'meters','coordinate_convention':'world_x=origin_x+col*resolution; world_y=origin_y+row*resolution','regions':[{'raw_id':0,'outer':[[0.,0.],[1.,0.],[1.,1.],[0.,1.]],'centroid_xy':[.5,.5],'area_m2':1.,'holes_supported':False,'adjacent_raw_ids':[]}],'diagnostics':{'preprocessing_policy':'extended_unknown_boundary'}}
 '''+response_mutation+'''\n print(json.dumps(r),flush=True)
'''


@pytest.mark.parametrize('mutation',[
    "r['input_revision']+=1", "r['request_id']='old'", "r['regions'][0]['raw_id']=True",
    "r['regions'][0]['adjacent_raw_ids']=[1]",
    "r['coordinate_convention']='other'", "r['diagnostics']['preprocessing_policy']='source'",
])
def test_bad_wire_response_poisoned_and_reaped(tmp_path,mutation):
    with DuDeWorkerClient(worker(tmp_path,wire_body(mutation))) as c:
        with pytest.raises(ValueError):c.integrate(RegionGrid.from_nav(nav()))
        assert c._proc.poll() is not None
        with pytest.raises(ValueError,match='error state'):c.integrate(RegionGrid.from_nav(nav(2)))


def test_valid_wire_and_request_response_bounds(tmp_path):
    binary=worker(tmp_path,wire_body())
    with DuDeWorkerClient(binary) as c:
        response,observations=c.integrate(RegionGrid.from_nav(nav()))
        assert response['status']=='success' and observations[0].polygon.net_area_m2==1
    with DuDeWorkerClient(binary,DuDeConfig(max_response_bytes=100)) as c:
        with pytest.raises(ValueError,match='byte cap'):c.integrate(RegionGrid.from_nav(nav()))
        assert c._proc.poll() is not None
    with DuDeWorkerClient(binary,DuDeConfig(max_request_bytes=100)) as c:
        with pytest.raises(ValueError,match='byte cap'):c.integrate(RegionGrid.from_nav(nav()))
        assert c._proc.poll() is None


def test_native_rejection_does_not_age_or_replace_pin():
    class RejectClient(SyntheticClient):
        def integrate(self,grid,**kwargs):
            if grid.source_map_revision==1:return {'status':'success'},(obs(),)
            return {'status':'rejected','rejection_reason':'synthetic_reject'},()
    b=RegionBackend(floor_id='f',client=RejectClient([]))
    b.update(nav());r=b.update(nav(2))
    assert r.stale and r.source_map_revision==1 and b.accepted_nav.revision==1
    assert b.processor.tracker.accepted_update_index==1


def test_crash_and_stderr_are_bounded(tmp_path):
    body="import os,sys\nos.write(2,b'x'*400000)\nsys.stdin.readline()\nsys.exit(3)\n"
    with DuDeWorkerClient(worker(tmp_path,body),DuDeConfig(timeout_s=1.)) as c:
        with pytest.raises(ValueError,match='stdout'):c.integrate(RegionGrid.from_nav(nav()))
        assert c._proc.poll() is not None
        assert sum(len(s) for s in c.stderr_tail)<=256*1024


def test_backend_validation_failure_cannot_age_tracker():
    # A malformed synthetic update is rejected before consuming accepted state.
    bad=RegionObservation(0,Polygon2D(((0.,0.),(1.,1.),(2.,2.))),2.,2,(1.,1.),1.)
    b=RegionBackend(floor_id='f',client=SyntheticClient([[obs()],[bad],[obs(rev=3)]]))
    b.update(nav());r=b.update(nav(2))
    assert r.stale and b.processor.tracker.accepted_update_index==1
    assert b.update(nav(3)).revision==2


def test_config_and_episode_revision_guards():
    for changes in ({'preprocessing_policy':'source'},{'timeout_s':0},{'max_response_bytes':True}):
        with pytest.raises(ValueError):DuDeConfig(**changes)
    b=RegionBackend(floor_id='f',client=SyntheticClient([[obs()]]));b.update(nav())
    with pytest.raises(ValueError):b.update(nav())
    with pytest.raises(ValueError):b.update(replace(nav(2),episode_id='other',source=FrameKey('other','depth',2)))


@pytest.mark.parametrize('version',[True,1.0])
@pytest.mark.parametrize('operation',['integrate','reset'])
def test_protocol_version_requires_exact_integer_one(tmp_path,version,operation):
    if operation=='integrate':body=wire_body("r['protocol_version']="+repr(version))
    else:
        body="import sys,json\nfor line in sys.stdin:\n q=json.loads(line)\n print(json.dumps({'protocol_version':"+repr(version)+",'status':'reset'}),flush=True)\n"
    with DuDeWorkerClient(worker(tmp_path,body)) as c:
        with pytest.raises(ValueError,match='protocol mismatch'):
            c.integrate(RegionGrid.from_nav(nav())) if operation=='integrate' else c.reset()
        assert c._proc.poll() is not None


def test_non_simple_nonzero_polygon_wire_cannot_advance_backend(tmp_path):
    mutation="if q['revision']>1:r['regions'][0]['outer']=[[0.,0.],[3.,0.],[0.,2.],[2.,2.]]"
    with RegionBackend(worker(tmp_path,wire_body(mutation)),floor_id='f') as b:
        first=b.update(nav());accepted=b.accepted_nav
        second=b.update(nav(2))
        assert second.stale and second.revision==first.revision
        assert second.source_map_revision==1 and b.accepted_nav is accepted
        assert b.processor.tracker.accepted_update_index==1
        assert b.client._proc.poll() is None
        assert 'simple' in b.last_reason


def test_non_simple_polygon_injected_client_rejected_before_tracker():
    polygon=Polygon2D(((0.,0.),(3.,0.),(0.,2.),(2.,2.)))
    bad=RegionObservation(0,polygon,2.,2,(1.,1.),16.)
    b=RegionBackend(floor_id='f',client=SyntheticClient([[obs()],[bad],[obs(rev=3)]]))
    first=b.update(nav());accepted=b.accepted_nav;tracks=b.processor.tracker.snapshot()
    second=b.update(nav(2))
    assert second.stale and second.revision==first.revision and second.source_map_revision==1
    assert b.accepted_nav is accepted and b.processor.tracker.snapshot()==tracks
    assert b.processor.tracker.accepted_update_index==1
    assert b.update(nav(3)).revision==2


@pytest.mark.parametrize('action',['timeout','close_after_leader_exit'])
def test_process_group_cleanup_kills_term_ignoring_descendant(tmp_path,action):
    import signal
    import sys
    from pathlib import Path
    pidfile=tmp_path/'child.pid'
    child="import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path("+repr(str(pidfile))+").write_text(str(os.getpid()));time.sleep(30)"
    body='import subprocess,sys,time\nfrom pathlib import Path\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'])\nwhile not Path('+repr(str(pidfile))+').exists():time.sleep(.01)\n'
    body += 'time.sleep(30)\n' if action=='timeout' else 'sys.exit(0)\n'
    c=DuDeWorkerClient(worker(tmp_path,body),DuDeConfig(timeout_s=.1))
    started=time.monotonic();child_pid=None
    def alive():
        stat=Path('/proc')/str(child_pid)/'stat'
        try:
            return stat.read_text().split()[2]!='Z'
        except (FileNotFoundError, ProcessLookupError):
            return False
    try:
        deadline=time.monotonic()+3
        while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert pidfile.exists(),'fault-injection child never started'
        child_pid=int(pidfile.read_text())
        if action=='timeout':
            with pytest.raises(ValueError,match='deadline'):c.integrate(RegionGrid.from_nav(nav()))
        else:
            c._proc.wait(timeout=1.)
            c.close()
        assert c._proc.poll() is not None
        deadline=time.monotonic()+1
        while alive() and time.monotonic()<deadline:time.sleep(.01)
        assert not alive(),'SIGTERM-ignoring descendant survived process-group cleanup'
        assert not c._stderr_thread.is_alive(),'stderr drain thread survived cleanup'
        c.close()
        assert all(s.closed for s in (c._proc.stdin,c._proc.stdout,c._proc.stderr))
        assert time.monotonic()-started<4
    finally:
        # The pre-fix RED run must not leave an injected process alive.
        try:os.killpg(c._proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        c.close()


def test_ring_vertex_cap_precedes_quadratic_validation(monkeypatch):
    from neusymnav.regions import geometry
    def forbidden(*args):raise AssertionError('over-cap ring reached triangulation')
    monkeypatch.setattr(geometry,'_triangulate',forbidden)
    theta=np.linspace(0,2*np.pi,1025,endpoint=False)
    ring=np.column_stack((np.cos(theta),np.sin(theta)))
    assert geometry.valid_ring(ring) is False


def test_simple_ring_validation_shared_and_collinear_rules():
    from neusymnav.regions.geometry import valid_ring
    from neusymnav.hierarchy.membership import valid_ring as member_predicate
    assert valid_ring is member_predicate
    assert valid_ring(((0.,0.),(1.,0.),(2.,0.),(2.,2.),(0.,2.)))
    assert not valid_ring(((0.,0.),(2.,0.),(1.,0.),(1.,2.),(0.,2.)))
    assert valid_ring(((0.,0.),(3.,0.),(3.,3.),(2.,3.),(2.,1.),(1.,1.),(1.,3.),(0.,3.)))
