"""Bounded YAML configuration with config-relative, checksummed local assets.

Parsing never launches workers or imports model/native frameworks. Interpreter
paths retain the configured venv spelling even when the executable is a symlink.
"""
from __future__ import annotations
import hashlib
import math
import os
from pathlib import Path
import re
import yaml

MAX_CONFIG_BYTES=256*1024
SHA=re.compile(r'^[0-9a-f]{64}$')
TOP={'schema_version','mode','profile','episode','floor','workers','sensor_config','detector','scene_graph',
     'fixture','appearance_mode','worker','provenance','navigation','budgets','ui','replay','measurements','keyframe_sampling','keyframe_novelty','runtime','long_demo','association'}


class _Loader(yaml.SafeLoader):
    pass
# YAML 1.2 booleans: the legacy appearance_mode: off remains the string 'off'.
_Loader.yaml_implicit_resolvers={k:[(tag,pattern) for tag,pattern in vals
    if tag!='tag:yaml.org,2002:bool'] for k,vals in yaml.SafeLoader.yaml_implicit_resolvers.items()}
_Loader.add_implicit_resolver('tag:yaml.org,2002:bool',re.compile(r'^(?:true|false)$',re.I),list('tTfF'))


def _mapping(value,label,allowed,required=()):
    if not isinstance(value,dict) or any(not isinstance(k,str) for k in value):
        raise ValueError(label+' must be a mapping with string keys')
    extra=set(value)-set(allowed);missing=set(required)-set(value)
    if extra or missing:raise ValueError(f'{label}: unknown fields {sorted(extra)}, missing fields {sorted(missing)}')
    return value


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def load_config(path):
    path=Path(path).absolute()
    try:
        if path.stat().st_size>MAX_CONFIG_BYTES:raise ValueError('configuration exceeds 256 KiB bound')
        payload=path.read_text()
        depth=0;tokens=0
        for token in yaml.scan(payload):
            tokens+=1
            if isinstance(token,(yaml.tokens.AliasToken,yaml.tokens.AnchorToken)):
                raise ValueError('YAML aliases and anchors are forbidden')
            if isinstance(token,(yaml.tokens.BlockMappingStartToken,yaml.tokens.BlockSequenceStartToken,
                                 yaml.tokens.FlowMappingStartToken,yaml.tokens.FlowSequenceStartToken)):depth+=1
            if isinstance(token,(yaml.tokens.BlockEndToken,yaml.tokens.FlowMappingEndToken,yaml.tokens.FlowSequenceEndToken)):depth-=1
            if depth>16 or tokens>20000:raise ValueError('configuration depth/token bound exceeded')
        # Duplicate keys must not silently override checked paths or identities.
        node=yaml.compose(payload,Loader=_Loader)
        def duplicates(n):
            if isinstance(n,yaml.MappingNode):
                keys=[]
                for key,value in n.value:
                    if not isinstance(key,yaml.ScalarNode) or key.value in keys:raise ValueError('duplicate or complex configuration key')
                    keys.append(key.value);duplicates(value)
            elif isinstance(n,yaml.SequenceNode):
                for child in n.value:duplicates(child)
        duplicates(node)
        value=yaml.load(payload,Loader=_Loader)
    except (OSError,UnicodeError,yaml.YAMLError) as exc:
        raise ValueError(f'cannot read configuration {path}: {exc}') from exc
    _mapping(value,'configuration',TOP,{'schema_version','mode','profile','episode','floor'})
    if type(value['schema_version']) is not int or value['schema_version']!=1:raise ValueError('schema_version must be integer 1')
    if value['mode'] not in {'live','fixture_cpu_no_models'}:raise ValueError('mode must be live or fixture_cpu_no_models')
    sampling=value.get('keyframe_sampling','novelty')
    if type(sampling) is not str or sampling not in {'novelty','capacity_deferred'}:raise ValueError('invalid keyframe_sampling')
    if 'keyframe_novelty' in value:
        # 3DSG keyframe novelty thresholds (scene-graph input density).
        novelty=value['keyframe_novelty']
        _mapping(novelty,'keyframe_novelty',{'min_translation_m','min_yaw_deg'},{'min_translation_m','min_yaw_deg'})
        for key,(low,high) in dict(min_translation_m=(.05,2.),min_yaw_deg=(5.,90.)).items():
            item=novelty[key]
            if type(item) not in (int,float) or not math.isfinite(item) or not low<=item<=high:
                raise ValueError(f'keyframe_novelty.{key} must be in [{low}, {high}]')
    if sampling=='capacity_deferred' and value['mode']!='live':raise ValueError('capacity_deferred sampling requires live mode')
    if value['profile'] not in {'baseline','geometry-only','appearance','rebuild-rgbd-m1-m5-v1'}:raise ValueError('unsupported profile')
    _mapping(value['episode'],'episode',{'id','primary_sensor_id','floor_id'},{'id','primary_sensor_id','floor_id'})
    for key,item in value['episode'].items():
        if not isinstance(item,str) or not item.strip():raise ValueError('episode.'+key+' must be explicit nonempty text')
    _mapping(value['floor'],'floor',{'z_m','datum_source','calibration_sha256'},{'z_m','datum_source','calibration_sha256'})
    floor=value['floor']
    if type(floor['z_m']) not in (int,float) or not math.isfinite(floor['z_m']):raise ValueError('floor.z_m requires explicit finite scene calibration')
    if not isinstance(floor['datum_source'],str) or not floor['datum_source'].strip():raise ValueError('floor.datum_source is required')
    if not isinstance(floor['calibration_sha256'],str) or not SHA.fullmatch(floor['calibration_sha256']):raise ValueError('floor.calibration_sha256 is required')
    if 'fixture' in value:_mapping(value['fixture'],'fixture',{'detections'},{'detections'})
    if 'scene_graph' in value:
        scene_graph=_mapping(value['scene_graph'],'scene_graph',{'backend','hydra'})
        backend=scene_graph.get('backend','legacy')
        if type(backend) is not str or backend not in {'legacy','hydra'}:
            raise ValueError('scene_graph.backend must be legacy or hydra')
        if backend=='hydra':
            if value['mode']!='live':raise ValueError('Hydra scene_graph backend requires live mode')
            workers=value.get('workers',{})
            region=workers.get('region',{})
            if 'room_pipeline' in workers or region.get('backend','dude')=='rebuild_m4_m5':
                raise ValueError('Hydra backend cannot run with legacy Rebuild/M5 room workers')
            if 'region' in workers:
                raise ValueError('Hydra backend cannot run with the legacy region worker')
            if value.get('appearance_mode','off')!='off' or 'association' in value:
                raise ValueError('Hydra backend cannot run with legacy identity/verification workers')
            if 'hydra' not in scene_graph or 'hydra' not in workers:
                raise ValueError('Hydra backend requires scene_graph.hydra and workers.hydra configuration')
            h=_mapping(scene_graph['hydra'],'scene_graph.hydra',
                {'config_root','dataset_sha256','labelspace_sha256','detector_profile_id','calibration'},
                {'config_root','dataset_sha256','labelspace_sha256','detector_profile_id','calibration'})
            for key in ('dataset_sha256','labelspace_sha256'):
                if type(h[key]) is not str or not SHA.fullmatch(h[key]):raise ValueError('scene_graph.hydra.'+key+' must be a SHA-256')
            if not isinstance(h['config_root'],str) or not h['config_root'].strip():raise ValueError('scene_graph.hydra.config_root is required')
            config_root=Path(h['config_root']).expanduser()
            if not config_root.is_absolute():config_root=path.parent/config_root
            dataset=config_root/'datasets'/'neusymnav.yaml';labelspace=config_root/'label_spaces'/'neusymnav_label_space.yaml'
            if not dataset.is_file() or not labelspace.is_file():raise ValueError('scene_graph.hydra.config_root lacks the pinned NeuSymNav Hydra configs')
            if file_sha256(dataset)!=h['dataset_sha256'] or file_sha256(labelspace)!=h['labelspace_sha256']:
                raise ValueError('scene_graph.hydra config SHA-256 mismatch')
            h['config_root']=str(config_root.resolve())
            if not isinstance(h['detector_profile_id'],str) or not h['detector_profile_id'].strip():
                raise ValueError('scene_graph.hydra.detector_profile_id is required')
            calibration=_mapping(h['calibration'],'scene_graph.hydra.calibration',
                {'calibration_id','version','sensor_id','camera_name','K','body_T_camera','pose_version',
                 'coordinate_convention','camera_convention','depth_convention','provenance'},
                {'calibration_id','version','sensor_id','camera_name','K','body_T_camera','pose_version',
                 'coordinate_convention','camera_convention','depth_convention','provenance'})
            if calibration['sensor_id']!=value['episode']['primary_sensor_id']:
                raise ValueError('Hydra calibration sensor_id must match episode.primary_sensor_id')
            for key,shape in (('K',(3,3)),('body_T_camera',(4,4))):
                matrix=calibration[key]
                if not isinstance(matrix,(list,tuple)) or len(matrix)!=shape[0] or any(
                    not isinstance(row,(list,tuple)) or len(row)!=shape[1] or any(
                        type(item) not in (int,float) or not math.isfinite(item) for item in row)
                    for row in matrix):raise ValueError('Hydra calibration '+key+' must be a finite '+str(shape[0])+'x'+str(shape[1])+' matrix')
    if 'workers' in value:
        _mapping(value['workers'],'workers',{'sensor','detector','region','appearance','ui','raycast','room_pipeline','hydra'})
        for name,worker in value['workers'].items():
            if name=='region':
                _mapping(worker,'workers.'+name,{'python','script','executable','timeout_s','startup_timeout_s','backend','source_root'})
                backend=worker.get('backend','dude')
                if not isinstance(backend,str) or backend not in {'dude','rebuild_m4_m5'}:raise ValueError('workers.region.backend must be dude or rebuild_m4_m5')
                if backend=='rebuild_m4_m5':
                    source_root=worker.get('source_root')
                    if not isinstance(source_root,str) or not source_root.strip():raise ValueError('workers.region.source_root is required for rebuild_m4_m5')
                    resolved=Path(source_root).expanduser()
                    if not resolved.is_absolute():resolved=path.parent/resolved
                    if not (resolved/'src'/'standalone_sg'/'__init__.py').is_file():raise ValueError('workers.region.source_root must contain src/standalone_sg')
                    worker['source_root']=str(resolved.resolve())
                elif 'source_root' in worker:
                    raise ValueError('workers.region.source_root is only valid for rebuild_m4_m5')
            elif name=='room_pipeline':
                _mapping(worker,'workers.room_pipeline',
                    {'source_root','m23_binary','m4_binary','ipc_timeout_s','m23_timeout_s','m4_timeout_s',
                     'resolution_m','backprojection_stride','min_depth_m','max_depth_m','max_range_m',
                     'fps_cap_hz','queue_policy'},
                    {'source_root','m23_binary','m4_binary'})
                source_root=worker['source_root']
                if not isinstance(source_root,str) or not source_root.strip():
                    raise ValueError('workers.room_pipeline.source_root is required')
                resolved=Path(source_root).expanduser()
                if not resolved.is_absolute():resolved=path.parent/resolved
                if not (resolved/'src'/'standalone_sg'/'__init__.py').is_file():
                    raise ValueError('workers.room_pipeline.source_root must contain src/standalone_sg')
                worker['source_root']=str(resolved.resolve())
                for key in ('ipc_timeout_s','m23_timeout_s','m4_timeout_s'):
                    if key in worker:_positive(worker[key],'workers.room_pipeline.'+key,maximum=120)
                for key in ('resolution_m','min_depth_m','max_depth_m','max_range_m'):
                    if key in worker:_positive(worker[key],'workers.room_pipeline.'+key)
                if 'backprojection_stride' in worker:
                    _positive(worker['backprojection_stride'],'workers.room_pipeline.backprojection_stride',integer=True)
                if worker.get('max_depth_m',10.)<=worker.get('min_depth_m',.1):
                    raise ValueError('workers.room_pipeline.max_depth_m must exceed min_depth_m')
                if 'fps_cap_hz' in worker:_positive(worker['fps_cap_hz'],'workers.room_pipeline.fps_cap_hz',maximum=20.)
                queue_policy=worker.get('queue_policy','bounded_fifo')
                if type(queue_policy) is not str or queue_policy not in {'bounded_fifo','latest_wins'}:
                    raise ValueError('workers.room_pipeline.queue_policy must be bounded_fifo or latest_wins')
                if queue_policy=='latest_wins' and 'fps_cap_hz' not in worker:
                    raise ValueError('workers.room_pipeline.queue_policy=latest_wins requires explicit fps_cap_hz')
            else:
                _mapping(worker,'workers.'+name,{'python','script','executable','setup_script','timeout_s','startup_timeout_s','fps_limit_hz','artifact_quota_bytes'})
    if 'navigation' in value:_mapping(value['navigation'],'navigation',{'robot','mapper','controller','tour'})
    if 'long_demo' in value:
        long=value['long_demo']
        _mapping(long,'long_demo',{'max_duration_s','payload_format'},{'max_duration_s','payload_format'})
        _positive(long['max_duration_s'],'long_demo.max_duration_s',maximum=600)
        if value['mode']!='live' or long['payload_format']!='npz_v2':
            raise ValueError('long_demo requires live mode and npz_v2 lossless recording')
    if 'runtime' in value:
        runtime=value['runtime']
        _mapping(runtime,'runtime',{'primary_hz','navigation_hz','control_sample_cap','defer_capture_gc','world_navigation_hz','process_priority','gil_switch_interval_ms'},
                 {'primary_hz','navigation_hz','control_sample_cap'})
        if 'defer_capture_gc' in runtime:
            if type(runtime['defer_capture_gc']) is not bool:
                raise ValueError('runtime.defer_capture_gc must be boolean')
            if runtime['defer_capture_gc'] and value.get('scene_graph',{}).get('backend')!='hydra':
                raise ValueError('runtime.defer_capture_gc currently requires Hydra backend')
        _positive(runtime['primary_hz'],'runtime.primary_hz',maximum=20)
        # Capture request ceiling, not a throughput claim. Fresh navigation
        # and source-bound actuation still run serially without timer catchup.
        _positive(runtime['navigation_hz'],'runtime.navigation_hz',maximum=30)
        if 'world_navigation_hz' in runtime:
            _positive(runtime['world_navigation_hz'],'runtime.world_navigation_hz',maximum=10)
        if 'gil_switch_interval_ms' in runtime:
            item=runtime['gil_switch_interval_ms']
            if type(item) not in (int,float) or not math.isfinite(item) or not .5<=item<=5:
                raise ValueError('runtime.gil_switch_interval_ms must be in [0.5, 5]')
        if 'process_priority' in runtime:
            from .priority import validate_process_priority
            validate_process_priority(runtime['process_priority'])
        _positive(runtime['control_sample_cap'],'runtime.control_sample_cap',integer=True,maximum=20000)
    if 'budgets' in value:
        _mapping(value['budgets'],'budgets',{'byte_cap','raw_cap','total_cap','shutdown_timeout_s','archive_cap'})
        for name,amount in value['budgets'].items():
            if type(amount) not in (int,float) or amount<=0 or amount>(32 if 'long_demo' in value else 8)*1024**3 or not math.isfinite(amount):raise ValueError('budget '+name+' must be positive finite and bounded')
            if name!='shutdown_timeout_s' and type(amount) is not int:raise ValueError('byte budgets must be integers')
        if 'archive_cap' in value['budgets'] and not 4096<=value['budgets']['archive_cap']<=value['budgets'].get('raw_cap',2*1024**3)//2:raise ValueError('archive_cap must fit half aggregate raw budget and certificate reserve')
    if 'ui' in value:_mapping(value['ui'],'ui',{'enabled','smoke_exit_ms','publish_hz','room_label_debug'})
    if 'replay' in value:_mapping(value['replay'],'replay',{'allow_incomplete'})
    if value.get('appearance_mode','off') not in {'off','openclip','openai_clip'}:raise ValueError('appearance_mode must be off, openclip or openai_clip')
    if 'association' in value:
        from ..objects.association_recipe import AssociationRecipe
        if not isinstance(value['association'],dict):raise ValueError('association must be a mapping with explicit mode')
        AssociationRecipe.from_mapping(value['association'])
    if value['mode']=='fixture_cpu_no_models' and value.get('appearance_mode','off')!='off':raise ValueError('fixture replay does not enable model inference')
    if value['profile']=='appearance' and value.get('appearance_mode') not in {'openclip','openai_clip'}:raise ValueError('appearance profile requires appearance_mode=openclip or openai_clip')
    if 'measurements' in value:
        m=value['measurements']
        _mapping(m,'measurements',{'enabled','sample_cap','capture_cap','trace_byte_cap','rss_cap_bytes','gpu_cap_bytes','gpu_executable','gpu_uuid','rss_sample_timeout_s','rss_retry_wait_s','proof_record_cap'})
        if 'rss_sample_timeout_s' in m:_positive(m['rss_sample_timeout_s'],'measurements.rss_sample_timeout_s',maximum=1.)
        if 'rss_retry_wait_s' in m:
            wait=m['rss_retry_wait_s']
            if type(wait) not in (int,float) or not 0<=wait<=.25 or not math.isfinite(wait):raise ValueError('measurements.rss_retry_wait_s must be finite in [0,.25]')
        if type(m.get('enabled',False)) is not bool:raise ValueError('measurements.enabled must be bool')
        for key,cap in [('sample_cap',65536),('capture_cap',65536),('trace_byte_cap',(512 if 'long_demo' in value else 64)*1024**2),('rss_cap_bytes',10*1024**3),('gpu_cap_bytes',5*1024**3)]:
            if key in m:_positive(m[key],'measurements.'+key,integer=True,maximum=cap)
        if 'proof_record_cap' in m:_positive(m['proof_record_cap'],'measurements.proof_record_cap',integer=True,maximum=20000 if 'long_demo' in value else 4096)
        if ('gpu_executable' in m)!=('gpu_uuid' in m):raise ValueError('GPU executable and UUID must be paired')
        if 'gpu_executable' in m:
            _mapping(m['gpu_executable'],'measurements.gpu_executable',{'path','sha256'},{'path','sha256'})
            if type(m['gpu_uuid']) is not str or re.fullmatch(r'GPU-[A-Za-z0-9-]{1,100}',m['gpu_uuid']) is None:raise ValueError('invalid measurement GPU UUID')
        if m.get('enabled') and (value['mode']!='live' or 'seed' not in value.get('sensor_config',{})):raise ValueError('measurements require explicit seeded live configuration')
    _validate_nested(value)
    return Configuration(path,value)


