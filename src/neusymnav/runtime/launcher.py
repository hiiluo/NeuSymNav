"""Explicit local launch/replay composition. No native/fixture fallback exists."""
from __future__ import annotations
from dataclasses import replace
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

from ..contracts import DetectionBatch, Observation, from_dict
from ..contracts.serialization import dumps, loads
from ..mapping.occupancy import NavMapper, RobotGeometry
from ..objects.store import ObjectOwner
from ..recording.replay import ReplayReader, ReplaySession, _canonical, _write_atomic
from ..recording.writer import ReplayWriter
from ..verification.ledger import VerificationOwner
from .configuration import load_config, file_sha256
from .coordinator import Pipeline


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


def _probe_interpreter(python,modules,label):
    """Read-only bounded interpreter/dependency probe; imports no model runtime."""
    import subprocess
    program=("import importlib.util,importlib.metadata,json,sys; "
        "print(json.dumps(dict(version=list(sys.version_info[:3]),executable=sys.executable,prefix=sys.prefix,missing=[m for m in "+repr(list(modules))+" if importlib.util.find_spec(m) is None])))")
    try:
        result=subprocess.run([str(python),'-I','-c',program],capture_output=True,timeout=3.,check=False)
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
    def __init__(self,client,sink):self.client=client;self.sink=sink
    def infer(self,obs):
        try:return self.client.infer(obs)
        finally:
            self.sink['detector']=dict(runtime_versions=getattr(self.client,'runtime_metadata',None),
                actual_recipe=dict(getattr(self.client,'recipe',{})))
    def close(self,timeout_s=1.):return self.client.close(timeout_s=timeout_s)


class _EncoderMetadata:
    def __init__(self,encoder,sink):self.encoder=encoder;self.sink=sink;self.used=0;self.fallback=0
    def encode(self,obs,batch):
        result=self.encoder.encode(obs,batch)
        if result is None:self.fallback+=1
        else:self.used+=1
        self.sink['appearance']=dict(feature_frames=self.used,geometry_fallback_frames=self.fallback,
            last_status=dict(self.encoder.last_status),space_metadata=None if self.encoder.space_metadata is None else dict(self.encoder.space_metadata))
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

    def snapshot(self,domain):
        return dict(schema_version=1,clock_domain=domain,population='actual_control_step_invocation_starts_including_stop_and_pending',
            starts_monotonic_ns=list(self.starts),total=self.total,retained=len(self.starts),
            dropped=self.total-len(self.starts),complete=self.total==len(self.starts),cap=self.cap,
            navigation_wait=dict(self.wait_counts),control_results=dict(self.results),
            result_total=self.result_total,result_missing=self.total-self.result_total,executed_results=self.executed,
            intervals=dict(count=self.count,mean_ns=None if not self.count else self.sum_ns/self.count,
                max_ns=None if not self.count else self.max_ns,miss_50ms=self.miss50,miss_100ms=self.miss100),
            limitation='capture/map waits contribute to intervals; no timer catchup; raw quantiles require complete starts')


def _append_raw(recorder,obs):
    if not recorder.append(obs):raise _RawAdmissionStopped('raw_recording_rejected')


def _wait_exact_navigation(pipeline,observation,run_deadline):
    """Yield only for the map of this capture, bounded by its original TTL.

    No detector, ledger, room or UI state can extend this deadline. Source age
    is checked again by control and worker after the wait.
    """
    remaining_age=(observation.capture_monotonic_ns+300_000_000-time.monotonic_ns())/1e9
    deadline=min(run_deadline,time.monotonic()+max(0.,remaining_age))
    while time.monotonic()<deadline:
        with pipeline._lock:
            nav=pipeline._latest_nav;stopped=pipeline._stop_requested or pipeline._closing or pipeline._paused
        if stopped:return False
        if pipeline.health.snapshot()['failed']:return False
        if nav is not None and nav.source==observation.key and nav.capture_monotonic_ns==observation.capture_monotonic_ns and nav.clock_domain==observation.clock_domain:
            return True
        time.sleep(.001)
    return False


