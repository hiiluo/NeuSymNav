"""Explicit local launch/replay composition. No native/fixture fallback exists."""
from __future__ import annotations
from dataclasses import replace
from collections.abc import Mapping
import json
import hashlib
import importlib.metadata
import sys
import uuid
import math
from pathlib import Path
import sqlite3
import threading
import time

from ..contracts import DetectionBatch, FrameKey, Observation, from_dict
from ..contracts.serialization import dumps, loads
from ..mapping.occupancy import NavMapper, RobotGeometry
from ..mapping._raycast_kernel import numba_available, warmup_raycast_kernel
from ..objects.store import ObjectOwner
from ..recording.replay import ReplayReader, ReplaySession, _canonical, _write_atomic
from ..recording.writer import ReplayWriter
from ..verification.ledger import VerificationOwner
from .configuration import load_config, file_sha256
from .coordinator import Pipeline, StaleNavigationCapture


def _write(path,data):_write_atomic(Path(path),_canonical(data))


def _measurement_payload(artifact,*,max_bytes=16*1024**2):
    """Bounded final export outside control; no silent truncation claim."""
    if type(max_bytes) is not int or not 1<=max_bytes<=64*1024**2:
        raise ValueError('measurement export byte cap must be an integer in [1,64MiB]')
    payload=_canonical(artifact)
    if len(payload)<=max_bytes:return payload
    artifact['completion'].update(complete=False,export_byte_overflow=True)
    artifact['collector']['complete']=False
    trace=artifact['collector']['trace']
    trace['export_dropped_records']=len(trace['records'])
    trace['dropped']=min(2**63-1,trace['dropped']+len(trace['records']))
    trace['records']=[];trace['charged_bytes']=0
    act=artifact['actuation']
    act['export_dropped_records']=len(act['proof_records'])+len(act['body_pose_records'])
    act['proof_records']=[];act['body_pose_records']=[]
    payload=_canonical(artifact)
    if len(payload)>max_bytes:raise RuntimeError('measurement export exceeds bounded summary size')
    return payload


def _probe_interpreter(python,modules,label,*,setup_script=None,timeout_s=3.):
    """Read-only bounded interpreter/dependency probe; imports no model runtime."""
    import subprocess
    if (type(timeout_s) not in (int,float) or not math.isfinite(timeout_s)
            or not 0<timeout_s<=60.):raise ValueError('interpreter probe timeout must be in (0, 60] seconds')
    program=("import importlib.util,importlib.metadata,json,sys; "
        "print(json.dumps(dict(version=list(sys.version_info[:3]),executable=sys.executable,prefix=sys.prefix,missing=[m for m in "+repr(list(modules))+" if importlib.util.find_spec(m) is None])))")
    try:
        # A sourced native setup can provide Python extension packages through
        # PYTHONPATH (Hydra's branch-local Spark-DSG bindings use this layout).
        # Isolated mode silently drops that path and makes a valid setup appear
        # broken, so retain -I only for workers without an explicit setup script.
        command=[str(python),*([] if setup_script is not None else ['-I']),'-c',program]
        if setup_script is not None:
            command=['/bin/bash','-c','set -eo pipefail; source "$1"; shift; exec "$@"',
                'hydra-interpreter-probe',str(setup_script),*command]
        result=subprocess.run(command,capture_output=True,timeout=float(timeout_s),check=False)
        if result.returncode or len(result.stdout)>4096:raise ValueError(label+' interpreter probe failed; check configured environment')
        info=json.loads(result.stdout)
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:raise ValueError(label+' interpreter unavailable: '+str(exc)) from exc
    if label in {'detector','ui','raycast'} and tuple(info['version'][:2])<(3,12):raise ValueError(label+' interpreter requires Python >=3.12; select an existing compatible environment')
    if info['missing']:raise ValueError(label+' environment missing '+', '.join(info['missing'])+'; install/select the required environment explicitly before launch')
    return info


