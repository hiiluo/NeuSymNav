import numpy as np
from test_sensor_actuation import actuator,execute


def test_float32_native_endpoint_on_exact_segment_is_accepted(monkeypatch):
    worker,command,_,_,_=actuator(monkeypatch)
    worker.sim.step_filter=lambda start,end:end
    execute(worker,command)
    start=np.array([1.4296170473098755,-1.8656576871871948,.9186217784881592],np.float32)
    end=np.array([1.4283196926116943,-1.864205002784729,.9187875986099243],np.float32)
    assert np.array_equal(worker.agent.controls.move_filter_fn(start,end),end)


def test_float32_candidate_outside_segment_still_stops(monkeypatch):
    worker,command,_,_,_=actuator(monkeypatch)
    candidate_box=[]
    worker.sim.step_filter=lambda a,b:candidate_box[0] if candidate_box else b
    execute(worker,command)
    start=np.array([1.,2.,3.],np.float32);end=np.array([1.001,2.,3.],np.float32)
    for candidate in [end+np.array([.001,0,0],np.float32),end+np.array([0,.0001,0],np.float32)]:
        candidate_box[:]=[candidate]
        assert np.array_equal(worker.agent.controls.move_filter_fn(start,end),start)