class Configuration:
    def __init__(self,path,data):self.path=path;self.data=data;self.checked_assets={};self.runtime_probes={}

    def asset(self,spec,label,*,executable=False):
        _mapping(spec,label,{'path','sha256'},{'path','sha256'})
        if not isinstance(spec['path'],str) or not spec['path']:raise ValueError(label+'.path must declare an existing local file')
        if not isinstance(spec['sha256'],str) or not SHA.fullmatch(spec['sha256']):raise ValueError(label+'.sha256 must declare exact SHA-256')
        path=Path(spec['path']).expanduser()
        if not path.is_absolute():path=self.path.parent/path
        path=Path(os.path.abspath(path))
        if not path.is_file():raise ValueError(label+' is missing: '+str(path))
        if file_sha256(path)!=spec['sha256']:raise ValueError(label+' checksum mismatch: '+str(path))
        if executable and not os.access(path,os.X_OK):raise ValueError(label+' is not executable: '+str(path))
        self.checked_assets[label]=dict(path=str(path),sha256=spec['sha256'])
        return path

    def worker(self,name):
        result=self.data.get('workers',{}).get(name)
        if result is None:raise ValueError('workers.'+name+' requires explicit local executable/interpreter and script with SHA-256')
        if name=='region':return self.asset(result.get('executable'),'workers.region.executable',executable=True)
        script=self.asset(result.get('script'),'workers.'+name+'.script')
        if not script.resolve().is_relative_to(Path(__file__).resolve().parents[1]):raise ValueError('worker script must use bundled package source: '+str(script))
        return (self.asset(result.get('python'),'workers.'+name+'.python',executable=True),script)