def _assets(config):
    """Resolve all declared resources without starting interpreters/frameworks."""
    d=config.data;resolved={};issues=[]
    def check(label,call):
        try:resolved[label]=call()
        except (ValueError,OSError,TypeError,KeyError) as exc:issues.append(str(exc))
    if d['mode']=='fixture_cpu_no_models':
        check('detections',lambda:config.asset(d.get('fixture',{}).get('detections'),'fixture.detections'))
    else:
        for name in ('sensor','detector','region'):
            check(name,lambda name=name:config.worker(name))
        sensor=d.get('sensor_config',{})
        check('scene',lambda:config.asset(sensor.get('scene'),'sensor_config.scene'))
        if not sensor.get('navigation'):issues.append('sensor_config.navigation requires a calibrated independent depth sensor')
        detector=d.get('detector',{})
        for name in ('checkpoint','encoder','taxonomy'):
            check(name,lambda name=name:config.asset(detector.get(name),'detector.'+name))
        if d.get('ui',{}).get('enabled',False):check('ui',lambda:config.worker('ui'))
        if d.get('navigation',{}).get('mapper',{}).get('raycast_backend','cpu')=='triton_cuda':
            check('raycast',lambda:config.worker('raycast'))
        if sensor.get('scene_dataset') is not None:check('scene_dataset',lambda:config.asset(sensor['scene_dataset'],'sensor_config.scene_dataset'))
    if d.get('measurements',{}).get('enabled') and 'gpu_executable' in d['measurements']:
        check('measurement_gpu',lambda:config.asset(d['measurements']['gpu_executable'],'measurements.gpu_executable',executable=True))
    if d.get('appearance_mode','off')=='openclip':
        worker=d.get('worker',{})
        check('appearance',lambda:config.worker('appearance'))
        check('appearance_checkpoint',lambda:config.asset(dict(path=worker.get('checkpoint_path'),sha256=worker.get('checkpoint_sha256')),'worker.checkpoint'))
    for name,modules in [('sensor',['numpy','habitat_sim']),('detector',['numpy','torch','ultralytics','clip']),('appearance',['numpy','PIL','torch','open_clip','safetensors']),('ui',['numpy','PyQt5']),('raycast',['numpy','torch','triton'])]:
        if name in resolved and isinstance(resolved[name],tuple):
            try:config.runtime_probes[name]=_probe_interpreter(resolved[name][0],modules,name)
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
    selected=options.pop('raycast_backend','cpu')
    if selected=='triton_cuda' and raycast_backend is None:raise ValueError('GPU raycast worker not initialized')
    if 'tile_archive_dir' in options:raise ValueError('mapper tile archive is assigned inside run root')
    return NavMapper(robot=robot,floor_z_m=floor['z_m'],floor_datum_source=floor['datum_source'],
        calibration_hash=floor['calibration_sha256'],tile_archive_dir=root/'tiles',raycast_backend=raycast_backend,**options)


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


def _pipeline(config,assets,root,domain,now_ns,*,recorded=None,publisher=None,measurements=None):
    backend=None
    if config.data.get('navigation',{}).get('mapper',{}).get('raycast_backend','cpu')=='triton_cuda':
        if recorded is not None or domain.startswith('replay:'):raise ValueError('GPU profile is live-only; replay requires an explicit CPU profile')
        from ..mapping.gpu_raycast_client import GpuRaycastClient
        python,script=assets['raycast'];worker=config.data['workers']['raycast']
        backend=GpuRaycastClient(python=python,worker_script=script,root=root/'gpu-raycast-ipc',
            timeout_s=worker.get('timeout_s',.25),startup_timeout_s=worker.get('startup_timeout_s',30.))
    try:
        return _pipeline_impl(config,assets,root,domain,now_ns,recorded=recorded,publisher=publisher,
                              measurements=measurements,raycast_backend=backend)
    except BaseException:
        if backend is not None:backend.close()
        raise


