"""Measured body-pose admission stays off control/mapper work."""
from dataclasses import replace
import threading
import time
import numpy as np
import pytest
from neusymnav.mapping.occupancy import RobotGeometry
from test_runtime_scheduling import pipeline,source,wait_for,nav_for,DOMAIN


def pose(obs,xy=(.75,.75)):
    return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,
        clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=xy,yaw_rad=0.)


class Map:
    robot=RobotGeometry('cylinder-v1',.05,.5,0.)
    def update(self,obs):
        nav=nav_for(obs,obs.key.frame_index+1)
        return replace(nav,states=np.zeros((30,30),np.int8),floor_support=np.ones((30,30),bool),
            clearance=np.ones((30,30),np.float32),origin_xy=(0.,0.),resolution_m=.1,robot_geometry_id=self.robot.geometry_id)


def test_measured_body_pose_places_use_footprint_not_camera_position(tmp_path):
    p,_,_=pipeline(tmp_path,mapper=Map())
    try:
        obs=source(0,modality='depth_only')
        assert not np.allclose(obs.T_world_camera[:2,3],(.75,.75))
        p.submit_robot_pose(obs,pose(obs));p.submit(obs)
        wait_for(lambda:p.snapshot() is not None and any(n.kind=='place' for n in p.snapshot().nodes.values()))
        place=next(n for n in p.snapshot().nodes.values() if n.kind=='place')
        assert tuple(place.attributes['xy'])==pytest.approx((.75,.75))
        assert place.attributes['footprint_validated'] is True
    finally:assert p.close(2)['clean_shutdown']


def test_slow_mapper_keeps_pose_pinned_to_each_exact_input(tmp_path):
    entered=threading.Event();release=threading.Event();observed=[]
    class Slow(Map):
        def update(self,obs):
            if obs.key.frame_index==0:entered.set();release.wait(1)
            return super().update(obs)
    from neusymnav.hierarchy.composer import HierarchyComposer
    original=HierarchyComposer.observe_place
    # Capture actual production invocation while preserving footprint planner.
    from unittest.mock import patch
    def consume(self,nav,xy,**proof):
        observed.append((nav.source.frame_index,tuple(xy),proof['pose_source']))
        return original(self,nav,xy,**proof)
    with patch.object(HierarchyComposer,'observe_place',consume):
        p,_,_=pipeline(tmp_path,mapper=Slow())
        try:
            old=source(0,modality='depth_only');new=source(1,modality='depth_only')
            p.submit_robot_pose(old,pose(old));p.submit(old);assert entered.wait(1)
            p.submit_robot_pose(new,pose(new,(1.55,.75)));p.submit(new)
            release.set()
            wait_for(lambda:any(i==1 for i,_,_ in observed))
            assert all(key.frame_index==index for index,_,key in observed)
            assert all(xy==((.75,.75) if index==0 else (1.55,.75)) for index,xy,_ in observed)
            assert p.telemetry()['places']['offered']==2
        finally:release.set();assert p.close(2)['clean_shutdown']


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(robot_xy=(float('nan'),0.)),lambda p:p.update(pose_version=999),
    lambda p:p.update(clock_domain='replay:bad'),lambda p:p.update(extra='camera-inferred'),
])
def test_pose_admission_rejects_invalid_or_inferred_provenance(tmp_path,mutation):
    p,_,_=pipeline(tmp_path,mapper=Map())
    try:
        obs=source(modality='depth_only');proof=pose(obs);mutation(proof)
        with pytest.raises(ValueError):p.submit_robot_pose(obs,proof)
    finally:assert p.close(2)['clean_shutdown']


def test_primary_frame_never_borrows_navigation_body_pose(tmp_path):
    p,_,_=pipeline(tmp_path,mapper=Map())
    try:
        depth=source(modality='depth_only');rgb=source()
        p.submit_robot_pose(depth,pose(depth));p.submit(rgb)
        wait_for(lambda:p.snapshot() is not None)
        assert not any(node.kind=='place' for node in p.snapshot().nodes.values())
        assert p.snapshot().statuses['places']=='unavailable_no_measured_pose'
    finally:assert p.close(2)['clean_shutdown']


def test_new_depth_cannot_actuate_on_old_primary_map_even_permissive_guard(tmp_path):
    from neusymnav.contracts import MotionCommand,NavigationDecision
    entered=threading.Event();release=threading.Event()
    class Slow(Map):
        def update(self,obs):
            if obs.modality=='depth_only':entered.set();release.wait(1)
            return super().update(obs)
    class Guard:
        def bind_nav(self,nav,**kwargs):self.nav=nav
        def filter(self,decision,latest,now):return MotionCommand(latest.key,self.nav.revision,now,now+1000,DOMAIN,.1,0.,'test',latest.capture_monotonic_ns)
    class Navigator:
        def step(self,nav,*args):return NavigationDecision(None,((0.,0.),),.1,0.,nav.revision,'test')
    class Actuator:
        calls=0
        def robot_pose(self,obs):return pose(obs)
        def execute(self,command):self.calls+=1;return dict(executed=True)
    p,_,_=pipeline(tmp_path,mapper=Slow(),navigator=Navigator(),guard=Guard());actuator=Actuator()
    try:
        p.submit(source());wait_for(lambda:p._latest_nav is not None)
        depth=source(modality='depth_only');p.submit(depth);assert entered.wait(1)
        assert p.control_step(actuator)==dict(executed=False,reason='navigation_source_pending')
        assert actuator.calls==0
        release.set();wait_for(lambda:p._latest_nav.source==depth.key)
        assert p.control_step(actuator)['executed']
        assert actuator.calls==1
    finally:release.set();assert p.close(2)['clean_shutdown']
