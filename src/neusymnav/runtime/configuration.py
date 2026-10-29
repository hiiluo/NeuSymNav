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
TOP={'schema_version','mode','profile','episode','floor','workers','sensor_config','detector',
     'fixture','appearance_mode','worker','provenance','navigation','budgets','ui','replay','measurements','keyframe_sampling','runtime','long_demo'}


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
    if sampling=='capacity_deferred' and value['mode']!='live':raise ValueError('capacity_deferred sampling requires live mode')
    if value['profile'] not in {'baseline','geometry-only','appearance'}:raise ValueError('unsupported profile')
    _mapping(value['episode'],'episode',{'id','primary_sensor_id','floor_id'},{'id','primary_sensor_id','floor_id'})
    for key,item in value['episode'].items():
        if not isinstance(item,str) or not item.strip():raise ValueError('episode.'+key+' must be explicit nonempty text')
    _mapping(value['floor'],'floor',{'z_m','datum_source','calibration_sha256'},{'z_m','datum_source','calibration_sha256'})
    floor=value['floor']
    if type(floor['z_m']) not in (int,float) or not math.isfinite(floor['z_m']):raise ValueError('floor.z_m requires explicit finite scene calibration')
    if not isinstance(floor['datum_source'],str) or not floor['datum_source'].strip():raise ValueError('floor.datum_source is required')
    if not isinstance(floor['calibration_sha256'],str) or not SHA.fullmatch(floor['calibration_sha256']):raise ValueError('floor.calibration_sha256 is required')
    if 'fixture' in value:_mapping(value['fixture'],'fixture',{'detections'},{'detections'})
    if 'workers' in value:
        _mapping(value['workers'],'workers',{'sensor','detector','region','appearance','ui'})
        for name,worker in value['workers'].items():
            _mapping(worker,'workers.'+name,{'python','script','executable','timeout_s','startup_timeout_s'})
    if 'navigation' in value:_mapping(value['navigation'],'navigation',{'robot','mapper'})
    if 'long_demo' in value:
        long=value['long_demo']
        _mapping(long,'long_demo',{'max_duration_s','payload_format'},{'max_duration_s','payload_format'})
        _positive(long['max_duration_s'],'long_demo.max_duration_s',maximum=600)
        if value['mode']!='live' or long['payload_format']!='npz_v2':
            raise ValueError('long_demo requires live mode and npz_v2 lossless recording')
    if 'runtime' in value:
        runtime=value['runtime']
        _mapping(runtime,'runtime',{'primary_hz','navigation_hz','control_sample_cap'},
                 {'primary_hz','navigation_hz','control_sample_cap'})
        for key in ('primary_hz','navigation_hz'):_positive(runtime[key],'runtime.'+key,maximum=20)
        _positive(runtime['control_sample_cap'],'runtime.control_sample_cap',integer=True,maximum=20000)
    if 'budgets' in value:
        _mapping(value['budgets'],'budgets',{'byte_cap','raw_cap','total_cap','shutdown_timeout_s','archive_cap'})
        for name,amount in value['budgets'].items():
            if type(amount) not in (int,float) or amount<=0 or amount>(32 if 'long_demo' in value else 8)*1024**3 or not math.isfinite(amount):raise ValueError('budget '+name+' must be positive finite and bounded')
            if name!='shutdown_timeout_s' and type(amount) is not int:raise ValueError('byte budgets must be integers')
        if 'archive_cap' in value['budgets'] and not 4096<=value['budgets']['archive_cap']<=value['budgets'].get('raw_cap',2*1024**3)//2:raise ValueError('archive_cap must fit half aggregate raw budget and certificate reserve')
    if 'ui' in value:_mapping(value['ui'],'ui',{'enabled','smoke_exit_ms','publish_hz'})
    if 'replay' in value:_mapping(value['replay'],'replay',{'allow_incomplete'})
    if value.get('appearance_mode','off') not in {'off','openclip'}:raise ValueError('appearance_mode must be off or openclip')
    if value['mode']=='fixture_cpu_no_models' and value.get('appearance_mode','off')!='off':raise ValueError('fixture replay does not enable model inference')
    if value['profile']=='appearance' and value.get('appearance_mode')!='openclip':raise ValueError('appearance profile requires appearance_mode=openclip')
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
    for name,worker in value.get('workers',{}).items():
        for key in ('timeout_s','startup_timeout_s'):
            if key in worker:_positive(worker[key],'workers.'+name+'.'+key,maximum=60)
        for key in ('python','script','executable'):
            if key in worker and worker[key] is not None:_mapping(worker[key],'workers.'+name+'.'+key,{'path','sha256'},{'path','sha256'})
    nav=value.get('navigation',{})
    if 'robot' in nav:
        robot=nav['robot'];_mapping(robot,'navigation.robot',{'geometry_id','radius_m','height_m','margin_m','near_ground_tolerance_m'},{'geometry_id','radius_m','height_m'})
        from ..mapping.occupancy import RobotGeometry
        try:RobotGeometry(**robot)
        except (ValueError,TypeError) as exc:raise ValueError('invalid navigation.robot: '+str(exc)) from exc
    if 'mapper' in nav:
        mapper=nav['mapper'];_mapping(mapper,'navigation.mapper',{'resolution_m','origin_xy','tile_size_cells','height_bin_m','min_depth_m','max_depth_m','sampling_stride','snapshot_radius_m','max_snapshot_cells','max_active_tiles','raycast_workers'})
        for key,item in mapper.items():
            if key=='origin_xy':
                if not isinstance(item,(list,tuple)) or len(item)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in item):raise ValueError('mapper.origin_xy requires two finite coordinates')
            else:_positive(item,'mapper.'+key,integer=key in {'tile_size_cells','sampling_stride','max_snapshot_cells','max_active_tiles','raycast_workers'},maximum=4 if key=='raycast_workers' else None)
    if 'ui' in value:
        ui=value['ui']
        if type(ui.get('enabled',False)) is not bool:raise ValueError('ui.enabled must be boolean')
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
        from ..perception.detector_client import RECIPE_KEYS
        _mapping(value['detector'],'detector',(RECIPE_KEYS-{'checkpoint_path','checkpoint_sha256','encoder_path','encoder_sha256','taxonomy_path','taxonomy_sha256'})|{'checkpoint','encoder','taxonomy'})
    if 'worker' in value:
        worker=value['worker'];_mapping(worker,'appearance worker',{'python_path','checkpoint_path','checkpoint_sha256','checkpoint_format','model_name','preprocessing_id','crop_recipe_id','feature_dimension','device','pretrained','state_dict_strict','timeout_s','startup_timeout_s','max_request_bytes','max_response_bytes'})
        expected={'checkpoint_format':'safetensors','model_name':'ViT-B-32',
            'preprocessing_id':'openclip-vit-b-32-openai-eval-224-maskbboxpad20-v1',
            'crop_recipe_id':'mask-tight-xyxy+20px-clipped+PIL-float-edge-rounding-v1',
            'feature_dimension':512,'device':'cpu','pretrained':None,'state_dict_strict':True}
        for key,wanted in expected.items():
            if key in worker and (worker[key]!=wanted or type(worker[key]) is not type(wanted)):raise ValueError('unsupported appearance recipe '+key)
        for key in ('timeout_s','startup_timeout_s'):
            if key in worker:_positive(worker[key],'appearance '+key,maximum=60)
        for key,cap in [('max_request_bytes',32*1024**2),('max_response_bytes',2*1024**2)]:
            if key in worker:_positive(worker[key],'appearance '+key,integer=True,maximum=cap)
