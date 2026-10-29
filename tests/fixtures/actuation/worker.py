"""External CPU process using the real actuator with a minimal simulator hook."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
# proof_worker rewrites the src entry above when copying this file. Derive the
# fixture helper directory from that resolved package root, not the copy path.
sys.path.insert(0, str(Path(sys.path[0]).resolve().parent / 'tests'))
from neusymnav.sensors.habitat_worker import HabitatCapture, host_clock_domain, encode_packet, normalize_capture
from test_quantized_yaw_preflight import BodyState,attach_native_yaw,turn_state

config = json.loads(sys.argv[sys.argv.index('--config-json') + 1])
worker = HabitatCapture.__new__(HabitatCapture)
worker.clock_domain = host_clock_domain()
worker.episode_id = 'episode'
worker.pose_version = 0
worker._navigation_state = None
worker._last_map_revision = -1
state = BodyState([1., 2., 3.])
worker.agent = SimpleNamespace(get_state=lambda: state, agent_config=SimpleNamespace(action_space={}),
                               controls=SimpleNamespace())
def act(action):
    spec = worker.agent.agent_config.action_space[action]
    if spec.name == 'move_forward':
        candidate = state.position + state.rotation @ np.array([0., 0., -spec.actuation.amount])
        state.position = worker.agent.controls.move_filter_fn(state.position, candidate)
    else:
        turn_state(state,spec.name,spec.actuation.amount)
world_time = [0.]
def physics(dt):
    world_time[0] += dt
def step(action):
    worker.agent.act(action)
    worker.sim.step_physics(1./60.)
    return worker.sim.get_sensor_observations()
worker.agent.act = act
attach_native_yaw(worker,state)
worker.sim = SimpleNamespace(step_filter=lambda a,b:b, step=step, step_physics=physics,
    get_world_time=lambda:world_time[0], get_sensor_observations=lambda:{})
worker.habitat_sim = SimpleNamespace(agent=SimpleNamespace(
    ActionSpec=lambda name, actuation: SimpleNamespace(name=name, actuation=actuation),
    ActuationSpec=lambda amount: SimpleNamespace(amount=amount)))
index = 0
print(json.dumps(dict(ready=True,wire_version=1)), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    op = request['op']
    if op == 'capture_navigation':
        capture = time.monotonic_ns()
        packet = normalize_capture(rgb=None,depth=np.ones((2,3),np.float32),K=np.eye(3),T_world_habitat=np.eye(4),
            episode_id='episode',sensor_id='navigation',frame_index=index,capture_monotonic_ns=capture,
            clock_domain=worker.clock_domain,sim_time_s=worker.sim.get_world_time(),calibration_id='fixture',pose_version=worker.pose_version,
            modality='depth_only',depth_min_m=.1,depth_max_m=10.)
        from neusymnav.sensors.habitat_worker import canonical_robot_pose
        worker._navigation_state = dict(packet['metadata'], **canonical_robot_pose(state))
        index += 1
        result = dict(packet=encode_packet(packet))
    elif op == 'robot_pose':
        result = dict(pose=worker.robot_pose())
    elif op == 'execute':
        time.sleep(config.get('delay_s',0.))
        result = dict(actuation=worker.execute(request['command'],request['pose_version']))
    else:
        raise ValueError('invalid fixture operation')
    print(json.dumps(dict(ok=True,**result)),flush=True)
