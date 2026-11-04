from dataclasses import replace
from types import SimpleNamespace

from neusymnav.runtime.active_perception import ActivePerception, EvidenceInput
from test_guard_goal_feedback import (context, real_navigator, pipeline, Guard, Actuator, DOMAIN, STAMP)
from test_reobserve_requests import fixture


def inputs():
    oid,snapshot,summary=fixture()
    view=summary.views[oid][0]
    key=replace(view.source,episode_id='episode')
    obj=replace(snapshot.objects[oid],source=key,clock_domain=DOMAIN)
    snapshot=replace(snapshot,episode_id='episode',source=key,objects={oid:obj})
    view=replace(view,episode_id='episode',source=key,clock_domain=DOMAIN)
    summary=replace(summary,episode_id='episode',views={oid:(view,)})
    return EvidenceInput(summary,snapshot)


def prepared(mode):
    obs,nav=context();n=real_navigator()
    active=ActivePerception(nav.episode_id,DOMAIN,mode)
    active.camera=object()
    target=SimpleNamespace(world_xy=(1.45,1.2),yaw_rad=0.,path=SimpleNamespace(cost_m=.25))
    proposal=SimpleNamespace(candidates=(target,),reason='ok')
    active.planner=SimpleNamespace(plan=lambda *a,**k:proposal,visible=lambda *a:True)
    evidence=inputs()
    active.step(n,nav,(1.2,1.2),0.,STAMP,evidence)
    active._proposal_result=((active.scheduler.queued()[0].id,active.camera),proposal)
    stamp=STAMP+2_000_000_000
    obs=replace(obs,capture_monotonic_ns=stamp)
    nav=replace(nav,capture_monotonic_ns=stamp)
    return obs,nav,n,active,evidence,stamp


def test_shadow_never_replaces_frontier_decision():
    _,nav,n,active,evidence,stamp=prepared('shadow')
    assert active.step(n,nav,(1.2,1.2),0.,stamp,evidence) is None
    assert active.shadow_viewpoints==1 and active.scheduler.active is None


def test_guard_veto_stays_zero_and_does_not_poison_suspended_frontier():
    obs,nav,n,active,evidence,stamp=prepared('active')
    baseline=n.step(nav,(1.2,1.2),0.,stamp)
    goal=n.policy._goal_world_xy
    p=pipeline(obs,nav,n,Guard(),now=stamp)
    p._active=active;p._active_input=evidence;p._admission_snapshot=None
    actuator=Actuator()
    result=p.control_step(actuator)
    assert result['executed'] is False
    assert p._step_decision.goal_id.startswith('reobserve:')
    assert len(actuator.commands)==1 and actuator.commands[0].linear_mps==0
    assert n.policy._goal_world_xy==goal and not n.policy._failed_until_revision
    assert active.scheduler.active is None
    assert baseline.goal_id and n.step(nav,(1.2,1.2),0.,stamp).goal_id==baseline.goal_id


def test_stale_nav_cannot_activate_and_pause_cancels_request():
    obs,nav,n,active,evidence,stamp=prepared('active')
    assert active.step(n,nav,(1.2,1.2),0.,stamp+301_000_000,evidence) is None
    assert active.scheduler.active is None
    obs,nav,n,active,evidence,stamp=prepared('active')
    assert active.step(n,nav,(1.2,1.2),0.,stamp,evidence) is not None
    p=pipeline(obs,nav,n,Guard(),now=stamp)
    p._active=active;p._paused=True
    actuator=Actuator()
    assert p.control_step(actuator)['reason']=='runtime_paused'
    assert not actuator.commands and active.scheduler.active is None


def test_arrival_only_completes_after_exact_tagged_commit():
    import numpy as np
    from contract_helpers import observation
    from neusymnav.contracts import FrameKey
    _,nav,n,active,evidence,stamp=prepared('active')
    xy=(1.45,1.2)
    decision=active.step(n,nav,xy,0.,stamp,evidence)
    assert decision.reason=='reobserve_capture_ready'
    assert active.scheduler.active is not None
    key=FrameKey('episode','rgb',2)
    captured=observation(key=key,clock_domain=DOMAIN,capture_monotonic_ns=stamp+10_000_000)
    assert active.tag_capture(captured,xy,0.)
    oid=next(iter(evidence.summary.views))
    old=evidence.summary.views[oid][0]
    pose=np.eye(4);pose[0,3]=-1.
    view=replace(old,event_id='new',source=key,capture_monotonic_ns=captured.capture_monotonic_ns,
                 camera_pose_world=pose)
    summary=replace(evidence.summary,evidence_revision=2,views={oid:(old,view)})
    t=stamp+20_000_000
    active.step(n,nav,xy,0.,t,EvidenceInput(summary,evidence.objects,committed_source=replace(key,frame_index=3)))
    assert active.scheduler.active is not None
    active.step(n,nav,xy,0.,t+1,EvidenceInput(summary,evidence.objects,committed_source=replace(key,frame_index=3)),capture_result=(key,True))
    assert active.scheduler.active is None
    assert active.scheduler.status()['terminal_history'][-1]['state']=='satisfied'


def test_active_config_profiles_are_opt_in_and_same_detector_recipe():
    from pathlib import Path
    from neusymnav.runtime.configuration import load_config
    root=Path(__file__).parents[1]/'configs/p10'
    base=load_config(root/'demo-yoloe11s-conceptgraphs-visual-gpu-00861.json').data
    assert base.get('active_perception',{}).get('mode','off')=='off'
    for kind,mode in [('memory','shadow'),('reobserve','active'),('scheduled','active')]:
        other=load_config(root/f'active-perception-{kind}-00861.json').data
        assert other['active_perception']['mode']==mode
        for field in ('detector','workers','navigation','sensor_config','runtime'):
            assert other.get(field)==base.get(field)


def test_slow_proposal_cannot_delay_shadow_frontier_control():
    from threading import Event
    obs,nav,n,active,evidence,stamp=prepared('shadow')
    active._proposal_result=None
    entered=Event();release=Event()
    def slow(*a,**k):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(candidates=(),reason='unreachable')
    active.planner.plan=slow
    p=pipeline(obs,nav,n,Guard(moving=True),now=stamp)
    p._active=active;p._active_input=evidence;p._admission_snapshot=None
    a=Actuator()
    try:
        p.control_step(a)
        assert entered.wait(1) and not release.is_set()
        assert len(a.commands)==1 and not p._step_decision.goal_id.startswith('reobserve:')
    finally:
        release.set()
        assert active.close(2)


def test_tag_ack_without_usable_view_allows_fresh_retry():
    from contract_helpers import observation
    from neusymnav.contracts import FrameKey
    _,nav,n,active,evidence,stamp=prepared('active')
    xy=(1.45,1.2)
    active.step(n,nav,xy,0.,stamp,evidence)
    key=FrameKey('episode','rgb',2)
    obs=observation(key=key,clock_domain=DOMAIN,capture_monotonic_ns=stamp+1)
    assert active.tag_capture(obs,xy,0.)
    # A later ordinary commit is latest, but tagged acknowledgement survives.
    active.step(n,nav,xy,0.,stamp+2,evidence,capture_result=(key,False))
    assert active.capture_source is None and active.scheduler.active is not None
    assert active.tag_capture(replace(obs,key=replace(key,frame_index=3),capture_monotonic_ns=stamp+3),xy,0.)
