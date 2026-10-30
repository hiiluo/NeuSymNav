"""Planner display consumes actual decisions with its own bounded provenance."""
from dataclasses import replace
import json
import pytest
from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.frontiers import Frontier,FrontierSet
from neusymnav.visualization.navigation_overlay import NavigationOverlay,from_plan
from neusymnav.visualization.publisher import DisplaySources
from neusymnav.runtime.ui_transport import encode_publication,decode_publication
from test_display_snapshot import make_publisher


def inputs():
    p,h,m,o,nav,_=make_publisher()
    f=Frontier('goal',nav.revision,((0,0),(1,1)),(1,1),2)
    fs=FrontierSet(nav.revision,str(nav.source),(f,))
    target=(nav.origin_xy[0]+1.5*nav.resolution_m,nav.origin_xy[1]+1.5*nav.resolution_m)
    d=NavigationDecision('goal',(target,),.1,0.,nav.revision,'follow_path')
    return p,h,m,nav,fs,d


def test_actual_frontier_world_coordinates_goal_and_route_are_retained():
    _,_,_,nav,fs,d=inputs();a=from_plan(nav,fs,d,'follow_path',nav.capture_monotonic_ns)
    assert a.goal_id==d.goal_id and a.goal_xy==d.path[-1] and a.path==d.path
    assert a.viewpoints==(a.goal_xy,)
    assert a.frontier_points[0]==(nav.origin_xy[0]+.5*nav.resolution_m,nav.origin_xy[1]+.5*nav.resolution_m)
    assert a.source==nav.source and a.map_revision==nav.revision
    assert from_plan(nav,fs,d,'runtime_paused',nav.capture_monotonic_ns,clear_goal=True).goal_xy is None
    with pytest.raises(ValueError,match='revision'):from_plan(nav,replace(fs,map_revision=nav.revision+1),d,'x',nav.capture_monotonic_ns)


def test_transport_tags_newer_plan_separately_from_region_pinned_map_and_rejects_foreign_sources():
    p,h,m,nav,fs,d=inputs()
    newer=replace(nav,revision=nav.revision+1,source=replace(nav.source,frame_index=nav.source.frame_index+1))
    a=from_plan(newer,replace(fs,map_revision=newer.revision),replace(d,map_revision=newer.revision),'follow_path',nav.capture_monotonic_ns)
    metrics=dict(m,sources=replace(m['sources'],navigation=a));p.publish(h,metrics)
    out=decode_publication(encode_publication(p.read_latest()))
    assert out.sources.navigation==a and out.sources.nav.revision!=a.map_revision
    for bad in [replace(a,source=replace(a.source,episode_id='wrong')),replace(a,clock_domain='other')]:
        with pytest.raises(ValueError):p.publish(h,dict(m,sources=replace(m['sources'],navigation=bad)))
    wire=json.loads(encode_publication(out));wire['payload']['fields']['sources']['fields'].pop('navigation')
    assert decode_publication(json.dumps(wire).encode()).sources.navigation is None


@pytest.mark.parametrize('change',[
    dict(frontier_points=((float('nan'),0.),)),dict(frontier_points=((0.,0.),)*8193),
    dict(viewpoints=((0.,0.),)*65),dict(path=((0.,0.),)*2049),dict(goal_xy=None),
    dict(clock_domain=''),dict(computed_monotonic_ns=-1),dict(status='x'*257),
])
def test_invalid_or_unbounded_display_rejected(change):
    _,_,_,nav,fs,d=inputs();a=from_plan(nav,fs,d,'follow_path',nav.capture_monotonic_ns)
    with pytest.raises(ValueError):replace(a,**change)


def test_large_boundary_is_bounded_and_long_route_is_omitted_not_shortcut():
    _,_,_,nav,fs,d=inputs();f=replace(fs.frontiers[0],boundary_cells=((0,0),)*9000)
    a=from_plan(nav,replace(fs,frontiers=(f,)),replace(d,path=d.path*2049),'follow_path',nav.capture_monotonic_ns)
    assert len(a.frontier_points)==8192 and a.truncated and a.path==() and a.goal_xy==d.path[-1]


def test_control_records_plan_once_and_ui_builds_it_later_with_pause_clear(tmp_path,monkeypatch):
    from test_runtime_scheduling import pipeline,source,nav_for,wait_for,DOMAIN
    from neusymnav.contracts import MotionCommand
    import neusymnav.visualization.navigation_overlay as module
    calls=[];original=module.from_plan
    monkeypatch.setattr(module,'from_plan',lambda *a,**kw:(calls.append(1),original(*a,**kw))[1])
    class Mapper:
        def update(self,obs):return nav_for(obs,1)
    class Navigator:
        def step(self,nav,xy,yaw,now):
            f=Frontier('selected',nav.revision,((1,1),),(2,2),1)
            self.last_frontiers=FrontierSet(nav.revision,str(nav.source),(f,))
            return NavigationDecision('selected',((-.25,-.25),),.1,0.,nav.revision,'follow_path')
    class Guard:
        def bind_nav(self,*a,**kw):pass
        def filter(self,decision,obs,now):return MotionCommand(obs.key,1,now,now+10_000_000,DOMAIN,.1,0.,'follow_path',obs.capture_monotonic_ns)
    class Actuator:
        def robot_pose(self,obs):return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=(0.,0.),yaw_rad=0.)
        def execute(self,command):return dict(executed=True)
    p,_,_=pipeline(tmp_path,mapper=Mapper(),navigator=Navigator(),guard=Guard())
    try:
        p.submit(source(modality='depth_only'));wait_for(lambda:p._latest_nav is not None)
        assert p.control_step(Actuator())['executed'] and not calls
        shown=p.navigation_display()
        assert len(calls)==1 and shown.goal_id=='selected' and shown.source==p._latest_nav.source
        p._paused=True;assert p.navigation_display().goal_id is None
        p._paused=False
        for reason in ['yaw_preflight_unavailable','collision_blocked']:
            class Veto(Actuator):
                def execute(self,command):return dict(executed=False,reason=reason)
            assert not p.control_step(Veto())['executed']
            assert p.navigation_display().goal_id is None and p.navigation_display().status==reason
        class ZeroGuard(Guard):
            def filter(self,*args):return replace(super().filter(*args),linear_mps=0.,yaw_radps=0.,reason='motion_limits')
        p.guard=ZeroGuard();p.control_step(Actuator())
        assert p.navigation_display().goal_id is None and p.navigation_display().status=='motion_limits'
        p.guard=Guard()
        class Broken(Actuator):
            def execute(self,command):raise RuntimeError('failed')
        assert p.control_step(Broken())['reason']=='control_rejected'
        assert p.navigation_display() is None
    finally:assert p.close(2)['clean_shutdown']


def test_ui_provider_is_called_only_after_publication_coalescing(tmp_path,monkeypatch):
    from test_ui_publication_cadence import fixed_clock,ui_process
    from neusymnav.runtime.ui_transport import decode_publication
    now=fixed_clock(monkeypatch);p,h,m,nav,fs,d=inputs();calls=[]
    a=from_plan(nav,fs,d,'follow_path',nav.capture_monotonic_ns)
    with ui_process(tmp_path,publish_hz=2,navigation_provider=lambda:(calls.append(1),a)[1]) as ui:
        ui.publish(h,m);assert len(calls)==1
        assert decode_publication((ui.root/'publication.json').read_bytes()).sources.navigation==a
        now[0]+=10_000_000;ui.publish(h,m);assert len(calls)==1