def _pipeline_impl(config,assets,root,domain,now_ns,*,recorded=None,publisher=None,measurements=None,raycast_backend=None):
    d=config.data;e=d['episode'];mapper=_mapper(config,root,raycast_backend=raycast_backend)
    encoder=None;region=None;navigator=None;guard=None;worker_metadata={}
    if recorded is None:
        from ..perception.detector_client import DetectorClient,validate_recipe
        from ..contracts import Taxonomy
        recipe={k:v for k,v in d['detector'].items() if k not in {'checkpoint','encoder','taxonomy'}}
        for name in ('checkpoint','encoder','taxonomy'):
            recipe[name+'_path']=str(assets[name]);recipe[name+'_sha256']=file_sha256(assets[name])
        recipe=validate_recipe(recipe);vocabulary=Taxonomy.load(recipe['taxonomy_path']).vocabulary_id
        detector_python,detector_script=assets['detector'];detector_worker=d['workers']['detector']
        detector=lambda:_DetectorMetadata(DetectorClient(python=detector_python,worker_script=detector_script,recipe=recipe,
            timeout_s=detector_worker.get('timeout_s',2.),startup_timeout_s=detector_worker.get('startup_timeout_s',30.)),worker_metadata)
        from ..regions.backend import RegionBackend
        region=lambda:RegionBackend(assets['region'],floor_id=e['floor_id'])
        if not domain.startswith('replay:'):
            from ..navigation.controller import Navigator
            from ..navigation.safety import MotionGuard
            navigator=Navigator(mapper.robot,clock_domain=domain);guard=MotionGuard(mapper,clock_domain=domain)
        if d.get('appearance_mode','off')=='openclip':
            from ..perception.appearance_client import AppearanceWorkerEncoder
            worker=d['worker'];appearance_python,appearance_script=assets['appearance']
            encoder=lambda:_EncoderMetadata(AppearanceWorkerEncoder(appearance_python,assets['appearance_checkpoint'],
                checkpoint_sha256=worker['checkpoint_sha256'],model_name=worker['model_name'],
                preprocessing_id=worker['preprocessing_id'],timeout_s=worker.get('timeout_s',2.),
                startup_timeout_s=worker.get('startup_timeout_s',30.),
                max_request_bytes=worker.get('max_request_bytes',32*1024**2),
                _worker_command=[str(appearance_python),str(appearance_script),'--worker']),worker_metadata)
    else:detector=lambda:recorded;vocabulary=recorded.vocabulary_id
    profile=d['profile']+(':'+d['mode'] if recorded is not None else ':yoloe:appearance-'+d.get('appearance_mode','off'))
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
        appearance_mode=d.get('appearance_mode','off'))
    budgets={k:v for k,v in d.get('budgets',{}).items() if k in {'byte_cap','raw_cap','total_cap'}}
    pipeline=Pipeline(root,episode_id=e['id'],primary_sensor_id=e['primary_sensor_id'],clock_domain=domain,
        floor_id=e['floor_id'],owner_factory=owner,detector_factory=detector,
        verifier_factory=lambda owner:VerificationOwner(owner,clock_domain=domain,now_ns=now_ns,root=root/'verification'),
        encoder_factory=encoder,region_factory=region,mapper=mapper,navigator=navigator,guard=guard,
        keyframe_policy=_RecordedPolicy() if recorded is not None else None,now_ns=now_ns,
        actual_profile=profile,publisher=publisher,measurements=measurements,
        **({'keyframe_sampling':sampling} if sampling!='novelty' else {}),**budgets)
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


def _export(root,pipeline,report,metadata):
    restored=False;export_issue=None
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
    payloads={}
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
    if snapshot is None or nav is None:
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


def _capture_sensor_pair(sensor,pipeline,append_raw,display_observer=None):
    """Acquire outside runtime locks, then publish the latest depth atomically.

    Acquisition failure retains capture-only metadata, never semantic fallback.
    Pair failures are outside that block: normal submit may already have
    registered captures, so replaying observer callbacks would double-count.
    """
    captured=[]
    try:
        rgb=sensor.capture();captured.append(rgb);append_raw(rgb)
        nav=sensor.capture_navigation();captured.append(nav);append_raw(nav)
        pose=sensor.robot_pose(nav)
    except Exception:
        if pipeline.measurements is not None:
            for obs in captured:pipeline.measurements.capture(obs)
        raise
    if display_observer is not None:
        display_observer(rgb,nav,pose)
    pipeline.submit_sensor_pair(rgb,nav,pose)
    return rgb,nav


