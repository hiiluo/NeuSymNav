"""Optional mesh precision is applied and certified without changing defaults."""
import json
import sys
import time
from types import SimpleNamespace
import pytest
from test_robot_geometry_binding import native_geometry_stub, GEOMETRY
from neusymnav.sensors.habitat_worker import HabitatCapture
from neusymnav.sensors.client import HabitatPoseSource

PRECISION = {'schema_version': 1, 'cell_height_m': .01}


def test_native_precision_applied_and_acknowledges_actual_start(monkeypatch):
    config, _ = native_geometry_stub(monkeypatch)
    config['navmesh_precision'] = dict(PRECISION)
    capture = HabitatCapture(config)
    try:
        assert capture.sim.pathfinder.nav_mesh_settings.cell_height == .01
        assert capture.navmesh_precision_ack == dict(PRECISION, initial_position_xyz=[0., 0., 0.])
        assert set(capture.geometry_ack) == {'geometry_id', 'radius_m', 'height_m', 'navmesh_radius_m', 'navmesh_height_m', 'navmesh_recomputed'}
    finally:
        capture.close()


def test_native_default_preserves_existing_precision(monkeypatch):
    config, _ = native_geometry_stub(monkeypatch)
    native = sys.modules['habitat_sim']; base = native.Simulator
    class Sim(base):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.pathfinder.nav_mesh_settings = SimpleNamespace(agent_radius=.1, agent_height=1.5, cell_height=.2)
    native.Simulator = Sim
    capture = HabitatCapture(config)
    try:
        assert capture.sim.pathfinder.nav_mesh_settings.cell_height == .2
        assert capture.navmesh_precision_ack is None
    finally:
        capture.close()


@pytest.mark.parametrize('bad', [None, {}, {'schema_version': True, 'cell_height_m': .01},
    {'schema_version': 1, 'cell_height_m': True}, {'schema_version': 1, 'cell_height_m': .02},
    {'schema_version': 1, 'cell_height_m': float('nan')}, dict(PRECISION, extra=1)])
def test_invalid_precision_fails_before_native_construction(monkeypatch,bad):
    config,calls = native_geometry_stub(monkeypatch); config['navmesh_precision']=bad
    with pytest.raises(ValueError,match='precision'):
        HabitatCapture(config)
    assert not calls


def test_precision_requires_geometry_before_native_construction(monkeypatch):
    config,calls=native_geometry_stub(monkeypatch); config.pop('agent_geometry');config['navmesh_precision']=PRECISION
    with pytest.raises(ValueError,match='precision'):
        HabitatCapture(config)
    assert not calls


def test_native_precision_readback_mismatch_closes_simulator(monkeypatch):
    config,calls=native_geometry_stub(monkeypatch);config['navmesh_precision']=PRECISION
    native=sys.modules['habitat_sim'];base=native.Simulator
    class Sim(base):
        def recompute_navmesh(self,pathfinder,settings):
            result=super().recompute_navmesh(pathfinder,settings)
            pathfinder.nav_mesh_settings.cell_height=.02
            return result
    native.Simulator=Sim
    with pytest.raises(RuntimeError,match='precision'):
        HabitatCapture(config)
    assert calls[-1]==('close',)


def ready_script(tmp_path, precision):
    ack=dict(GEOMETRY,navmesh_radius_m=.125,navmesh_height_m=1.,navmesh_recomputed=True)
    ready=dict(ready=True,wire_version=1,pose_source='simulator_ground_truth',execution=None,agent_geometry=ack,navmesh_precision=precision)
    script=tmp_path/'ready.py'
    script.write_text('import json,sys\n'+f'print(json.dumps({ready!r}),flush=True)\n'+'for line in sys.stdin:\n if json.loads(line)["op"]=="close":break\n')
    return script


def client_config():
    return dict(agent_geometry=GEOMETRY,navmesh_precision=PRECISION,initial_position=[1.,.0010702843,-5.])


@pytest.mark.parametrize('bad',[None, {}, dict(PRECISION,initial_position_xyz=[1., .01, -5.]),
    dict(PRECISION,cell_height_m=.02,initial_position_xyz=[1.,.0010702843,-5.]),
    dict(PRECISION,initial_position_xyz=[1.,.0010702843,-5.],extra=1)])
def test_ipc_rejects_missing_or_mismatched_precision_ack(tmp_path,bad):
    with pytest.raises(ValueError,match='precision'):
        HabitatPoseSource(python=sys.executable,config=client_config(),worker_script=ready_script(tmp_path,bad),timeout_s=3)


def test_ipc_metadata_retains_precision_ack(tmp_path):
    ack=dict(PRECISION,initial_position_xyz=[1.,.0010702843,-5.])
    source=HabitatPoseSource(python=sys.executable,config=client_config(),worker_script=ready_script(tmp_path,ack),timeout_s=3)
    try:
        assert source.runtime_metadata['navmesh_precision']==ack
    finally: source.close()


def test_real_worker_ready_contains_measured_precision_and_position(tmp_path, monkeypatch):
    from pathlib import Path
    config, _ = native_geometry_stub(monkeypatch)
    config['navmesh_precision'] = dict(PRECISION)
    script=tmp_path/'worker.py'
    tests=Path(__file__).resolve().parent
    script.write_text(f'import sys\nsys.path.insert(0,{str(tests)!r})\nimport pytest\nfrom test_robot_geometry_binding import native_geometry_stub\nnative_geometry_stub(pytest.MonkeyPatch())\nfrom neusymnav.sensors.habitat_worker import main\nraise SystemExit(main())\n')
    source=HabitatPoseSource(python=sys.executable,config=config,worker_script=script,timeout_s=3)
    try:
        assert source.runtime_metadata['navmesh_precision'] == dict(PRECISION,initial_position_xyz=[0.,0.,0.])
        assert source.runtime_metadata['execution']['seed']==7
    finally:
        source.close()


def test_late_precision_validation_closes_worker_without_publishing_ack(tmp_path,monkeypatch):
    from neusymnav.sensors import client
    ack=dict(PRECISION,initial_position_xyz=[1.,.0010702843,-5.])
    real=client._validate_navmesh_precision_ack
    real_clock=time.monotonic
    offset=[0.]
    monkeypatch.setattr(client.time,'monotonic',lambda:real_clock()+offset[0])
    def late(*args):
        value=real(*args)
        offset[0]=10.
        return value
    monkeypatch.setattr(client,'_validate_navmesh_precision_ack',late)
    source=client.HabitatPoseSource.__new__(client.HabitatPoseSource)
    with pytest.raises(TimeoutError):
        source.__init__(python=sys.executable,config=client_config(),worker_script=ready_script(tmp_path,ack),timeout_s=3)
    assert source.process.poll() is not None
    assert 'navmesh_precision' not in source.runtime_metadata


def test_unsolicited_precision_ack_rejected(tmp_path):
    config=client_config();config.pop('navmesh_precision')
    ack=dict(PRECISION,initial_position_xyz=[1.,.0010702843,-5.])
    with pytest.raises(ValueError,match='precision'):
        HabitatPoseSource(python=sys.executable,config=config,worker_script=ready_script(tmp_path,ack),timeout_s=3)
