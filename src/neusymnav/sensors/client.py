"""Host-side PoseSource using bounded JSON/NPZ IPC to a native interpreter.

No Habitat/Torch import reaches this process. Requests are serialized and have a
finite timeout. A timeout/protocol failure closes the process, preventing late
responses from masquerading as a later fresh capture. Diagnostics are bounded.
"""
from __future__ import annotations

import base64
import copy
import threading
import io
import json
import hashlib
import math
from pathlib import Path
from typing import Mapping
import zipfile
import time
from dataclasses import asdict

import numpy as np

from neusymnav.contracts import FrameKey, Observation, MotionCommand
from .habitat_worker import MAX_WIRE_BYTES, _ARRAY_NAMES, _checksum, _canonical, host_clock_domain


_METADATA = {'episode_id', 'sensor_id', 'frame_index', 'capture_monotonic_ns', 'clock_domain',
             'sim_time_s', 'calibration_id', 'pose_version', 'modality',
             'coordinate_convention', 'depth_convention'}


def _check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('sensor decode/validation exceeded whole-operation deadline')


def observation_from_packet(packet: dict, *, deadline: float | None = None) -> Observation:
    """Validate the closed wire schema and checksum before constructing arrays."""
    _check_deadline(deadline)
    if (not isinstance(packet, dict) or set(packet) != {'wire_version', 'metadata', 'arrays_b64', 'sha256'}
            or type(packet['wire_version']) is not int or packet['wire_version'] != 1):
        raise ValueError('invalid sensor packet fields/version')
    metadata = packet['metadata']
    if not isinstance(metadata, dict) or set(metadata) != _METADATA:
        raise ValueError('invalid sensor metadata fields')
    try:
        encoded = packet['arrays_b64']
        if not isinstance(encoded, str) or len(encoded) > MAX_WIRE_BYTES:
            raise ValueError('wire payload exceeds bound')
        payload = base64.b64decode(encoded, validate=True)
        if _checksum(metadata, payload) != packet['sha256']:
            raise ValueError('sensor packet checksum mismatch')
        _check_deadline(deadline)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if (len(archive.infolist()) != len(_ARRAY_NAMES)
                    or set(archive.namelist()) != {name + '.npy' for name in _ARRAY_NAMES}
                    or sum(x.file_size for x in archive.infolist()) > MAX_WIRE_BYTES):
                raise ValueError('invalid/bounded sensor array archive')
            arrays = {}
            for name in _ARRAY_NAMES:
                info = archive.getinfo(name + '.npy')
                with archive.open(info) as member:
                    version = np.lib.format.read_magic(member)
                    if version == (1, 0):
                        shape, fortran, dtype = np.lib.format.read_array_header_1_0(member)
                    elif version == (2, 0):
                        shape, fortran, dtype = np.lib.format.read_array_header_2_0(member)
                    else:
                        raise ValueError('unsupported NumPy header version')
                    if dtype.kind not in 'biuf' or len(shape) > 3:
                        raise ValueError('unsafe NumPy header dtype/shape')
                    count = 1
                    for dimension in shape:
                        if type(dimension) is not int or dimension < 0:
                            raise ValueError('invalid NumPy header shape')
                        count *= dimension
                    size = count * dtype.itemsize
                    if size > MAX_WIRE_BYTES or size != info.file_size - member.tell():
                        raise ValueError('NumPy header byte size exceeds archive bound')
                    data = member.read(size)
                    if len(data) != size:
                        raise ValueError('truncated NumPy payload size')
                    arrays[name] = np.frombuffer(data, dtype=dtype).reshape(shape, order='F' if fortran else 'C')
                    _check_deadline(deadline)
        values = dict(metadata)
        key = FrameKey(values.pop('episode_id'), values.pop('sensor_id'), values.pop('frame_index'))
        result = Observation(key=key, **values, **arrays)
        _check_deadline(deadline)
        return result
    except TimeoutError:
        raise
    except (OSError, TypeError, KeyError, zipfile.BadZipFile, OverflowError) as exc:
        raise ValueError('invalid sensor wire payload') from exc


def _validate_geometry_ack(requested, actual):
    """Require both native agent and collision-navmesh dimensions on new launches."""
    if requested is None:
        if actual is not None:raise ValueError('unsolicited native agent geometry ACK')
        return None
    fields={'geometry_id','radius_m','height_m','navmesh_radius_m','navmesh_height_m','navmesh_recomputed'}
    if (not isinstance(actual,dict) or set(actual)!=fields or actual['geometry_id']!=requested['geometry_id']
            or actual['navmesh_recomputed'] is not True):
        raise ValueError('native agent geometry ACK absent or mismatched')
    for key,target in [('radius_m','radius_m'),('height_m','height_m'),('navmesh_radius_m','radius_m'),('navmesh_height_m','height_m')]:
        if (type(actual[key]) not in (int,float) or not math.isfinite(actual[key])
                or not math.isclose(actual[key],requested[target],rel_tol=0,abs_tol=1e-6)):
            raise ValueError('native agent geometry ACK dimensions mismatch')
    return dict(actual)