def _capture_navigation(sensor,pipeline,append_raw,display_observer=None):
    captured=None
    try:
        captured=sensor.capture_navigation();append_raw(captured)
        pose=sensor.robot_pose(captured)
    except Exception:
        if captured is not None and pipeline.measurements is not None:
            pipeline.measurements.capture(captured)
        raise
    # Register the exact measured body before its map can reach publication.
    # RGB is absent on this lane; never attach a previous frame's camera cone.
    if display_observer is not None:
        display_observer(None,captured,pose)
    pipeline.submit_navigation(captured,pose)
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
    frames=0;skipped=0;error=None;last_report=None;attempt=None
    try:
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
    finally:last_report=pipeline.close(config.data.get('budgets',{}).get('shutdown_timeout_s',5.))
    failed=error is not None or bool(last_report['failed'])
    complete=reader.certificate.get('complete') and last_report['clean_shutdown'] and last_report['recorder_certificate']['complete']
    result=_export(root,pipeline,last_report,dict(outcome='failed' if failed else 'completed' if complete else 'incomplete',
        mode=config.data['mode'],episode_id=config.data['episode']['id'],frames=frames,skipped_restored_frames=skipped,
        source_input_sha256=session.state['input_sha256'],replay_session=dict(session.state,clock_domain=session.clock_domain),
        recording_certificate=reader.certificate,error=error,attempt_id=attempt))
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
    sensor_config=dict(config.data['sensor_config']);sensor_config.pop('scene',None)
    sensor_config.pop('scene_dataset',None)
    if 'scene_dataset' in assets:sensor_config['scene_dataset_config_file']=str(assets['scene_dataset'])
    sensor_config['scene_id']=str(assets['scene']);sensor_config['episode_id']=config.data['episode']['id']
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
            python,script=assets['ui']
            ui=UiProcess(root/'ui',python=python,script=script,clock_domain=first.clock_domain,
                command_handler=pipeline.handle_ui_command,assets_root=root/'objects'/'assets',
                navigation_provider=pipeline.navigation_display,
                smoke_exit_ms=config.data.get('ui',{}).get('smoke_exit_ms'),quota=pipeline.quota,
                **({'publish_hz':config.data['ui']['publish_hz']} if 'publish_hz' in config.data.get('ui',{}) else {}))
            pipeline.publisher=ui
        # The startup capture binds the seed/clock ACK, but constructing the
        # pipeline/recorder/UI can outlive its control freshness window. Obtain
        # a new source after setup; never refresh the old capture's timestamp.
        # Preserve the startup source as raw history so the deliberate recapture
        # does not create a missing frame in the lossless recording certificate.
        _append_raw(recorder,first);frames+=1
        first=sensor.capture_navigation()
        first_pose=sensor.robot_pose(first)
        _append_raw(recorder,first)
        if ui is not None:ui.observe_robot(None,first,first_pose)
        pipeline.submit_robot_pose(first,first_pose);pipeline.submit(first);frames+=1
        deadline=time.monotonic()+duration_s
        def append_active_raw(obs):
            nonlocal frames
            _append_raw(recorder,obs);frames+=1
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
            primary_due=cadence is None or cadence.primary_due(time.monotonic())
            if primary_due:
                rgb,obs=_capture_sensor_pair(sensor,pipeline,append_active_raw,display_observer=None if ui is None else ui.observe_robot)
                if ui is not None:ui.set_rgb(rgb)
            else:
                obs=_capture_navigation(sensor,pipeline,append_active_raw,display_observer=None if ui is None else ui.observe_robot)
            ready=_wait_exact_navigation(pipeline,obs,deadline)
            pipeline._control_invocations.record(time.monotonic_ns(),navigation_ready=ready)
            pipeline._control_invocations.result(pipeline.control_step(sensor))
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
