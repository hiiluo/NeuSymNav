"""Physical dimensions must agree across native agent, navmesh and navigation."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
from test_sensor_execution_metadata import habitat_stub
from neusymnav.sensors.habitat_worker import HabitatCapture

GEOMETRY=dict(geometry_id='cylinder-r125-h1000-v1',radius_m=.125,height_m=1.)

def native_geometry_stub(monkeypatch,*,success=True):
    config,calls=habitat_stub(monkeypatch);native=sys.modules['habitat_sim'];base=native.Simulator
    class Settings:
        def set_defaults(self):self.agent_radius=.1;self.agent_height=1.5
    class Sim(base):
        def __init__(self,config):
            super().__init__(config);self.agent.agent_config=config[1][0]
            self.pathfinder=SimpleNamespace(nav_mesh_settings=None)
        def recompute_navmesh(self,pathfinder,settings):
            calls.append(('navmesh',settings.agent_radius,settings.agent_height))
            pathfinder.nav_mesh_settings=settings
            return success
    native.Simulator=Sim;native.NavMeshSettings=Settings
    config['agent_geometry']=dict(GEOMETRY)
    return config,calls

def test_native_agent_and_navmesh_receive_same_geometry_before_seed(monkeypatch):
    config,calls=native_geometry_stub(monkeypatch);capture=HabitatCapture(config)
    try:
        assert capture.agent.agent_config.radius==.125
        assert capture.agent.agent_config.height==1.
        assert capture.sim.pathfinder.nav_mesh_settings.agent_radius==.125
        assert capture.sim.pathfinder.nav_mesh_settings.agent_height==1.
        assert calls.index(('navmesh',.125,1.))<calls.index(('seed',7))
        assert capture.geometry_ack['geometry_id']==GEOMETRY['geometry_id']
        assert capture.geometry_ack['navmesh_recomputed'] is True
    finally:capture.close()

def test_navmesh_failure_closes_and_never_acknowledges_geometry(monkeypatch):
    config,calls=native_geometry_stub(monkeypatch,success=False)
    with pytest.raises(RuntimeError,match='navmesh'):HabitatCapture(config)
    assert calls[-1]==('close',)

@pytest.mark.parametrize('change',[{'radius_m':0},{'radius_m':True},{'height_m':float('nan')},{'height_m':-1},{'extra':1},{'geometry_id':''}])
def test_invalid_geometry_rejected_before_native_import(monkeypatch,change):
    config,calls=habitat_stub(monkeypatch);config['agent_geometry']=dict(GEOMETRY,**change)
    with pytest.raises(ValueError,match='geometry'):HabitatCapture(config)
    assert calls==[]

def test_launcher_derives_geometry_from_navigation_not_independent_sensor_config(tmp_path):
    from neusymnav.runtime.launcher import _sensor_launch_configuration
    config=SimpleNamespace(data=dict(sensor_config=dict(scene={'path':'old'},scene_dataset={'path':'old'},seed=0),episode={'id':'episode'},navigation={'robot':dict(GEOMETRY,margin_m=.05)}))
    result=_sensor_launch_configuration(config,dict(scene=Path('/scene'),scene_dataset=Path('/dataset')))
    assert result['agent_geometry']==GEOMETRY
    assert result['scene_id']=='/scene' and result['episode_id']=='episode'
    assert 'agent_geometry' not in config.data['sensor_config']


def test_requested_body_opens_observed_narrow_corridor_without_unknown_relaxation():
    import numpy as np
    from neusymnav.contracts import GridState
    from neusymnav.navigation._grid import footprint_mask
    states=np.full((21,21),GridState.OCCUPIED,np.int8)
    states[:,6:15]=GridState.FREE  # .45m fully observed strip, .05m grid.
    snapshot=SimpleNamespace(states=states,resolution_m=.05)
    assert footprint_mask(snapshot,.125+.05)[10,10]
    assert not footprint_mask(snapshot,.2+.05)[10,10]
    states[10,10]=GridState.UNKNOWN
    assert not footprint_mask(snapshot,.125+.05)[10,10]

def test_client_rejects_missing_or_mismatched_native_body_ack():
    from neusymnav.sensors.client import _validate_geometry_ack
    ack=dict(GEOMETRY,navmesh_radius_m=.125,navmesh_height_m=1.,navmesh_recomputed=True)
    assert _validate_geometry_ack(GEOMETRY,ack)==ack
    for bad in (None,dict(ack,radius_m=.2),dict(ack,navmesh_recomputed=False),dict(ack,navmesh_height_m=1.5),dict(ack,radius_m=True)):
        with pytest.raises(ValueError):_validate_geometry_ack(GEOMETRY,bad)

def test_existing_navmesh_nonbody_settings_preserved(monkeypatch):
    config,calls=native_geometry_stub(monkeypatch);native=sys.modules['habitat_sim'];base=native.Simulator
    class Sim(base):
        def __init__(self,config):
            super().__init__(config)
            self.pathfinder.nav_mesh_settings=SimpleNamespace(agent_radius=.1,agent_height=1.5,cell_size=.0375,agent_max_climb=.02)
    native.Simulator=Sim
    capture=HabitatCapture(config)
    try:
        settings=capture.sim.pathfinder.nav_mesh_settings
        assert settings.cell_size==.0375 and settings.agent_max_climb==.02
    finally:capture.close()


def test_motion_guard_uses_new_body_and_rejects_narrow_unknown_or_low_clearance():
    import numpy as np
    from neusymnav.contracts import GridState
    from neusymnav.mapping.occupancy import RobotGeometry
    from neusymnav.navigation.safety import MotionGuard
    robot=RobotGeometry(**GEOMETRY,margin_m=.05)
    guard=MotionGuard(SimpleNamespace(robot=robot),clock_domain='host_monotonic:fixture')
    states=np.full((21,21),GridState.OCCUPIED,np.int8);states[:,6:15]=GridState.FREE
    floor=np.ones((21,21),bool);clear=np.ones((21,21),np.float32)
    nav=SimpleNamespace(origin_xy=(0.,0.),resolution_m=.05,states=states,floor_support=floor,clearance=clear)
    point=(.525,.525)
    assert guard._clear(nav,point,point)
    states[10,10]=GridState.UNKNOWN
    assert not guard._clear(nav,point,point)
    states[10,10]=GridState.FREE;clear[10,10]=.95
    assert not guard._clear(nav,point,point)
    clear[10,10]=1.;floor[10,10]=False
    assert not guard._clear(nav,point,point)
    floor[10,10]=True;states[:,:]=GridState.OCCUPIED;states[:,8:14]=GridState.FREE
    assert not guard._clear(nav,point,point)