def _positive(value,label,*,integer=False,maximum=None):
    if type(value) not in ((int,) if integer else (int,float)) or value<=0 or maximum is not None and value>maximum or not math.isfinite(value):
        raise ValueError(label+' must be positive finite'+(' integer' if integer else ''))


def _validate_nested(value):
    extended='long_demo' in value
    for key,cap in [('byte_cap',32*1024**2),('raw_cap',(24 if extended else 2)*1024**3),('total_cap',(32 if extended else 8)*1024**3)]:
        if value.get('budgets',{}).get(key,0)>cap:raise ValueError(key+' exceeds locked runtime policy cap')
    if value.get('budgets',{}).get('raw_cap',2*1024**3)>value.get('budgets',{}).get('total_cap',8*1024**3):raise ValueError('raw_cap exceeds total_cap')
    if ('room_pipeline' in value.get('workers',{}) and
            value.get('budgets',{}).get('total_cap',8*1024**3)<2*1024**3+128*1024**2):
        raise ValueError('room_pipeline requires 2 GiB plus 128 MiB reserved run space')
    for name,worker in value.get('workers',{}).items():
        for key in ('timeout_s','startup_timeout_s'):
            if key in worker:_positive(worker[key],'workers.'+name+'.'+key,maximum=60)
        if name=='hydra':
            if 'fps_limit_hz' in worker:_positive(worker['fps_limit_hz'],'workers.hydra.fps_limit_hz',maximum=60)
            if 'artifact_quota_bytes' in worker:_positive(worker['artifact_quota_bytes'],'workers.hydra.artifact_quota_bytes',integer=True,maximum=8*1024**3)
        for key in ('python','script','executable','setup_script'):
            if key in worker and worker[key] is not None:_mapping(worker[key],'workers.'+name+'.'+key,{'path','sha256'},{'path','sha256'})
    nav=value.get('navigation',{})
    if 'robot' in nav:
        robot=nav['robot'];_mapping(robot,'navigation.robot',{'geometry_id','radius_m','height_m','margin_m','near_ground_tolerance_m'},{'geometry_id','radius_m','height_m'})
        from ..mapping.occupancy import RobotGeometry
        try:RobotGeometry(**robot)
        except (ValueError,TypeError) as exc:raise ValueError('invalid navigation.robot: '+str(exc)) from exc
    if 'mapper' in nav:
        mapper=nav['mapper'];_mapping(mapper,'navigation.mapper',{'resolution_m','origin_xy','tile_size_cells','height_bin_m','min_depth_m','max_depth_m','sampling_stride','free_ray_stride','snapshot_radius_m','local_retention_s','max_snapshot_cells','max_active_tiles','raycast_workers','raycast_backend','local_sampling_stride','overview_refresh_s'})
        for key,item in mapper.items():
            if key=='raycast_backend':
                if item not in ('cpu','triton_cuda'):raise ValueError('mapper.raycast_backend must be cpu or triton_cuda')
                if item=='triton_cuda':
                    if value['mode']!='live':raise ValueError('GPU raycast_backend requires live mode')
                    if 'raycast' not in value.get('workers',{}):raise ValueError('GPU raycast_backend requires workers.raycast')
            elif key=='local_retention_s':
                _positive(item,'mapper.local_retention_s',maximum=300)
            elif key=='overview_refresh_s':
                # Display/room-history overview refresh period (world thread).
                if type(item) not in (int,float) or not math.isfinite(item) or not .5<=item<=10:
                    raise ValueError('mapper.overview_refresh_s must be in [0.5, 10]')
            elif key=='origin_xy':
                if not isinstance(item,(list,tuple)) or len(item)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in item):raise ValueError('mapper.origin_xy requires two finite coordinates')
            else:_positive(item,'mapper.'+key,integer=key in {'tile_size_cells','sampling_stride','free_ray_stride','max_snapshot_cells','max_active_tiles','raycast_workers','local_sampling_stride'},maximum=4 if key in {'free_ray_stride','raycast_workers','local_sampling_stride'} else None)
        if mapper.get('free_ray_stride',1)>1 and mapper.get('raycast_backend','cpu')!='cpu':
            raise ValueError('free_ray_stride > 1 requires the CPU raycast backend')
    if 'controller' in nav:
        controller=nav['controller'];_mapping(controller,'navigation.controller',{'nominal_speed_mps','discrete_heading_control','gain_aware','allow_fresh_map_lag','acceleration_mps2','hybrid_pulse_control','local_depth_control','world_goal_max_age_ms','world_intent_ttl_ms','pulse_ms','rotation_pulse_ms','start_unknown_tolerance'})
        if 'world_goal_max_age_ms' in controller:
            item=controller['world_goal_max_age_ms']
            if type(item) is not int or not 300<=item<=2000:
                raise ValueError('navigation.controller.world_goal_max_age_ms must be an int in [300, 2000]')
        for key,(low,high) in dict(pulse_ms=(100,300),rotation_pulse_ms=(100,500)).items():
            if key in controller and (type(controller[key]) is not int or not low<=controller[key]<=high):
                raise ValueError(f'navigation.controller.{key} must be an int in [{low}, {high}]')
        if 'start_unknown_tolerance' in controller:
            item=controller['start_unknown_tolerance']
            if type(item) not in (int,float) or not math.isfinite(item) or not 0<=item<=.3:
                raise ValueError('navigation.controller.start_unknown_tolerance must be in [0, 0.3]')
        if controller.get('rotation_pulse_ms',500)<controller.get('pulse_ms',100):
            raise ValueError('navigation.controller.rotation_pulse_ms must be >= pulse_ms')
        if 'world_intent_ttl_ms' in controller:
            item=controller['world_intent_ttl_ms']
            if type(item) is not int or not 2000<=item<=5000:
                raise ValueError('navigation.controller.world_intent_ttl_ms must be an int in [2000, 5000]')
        if 'nominal_speed_mps' in controller:
            _positive(controller['nominal_speed_mps'],'navigation.controller.nominal_speed_mps',maximum=.2)
        if 'acceleration_mps2' in controller:
            _positive(controller['acceleration_mps2'],'navigation.controller.acceleration_mps2',maximum=1.)
        for key in ('discrete_heading_control','gain_aware','allow_fresh_map_lag','hybrid_pulse_control','local_depth_control'):
            if key in controller and type(controller[key]) is not bool:
                raise ValueError('navigation.controller.'+key+' must be boolean')
        if controller.get('discrete_heading_control') and controller.get('hybrid_pulse_control'):
            raise ValueError('navigation steering modes are mutually exclusive')
    if ('world_navigation_hz' in value.get('runtime',{})
            and not nav.get('controller',{}).get('local_depth_control',False)):
        raise ValueError('runtime.world_navigation_hz requires local_depth_control')
    if 'tour' in nav:
        tour=nav['tour'];_mapping(tour,'navigation.tour',{'path','sha256','reach_m','lookahead_m','stuck_timeout_s','skip_m','relax_m','approach_m','stall_timeout_s','scan_degrees','scan_step_degrees','scan_min_separation_m','scan_step_timeout_s'},{'path','sha256'})
        if not nav.get('controller',{}).get('local_depth_control',False):
            raise ValueError('navigation.tour requires local_depth_control')
        if type(tour['path']) is not str or not tour['path'] or type(tour['sha256']) is not str or len(tour['sha256'])!=64:
            raise ValueError('navigation.tour requires path and sha256')
        for key,(low,high) in dict(reach_m=(.1,2.),lookahead_m=(.3,5.),stuck_timeout_s=(1.,120.),skip_m=(.2,5.),relax_m=(0.,1.5),approach_m=(0.,10.),stall_timeout_s=(1.,600.),scan_degrees=(0.,360.),scan_step_degrees=(30.,180.),scan_min_separation_m=(0.,20.),scan_step_timeout_s=(1.,60.)).items():
            if key in tour and (type(tour[key]) not in (int,float) or not math.isfinite(tour[key]) or not low<=tour[key]<=high):
                raise ValueError(f'navigation.tour.{key} must be in [{low}, {high}]')
    if not nav.get('controller',{}).get('local_depth_control',False) and (
            any(key in nav.get('controller',{}) for key in ('world_goal_max_age_ms','world_intent_ttl_ms','pulse_ms','rotation_pulse_ms','start_unknown_tolerance'))
            or 'local_sampling_stride' in nav.get('mapper',{})):
        # Goal-selection age and intent TTL are only safe when every command is
        # re-planned and guarded on the current local depth frame.
        raise ValueError('world_goal_max_age_ms, world_intent_ttl_ms, pulse_ms, rotation_pulse_ms and local_sampling_stride require local_depth_control')
    if 'ui' in value:
        ui=value['ui']
        if type(ui.get('enabled',False)) is not bool:raise ValueError('ui.enabled must be boolean')
        if 'room_label_debug' in ui:
            from ..rooms.debug_runtime import validate_debug_options
            validate_debug_options(ui['room_label_debug'])
            if not ui.get('enabled') or value.get('scene_graph',{}).get('backend')!='hydra':
                raise ValueError('room_label_debug requires enabled Hydra UI')
            entry=value.get('workers',{}).get('ui',{}).get('script',{}).get('path','')
            if Path(entry).resolve()!=Path(__file__).with_name('room_label_ui_entry.py').resolve():
                raise ValueError('room_label_debug requires its pinned UI worker entry')
        if 'publish_hz' in ui:_positive(ui['publish_hz'],'ui.publish_hz',maximum=20)
        if 'smoke_exit_ms' in ui and ui['smoke_exit_ms'] is not None:_positive(ui['smoke_exit_ms'],'ui.smoke_exit_ms',integer=True,maximum=300000)
    if 'replay' in value and type(value['replay'].get('allow_incomplete',False)) is not bool:raise ValueError('replay.allow_incomplete must be boolean')
    if 'sensor_config' in value:
        sensor=value['sensor_config'];_mapping(sensor,'sensor_config',{'scene','scene_dataset','initial_position','initial_rotation_xyzw','gpu_device_id','floor_datum','primary','navigation','seed','motion_adapter'})
        adapter=sensor.get('motion_adapter','strict_3d')
        if type(adapter) is not str or adapter not in {'strict_3d','planar_fixed_y_v1'}:raise ValueError('unsupported sensor_config.motion_adapter')
        if 'seed' in sensor and (type(sensor['seed']) is not int or not 0<=sensor['seed']<=2**32-1):raise ValueError('sensor_config.seed must be a uint32 integer')
        for lane in ('primary','navigation'):
            if lane not in sensor:continue
            _mapping(sensor[lane],'sensor_config.'+lane,{'sensor_id','rgb_uuid','depth_uuid','resolution_hw','position_xyz','orientation_xyz_rad','hfov_deg','depth_min_m','depth_max_m'})
        if 'floor_datum' in sensor:_mapping(sensor['floor_datum'],'sensor_config.floor_datum',{'source_convention','source_floor_y_m','canonical_floor_z_m','provenance'})
    if 'detector' in value:
        from ..perception.detector_client import BASE_RECIPE_KEYS, RECIPE_CONFIG_ASSETS
        _mapping(value['detector'],'detector',
            (BASE_RECIPE_KEYS-{'checkpoint_path','checkpoint_sha256','encoder_path','encoder_sha256',
                               'taxonomy_path','taxonomy_sha256'})
            | {'backend','fallback_policy'} | RECIPE_CONFIG_ASSETS)
        backend=value['detector'].get('backend','torch')
        if type(backend) is not str or backend not in {'torch','openvino_gpu'}:
            raise ValueError('detector.backend must be torch or openvino_gpu')
        fallback=value['detector'].get('fallback_policy','torch_cpu' if backend=='openvino_gpu' else 'none')
        if type(fallback) is not str or (backend=='torch' and fallback!='none') or (backend=='openvino_gpu' and fallback not in {'torch_cpu','fail'}):
            raise ValueError('detector.fallback_policy is incompatible with detector.backend')
        if backend=='openvino_gpu' and value['detector'].get('device')!='intel:gpu':
            raise ValueError('detector.backend=openvino_gpu requires detector.device=intel:gpu')
        if backend=='torch' and any(name in value['detector'] for name in ('openvino_model','openvino_bin','openvino_metadata')):
            raise ValueError('OpenVINO IR assets require detector.backend=openvino_gpu')
    if 'worker' in value:
        worker=value['worker'];_mapping(worker,'appearance worker',{'python_path','checkpoint_path','checkpoint_sha256','checkpoint_format','model_name','preprocessing_id','crop_recipe_id','feature_dimension','device','pretrained','state_dict_strict','timeout_s','startup_timeout_s','max_request_bytes','max_response_bytes'})
        backend=value.get('appearance_mode','off')
        new_backend=backend=='openai_clip'
        expected={'checkpoint_format':'openai_jit' if new_backend else 'safetensors','model_name':'ViT-B-32',
            'preprocessing_id':('openai-clip-vit-b-32-eval-224-maskbboxpad20-v1' if new_backend else 'openclip-vit-b-32-openai-eval-224-maskbboxpad20-v1'),
            'crop_recipe_id':'mask-tight-xyxy+20px-clipped+PIL-float-edge-rounding-v1',
            'feature_dimension':512,'device':'cpu','pretrained':None,'state_dict_strict':True}
        for key,wanted in expected.items():
            if key in worker and (worker[key]!=wanted or type(worker[key]) is not type(wanted)):raise ValueError('unsupported appearance recipe '+key)
        for key in ('timeout_s','startup_timeout_s'):
            if key in worker:_positive(worker[key],'appearance '+key,maximum=60)
        for key,cap in [('max_request_bytes',32*1024**2),('max_response_bytes',2*1024**2)]:
            if key in worker:_positive(worker[key],'appearance '+key,integer=True,maximum=cap)