def _provenance(config):
    package=Path(__file__).resolve().parents[1]
    sources={str(path.relative_to(package)):file_sha256(path) for path in sorted(package.rglob('*.py'))}
    versions={}
    for name in ('numpy','PyYAML','PyQt5','scipy'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='not_installed'
    return dict(schema_version=1,config_sha256=file_sha256(config.path),effective_config=config.data,
        assets=dict(config.checked_assets),worker_interpreter_probes=dict(config.runtime_probes),
        package_source_sha256=sources,host=dict(python=sys.version,executable=sys.executable,prefix=sys.prefix,distributions=versions))


def _record_attempt(root,pipeline,provenance,*,attempt_id=None):
    value=dict(provenance,attempt_id=attempt_id or str(uuid.uuid4()),attempt_wall_time_ns=time.time_ns(),clock_domain=pipeline.clock_domain)
    payload=_canonical(value);pipeline.quota.reserve('attempt-provenance',2*len(payload)+16384)
    try:
        directory=root/'attempts';directory.mkdir(exist_ok=True)
        _write_atomic(directory/(value['attempt_id']+'.json'),payload)
    finally:pipeline.quota.release('attempt-provenance')
    return value['attempt_id']


class _DetectorMetadata:
    def __init__(self,client,sink):
        self.client=client;self.sink=sink;self._sync()
    def _sync(self):
        metadata=getattr(self.client,'runtime_metadata',None)
        if metadata is not None:
            self.sink['detector']=dict(runtime_versions=metadata,
                actual_recipe=dict(getattr(self.client,'recipe',{})))
    def infer(self,obs):
        try:return self.client.infer(obs)
        finally:self._sync()
    def close(self,timeout_s=1.):return self.client.close(timeout_s=timeout_s)


def _plain_metadata(value):
    """Copy immutable worker metadata into the runtime JSON boundary."""
    if isinstance(value,Mapping):return {key:_plain_metadata(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)):return [_plain_metadata(item) for item in value]
    return value


class _EncoderMetadata:
    def __init__(self,encoder,sink):self.encoder=encoder;self.sink=sink;self.used=0;self.fallback=0
    def encode(self,obs,batch):
        result=self.encoder.encode(obs,batch)
        if result is None:self.fallback+=1
        else:self.used+=1
        self.sink['appearance']=dict(feature_frames=self.used,geometry_fallback_frames=self.fallback,
            last_status=_plain_metadata(self.encoder.last_status),space_metadata=None if self.encoder.space_metadata is None else _plain_metadata(self.encoder.space_metadata))
        return result
    def close(self):return self.encoder.close()


def _recording_policy(config):
    raw=config.data.get('budgets',{}).get('raw_cap',2*1024**3)
    archive=config.data.get('budgets',{}).get('archive_cap',min(raw//4,256*1024**2))
    return dict(aggregate_raw_cap=raw,archive_max_bytes=archive,
        payload_format=config.data.get('long_demo',{}).get('payload_format','json_v1'),
        max_duration_s=config.data.get('long_demo',{}).get('max_duration_s',300),
        capture_cadence=config.data.get('runtime',dict(mode='legacy_paired_unpaced')),
        reservation='fixed_bounded_archive_subtree' if 'long_demo' in config.data else 'fixed_archive_budget_plus_actual_bytes_conservative',
        lower_archive_cap_is_explicit=True)


class _RawAdmissionStopped(RuntimeError):pass


class _CaptureCadence:
    """Owner-thread capture deadlines; late slots are skipped, never replayed."""
    def __init__(self,*,primary_hz,navigation_hz):
        self.primary_period=1./primary_hz;self.navigation_period=1./navigation_hz
        self.next_primary=None;self.next_navigation=None

    def primary_due(self,now):
        if self.next_primary is not None and now<self.next_primary:return False
        self.next_primary=now+self.primary_period
        return True

    def navigation_delay(self,now):
        return 0. if self.next_navigation is None else max(0.,self.next_navigation-now)

    def navigation_started(self,now):
        self.next_navigation=now+self.navigation_period


class _ControlInvocations:
    """Bounded raw starts plus exact all-invocation interval aggregates."""
    def __init__(self,cap):
        self.cap=cap;self.starts=[];self.total=0;self.previous=None
        self.count=0;self.sum_ns=0;self.max_ns=0;self.miss50=0;self.miss100=0
        self.wait_counts=dict(matched=0,unmatched=0,unspecified=0)
        self.results={};self.result_total=0;self.executed=0
        self.run_deadline_skips=dict(total=0,navigation_ready=0,navigation_pending=0,last_source=None)

    def record(self,stamp,*,navigation_ready=None):
        if self.previous is not None:
            delta=stamp-self.previous
            self.count+=1;self.sum_ns+=delta;self.max_ns=max(self.max_ns,delta)
            self.miss50+=delta>50_000_000;self.miss100+=delta>100_000_000
        self.previous=stamp;self.total+=1
        self.wait_counts['matched' if navigation_ready is True else 'unmatched' if navigation_ready is False else 'unspecified']+=1
        if len(self.starts)<self.cap:self.starts.append(stamp)

    def result(self,value):
        self.result_total+=1;self.executed+=value.get('executed') is True
        reason=str(value.get('reason','unspecified'))[:128]
        if reason not in self.results and len(self.results)>=64:reason='other_bounded_reasons'
        self.results[reason]=self.results.get(reason,0)+1

    def skip_run_deadline(self,observation,*,navigation_ready):
        self.run_deadline_skips['total']+=1
        key=observation.key
        field='navigation_ready' if navigation_ready else 'navigation_pending'
        self.run_deadline_skips[field]+=1
        self.run_deadline_skips['last_source']=dict(episode_id=key.episode_id,
            sensor_id=key.sensor_id,frame_index=key.frame_index)

    def snapshot(self,domain):
        return dict(schema_version=1,clock_domain=domain,population='actual_control_step_invocation_starts_including_stop_and_pending',
            starts_monotonic_ns=list(self.starts),total=self.total,retained=len(self.starts),
            dropped=self.total-len(self.starts),complete=self.total==len(self.starts),cap=self.cap,
            navigation_wait=dict(self.wait_counts),control_results=dict(self.results),
            run_deadline_skips=dict(self.run_deadline_skips),
            result_total=self.result_total,result_missing=self.total-self.result_total,executed_results=self.executed,
            intervals=dict(count=self.count,mean_ns=None if not self.count else self.sum_ns/self.count,
                max_ns=None if not self.count else self.max_ns,miss_50ms=self.miss50,miss_100ms=self.miss100),
            limitation='capture/map waits contribute to intervals; no timer catchup; raw quantiles require complete starts')


def _invoke_control_before_run_deadline(pipeline,actuator,observation,*,navigation_ready,run_deadline):
    """Do not issue a terminal control call after its run budget has elapsed."""
    if time.monotonic()>=run_deadline:
        pipeline._control_invocations.skip_run_deadline(observation,navigation_ready=navigation_ready)
        return False
    pipeline._control_invocations.record(time.monotonic_ns(),navigation_ready=navigation_ready)
    pipeline._control_invocations.result(pipeline.control_step(actuator))
    return True


def _append_raw(recorder,obs):
    if not recorder.append(obs):raise _RawAdmissionStopped('raw_recording_rejected')


def _wait_exact_navigation(pipeline,observation,run_deadline):
    """Yield only for the map of this capture, bounded by its original TTL.

    No detector, ledger, room or UI state can extend this deadline. Source age
    is checked again by control and worker after the wait.
    """
    if getattr(pipeline,'local_depth_control',False):return None
    remaining_age=(observation.capture_monotonic_ns+300_000_000-time.monotonic_ns())/1e9
    deadline=min(run_deadline,time.monotonic()+max(0.,remaining_age))
    while time.monotonic()<deadline:
        with pipeline._lock:
            nav=pipeline._latest_nav;stopped=pipeline._stop_requested or pipeline._closing or pipeline._paused
        if stopped:return False
        if pipeline.health.snapshot()['failed']:return False
        if nav is not None and nav.source==observation.key and nav.capture_monotonic_ns==observation.capture_monotonic_ns and nav.clock_domain==observation.clock_domain:
            return True
        if (getattr(pipeline,'allow_fresh_map_lag',False)
                and pipeline._navigation_map_compatible(nav,observation)):
            return True
        time.sleep(.001)
    return False


def _sensor_launch_configuration(config, assets):
    """Use navigation's physical body as the single native geometry authority."""
    sensor_config=dict(config.data['sensor_config']);sensor_config.pop('scene',None)
    sensor_config.pop('scene_dataset',None)
    if 'scene_dataset' in assets:sensor_config['scene_dataset_config_file']=str(assets['scene_dataset'])
    sensor_config['scene_id']=str(assets['scene']);sensor_config['episode_id']=config.data['episode']['id']
    robot=config.data.get('navigation',{}).get('robot')
    if robot is not None:
        sensor_config['agent_geometry']={key:robot[key] for key in ('geometry_id','radius_m','height_m')}
    return sensor_config


def _assets(config):
    """Resolve all declared resources without starting interpreters/frameworks."""
    d=config.data;resolved={};issues=[]
    def check(label,call):
        try:resolved[label]=call()
        except (ValueError,OSError,TypeError,KeyError) as exc:issues.append(str(exc))
    if d['mode']=='fixture_cpu_no_models':
        check('detections',lambda:config.asset(d.get('fixture',{}).get('detections'),'fixture.detections'))
    else:
        for name in ('sensor','detector'):
            check(name,lambda name=name:config.worker(name))
        room_config=d.get('workers',{}).get('room_pipeline')
        scene_graph_backend=d.get('scene_graph',{}).get('backend','legacy')
        if room_config is None and scene_graph_backend=='legacy':
            check('region',lambda:config.worker('region'))
        sensor=d.get('sensor_config',{})
        check('scene',lambda:config.asset(sensor.get('scene'),'sensor_config.scene'))
        if not sensor.get('navigation'):issues.append('sensor_config.navigation requires a calibrated independent depth sensor')
        detector=d.get('detector',{})
        for name in ('checkpoint','encoder','taxonomy'):
            check(name,lambda name=name:config.asset(detector.get(name),'detector.'+name))
        if detector.get('backend','torch')=='openvino_gpu':
            for name in ('openvino_model','openvino_bin','openvino_metadata'):
                check(name,lambda name=name:config.asset(detector.get(name),'detector.'+name))
        if d.get('ui',{}).get('enabled',False):check('ui',lambda:config.worker('ui'))
        if d.get('navigation',{}).get('mapper',{}).get('raycast_backend','cpu')=='triton_cuda':
            check('raycast',lambda:config.worker('raycast'))
        if sensor.get('scene_dataset') is not None:check('scene_dataset',lambda:config.asset(sensor['scene_dataset'],'sensor_config.scene_dataset'))
    if d.get('scene_graph',{}).get('backend','legacy')=='hydra':
        check('hydra',lambda:config.worker('hydra'))
        check('hydra_setup',lambda:config.asset(d['workers']['hydra'].get('setup_script'),'workers.hydra.setup_script'))
    room_config=d.get('workers',{}).get('room_pipeline')
    if room_config is not None:
        from ..regions.rebuild_room_worker import (
            EXPECTED_M23_SHA256,EXPECTED_M4_SHA256,EXPECTED_SOURCE_TREE_SHA256,
            _source_tree_sha256,
        )
        check('room_m23',lambda:config.asset(room_config.get('m23_binary'),'workers.room_pipeline.m23_binary',executable=True))
        check('room_m4',lambda:config.asset(room_config.get('m4_binary'),'workers.room_pipeline.m4_binary',executable=True))
        def check_room_pins():
            if 'room_m23' in resolved and file_sha256(resolved['room_m23'])!=EXPECTED_M23_SHA256:
                raise ValueError('workers.room_pipeline M2/M3 binary differs from the pinned source profile')
            if 'room_m4' in resolved and file_sha256(resolved['room_m4'])!=EXPECTED_M4_SHA256:
                raise ValueError('workers.room_pipeline M4 binary differs from the pinned source profile')
            source_root=Path(room_config['source_root'])
            actual=_source_tree_sha256(source_root)
            if actual!=EXPECTED_SOURCE_TREE_SHA256:
                raise ValueError('workers.room_pipeline Rebuild Python closure differs from the pinned source profile')
            return dict(source_root=str(source_root),source_sha256=actual,
                        m23_sha256=EXPECTED_M23_SHA256,m4_sha256=EXPECTED_M4_SHA256)
        check('room_pipeline_pins',check_room_pins)
    if d.get('measurements',{}).get('enabled') and 'gpu_executable' in d['measurements']:
        check('measurement_gpu',lambda:config.asset(d['measurements']['gpu_executable'],'measurements.gpu_executable',executable=True))
    if d.get('appearance_mode','off') in {'openclip','openai_clip'}:
        worker=d.get('worker',{})
        check('appearance',lambda:config.worker('appearance'))
        check('appearance_checkpoint',lambda:config.asset(dict(path=worker.get('checkpoint_path'),sha256=worker.get('checkpoint_sha256')),'worker.checkpoint'))
    appearance_modules=(['numpy','PIL','torch','clip'] if d.get('appearance_mode')=='openai_clip'
                        else ['numpy','PIL','torch','open_clip','safetensors'])
    detector_modules=['numpy','torch','ultralytics','clip']
    if d.get('detector',{}).get('backend','torch')=='openvino_gpu':detector_modules.append('openvino')
    for name,modules in [('sensor',['numpy','habitat_sim']),('detector',detector_modules),('appearance',appearance_modules),('ui',['numpy','PyQt5']),('raycast',['numpy','torch','triton']),('hydra',['numpy','yaml','scipy','hydra_python._hydra_bindings','spark_dsg'])]:
        if name in resolved and isinstance(resolved[name],tuple):
            try:config.runtime_probes[name]=_probe_interpreter(resolved[name][0],modules,name,
                setup_script=resolved.get('hydra_setup') if name=='hydra' else None,
                **({'timeout_s':d.get('workers',{}).get('hydra',{}).get('startup_timeout_s',10.)}
                   if name=='hydra' else {}))
            except ValueError as exc:issues.append(str(exc))
    return resolved,issues


def preflight(config_path)->dict:
    try:
        config=load_config(config_path);resources,issues=_assets(config)
    except (ValueError,OSError,TypeError) as exc:
        return dict(ready=False,issues=[str(exc)],native_runtime_validated=False)
    return dict(ready=not issues,issues=issues,mode=config.data['mode'],profile=config.data['profile'],
                config_path=str(config.path),config_sha256=file_sha256(config.path),
                p10_seed_support='requested_unverified_until_worker_ack' if 'seed' in config.data.get('sensor_config',{}) else 'unavailable_unseeded_config',
                native_runtime_validated=False,recording_policy=_recording_policy(config),
                assets={k:[str(p) for p in v] if isinstance(v,tuple) else str(v) for k,v in resources.items()})


def _checked(config_path):
    config=load_config(config_path);assets,issues=_assets(config)
    if issues:raise ValueError('preflight blocked: '+'; '.join(issues))
    return config,assets


def _mapper(config,root,*,raycast_backend=None):
    d=config.data;nav=d.get('navigation',{});floor=d['floor']
    robot=RobotGeometry(**nav.get('robot',dict(geometry_id='cylinder-v1',radius_m=.2,height_m=1.5,margin_m=.05)))
    options=dict(nav.get('mapper',{}))
    options.pop('local_sampling_stride',None)  # local safety-map lattice, not the world mapper
    options.pop('overview_refresh_s',None)  # world-thread scheduling, not a mapper option
    selected=options.pop('raycast_backend','cpu')
    if selected=='triton_cuda' and raycast_backend is None:raise ValueError('GPU raycast worker not initialized')
    if 'tile_archive_dir' in options:raise ValueError('mapper tile archive is assigned inside run root')
    return NavMapper(robot=robot,floor_z_m=floor['z_m'],floor_datum_source=floor['datum_source'],
        calibration_hash=floor['calibration_sha256'],tile_archive_dir=root/'tiles',raycast_backend=raycast_backend,**options)


def _runtime_mapper(config,root,domain,*,raycast_backend=None,offline_replay_control=False):
    """Hydra graph replay has no recorded measured pose for a NavMap update."""
    if (domain.startswith('replay:') and not offline_replay_control
            and config.data.get('scene_graph',{}).get('backend')=='hydra'):
        return None
    return _mapper(config,root,raycast_backend=raycast_backend)


class _RecordedDetector:
    """Explicit recorded model outputs, validated against original recording."""
    def __init__(self,path,manifest):
        if Path(path).stat().st_size>32*1024**2:raise ValueError('fixture detections exceed 32 MiB')
        value=json.loads(Path(path).read_text())
        if set(value)!={'schema_version','batches'} or type(value['schema_version']) is not int or value['schema_version']!=1 or not isinstance(value['batches'],list):
            raise ValueError('fixture detections require schema_version:1 and batches list')
        records={loads_key(r['source_key']):r for r in manifest['records']}
        self.batches={};vocab=set()
        for encoded in value['batches']:
            batch=from_dict(encoded)
            if not isinstance(batch,DetectionBatch):raise ValueError('fixture payload must be DetectionBatch')
            record=records.get(batch.source)
            if record is None or batch.geometry_hash!=record['source_geometry_hash']:
                raise ValueError('recorded detection original source/geometry_hash mismatch')
            if batch.source in self.batches:raise ValueError('duplicate recorded detection source')
            self.batches[batch.source]=batch;vocab.add(batch.vocabulary_id)
        if len(vocab)!=1:raise ValueError('fixture requires one explicit vocabulary and at least one batch')
        self.vocabulary_id=next(iter(vocab))
    def infer(self,obs):
        if not obs.clock_domain.startswith('replay:'):raise ValueError('recorded detector is replay only')
        if obs.key not in self.batches:raise ValueError('missing recorded detection for '+str(obs.key))
        return replace(self.batches[obs.key],geometry_hash=obs.geometry_hash)
    def close(self):pass


def loads_key(encoded):
    key=from_dict(encoded)
    from ..contracts import FrameKey
    if not isinstance(key,FrameKey):raise ValueError('recording source_key must be FrameKey')
    return key


class _RecordedPolicy:
    """Replay all explicitly recorded RGB-D model results in order."""
    def propose(self,obs):return True,None,1.
    def commit(self,obs):pass


def _pipeline(config,assets,root,domain,now_ns,*,recorded=None,publisher=None,measurements=None,
              offline_replay_control=False):
    backend=None
    if config.data.get('navigation',{}).get('mapper',{}).get('raycast_backend','cpu')=='triton_cuda':
        if recorded is not None or domain.startswith('replay:'):raise ValueError('GPU profile is live-only; replay requires an explicit CPU profile')
        from ..mapping.gpu_raycast_client import GpuRaycastClient
        python,script=assets['raycast'];worker=config.data['workers']['raycast']
        backend=GpuRaycastClient(python=python,worker_script=script,root=root/'gpu-raycast-ipc',
            timeout_s=worker.get('timeout_s',.25),startup_timeout_s=worker.get('startup_timeout_s',30.))
    try:
        return _pipeline_impl(config,assets,root,domain,now_ns,recorded=recorded,publisher=publisher,
                              measurements=measurements,raycast_backend=backend,
                              offline_replay_control=offline_replay_control)
    except BaseException:
        if backend is not None:backend.close()
        raise


def _process_priority(config):
    from .priority import validate_process_priority
    return validate_process_priority(config.data.get('runtime',{}).get('process_priority'))


def _apply_ui_priority(config,ui,pipeline):
    """Lower the optional UI (and its room-label model server) below perception."""
    nice=_process_priority(config).get('ui',0)
    process=getattr(ui,'process',None)
    if not nice or process is None:return None
    from .priority import renice_tree
    report=renice_tree(process.pid,nice)
    try:ui.priority_report=dict(report)
    except Exception:pass
    return report


def _keyframe_policy(config):
    """Configured 3DSG keyframe novelty thresholds, or the default policy."""
    novelty=config.data.get('keyframe_novelty')
    if novelty is None:return None
    from .scheduler import KeyframePolicy
    return KeyframePolicy(min_translation_m=float(novelty['min_translation_m']),
                          min_yaw_rad=math.radians(float(novelty['min_yaw_deg'])))


def _pulse_horizons_ns(config):
    """(translation, pure-rotation) guarded pulse horizons in ns."""
    controller=config.data.get('navigation',{}).get('controller',{})
    pulse=int(controller.get('pulse_ms',100))*1_000_000
    rotation=controller.get('rotation_pulse_ms')
    return pulse,None if rotation is None else int(rotation)*1_000_000


def _navigation_options(config):
    controller=config.data.get('navigation',{}).get('controller',{})
    hybrid=controller.get('hybrid_pulse_control',False)
    discrete=controller.get('discrete_heading_control',not hybrid)
    result=dict(nominal_speed_mps=controller.get('nominal_speed_mps',.15),
        discrete_heading_control=discrete,gain_aware=controller.get('gain_aware',True),
        acceleration_mps2=controller.get('acceleration_mps2',.6 if discrete or hybrid else .15))
    if 'hybrid_pulse_control' in controller:result['hybrid_pulse_control']=hybrid
    if 'world_goal_max_age_ms' in controller:
        result['goal_selection_max_age_ns']=int(controller['world_goal_max_age_ms'])*1_000_000
    if 'pulse_ms' in controller or 'rotation_pulse_ms' in controller:
        result['max_pulse_s']=max(v for v in _pulse_horizons_ns(config) if v is not None)/1e9
    if controller.get('start_unknown_tolerance'):
        result['start_unknown_tolerance']=float(controller['start_unknown_tolerance'])
    tour=config.data.get('navigation',{}).get('tour')
    if tour is not None:
        from ..navigation.tour import TourFollower,TourPlan
        plan=TourPlan.load(tour['path'],tour['sha256'])
        initial=config.data.get('sensor_config',{}).get('initial_position')
        if initial is not None:
            import math as _math
            start=(float(initial[0]),-float(initial[2]))
            if _math.dist(start,plan.start_xy)>.5:
                raise ValueError('navigation.tour start does not match sensor_config.initial_position')
        result['tour']=TourFollower(plan,**{k:float(tour[k]) for k in ('reach_m','lookahead_m','stuck_timeout_s','skip_m','relax_m','approach_m','stall_timeout_s','scan_degrees','scan_step_degrees','scan_min_separation_m','scan_step_timeout_s') if k in tour})
    return result


def _pipeline_impl(config,assets,root,domain,now_ns,*,recorded=None,publisher=None,measurements=None,
                   raycast_backend=None,offline_replay_control=False):
    d=config.data;e=d['episode'];scene_graph_backend=d.get('scene_graph',{}).get('backend','legacy')
    if type(offline_replay_control) is not bool or (offline_replay_control and not domain.startswith('replay:')):
        raise ValueError('offline replay control requires an explicit replay clock')
    mapper=_runtime_mapper(config,root,domain,raycast_backend=raycast_backend,
        offline_replay_control=offline_replay_control)
    encoder=None;region=None;room_pipeline=None;navigator=None;guard=None;worker_metadata={}
    raycast_mode=d.get('navigation',{}).get('mapper',{}).get('raycast_backend','cpu')
    if mapper is None:
        worker_metadata['navigation_mapper_startup']=dict(raycast_backend='not_instantiated',
            numba_available=False,numba_warmed=False,warmup_duration_ns=0,
            reason='hydra_graph_replay_has_no_recorded_body_pose')
    elif raycast_mode=='cpu' and raycast_backend is None:
        warmup_started_ns=time.perf_counter_ns()
        available=numba_available()
        warmed=warmup_raycast_kernel()
        worker_metadata['navigation_mapper_startup']=dict(raycast_backend='cpu',
            numba_available=available,numba_warmed=warmed,
            warmup_duration_ns=time.perf_counter_ns()-warmup_started_ns)
    else:
        worker_metadata['navigation_mapper_startup']=dict(raycast_backend=raycast_mode,
            numba_available=False,numba_warmed=False,warmup_duration_ns=0)
    room_config=d.get('workers',{}).get('room_pipeline')
    if recorded is None:
        from ..perception.detector_client import DetectorClient,validate_recipe
        from ..contracts import Taxonomy
        from ..perception.detector_client import RECIPE_CONFIG_ASSETS
        recipe={k:v for k,v in d['detector'].items() if k not in RECIPE_CONFIG_ASSETS}
        for name in ('checkpoint','encoder','taxonomy'):
            recipe[name+'_path']=str(assets[name]);recipe[name+'_sha256']=file_sha256(assets[name])
        if recipe.get('backend','torch')=='openvino_gpu':
            for name in ('openvino_model','openvino_bin','openvino_metadata'):
                recipe[name+'_path']=str(assets[name]);recipe[name+'_sha256']=file_sha256(assets[name])
        recipe=validate_recipe(recipe);vocabulary=Taxonomy.load(recipe['taxonomy_path']).vocabulary_id
        detector_python,detector_script=assets['detector'];detector_worker=d['workers']['detector']
        def detector():
            client=DetectorClient(python=detector_python,worker_script=detector_script,recipe=recipe,
                timeout_s=detector_worker.get('timeout_s',2.),
                startup_timeout_s=detector_worker.get('startup_timeout_s',30.),
                nice=_process_priority(config).get('detector',0))
            if recipe.get('backend','torch')=='openvino_gpu':client.start()
            return _DetectorMetadata(client,worker_metadata)
        startup_timeout_s=5.
        if recipe.get('backend','torch')=='openvino_gpu':
            hydra_startup=d.get('workers',{}).get('hydra',{}).get('startup_timeout_s',0.)
            startup_timeout_s=max(startup_timeout_s,detector_worker.get('startup_timeout_s',30.)+hydra_startup+5.)
        region_config=d.get('workers',{}).get('region',{})
        if room_config is None and scene_graph_backend=='legacy':
            if region_config.get('backend','dude')=='rebuild_m4_m5':
                from ..regions.rebuild_backend import RebuildRegionBackend
                region=lambda:RebuildRegionBackend(assets['region'],floor_id=e['floor_id'],
                    source_root=region_config['source_root'],
                    timeout_s=region_config.get('timeout_s',30.))
            else:
                from ..regions.backend import RegionBackend
                region=lambda:RegionBackend(assets['region'],floor_id=e['floor_id'],reset_on_geometry_change=True)
        if not domain.startswith('replay:') or offline_replay_control:
            from ..navigation.controller import Navigator
            from ..navigation.safety import MotionGuard
            navigation_options=_navigation_options(config)
            navigator=Navigator(mapper.robot,clock_domain=domain,offline_replay=offline_replay_control,**navigation_options)
            pulse_ns,rotation_pulse_ns=_pulse_horizons_ns(config)
            paced={'pulse_ms','rotation_pulse_ms'}&set(d.get('navigation',{}).get('controller',{}))
            guard=MotionGuard(mapper,clock_domain=domain,now_ns=now_ns,offline_replay=offline_replay_control,
                **(dict(command_horizon_ns=pulse_ns,rotation_horizon_ns=rotation_pulse_ns,pace_to_wall_time=True)
                   if paced else {}))
            worker_metadata['navigation']=dict({k:v for k,v in navigation_options.items() if k!='tour'},
                **({'goal_source':'navmesh_tour_privileged_v1','tour_sha256':navigation_options['tour'].plan.sha256}
                   if 'tour' in navigation_options else {}),
                hybrid_pulse_control=navigator.hybrid_pulse_control,
                drive_mode=('hybrid_pursuit_v1' if navigator.hybrid_pulse_control else
                    'discrete_heading_v1' if navigator.discrete_heading_control else 'legacy_continuous'),
                yaw_acceleration_radps2=navigator.controller.config.yaw_acceleration_radps2,
                max_source_age_ns=guard.max_depth_age_ns,command_horizon_ns=guard.command_horizon_ns,
                rotation_horizon_ns=guard.rotation_horizon_ns,
                frontier_selection='gain-heading-v1' if navigator.gain_aware else 'nearest-v1',
                frontier_views_per_component=navigator.extractor.max_viewpoints_per_frontier,
                frontier_gain_weight=navigator.policy.config.frontier_gain_weight,
                min_goal_distance_m=navigator.policy.config.min_goal_distance_m,
                turn_cost_m_per_rad=navigator.policy.config.turn_cost_m_per_rad,
                allow_fresh_map_lag=d.get('navigation',{}).get('controller',{}).get(
                    'allow_fresh_map_lag',False))
        if d.get('appearance_mode','off') in {'openclip','openai_clip'}:
            from ..perception.appearance_client import AppearanceWorkerEncoder
            worker=d['worker'];appearance_python,appearance_script=assets['appearance']
            encoder=lambda:_EncoderMetadata(AppearanceWorkerEncoder(appearance_python,assets['appearance_checkpoint'],
                checkpoint_sha256=worker['checkpoint_sha256'],model_name=worker['model_name'],
                checkpoint_format=worker.get('checkpoint_format','safetensors'),
                preprocessing_id=worker['preprocessing_id'],timeout_s=worker.get('timeout_s',2.),
                startup_timeout_s=worker.get('startup_timeout_s',30.),
                max_request_bytes=worker.get('max_request_bytes',32*1024**2),
                _worker_command=[str(appearance_python),str(appearance_script),'--worker']),worker_metadata)
    else:detector=lambda:recorded;vocabulary=recorded.vocabulary_id
    if recorded is not None:startup_timeout_s=5.
    if room_config is not None:
        from ..regions.rebuild_rgbd_input import RebuildRGBDConfig
        from ..regions.rebuild_room_session import RebuildRoomSession
        room_config=dict(room_config)
        room_profile=RebuildRGBDConfig(**{key:room_config[key] for key in (
            'resolution_m','backprojection_stride','min_depth_m','max_depth_m','max_range_m')
            if key in room_config})
        room_pipeline=lambda:RebuildRoomSession(
            source_root=room_config['source_root'],m23_binary=assets['room_m23'],
            m4_binary=assets['room_m4'],episode_id=e['id'],floor_id=e['floor_id'],
            config=room_profile,ipc_timeout_s=room_config.get('ipc_timeout_s',60.),
            m23_timeout_s=room_config.get('m23_timeout_s',15.),
            m4_timeout_s=room_config.get('m4_timeout_s',30.),
            run_dir=root/'room-pipeline'/'session')
    profile=d['profile']+(':'+d['mode'] if recorded is not None else ':yoloe:appearance-'+d.get('appearance_mode','off'))
    if d.get('scene_graph',{}).get('backend','legacy')=='hydra':profile+=':scene-graph-hydra'
    if d.get('workers',{}).get('region',{}).get('backend','dude')=='rebuild_m4_m5':
        profile+=':rooms-rebuild_m4_m5'
    if d.get('workers',{}).get('room_pipeline') is not None:
        profile+=':rooms-rebuild_rgbd_m1_m5'
        if room_config.get('fps_cap_hz') is not None:
            profile+=f":room-fps{float(room_config['fps_cap_hz']):g}-{room_config.get('queue_policy','bounded_fifo')}"
    sampling=d.get('keyframe_sampling','novelty')
    if (recorded is not None or domain.startswith('replay:')) and sampling!='novelty':raise ValueError('recorded replay requires exact semantic input, not live capacity sampling')
    if sampling!='novelty':profile+=':sampling-'+sampling
    adapter=d.get('sensor_config',{}).get('motion_adapter','strict_3d')
    if adapter!='strict_3d':profile+=':motion-'+adapter
    if raycast_backend is not None:
        profile+=':mapping-triton_cuda'
        worker_metadata['raycast']=raycast_backend.runtime_metadata
    owner=lambda:ObjectOwner(root/'objects',episode_id=e['id'],primary_sensor_id=e['primary_sensor_id'],
        floor_id=e['floor_id'],detector_profile_id=profile,vocabulary_id=vocabulary,clock_domain=domain,now_ns=now_ns,
        appearance_mode=d.get('appearance_mode','off'),association_recipe=d.get('association'))
    budgets={k:v for k,v in d.get('budgets',{}).items() if k in {'byte_cap','raw_cap','total_cap'}}
    hydra_runtime_factory=None
    if d.get('scene_graph',{}).get('backend','legacy')=='hydra':
        import numpy as np
        from ..contracts import Taxonomy
        from ..contracts.hydra_graph import HydraCalibration
        from ..backends.hydra.runtime import HydraGraphRuntime
        from ..backends.hydra.session import HydraSession
        scene_config=d['scene_graph']['hydra'];cal=scene_config['calibration']
        calibration=HydraCalibration(cal['calibration_id'],cal['version'],cal['sensor_id'],cal['camera_name'],
            np.asarray(cal['K'],np.float64),np.asarray(cal['body_T_camera'],np.float64),cal['pose_version'],
            cal['coordinate_convention'],cal['camera_convention'],cal['depth_convention'],cal['provenance'])
        taxonomy=Taxonomy.load(assets['taxonomy'])
        hydra_python,hydra_entry=assets['hydra'];hydra_worker=d['workers']['hydra']
        hydra_setup=assets['hydra_setup']
        child_wrapper=Path(__file__).resolve().parents[1]/'backends'/'hydra'/'child.sh'
        def hydra_runtime_factory():
            worker_dir=root/'hydra';artifact_dir=worker_dir/'native-output'
            worker_dir.mkdir(parents=True,exist_ok=True)
            from .priority import nice_prefix
            command=(*nice_prefix(_process_priority(config).get('hydra',0)),
                '/bin/bash',str(child_wrapper),str(hydra_setup),str(hydra_python),str(hydra_entry),
                '--config-root',scene_config['config_root'],'--artifact-dir',str(artifact_dir))
            session=HydraSession(e['id'],command=command,journal_path=worker_dir/'journal.jsonl',
                worker_timeout_s=hydra_worker.get('timeout_s',30.),
                startup_timeout_s=hydra_worker.get('startup_timeout_s',10.),
                fps_limit_hz=hydra_worker.get('fps_limit_hz'),
                artifact_quota_bytes=hydra_worker.get('artifact_quota_bytes',2*1024**3))
            return HydraGraphRuntime(session,calibration=calibration,taxonomy=taxonomy,
                detector_profile_id=scene_config['detector_profile_id'])
    pipeline=Pipeline(root,episode_id=e['id'],primary_sensor_id=e['primary_sensor_id'],clock_domain=domain,
        floor_id=e['floor_id'],owner_factory=None if hydra_runtime_factory else owner,detector_factory=detector,
        verifier_factory=None if hydra_runtime_factory else lambda owner:VerificationOwner(owner,clock_domain=domain,now_ns=now_ns,root=root/'verification'),
        encoder_factory=encoder,region_factory=region,mapper=mapper,navigator=navigator,guard=guard,
        allow_fresh_map_lag=False if navigator is None else worker_metadata['navigation']['allow_fresh_map_lag'],
        local_depth_control=d.get('navigation',{}).get('controller',{}).get('local_depth_control',False),
        world_navigation_hz=d.get('runtime',{}).get('world_navigation_hz'),
        **({'overview_refresh_ns':int(round(float(d['navigation']['mapper']['overview_refresh_s'])*1e9))}
           if 'overview_refresh_s' in d.get('navigation',{}).get('mapper',{}) else {}),
        **({'gil_switch_interval_s':float(d['runtime']['gil_switch_interval_ms'])/1000.}
           if 'gil_switch_interval_ms' in d.get('runtime',{}) else {}),
        **({'world_intent_ttl_ns':int(d['navigation']['controller']['world_intent_ttl_ms'])*1_000_000}
           if 'world_intent_ttl_ms' in d.get('navigation',{}).get('controller',{}) else {}),
        **({'local_sampling_stride':d['navigation']['mapper']['local_sampling_stride']}
           if 'local_sampling_stride' in d.get('navigation',{}).get('mapper',{}) else {}),
        **(dict(zip(('command_horizon_ns','rotation_horizon_ns'),_pulse_horizons_ns(config)))
           if {'pulse_ms','rotation_pulse_ms'}&set(d.get('navigation',{}).get('controller',{})) else {}),
        **({'start_unknown_tolerance':float(d['navigation']['controller']['start_unknown_tolerance'])}
           if d.get('navigation',{}).get('controller',{}).get('start_unknown_tolerance') else {}),
        keyframe_policy=_RecordedPolicy() if recorded is not None else _keyframe_policy(config),now_ns=now_ns,
        actual_profile=profile,publisher=publisher,measurements=measurements,
        **({'keyframe_sampling':sampling} if sampling!='novelty' else {}),
        **({'room_fps_cap_hz':room_config['fps_cap_hz']} if room_config is not None and 'fps_cap_hz' in room_config else {}),
        **({'room_queue_policy':room_config.get('queue_policy','bounded_fifo')} if room_config is not None else {}),
        room_pipeline_factory=room_pipeline,scene_graph_backend=d.get('scene_graph',{}).get('backend','legacy'),
        hydra_runtime_factory=hydra_runtime_factory,startup_timeout_s=startup_timeout_s,
        offline_replay_control=offline_replay_control,**budgets)
    pipeline._launcher_worker_metadata=worker_metadata
    if raycast_backend is not None:
        try:
            from ..mapping.gpu_raycast_client import LIMITS
            pipeline.quota.reserve('gpu-raycast-ipc',2*(LIMITS['max_output_bytes']+LIMITS['max_rays']*25)+65536)
        except BaseException:
            pipeline.close(5.)
            raise
    return pipeline


def _root(out,*,resume):
    root=Path(out).absolute()
    if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('run root may not contain symlinks')
    root.mkdir(parents=True,exist_ok=True)
    if not resume and any(root.iterdir()):raise ValueError('live episode requires a new empty run directory')
    return root


def _hydra_native_export(report):
    """Validate and expose Hydra's native graph manifest independently of legacy hierarchy."""
    info=report.get('metrics',{}).get('hydra',{}).get('native_export')
    result=dict(available=False,complete=False,manifest_path=None,manifest_sha256=None,
        graph_revision=None,selected_input_count=0,failure_reason='native_export_not_reported')
    if not isinstance(info,dict) or not isinstance(info.get('manifest_path'),str):
        return result,None
    path=Path(info['manifest_path'])
    try:
        raw=path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=info.get('manifest_sha256'):
            raise ValueError('native export manifest SHA-256 mismatch')
        manifest=json.loads(raw)
        if not isinstance(manifest,dict) or manifest.get('schema_version')!=1:
            raise ValueError('native export manifest schema is invalid')
        result.update(available=True,manifest_path='hydra-export-manifest.json',manifest_sha256=digest,
            graph_revision=manifest.get('graph_revision'),
            selected_input_count=len(manifest.get('selected_inputs',[]))
                if isinstance(manifest.get('selected_inputs'),list) else 0,
            failure_reason=manifest.get('failure_reason'))
        graph=Path(manifest['graph_path'])
        journal=Path(manifest['journal_path'])
        selected=manifest.get('selected_inputs')
        graph_ok=(graph.is_file() and graph.stat().st_size==manifest.get('graph_bytes')
            and hashlib.sha256(graph.read_bytes()).hexdigest()==manifest.get('graph_sha256'))
        journal_ok=(journal.is_file()
            and hashlib.sha256(journal.read_bytes()).hexdigest()==manifest.get('journal_sha256'))
        prefix_ok=(isinstance(selected,list) and bool(selected)
            and manifest.get('graph_revision')==len(selected)
            and selected[-1].get('input_prefix_sha256')==manifest.get('input_prefix_sha256'))
        complete=(info.get('complete') is True and info.get('graph_asset_verified') is True
            and manifest.get('complete') is True and graph_ok and journal_ok and prefix_ok)
        result['complete']=complete
        if not complete and not result['failure_reason']:
            result['failure_reason']='native graph, journal, or selected-input prefix verification failed'
        return result,raw
    except (OSError,KeyError,TypeError,ValueError,json.JSONDecodeError) as exc:
        result['failure_reason']=str(exc)
        return result,None


def _export(root,pipeline,report,metadata):
    restored=False;export_issue=None
    room_bundle=getattr(pipeline,'room_pipeline_snapshot',None)
    room_pipeline=room_bundle() if callable(room_bundle) else None
    bundle=getattr(pipeline,'snapshot_bundle',None)
    if callable(bundle):
        snapshot,nav=bundle()
    else:
        # Compatibility for legacy/fake pipeline providers that have not
        # implemented canonical pair access. Never use display as a fallback
        # for an unavailable or invalid pair returned by the canonical API.
        snapshot=pipeline.snapshot();nav=None
        publisher=pipeline.publisher
        if publisher is not None:
            if hasattr(publisher,'publisher'):publisher=publisher.publisher
            envelope=publisher.read_latest()
            if envelope is not None:nav=envelope.sources.nav
    checkpoint=root/'objects'/'objects.sqlite3';objects=None;events=[];events_total=None
    # Only after the owner has quiesced. Never open a second owner connection.
    if report['clean_shutdown'] and checkpoint.exists():
        with sqlite3.connect('file:'+str(checkpoint)+'?mode=ro',uri=True) as connection:
            row=connection.execute("SELECT value FROM metadata WHERE key='checkpoint'").fetchone()
            if row:objects=loads(json.loads(row[0])['snapshot'])
            events_total=connection.execute('SELECT count(*) FROM events').fetchone()[0]
            events=[dict(event_id=a,object_id=b,source=json.loads(c).get('source')) for a,b,c in
                connection.execute('SELECT event_id,object_id,data FROM events ORDER BY event_id LIMIT 4096')]
    if snapshot is None and metadata.get('replay_session') and (root/'export-manifest.json').exists():
        try:
            previous=json.loads((root/'export-manifest.json').read_text())
            if previous['clock_domain']!=metadata['replay_session']['clock_domain']:raise ValueError('export session mismatch')
            for name in ('hierarchy.json','nav.json'):
                if file_sha256(root/name)!=previous['files'][name]:raise ValueError('persisted '+name+' checksum mismatch')
            snapshot=loads((root/'hierarchy.json').read_text());nav=loads((root/'nav.json').read_text())
            if objects is None or snapshot.episode_id!=objects.episode_id or snapshot.object_revision!=objects.revision or snapshot.map_revision!=nav.revision or nav.clock_domain!=previous['clock_domain']:
                raise ValueError('persisted hierarchy/object/map revisions mismatch')
            restored=True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            snapshot=nav=None;export_issue=str(exc)
    # The canonical pair still must match the final durable object checkpoint.
    # Never synthesize revisions or relabel a newer map to fit an older bundle.
    if snapshot is not None and (nav is None or objects is None
        or snapshot.episode_id!=nav.episode_id or snapshot.episode_id!=objects.episode_id
        or snapshot.map_revision!=nav.revision or snapshot.object_revision!=objects.revision
        or nav.clock_domain!=pipeline.clock_domain):
        snapshot=nav=None
        export_issue='final hierarchy/map/object bundle revisions or clock mismatch'
    native_graph_export,native_manifest_payload=_hydra_native_export(report)
    payloads={}
    if native_manifest_payload is not None:payloads['hydra-export-manifest.json']=native_manifest_payload
    invocations=getattr(pipeline,'_control_invocations',None)
    if invocations is not None:
        trace=invocations.snapshot(pipeline.clock_domain)
        payloads['control-invocations.json']=_canonical(trace)
        metadata=dict(metadata,control_invocations_artifact=dict(path='control-invocations.json',
            sha256=hashlib.sha256(payloads['control-invocations.json']).hexdigest(),complete=trace['complete']))
        if not trace['complete'] and metadata['outcome']=='completed':metadata=dict(metadata,outcome='incomplete')
    if snapshot is not None:payloads['hierarchy.json']=dumps(snapshot).encode()
    if nav is not None:payloads['nav.json']=dumps(nav).encode()
    if objects is not None:payloads['objects.json']=dumps(objects).encode()
    if room_pipeline is not None:payloads['room-pipeline.json']=dumps(room_pipeline).encode()
    legacy_bundle_expected=getattr(pipeline,'scene_graph_backend','legacy')!='hydra'
    legacy_bundle_available=snapshot is not None and nav is not None and objects is not None
    if not legacy_bundle_available:
        if not legacy_bundle_expected and native_graph_export['complete']:
            # Hydra-only profiles deliberately do not construct the legacy
            # hierarchy/NavMap/object trio. Native export is their required graph.
            export_issue=None
        else:
            if native_graph_export['complete']:
                export_issue=export_issue or 'legacy hierarchy/NavMap/object bundle unavailable; Hydra-native graph export verified'
            else:
                export_issue=export_issue or 'coherent hierarchy/map unavailable; replay accepted evidence to rebuild'
            if metadata['outcome']=='completed':metadata['outcome']='incomplete'
    measurement=getattr(pipeline,'_final_measurements',None)
    if measurement is not None:
        export_cap=getattr(pipeline,'_measurement_export_byte_cap',16*1024**2)
        if not measurement['completion']['complete'] and metadata['outcome']=='completed':metadata=dict(metadata,outcome='incomplete')
        measurement['lifecycle']['outcome']=metadata['outcome']
        payloads['measurements.json']=_measurement_payload(measurement,max_bytes=export_cap)
        if not measurement['completion']['complete'] and metadata['outcome']=='completed':
            metadata=dict(metadata,outcome='incomplete');measurement['lifecycle']['outcome']='incomplete'
            payloads['measurements.json']=_measurement_payload(measurement,max_bytes=export_cap)
        metadata=dict(metadata,measurement_artifact=dict(path='measurements.json',sha256=hashlib.sha256(payloads['measurements.json']).hexdigest()),
            measurement_export_byte_cap=export_cap)
    result=dict(schema_version=1,**metadata,runtime=report,
        actual_profile=report['actual_profile'],worker_runtime=dict(getattr(pipeline,'_launcher_worker_metadata',{})),native_runtime_validated=False,
        object_ids=[] if objects is None else sorted(objects.objects),events=events,
        events_total=events_total,events_complete=events_total is not None and len(events)==events_total,
        events_scope='summary_first4096_by_event_id; canonical ledger retains full history',
        hierarchy_available=snapshot is not None,hierarchy_restored=restored,export_issue=export_issue,
        legacy_bundle=dict(expected=legacy_bundle_expected,available=legacy_bundle_available),
        native_graph_export=native_graph_export,
        room_pipeline_available=room_pipeline is not None,
        room_pipeline_revisions=None if room_pipeline is None else dict(
            domain=room_pipeline.map_domain_id,latest_m3=room_pipeline.latest_map.revision,
            accepted_m3=room_pipeline.accepted_map_revision,m5=room_pipeline.m5_revision,
            regions_stale=room_pipeline.regions_stale,replay_required=room_pipeline.replay_required),
        source_revisions=None if snapshot is None else dict(object=snapshot.object_revision,map=snapshot.map_revision,
            region=snapshot.region_revision,latest_nav=snapshot.latest_nav_revision),
        limitations=['CPU fixture evidence is not native runtime validation'] if metadata['mode']=='fixture_cpu_no_models' else ['native pipeline acceptance requires P10 measurements'])
    payloads['summary.json']=_canonical(result)
    manifest=dict(schema_version=2 if measurement is not None else 1,clock_domain=pipeline.clock_domain,
        files={name:__import__('hashlib').sha256(data).hexdigest() for name,data in payloads.items()})
    # Include encoded final snapshots, atomic temporary copies and summary in the
    # shared total cap. Serialization/export runs after control has stopped.
    pipeline.quota.reserve('final-exports',2*sum(map(len,payloads.values()))+65536)
    try:
        for name,payload in payloads.items():_write_atomic(root/name,payload)
        _write(root/'export-manifest.json',manifest)
    finally:pipeline.quota.release('final-exports')
    return result


def _record_expired_navigation(pipeline,captures):
    if pipeline.measurements is not None:
        for obs in captures:pipeline.measurements.capture(obs)
    health=getattr(pipeline,'health',None)
    if health is not None:health.increment('navigation_capture_expired')


def _record_sensor_timing(pipeline,observation,timing,lane):
    measurements=getattr(pipeline,'measurements',None)
    if measurements is None or not isinstance(timing,dict):return
    prefix='primary' if lane=='primary' else 'navigation'
    pairs=((f'sensor_{prefix}_roundtrip','host_request_start_ns','host_response_received_ns'),
           (f'sensor_{prefix}_decode','host_decode_start_ns','host_decode_end_ns'),
           ('sensor_worker_dispatch','worker_request_received_ns','worker_handler_start_ns'),
           ('sensor_worker_handler','worker_handler_start_ns','worker_handler_end_ns'))
    for stage,start_name,end_name in pairs:
        start,end=timing.get(start_name),timing.get(end_name)
        if type(start) is int and type(end) is int and end>=start:
            measurements.stage(observation,stage,start,end)
    for item in timing.get('worker_stages',()):
        if isinstance(item,dict):
            measurements.stage(observation,item.get('stage'),item.get('start_ns'),item.get('end_ns'))


def _pose_ready_for_display(pipeline,observation,pose,captures):
    # The UI marker must exist BEFORE this exact map can be published. Check
    # expiration without admission first. A source can age during the observer;
    # admission rechecks it below. Such a marker is historical only: the UI
    # associates markers by exact accepted map source, never by arrival order.
    validate=getattr(pipeline,'_validated_robot_pose',None)
    if callable(validate):
        try:validate(observation,pose)
        except StaleNavigationCapture:
            _record_expired_navigation(pipeline,captures)
            return False
    return True


def _capture_sensor_pair(sensor,pipeline,append_raw,display_observer=None):
    """Acquire outside runtime locks, then publish the latest depth atomically.

    Acquisition failure retains capture-only metadata, never semantic fallback.
    Pair failures are outside that block: normal submit may already have
    registered captures, so replaying observer callbacks would double-count.
    """
    captured=[];timings=[]
    try:
        rgb=sensor.capture();captured.append(rgb);timings.append(('primary',getattr(sensor,'last_capture_timing',None)));append_raw(rgb)
        nav=sensor.capture_navigation();captured.append(nav);timings.append(('navigation',getattr(sensor,'last_capture_timing',None)));append_raw(nav)
        pose=sensor.robot_pose(nav)
    except Exception:
        if pipeline.measurements is not None:
            for obs in captured:pipeline.measurements.capture(obs)
        for obs,(lane,timing) in zip(captured,timings):_record_sensor_timing(pipeline,obs,timing,lane)
        raise
    if not _pose_ready_for_display(pipeline,nav,pose,captured):
        for obs,(lane,timing) in zip(captured,timings):_record_sensor_timing(pipeline,obs,timing,lane)
        return rgb,None
    if display_observer is not None:display_observer(rgb,nav,pose)
    try:pipeline.submit_sensor_pair(rgb,nav,pose)
    except StaleNavigationCapture:
        # Recover only BEFORE any pair admission. Partial mutation remains a
        # hard error; replaying observer/submit calls would double-count input.
        if getattr(pipeline,'_last_index',-1)>=rgb.key.frame_index:raise
        _record_expired_navigation(pipeline,captured)
        for obs,(lane,timing) in zip(captured,timings):_record_sensor_timing(pipeline,obs,timing,lane)
        return rgb,None
    for obs,(lane,timing) in zip(captured,timings):_record_sensor_timing(pipeline,obs,timing,lane)
    return rgb,nav


def _capture_navigation(sensor,pipeline,append_raw,display_observer=None):
    captured=None;timing=None
    try:
        captured=sensor.capture_navigation();timing=getattr(sensor,'last_capture_timing',None);append_raw(captured)
        pose=sensor.robot_pose(captured)
    except Exception:
        if captured is not None and pipeline.measurements is not None:
            pipeline.measurements.capture(captured)
        if captured is not None:_record_sensor_timing(pipeline,captured,timing,'navigation')
        raise
    # Register the exact measured body before its map can reach publication.
    # RGB is absent on this lane; never attach a previous frame's camera cone.
    if not _pose_ready_for_display(pipeline,captured,pose,(captured,)):
        _record_sensor_timing(pipeline,captured,timing,'navigation')
        return None
    if display_observer is not None:display_observer(None,captured,pose)
    try:pipeline.submit_navigation(captured,pose)
    except StaleNavigationCapture:
        _record_expired_navigation(pipeline,(captured,))
        _record_sensor_timing(pipeline,captured,timing,'navigation')
        return None
    _record_sensor_timing(pipeline,captured,timing,'navigation')
    return captured


def replay(input_path,config_path,*,out)->dict:
    config,assets=_checked(config_path)
    if config.data.get('keyframe_sampling','novelty')!='novelty':
        raise ValueError('capacity profile replay requires exact selected semantic journal support; raw resampling is unavailable')
    provenance=_provenance(config);root=_root(out,resume=True)
    session_path=root/'replay-session.json'
    if any(root.iterdir()) and not session_path.exists():raise ValueError('existing output requires its explicit replay-session.json')
    session=ReplaySession.open(session_path,input_path)
    reader=ReplayReader(input_path,allow_incomplete=config.data.get('replay',{}).get('allow_incomplete',False),session=session)
    if reader.manifest['episode_id']!=config.data['episode']['id']:raise ValueError('replay episode does not match config')
    pinned=dict(config_sha256=file_sha256(config.path),input_sha256=session.state['input_sha256'],
        detections_sha256=file_sha256(assets['detections']) if 'detections' in assets else None,
        provenance=provenance)
    pinpath=root/'replay-inputs.json'
    if pinpath.exists() and json.loads(pinpath.read_text())!=pinned:raise ValueError('replay session config/detection inputs changed')
    _write(pinpath,pinned)
    detector=_RecordedDetector(assets['detections'],reader.manifest) if config.data['mode']=='fixture_cpu_no_models' else None
    # Recover virtual time before pending accepted frames reach owner/verifier.
    for record in reader.manifest['records']:
        if record['source_clock_domain']!=reader.manifest['records'][0]['source_clock_domain']:
            raise ValueError('recording clock changed')
    if reader.manifest['records']:
        anchor=reader.manifest['records'][0]['source_capture_monotonic_ns']
        session.advance(session.start_ns+max(r['source_capture_monotonic_ns']-anchor for r in reader.manifest['records']))
    from ..visualization.publisher import DisplayPublisher
    publisher=DisplayPublisher(clock_domain=session.clock_domain,now_ns=session.now_ns)
    pipeline=_pipeline(config,assets,root,session.clock_domain,session.now_ns,recorded=detector,publisher=publisher)
    frames=0;skipped=0;error=None;last_report=None;attempt=None;ui=None;ui_cleanup=None
    try:
        if config.data.get('ui',{}).get('enabled',False):
            from .ui_transport import UiProcess
            if config.data.get('ui',{}).get('room_label_debug') is not None:
                from .room_label_ui_entry import RoomLabelUiProcess as UiProcess
            python,script=assets['ui']
            ui=UiProcess(root/'ui',python=python,script=script,clock_domain=session.clock_domain,
                command_handler=pipeline.handle_ui_command,assets_root=root/'objects'/'assets',
                recording_root=input_path,
                navigation_provider=pipeline.navigation_display,
                live_nav_provider=pipeline.live_navigation_display,
                overview_provider=pipeline.global_map_display,
                **({'room_label_debug':config.data['ui']['room_label_debug']} if 'room_label_debug' in config.data.get('ui',{}) else {}),
                smoke_exit_ms=config.data.get('ui',{}).get('smoke_exit_ms'),quota=pipeline.quota,
                **({'publish_hz':config.data['ui']['publish_hz']} if 'publish_hz' in config.data.get('ui',{}) else {}))
            pipeline.publisher=ui
            _apply_ui_priority(config,ui,pipeline)
        attempt=_record_attempt(root,pipeline,provenance)
        watermark=pipeline.telemetry()['scheduler']['watermark']
        for obs in reader.frames():
            frames+=1;session.advance(obs.capture_monotonic_ns)
            if obs.modality=='rgbd' and obs.key.frame_index<=watermark:
                skipped+=1;continue
            before=pipeline.telemetry()['committed']
            pipeline.submit(obs)
            if obs.modality=='rgbd':
                deadline=time.monotonic()+30.
                while time.monotonic()<deadline:
                    state=pipeline.telemetry()
                    if state['health']['failed']:raise RuntimeError('replay worker failed: '+str(state['health']['failed']))
                    if state['committed']>before or state['offered']==0:break
                    # Non-keyframe live replay can legitimately make no offer.
                    if detector is None and state['scheduler']['pending']==state['scheduler']['inflight']==0:break
                    time.sleep(.002)
                else:raise RuntimeError('replay commit deadline exceeded')
    except (ValueError,RuntimeError,OSError) as exc:error=f'{type(exc).__name__}: {exc}'
    finally:
        timeout=config.data.get('budgets',{}).get('shutdown_timeout_s',5.)
        deadline=time.monotonic()+timeout
        last_report=pipeline.close(max(.001,deadline-time.monotonic()))
        if ui is not None:ui_cleanup=ui.close(max(.001,deadline-time.monotonic()))
    failed=error is not None or bool(last_report['failed'])
    complete=(reader.certificate.get('complete') and last_report['clean_shutdown']
        and last_report['recorder_certificate']['complete']
        and (ui_cleanup is None or ui_cleanup.get('clean_shutdown') is True))
    result=_export(root,pipeline,last_report,dict(outcome='failed' if failed else 'completed' if complete else 'incomplete',
        mode=config.data['mode'],episode_id=config.data['episode']['id'],frames=frames,skipped_restored_frames=skipped,
        source_input_sha256=session.state['input_sha256'],replay_session=dict(session.state,clock_domain=session.clock_domain),
        recording_certificate=reader.certificate,error=error,attempt_id=attempt,ui_cleanup=ui_cleanup))
    return result


def replay_control_cadence(input_path,config_path,measurements_path,*,out,
                           duration_s=15.,warmup_s=5.)->dict:
    """Replay a bounded source window through control with a non-actuating fake.

    This is deliberately separate from live ``run`` and ordinary ``replay``.
    Recorded poses are re-keyed into a private replay clock; no Habitat client
    or simulator actuator is constructed. Only the explicit OfflineReplayActuator
    can pass the Pipeline control seam in this mode.
    """
    if (type(duration_s) not in (int,float) or not math.isfinite(duration_s)
            or not 1.<=duration_s<=60.):
        raise ValueError('cadence replay duration must be in [1,60] seconds')
    if (type(warmup_s) not in (int,float) or not math.isfinite(warmup_s)
            or not 0.<=warmup_s<=15.):
        raise ValueError('cadence replay warmup must be in [0,15] seconds')
    config,assets=_checked(config_path)
    if config.data['mode']!='live':raise ValueError('control cadence replay requires a calibrated live profile')
    if config.data.get('keyframe_sampling','novelty')!='novelty':
        raise ValueError('control cadence replay requires novelty sampling or a selected-input journal')
    root=_root(out,resume=False)
    session_path=root/'replay-session.json'
    session=ReplaySession.open(session_path,input_path)
    reader=ReplayReader(input_path,session=session)
    raw=list(reader.source_frames())
    if not raw:raise ValueError('control cadence replay requires nonempty recording')
    try:sidecar=json.loads(Path(measurements_path).read_text())
    except (OSError,json.JSONDecodeError) as exc:raise ValueError('cannot read control cadence sidecar') from exc
    if (not isinstance(sidecar,dict) or sidecar.get('schema_version')!=1
            or sidecar.get('context',{}).get('episode_id')!=reader.manifest['episode_id']
            or sidecar.get('context',{}).get('clock_domain')!=reader.manifest['records'][0]['source_clock_domain']):
        raise ValueError('measurement sidecar episode/clock does not match recording')

    from .replay_control import OfflineReplayActuator,ReplayControlClock,ReplayPose,source_identity
    by_source={source_identity(obs.key):obs for obs in raw}
    control_rows=[row for row in sidecar.get('collector',{}).get('trace',{}).get('records',[])
        if row.get('event')=='control']
    control_stamps={};source_results={}
    for row in control_rows:
        source=row.get('source')
        if not isinstance(source,dict):continue
        key_value=source.get('key',{})
        key=FrameKey(key_value.get('episode_id'),key_value.get('sensor_id'),key_value.get('frame_index'))
        original=by_source.get(source_identity(key))
        if (original is None or original.modality!='depth_only'
                or source.get('capture_monotonic_ns')!=original.capture_monotonic_ns
                or source.get('clock_domain')!=original.clock_domain
                or source.get('pose_version')!=original.pose_version
                or source.get('calibration_id')!=original.calibration_id):
            raise ValueError('control trace is not bound to its exact recorded navigation observation')
        identity=source_identity(key)
        if identity in control_stamps:raise ValueError('duplicate control event source')
        control_stamps[identity]=original.capture_monotonic_ns
        source_results[identity]=str(row.get('reason','unreported_control_result'))
    if not control_rows or not control_stamps:
        raise ValueError('measurement sidecar has no source-bound control events')
    first_control_stamp=min(control_stamps.values())
    poses={}
    for row in sidecar.get('actuation',{}).get('body_pose_records',[]):
        source=row.get('source',{});key_value=source.get('key',{})
        key=FrameKey(key_value.get('episode_id'),key_value.get('sensor_id'),key_value.get('frame_index'))
        original=by_source.get(source_identity(key))
        if original is None or (source.get('capture_monotonic_ns')!=original.capture_monotonic_ns
                or source.get('clock_domain')!=original.clock_domain
                or source.get('pose_version')!=original.pose_version
                or source.get('calibration_id')!=original.calibration_id
                or original.modality!='depth_only'):
            raise ValueError('pose sidecar is not bound to its exact recorded navigation observation')
        replay_stamp=session.start_ns+(original.capture_monotonic_ns-first_control_stamp)
        pose=ReplayPose(key,replay_stamp,session.clock_domain,original.pose_version,
            tuple(float(v) for v in row['robot_xy']),float(row['yaw_rad']))
        if source_identity(key) in poses:raise ValueError('duplicate pose source in sidecar')
        poses[source_identity(key)]=pose
    missing_pose=set(control_stamps)-set(poses)
    if missing_pose:raise ValueError('control event source has no measured pose sidecar')

    window_start=first_control_stamp+int(warmup_s*1e9)
    window_end=window_start+int(duration_s*1e9)
    selected=[obs for obs in raw if first_control_stamp<=obs.capture_monotonic_ns<=window_end]
    if not selected:raise ValueError('selected control cadence window has no recorded observations')
    selected_controls={identity for identity,stamp in control_stamps.items() if window_start<=stamp<=window_end}
    if not selected_controls:raise ValueError('selected control cadence window has no control events')

    clock=ReplayControlClock(start_ns=session.start_ns,clock_domain=session.clock_domain)
    actor=OfflineReplayActuator(poses,clock_domain=session.clock_domain,now_ns=clock.now_ns)
    ui=None;pipeline=None;error=None;ui_cleanup=None;report=None
    control=_ControlInvocations(20000)
    try:
        from ..visualization.publisher import DisplayPublisher
        publisher=DisplayPublisher(clock_domain=session.clock_domain,now_ns=clock.now_ns)
        pipeline=_pipeline(config,assets,root,session.clock_domain,clock.now_ns,
            publisher=publisher,offline_replay_control=True)
        pipeline._control_invocations=control
        if config.data.get('ui',{}).get('enabled',False):
            from .ui_transport import UiProcess
            if config.data.get('ui',{}).get('room_label_debug') is not None:
                from .room_label_ui_entry import RoomLabelUiProcess as UiProcess
            python,script=assets['ui']
            ui=UiProcess(root/'ui',python=python,script=script,clock_domain=session.clock_domain,
                command_handler=pipeline.handle_ui_command,assets_root=root/'objects'/'assets',
                recording_root=input_path,
                navigation_provider=pipeline.navigation_display,
                live_nav_provider=pipeline.live_navigation_display,
                overview_provider=pipeline.global_map_display,quota=pipeline.quota,
                **({'room_label_debug':config.data['ui']['room_label_debug']} if 'room_label_debug' in config.data.get('ui',{}) else {}),
                smoke_exit_ms=config.data.get('ui',{}).get('smoke_exit_ms'),
                **({'publish_hz':config.data['ui']['publish_hz']} if 'publish_hz' in config.data.get('ui',{}) else {}))
            pipeline.publisher=ui
            _apply_ui_priority(config,ui,pipeline)
        clock.reset_wall_anchor()
        wall_anchor=time.monotonic_ns()
        for source in selected:
            relative=source.capture_monotonic_ns-first_control_stamp
            due=wall_anchor+relative
            remaining=(due-time.monotonic_ns())/1e9
            if remaining>0:time.sleep(remaining)
            replay_stamp=session.start_ns+relative
            clock.set_source_time(replay_stamp)
            obs=replace(source,capture_monotonic_ns=replay_stamp,clock_domain=session.clock_domain)
            identity=source_identity(source.key)
            if obs.modality=='rgbd':
                pipeline.submit(obs)
            elif obs.modality=='depth_only':
                pose=poses.get(identity)
                if pose is None:continue
                replay_pose=ReplayPose(obs.key,obs.capture_monotonic_ns,obs.clock_domain,
                    pose.pose_version,pose.robot_xy,pose.yaw_rad)
                pipeline.submit_navigation(obs,dict(source=replay_pose.source,
                    capture_monotonic_ns=replay_pose.capture_monotonic_ns,
                    clock_domain=replay_pose.clock_domain,pose_version=replay_pose.pose_version,
                    robot_xy=replay_pose.robot_xy,yaw_rad=replay_pose.yaw_rad))
                if identity not in selected_controls:continue
                freshness_deadline=time.monotonic()+.300
                ready=False
                while time.monotonic()<freshness_deadline:
                    with pipeline._lock:
                        nav=pipeline._latest_nav
                    if (nav is not None and nav.source==obs.key and nav.capture_monotonic_ns==obs.capture_monotonic_ns
                            and nav.clock_domain==obs.clock_domain):
                        ready=True;break
                    if pipeline.health.snapshot()['failed']:break
                    time.sleep(.001)
                stamp=clock.now_ns()
                control.record(stamp,navigation_ready=ready)
                result=pipeline.control_step(actor)
                control.result(result)
        runtime_report=pipeline.close(config.data.get('budgets',{}).get('shutdown_timeout_s',10.))
        report=runtime_report
    except (ValueError,RuntimeError,OSError,TimeoutError,TypeError) as exc:
        error=f'{type(exc).__name__}: {exc}'
    finally:
        if pipeline is not None and report is None:
            report=pipeline.close(config.data.get('budgets',{}).get('shutdown_timeout_s',10.))
        if ui is not None:
            ui_cleanup=ui.close(config.data.get('budgets',{}).get('shutdown_timeout_s',10.))
    stats=control.snapshot(session.clock_domain)
    durations=[(b-a)/1e6 for a,b in zip(stats['starts_monotonic_ns'],stats['starts_monotonic_ns'][1:])]
    ordered=sorted(durations)
    latency=dict(count=len(durations),mean_ms=None if not durations else sum(durations)/len(durations),
        p50_ms=None if not ordered else ordered[(len(ordered)-1)//2],
        p95_ms=None if not ordered else ordered[round((len(ordered)-1)*.95)],
        max_ms=None if not ordered else ordered[-1])
    selected_source_results={}
    for identity in selected_controls:
        reason=source_results[identity]
        selected_source_results[reason]=selected_source_results.get(reason,0)+1
    result=dict(schema_version=1,outcome='failed' if error else 'completed' if report and report.get('clean_shutdown') else 'incomplete',
        error=error,episode_id=reader.manifest['episode_id'],input_sha256=session.state['input_sha256'],
        config_sha256=file_sha256(config.path),ui_enabled=bool(config.data.get('ui',{}).get('enabled',False)),
        actuator='offline_replay_ack_only',source_window=dict(start_ns=window_start,end_ns=window_end,
            warmup_s=float(warmup_s),duration_s=float(duration_s),observations=len(selected),control_events=len(selected_controls)),
        control_invocations=stats['total'],control_results=stats['control_results'],
        control_status_counts=dict(simulated_ack=stats['control_results'].get('offline_replay_ack',0),
            expired_or_zero=stats['control_results'].get('expired_or_zero',0),
            navigation_source_pending=stats['control_results'].get('navigation_source_pending',0)),
        source_run_control_results=selected_source_results,
        navigation_wait=stats['navigation_wait'],control_interval=latency,
        actuator_calls=actor.calls,ui_cleanup=ui_cleanup,
        worker_runtime=dict(getattr(pipeline,'_launcher_worker_metadata',{})) if pipeline is not None else {},
        runtime=report)
    _write(root/'cadence-replay.json',result)
    session.advance(clock.now_ns())
    return result


def run(config_path,*,duration_s,out)->dict:
    if type(duration_s) not in (int,float) or not math.isfinite(duration_s) or not 0<duration_s<=600:
        raise ValueError('duration_s must be positive finite and <=600 seconds')
    config=load_config(config_path)
    maximum=config.data.get('long_demo',{}).get('max_duration_s',300)
    if duration_s>maximum:raise ValueError('duration_s exceeds explicit profile ceiling '+str(maximum))
    if config.data['mode']!='live':raise ValueError('fixture_cpu_no_models is replay only')
    config,assets=_checked(config_path);provenance=_provenance(config);root=_root(out,resume=False)
    if 'long_demo' in config.data:
        import shutil
        required=config.data.get('budgets',{}).get('total_cap',8*1024**3)+1024**3
        if shutil.disk_usage(root).free<required:
            raise ValueError('long_demo requires free disk >= total_cap plus 1 GiB before worker startup')
    from ..sensors.client import HabitatPoseSource
    from .capture_gc import CaptureGCWindow
    capture_gc=CaptureGCWindow(config.data.get('runtime',{}).get('defer_capture_gc',False))
    sensor_config=_sensor_launch_configuration(config,assets)
    python,script=assets['sensor'];sensor=None;pipeline=None;recorder=None;ui=None;error=None;raw_cert=None;report=None;frames=0;admission_stop=None
    policy=_recording_policy(config);attempt=None
    measurement_options=config.data.get('measurements',{});measured=measurement_options.get('enabled',False)
    sampler=None;measurements=None;resource_report=None;provider_diagnostics=None;cap_event=__import__('threading').Event();cap_payload=[]
    launch_digest=hashlib.sha256(_canonical(sensor_config)).hexdigest()
    def cap_breach(payload):
        if not cap_payload:cap_payload.append(dict(payload))
        cap_event.set()
        if measurements is not None:measurements.cap_breach(payload)
    def make_measurements(domain,metadata):
        from .measurements import MeasurementContext
        from .observability import RunMeasurements
        execution=None if metadata is None else metadata.get('execution')
        ids=tuple(dict.fromkeys(sensor_config[lane]['sensor_id'] for lane in ('primary','navigation')))
        context=MeasurementContext(attempt,config.data['episode']['id'],domain,file_sha256(config.path),launch_digest,
            None if execution is None else hashlib.sha256(_canonical(execution)).hexdigest(),ids)
        value=RunMeasurements(context,**{k:v for k,v in measurement_options.items() if k in {'sample_cap','capture_cap','trace_byte_cap','proof_record_cap'}})
        if cap_payload:value.cap_breach(cap_payload[0])
        return value
    try:
        if measured:
            from .resources import ResourceSampler,ProcTreeProvider
            from .quota import RunQuota
            from ..sensors.habitat_worker import host_clock_domain
            gpu=None
            if 'measurement_gpu' in assets:
                from .gpu_provider import NvidiaSmiProvider
                gpu=NvidiaSmiProvider(executable=assets['measurement_gpu'],gpu_uuid=measurement_options['gpu_uuid'])
            sampler=ResourceSampler(provider=ProcTreeProvider(sample_timeout_s=measurement_options.get('rss_sample_timeout_s',.1),
                **({'retry_wait_s':measurement_options['rss_retry_wait_s']} if 'rss_retry_wait_s' in measurement_options else {})),
                gpu_provider=gpu,rss_cap_bytes=measurement_options.get('rss_cap_bytes',10*1024**3),
                gpu_cap_bytes=measurement_options.get('gpu_cap_bytes',5*1024**3),on_cap_breach=cap_breach)
            attempt=str(uuid.uuid4());sampler.start()
            startup=dict(provenance,attempt_id=attempt,clock_domain=host_clock_domain(),phase='before_sensor_model_startup',
                sensor_launch=dict(configuration=sensor_config,config_sha256=launch_digest,runtime_metadata=None))
            payload=_canonical(startup)
            quota=RunQuota(root,raw_cap=config.data.get('budgets',{}).get('raw_cap',2*1024**3),total_cap=config.data.get('budgets',{}).get('total_cap',8*1024**3))
            quota.reserve('startup-measurement-provenance',2*len(payload)+65536)
            try:
                (root/'attempts').mkdir(exist_ok=True)
                _write_atomic(root/'attempts'/(attempt+'-startup.json'),payload)
            finally:quota.release('startup-measurement-provenance')
            if cap_event.is_set():raise RuntimeError('resource cap breached before sensor startup')
        sensor=HabitatPoseSource(python=python,worker_script=script,config=sensor_config,
            timeout_s=config.data['workers']['sensor'].get('timeout_s',10.))
        first=sensor.capture_navigation()
        if first.key.episode_id!=config.data['episode']['id']:raise ValueError('sensor episode mismatch')
        sensor_metadata=getattr(sensor,'runtime_metadata',None)
        launch_digest=hashlib.sha256(_canonical(sensor_config)).hexdigest()
        if 'seed' in sensor_config:
            execution=None if sensor_metadata is None else sensor_metadata.get('execution')
            if (not isinstance(execution,dict) or type(execution.get('seed')) is not int
                or execution['seed']!=sensor_config['seed'] or execution.get('seed_applied') is not True
                or execution.get('config_sha256')!=launch_digest
                or execution.get('episode_id')!=first.key.episode_id
                or execution.get('clock_domain')!=first.clock_domain
                or sensor_metadata.get('launch_config_sha256')!=launch_digest):
                raise ValueError('seeded sensor launch execution ACK does not match source/config')
        # Startup proof is immutable attempt provenance. Primary-resolution
        # support is still absent until a primary capture actually succeeds.
        provenance['sensor_launch']=dict(configuration=sensor_config,config_sha256=launch_digest,
            runtime_metadata=sensor_metadata)
        from ..visualization.publisher import DisplayPublisher
        publisher=DisplayPublisher(clock_domain=first.clock_domain)
        if measured:measurements=make_measurements(first.clock_domain,sensor_metadata)
        pipeline=_pipeline(config,assets,root,first.clock_domain,time.monotonic_ns,publisher=publisher,**({'measurements':measurements} if measured else {}))
        runtime=config.data.get('runtime')
        pipeline._control_invocations=_ControlInvocations(20000 if runtime is None else runtime['control_sample_cap'])
        pipeline._measurement_export_byte_cap=(64 if 'long_demo' in config.data else 16)*1024**2
        cadence=None if runtime is None else _CaptureCadence(primary_hz=runtime['primary_hz'],navigation_hz=runtime['navigation_hz'])
        attempt=_record_attempt(root,pipeline,provenance,**({'attempt_id':attempt} if measured else {}))
        archive_budget=policy['archive_max_bytes']
        archive_path=root/'keyframes'/'recording'
        covered={}
        if 'long_demo' in config.data:
            # Exclusive recorder subtree: its writer bounds payloads, atomic
            # staging and metadata; the full cap stays charged without scanning
            # thousands of immutable payload files on every navigation update.
            archive_path.mkdir(parents=True,exist_ok=True)
            covered['covered_path']=archive_path
        pipeline.quota.reserve('full-raw-recording',archive_budget,archive_budget,**covered)
        recorder=ReplayWriter(archive_path,max_bytes=archive_budget,
            payload_format=config.data.get('long_demo',{}).get('payload_format','json_v1'),
            source_provenance=dict(config_sha256=file_sha256(config.path),mode='live'))
        if config.data.get('ui',{}).get('enabled',False):
            from .ui_transport import UiProcess
            if config.data.get('ui',{}).get('room_label_debug') is not None:
                from .room_label_ui_entry import RoomLabelUiProcess as UiProcess
            python,script=assets['ui']
            ui=UiProcess(root/'ui',python=python,script=script,clock_domain=first.clock_domain,
                command_handler=pipeline.handle_ui_command,assets_root=root/'objects'/'assets',
                recording_root=archive_path,
                navigation_provider=pipeline.navigation_display,
                live_nav_provider=pipeline.live_navigation_display,
                overview_provider=pipeline.global_map_display,
                **({'room_label_debug':config.data['ui']['room_label_debug']} if 'room_label_debug' in config.data.get('ui',{}) else {}),
                smoke_exit_ms=config.data.get('ui',{}).get('smoke_exit_ms'),quota=pipeline.quota,
                **({'publish_hz':config.data['ui']['publish_hz']} if 'publish_hz' in config.data.get('ui',{}) else {}))
            pipeline.publisher=ui
            _apply_ui_priority(config,ui,pipeline)
        # The startup capture binds the seed/clock ACK, but constructing the
        # pipeline/recorder/UI can outlive its control freshness window. Obtain
        # a new source after setup; never refresh the old capture's timestamp.
        # Preserve the startup source as raw history so the deliberate recapture
        # does not create a missing frame in the lossless recording certificate.
        _append_raw(recorder,first);frames+=1
        def append_active_raw(obs):
            nonlocal frames
            _append_raw(recorder,obs);frames+=1
        capture_deadline=time.monotonic()+5.
        while _capture_navigation(sensor,pipeline,append_active_raw,
                display_observer=None if ui is None else ui.observe_robot) is None:
            if time.monotonic()>=capture_deadline:
                raise TimeoutError('navigation captures repeatedly expired during startup')
        deadline=time.monotonic()+duration_s
        while time.monotonic()<deadline:
            if cap_event.is_set():admission_stop='resource_cap_breached';break
            if pipeline.health.snapshot()['failed']:admission_stop='runtime_health_failed';break
            if cadence is not None:
                delay=min(cadence.navigation_delay(time.monotonic()),max(0.,deadline-time.monotonic()))
                if delay:time.sleep(delay)
                if time.monotonic()>=deadline:break
                cadence.navigation_started(time.monotonic())
            # Both captures and guarded motion remain on this sensor thread;
            # graph/model/region/Qt publication happens independently. The last
            # nav input in each pair is the source-bound independent depth.
            with capture_gc:
                primary_due=cadence is None or cadence.primary_due(time.monotonic())
                if primary_due:
                    rgb,obs=_capture_sensor_pair(sensor,pipeline,append_active_raw,display_observer=None if ui is None else ui.observe_robot)
                    if ui is not None:ui.set_rgb(rgb)
                else:
                    obs=_capture_navigation(sensor,pipeline,append_active_raw,display_observer=None if ui is None else ui.observe_robot)
                if obs is None:continue  # Recorded expired input never becomes a control command.
                wait_start_ns=time.monotonic_ns()
                try:ready=_wait_exact_navigation(pipeline,obs,deadline)
                finally:
                    wait_end_ns=time.monotonic_ns()
                    if pipeline.measurements is not None:
                        pipeline.measurements.stage(obs,'control_navigation_wait',wait_start_ns,wait_end_ns)
                _invoke_control_before_run_deadline(pipeline,sensor,obs,
                    navigation_ready=ready,run_deadline=deadline)
            with pipeline._lock:stop_requested=pipeline._stop_requested
            if stop_requested:break
    except _RawAdmissionStopped as exc:admission_stop=str(exc)
    except (ValueError,RuntimeError,OSError,TimeoutError) as exc:error=f'{type(exc).__name__}: {exc}'
    finally:
        timeout=config.data.get('budgets',{}).get('shutdown_timeout_s',5.)
        deadline=time.monotonic()+timeout
        if pipeline is not None:report=pipeline.close(max(.001,deadline-time.monotonic()))
        if recorder is not None:
            raw_cert=recorder.close(max(0.,deadline-time.monotonic()))
            if raw_cert.get('stopped') and pipeline is not None:pipeline.quota.release('full-raw-recording')
        cleanup={}
        if recorder is not None:cleanup['raw_recorder']=dict(clean_shutdown=bool(raw_cert and raw_cert.get('stopped') is True))
        if sensor is not None:cleanup['sensor']=sensor.close(max(.001,deadline-time.monotonic()))
        if ui is not None:cleanup['ui']=ui.close(max(.001,deadline-time.monotonic()))
        if pipeline is not None and sensor is not None:
            metadata=getattr(sensor,'runtime_metadata',None)
            if metadata is not None:
                pipeline._launcher_worker_metadata=getattr(pipeline,'_launcher_worker_metadata',{})
                pipeline._launcher_worker_metadata['sensor']=metadata
        if sampler is not None:
            resource_report=sampler.close(timeout_s=max(0.,deadline-time.monotonic()))
            provider_diagnostics=sampler.provider_diagnostics()
            cleanup['resources']=dict(resource_report,clean_shutdown=not resource_report['worker_pending'])
            if measurements is None:
                from ..sensors.habitat_worker import host_clock_domain
                measurements=make_measurements(host_clock_domain(),getattr(sensor,'runtime_metadata',None))
            execution=getattr(sensor,'runtime_metadata',{}).get('execution') if sensor is not None else None
            artifact=measurements.finalize(runtime_report=report or dict(clean_shutdown=False,pending=None),resources=resource_report,
                seed_ack=execution,launch_config=sensor_config,cleanup=cleanup,outcome='failed' if error else 'incomplete' if admission_stop else 'runtime_finished')
            if pipeline is not None:pipeline._final_measurements=artifact
    if report is None:
        result=dict(outcome='failed',error=error,mode='live',native_runtime_validated=False,cleanup=cleanup,attempt_id=attempt,config_sha256=file_sha256(config.path),resource_provider_diagnostics=provider_diagnostics,
            resource_acquisition=_resource_acquisition(measurement_options,resource_report))
        if measurements is not None:
            payload=_measurement_payload(artifact,max_bytes=(64 if 'long_demo' in config.data else 16)*1024**2)
            quota=RunQuota(root,raw_cap=config.data.get('budgets',{}).get('raw_cap',2*1024**3),total_cap=config.data.get('budgets',{}).get('total_cap',8*1024**3))
            quota.reserve('partial-measurement-export',2*len(payload)+65536)
            try:
                _write_atomic(root/'measurements.json',payload)
                result['measurement_artifact']=dict(path='measurements.json',sha256=hashlib.sha256(payload).hexdigest())
                result['measurement_export_byte_cap']=(64 if 'long_demo' in config.data else 16)*1024**2
                _write(root/'summary.json',result)
            finally:quota.release('partial-measurement-export')
            return result
        _write(root/'summary.json',result);return result
    if capture_gc.enabled:report['capture_gc']=capture_gc.snapshot()
    clean=report['clean_shutdown'] and all(x.get('clean_shutdown',False) for x in cleanup.values())
    complete=clean and bool(raw_cert and raw_cert.get('complete')) and report['recorder_certificate']['complete']
    return _export(root,pipeline,report,dict(outcome='failed' if error or report['failed'] else 'completed' if complete else 'incomplete',
        mode='live',episode_id=config.data['episode']['id'],frames=frames,error=error,
        recording_certificate=raw_cert,cleanup=cleanup,config_sha256=file_sha256(config.path),
        recording_policy=policy,admission_stop=admission_stop,attempt_id=attempt,resource_provider_diagnostics=provider_diagnostics,
        resource_acquisition=_resource_acquisition(measurement_options,resource_report)))


def _resource_acquisition(options,report):
    if report is None:return None
    rss=report['rss']
    return dict(schema_version=1,rss_sample_timeout_s=options.get('rss_sample_timeout_s',.1),
        rss_retry_wait_s=options.get('rss_retry_wait_s',.005),
        rss_interval_s=report['interval_s'],first_sample_ns=rss['first_sample_ns'],
        last_sample_ns=rss['last_sample_ns'],max_sample_gap_ns=rss['max_sample_gap_ns'],
        limitation='sampled sequential tree reads; successful trial start timestamps; acquisition plus interval and scheduling determines gaps; no continuous cap enforcement')