class HabitatPoseSource:
    """Real worker launch with independently configured ``python`` and scene.

    ``worker_script`` selects an alternative implementation of the same closed
    wire protocol, useful for process-boundary tests. The default is always the
    real standalone Habitat entrypoint. ``step`` executes one configured Habitat
    action; P07 control uses execute(MotionCommand), which validates at the worker.
    """
    def __init__(self, *, python: str | Path, config: Mapping | str | Path,
                 timeout_s: float = 10., worker_script: str | Path | None = None):
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('timeout_s must be positive finite')
        interpreter = Path(python)
        if not interpreter.is_absolute() or not interpreter.is_file():
            raise ValueError('python must be an explicit absolute interpreter path')
        script = Path(worker_script) if worker_script else Path(__file__).with_name('habitat_worker.py')
        command = [str(interpreter), '-u', str(script.resolve())]
        if isinstance(config, Mapping):
            launch_config = json.loads(_canonical(dict(config)))
        else:
            path = Path(config)
            if path.stat().st_size > 256 * 1024:
                raise ValueError('sensor launch config exceeds 256 KiB')
            launch_config = json.loads(path.read_text())
        if not isinstance(launch_config, dict):
            raise ValueError('sensor launch config must be an object')
        encoded_config = _canonical(launch_config)
        if len(encoded_config) > 256 * 1024:
            raise ValueError('sensor launch config exceeds 256 KiB')
        seed_requested = 'seed' in launch_config
        if seed_requested and (type(launch_config['seed']) is not int or not 0 <= launch_config['seed'] <= 2**32 - 1):
            raise ValueError('sensor seed must be a uint32 integer')
        if seed_requested and (not isinstance(launch_config.get('episode_id'), str) or not launch_config['episode_id']):
            raise ValueError('seed execution requires an explicit episode_id')
        # Snapshot file inputs too: ACK hashes exactly the config passed to the
        # process, not mutable bytes that it could reread later from another path.
        command += ['--config-json', encoded_config.decode()]
        self.launch_config_sha256 = hashlib.sha256(encoded_config).hexdigest()
        self._runtime_metadata = dict(schema_version=1, launch_config_sha256=self.launch_config_sha256,
            worker_script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(), execution=None,
            seed_status='not_requested', actual_resolution_hw={})
        from ..perception.detector_client import _BoundedProcess
        self.timeout_s = timeout_s
        self._wire = _BoundedProcess(command, timeout_s=timeout_s, response_limit=MAX_WIRE_BYTES, lines=True)
        self._lock = self._wire.lock
        self._closed = False
        self._last = {}
        self._episode = None
        self._retired_episodes = set()
        self._last_capture_ns = -1
        self._domain = None
        self._navigation = None
        self._navigation_pose = None
        self._last_actuation_proof = None
        self._proof_lock = threading.Lock()
        self._proof_generation = 0
        self.diagnostics = self._wire.diagnostics
        try:
            ready_deadline = time.monotonic() + self.timeout_s
            self._wire.start()
            self.process = self._wire.process
            ready = self._wire.receive(ready_deadline)
            if ready.get('ready') is not True or type(ready.get('wire_version')) is not int or ready['wire_version'] != 1:
                raise RuntimeError('sensor worker unavailable: ' + str(ready.get('error', ready)))
            geometry = _validate_geometry_ack(launch_config.get('agent_geometry'),ready.get('agent_geometry'))
            if geometry is not None:self._runtime_metadata['agent_geometry']=geometry
            execution = ready.get('execution')
            if seed_requested:
                fields = {'schema_version','episode_id','clock_domain','seed','seed_method',
                          'seed_applied','config_sha256','runtime_version'}
                if (not isinstance(execution, dict) or set(execution) != fields
                    or type(execution['schema_version']) is not int or execution['schema_version'] != 1
                    or type(execution['seed']) is not int or execution['seed'] != launch_config['seed']
                    or execution['seed_applied'] is not True
                    or execution['seed_method'] != 'habitat_sim.Simulator.seed'
                    or execution['episode_id'] != launch_config['episode_id']
                    or execution['clock_domain'] != host_clock_domain()
                    or execution['config_sha256'] != self.launch_config_sha256
                    or not isinstance(execution['runtime_version'], str) or not 0 < len(execution['runtime_version']) <= 256
                    or ready.get('pose_source') != 'simulator_ground_truth'):
                    raise ValueError('sensor seed execution ACK absent or mismatched')
            elif execution is not None:
                raise ValueError('unsolicited seed execution ACK without requested seed')
            # Receipt is only one part of startup. Config/clock/seed proof may
            # involve I/O too; never publish applied proof after this deadline.
            _check_deadline(ready_deadline)
            if seed_requested:
                self._runtime_metadata.update(execution=dict(execution), seed_status='applied')
                self._episode = execution['episode_id']; self._domain = execution['clock_domain']
        except Exception:
            self.close()
            raise

    @property
    def is_alive(self):
        return self._wire.process is not None and self._wire.process.poll() is None

    @property
    def runtime_metadata(self):
        """Independent bounded snapshot; dimensions have decoded-array support."""
        return json.loads(json.dumps(self._runtime_metadata))

    def _request(self, op: str, *, _deadline: float | None = None, **values) -> dict:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('sensor request already in flight')
        failed = False
        try:
            if self._closed or self._wire.closed.is_set():
                raise RuntimeError('sensor worker is closed')
            deadline = _deadline if _deadline is not None else time.monotonic() + self.timeout_s
            self._wire.send(dict(op=op, **values), deadline, limit=4096)
            response = self._wire.receive(deadline)
            if response.get('ok') is not True:
                raise RuntimeError('sensor request failed: ' + str(response.get('error')))
            _check_deadline(deadline)
            return response
        except Exception:
            failed = True
            raise
        finally:
            self._lock.release()
            if failed:
                self.close()

    def _capture(self, op: str, modality: str) -> Observation:
        self._invalidate_actuation_proof()
        deadline = time.monotonic() + self.timeout_s
        try:
            response = self._request(op, _deadline=deadline)
            result = observation_from_packet(response['packet'], deadline=deadline)
            if result.modality != modality:
                raise ValueError('sensor modality mismatch')
            if result.clock_domain.startswith('replay:'):
                raise ValueError('historical replay cannot be live sensor input')
            if self._episode is not None and result.key.episode_id != self._episode:
                raise ValueError('episode changed without explicit reset')
            if (result.key.frame_index <= self._last.get(result.key.sensor_id, -1)
                    or result.capture_monotonic_ns <= self._last_capture_ns):
                raise ValueError('duplicate/nonmonotonic sensor capture')
            if self._domain is not None and result.clock_domain != self._domain:
                raise ValueError('live sensor clock domain changed')
            lane = 'primary' if modality == 'rgbd' else 'navigation'
            pose = None
            if modality == 'depth_only' and 'pose' in response:
                pose = self._validated_pose(response['pose'], result)
            previous = self._runtime_metadata['actual_resolution_hw'].get(lane)
            dimensions = list(result.depth_m.shape)
            resolution_record = dict(resolution_hw=dimensions,
                source=asdict(result.key), capture_monotonic_ns=result.capture_monotonic_ns,
                clock_domain=result.clock_domain, samples=1 if previous is None else previous['samples']+1,
                changed=previous is not None and (previous['changed'] or previous['resolution_hw'] != dimensions))
            _check_deadline(deadline)
            self._episode = result.key.episode_id
            self._last[result.key.sensor_id] = result.key.frame_index
            self._last_capture_ns, self._domain = result.capture_monotonic_ns, result.clock_domain
            if modality == 'depth_only':
                self._navigation = result
                self._navigation_pose = pose
            self._runtime_metadata['actual_resolution_hw'][lane] = resolution_record
            return result
        except Exception:
            self.close()
            raise

    def capture(self) -> Observation:
        return self._capture('capture', 'rgbd')

    def capture_navigation(self) -> Observation:
        return self._capture('capture_navigation', 'depth_only')

    def robot_pose(self, source: Observation | FrameKey | None = None) -> dict:
        observation = self._navigation
        if observation is None:
            raise ValueError('fresh navigation capture required for robot pose')
        expected = source.key if isinstance(source, Observation) else source
        if expected is not None and expected != observation.key:
            raise ValueError('robot pose source mismatch')
        if self._navigation_pose is not None:
            return dict(self._navigation_pose)
        result = self._request('robot_pose')['pose']
        self._navigation_pose = self._validated_pose(result, observation)
        return dict(self._navigation_pose)

    def _validated_pose(self, result, observation):
        names = {'source', 'capture_monotonic_ns', 'clock_domain', 'pose_version', 'robot_xy', 'yaw_rad'}
        if not isinstance(result, dict) or set(result) != names:
            self.close()
            raise ValueError('invalid robot pose response')
        if (result['source'] != asdict(observation.key)
                or type(result['capture_monotonic_ns']) is not int
                or type(result['pose_version']) is not int
                or result['capture_monotonic_ns'] != observation.capture_monotonic_ns
                or result['pose_version'] != observation.pose_version
                or result['clock_domain'] != observation.clock_domain
                or not isinstance(result['robot_xy'], list) or len(result['robot_xy']) != 2
                or any(type(v) not in (float, int) or not math.isfinite(v)
                       for v in (*result['robot_xy'], result['yaw_rad']))):
            self.close()
            raise ValueError('robot pose source/geometry mismatch')
        return dict(result, source=observation.key, robot_xy=tuple(result['robot_xy']))

    def _invalidate_actuation_proof(self):
        # Held only for a scalar generation/assignment, never across IPC or
        # validation. A later operation cannot revive an earlier proof.
        with self._proof_lock:
            self._last_actuation_proof = None
            self._proof_generation += 1
            return self._proof_generation

    @property
    def last_actuation_proof(self):
        with self._proof_lock:
            return copy.deepcopy(self._last_actuation_proof)

    def execute(self, command: MotionCommand) -> dict:
        deadline = time.monotonic() + self.timeout_s
        generation = self._invalidate_actuation_proof()
        if not isinstance(command, MotionCommand):
            raise TypeError('execute requires MotionCommand')
        observation, self._navigation = self._navigation, None
        self._navigation_pose = None
        # Worker is authoritative after IPC latency. Even rejected commands
        # consume the capture. A proof never grants motion authority.
        version = observation.pose_version if observation is not None else 0
        try:
            response = self._request('execute', _deadline=deadline, command=asdict(command), pose_version=version)
            result = response.get('actuation')
            if (not isinstance(result, dict) or set(result) != {'executed', 'reason', 'actions', 'displacement_m', 'yaw_rad'}
                    or type(result['executed']) is not bool or not isinstance(result['reason'], str)
                    or not isinstance(result['actions'], list)
                    or any(type(result[n]) not in (int, float) or not math.isfinite(result[n])
                           for n in ('displacement_m', 'yaw_rad'))):
                raise ValueError('invalid actuator response')
            proof = response.get('actuation_proof')
            if proof is not None:
                from ..runtime.actuation_measurements import validate_actuation_proof
                checked = validate_actuation_proof(proof, command, observation)
                actions = checked['proof']['actions']
                if (result['actions'] != [dict(action=a['action'],amount=a['amount']) for a in actions]
                    or result['executed'] != bool(actions) or result['reason'] != proof['reason']
                    or abs(result['displacement_m']-checked['body_translation_m']) > 1e-7):
                    raise ValueError('actuation result/proof mismatch')
                if actions:
                    yaw = math.remainder(actions[-1]['yaw_after_rad']-actions[0]['yaw_before_rad'],2*math.pi)
                    if abs(math.remainder(result['yaw_rad']-yaw,2*math.pi))>1e-7:
                        raise ValueError('actuation yaw proof mismatch')
            with self._proof_lock:
                _check_deadline(deadline)
                if generation != self._proof_generation:
                    raise RuntimeError('actuation proof superseded by another sensor operation')
                self._last_actuation_proof = None if proof is None else checked['proof']
            return result
        except Exception:
            self.close()
            raise

    def step(self, action: str) -> None:
        self._invalidate_actuation_proof()
        self._navigation = None
        self._navigation_pose = None
        self._request('step', action=action)

    def reset(self, episode_id: str, *, position: tuple, rotation_xyzw: tuple) -> None:
        self._invalidate_actuation_proof()
        if not episode_id or episode_id == self._episode or episode_id in self._retired_episodes:
            raise ValueError('reset needs new unused episode_id')
        self._request('reset', episode_id=episode_id, position=position, rotation_xyzw=rotation_xyzw)
        if self._runtime_metadata['execution'] is not None:
            self._runtime_metadata.update(execution=None, seed_status='unsupported_after_reset')
        self._runtime_metadata['actual_resolution_hw'] = {}
        if self._episode:
            self._retired_episodes.add(self._episode)
        self._episode = episode_id
        self._last.clear()
        self._navigation = None
        self._navigation_pose = None
        # Host clock stays comparable and is never reset into the past.

    def close(self, timeout_s: float = 1.) -> dict:
        self._invalidate_actuation_proof()
        self._closed = True
        self._navigation = None
        self._navigation_pose = None
        return self._wire.close(timeout_s)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
