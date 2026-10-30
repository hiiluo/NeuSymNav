"""Offline HM3D annotation trust boundary and separately launched native renderer.

This file can be run directly with PYTHONPATH=src and the Python 3.9 Habitat interpreter. Native
imports occur only in render_request(); runtime code must never import this file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np

# Declared before looking at any native alignment result. RGB is in byte units.
ALIGNMENT_POLICY = dict(min_depth_pixels=100, depth_atol_m=.001, depth_rtol=.0001,
                        min_depth_fraction=.999, rgb_mae_max=.5, rgb_p99_max=3.)
MIN_VISIBLE_PIXELS = 100


def canonical_optical_to_habitat(pose):
    pose=np.asarray(pose,dtype=np.float64)
    if (pose.shape!=(4,4) or not np.isfinite(pose).all() or
        not np.allclose(pose[3],[0,0,0,1],rtol=0,atol=1e-8) or
        not np.allclose(pose[:3,:3].T@pose[:3,:3],np.eye(3),rtol=0,atol=1e-8) or
        not np.isclose(np.linalg.det(pose[:3,:3]),1,rtol=0,atol=1e-8)):
        raise ValueError('camera pose must be finite rigid transform')
    # Inverse of source Y-up -> canonical Z-up on the LEFT; optical on RIGHT.
    world=np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]],float)
    return world.T@pose@np.diag([1.,-1.,-1.,1.])


def validate_calibration(K,width,height):
    if type(width) is not int or type(height) is not int or width<=0 or height<=0:
        raise ValueError('positive image dimensions required')
    k=np.asarray(K,dtype=float)
    if k.shape!=(3,3) or not np.isfinite(k).all() or k[0,0]<=0:
        raise ValueError('finite pinhole calibration required')
    expected=np.array([[k[0,0],0,(width-1)/2],[0,k[1,1],(height-1)/2],[0,0,1.]])
    if not np.allclose(k,expected,rtol=0,atol=1e-8) or abs(k[1,1]-k[0,0])>1e-4:
        raise ValueError('Habitat pinhole K mismatch')
    return math.degrees(2*math.atan(width/(2*k[0,0])))


def validate_alignment(rgb,depth,valid,rendered_rgb,rendered_depth):
    rgb,depth,valid=map(np.asarray,(rgb,depth,valid))
    other_rgb,other_depth=map(np.asarray,(rendered_rgb,rendered_depth))
    if (depth.ndim!=2 or rgb.shape!=depth.shape+(3,) or valid.shape!=depth.shape or
        valid.dtype!=np.bool_ or rgb.dtype!=np.uint8 or other_rgb.shape!=rgb.shape or
        other_rgb.dtype!=np.uint8 or other_depth.shape!=depth.shape):
        raise ValueError('RGB-D alignment shape or dtype mismatch')
    if int(valid.sum())<ALIGNMENT_POLICY['min_depth_pixels']:
        raise ValueError('insufficient valid depth support for GT trust')
    if not np.isfinite(depth[valid]).all() or np.any(depth[valid]<=0) or not np.isfinite(other_depth[valid]).all():
        raise ValueError('nonfinite or invalid alignment depth')
    difference=np.abs(other_depth[valid].astype(float)-depth[valid])
    fraction=float(np.mean(difference<=ALIGNMENT_POLICY['depth_atol_m']+ALIGNMENT_POLICY['depth_rtol']*np.abs(depth[valid])))
    rgb_difference=np.abs(other_rgb.astype(float)-rgb.astype(float))
    report=dict(valid_depth_pixels=int(valid.sum()),depth_mae_m=float(difference.mean()),
                depth_p99_m=float(np.quantile(difference,.99)),depth_within_tolerance_fraction=fraction,
                rgb_mae=float(rgb_difference.mean()),rgb_p99=float(np.quantile(rgb_difference,.99)))
    if (fraction<ALIGNMENT_POLICY['min_depth_fraction'] or
        report['rgb_mae']>ALIGNMENT_POLICY['rgb_mae_max'] or report['rgb_p99']>ALIGNMENT_POLICY['rgb_p99_max']):
        raise ValueError('rendered RGB-D alignment failed: '+json.dumps(report,sort_keys=True))
    return report


def parse_annotations(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        if stream.readline().strip()!='HM3D Semantic Annotations':
            raise ValueError('invalid HM3D annotation header')
        annotations={}
        for fields in csv.reader(stream):
            if len(fields)!=4: raise ValueError('invalid HM3D annotation row')
            try:
                instance_id=int(fields[0]);int(fields[1],16);int(fields[3])
            except ValueError as exc: raise ValueError('invalid HM3D annotation value') from exc
            if instance_id<1 or instance_id in annotations or len(fields[1])!=6 or not fields[2].strip():
                raise ValueError('invalid or duplicate HM3D semantic ID')
            annotations[instance_id]=fields[2].strip()
    if not annotations: raise ValueError('empty semantic annotation descriptor')
    return annotations


def extract_instances(instance_ids,annotations,taxonomy,*,min_visible_pixels=MIN_VISIBLE_PIXELS):
    ids=np.asarray(instance_ids)
    if ids.ndim!=2 or ids.dtype.kind not in 'iu': raise ValueError('semantic IDs must be integer raster')
    if type(min_visible_pixels) is not int or min_visible_pixels<1: raise ValueError('invalid minimum visibility')
    categories=set(taxonomy['categories']);aliases=taxonomy.get('aliases',{})
    objects=[];excluded=[]
    for raw_id,count in zip(*np.unique(ids,return_counts=True)):
        instance_id=int(raw_id);label=annotations.get(instance_id)
        normalized=None if label is None else label.strip().casefold()
        mapped=aliases.get(normalized,normalized)
        reason=('background' if instance_id in (-1,0,4294967295) else
                'unmapped_id' if label is None else
                'unsupported_taxonomy' if mapped not in categories else
                'small' if count<min_visible_pixels else None)
        if reason:
            excluded.append(dict(instance_id=instance_id,label=label,pixels=int(count),reason=reason));continue
        mask=ids==instance_id;y,x=np.nonzero(mask)
        objects.append(dict(id=f'hm3d:{instance_id}',label=mapped,
                            bbox=[int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1],mask=mask))
    return objects,excluded


def _sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def _checked_asset(descriptor):
    path=Path(descriptor['path'])
    if _sha(path)!=descriptor['sha256']: raise ValueError('asset SHA mismatch: '+str(path))
    return path


def _json(path,value):
    Path(path).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def verify_capture_binding(path,recording_sha256,config_sha256,kind):
    _checked_asset(dict(path=str(path),sha256=recording_sha256))
    recording=json.loads(Path(path).read_text())
    capture_config=recording.get('source_provenance',{}).get('config_sha256')
    if (kind=='recorded' or capture_config is not None) and capture_config!=config_sha256:
        raise ValueError('recording capture config SHA mismatch')
    return recording


def prepare_request(predictions_path,ledger_root,config_path,config_sha256,
                    semantic_path,annotation_path,out):
    """CPU-only conversion of SHA-verified source contracts to portable NPZ."""
    from neusymnav.contracts.observations import Observation
    from neusymnav.contracts.serialization import loads
    from neusymnav.evaluation.quality_dataset import read_document,_validate_document,FRAME_FIELDS
    import tempfile
    predictions_path=Path(predictions_path).resolve();root=Path(ledger_root).resolve()
    output=Path(out).absolute()
    if output.resolve().is_relative_to(root):raise ValueError('output inside source ledger')
    if output.exists():raise FileExistsError('request output already exists')
    config_path=Path(config_path).resolve()
    _checked_asset(dict(path=str(config_path),sha256=config_sha256))
    config=json.loads(config_path.read_text());predictions,_=read_document(predictions_path)
    _validate_document(predictions,True)
    export_path=predictions_path.with_name('export-manifest.json')
    exported=json.loads(export_path.read_text())
    if exported['files']['predictions.json']!=_sha(predictions_path):raise ValueError('exported predictions SHA mismatch')
    recording_path=Path(exported['recording_manifest'])
    recording=verify_capture_binding(recording_path,predictions['binding']['recording_sha256'],
        config_sha256,predictions['provenance']['kind'])
    if recording['episode_id']!=predictions['binding']['episode_id']:raise ValueError('recording episode mismatch')
    if not 1<=len(predictions['frames'])<=12:raise ValueError('bounded render requires 1..12 frames')
    if predictions['binding']['episode_id']!=config['episode']['id']:raise ValueError('episode mismatch')
    if (predictions['provenance']['kind']=='recorded' and
        predictions['binding']['scene_id'] not in Path(config['sensor_config']['scene']['path']).parts):
        raise ValueError('scene ID does not bind configured scene path')
    taxonomy_path=_checked_asset(config['detector']['taxonomy'])
    if _sha(taxonomy_path)!=predictions['binding']['taxonomy_sha256']:raise ValueError('taxonomy binding mismatch')
    scene=_checked_asset(config['sensor_config']['scene'])
    dataset=_checked_asset(config['sensor_config']['scene_dataset'])
    semantic_path=Path(semantic_path).resolve();annotation_path=Path(annotation_path).resolve()
    if (semantic_path!=scene.with_name(scene.name.replace('.basis.glb','.semantic.glb')) or
        annotation_path!=semantic_path.with_suffix('.txt')):
        raise ValueError('semantic assets do not match scene geometry')
    parse_annotations(annotation_path)
    descriptor=lambda path:dict(path=str(path),sha256=_sha(path))
    descriptors=dict(config=dict(path=str(config_path),sha256=config_sha256),predictions=descriptor(predictions_path),
        taxonomy=descriptor(taxonomy_path),scene=descriptor(scene),dataset=descriptor(dataset),
        semantic=descriptor(semantic_path),annotation=descriptor(annotation_path),recording=descriptor(recording_path),
        export_manifest=descriptor(export_path))
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='semantic-prepare-',dir=output.parent) as temporary:
        stage=Path(temporary);frames=[]
        for ordinal,frame in enumerate(predictions['frames']):
            source_path=root/'assets'/frame['source_sha256']
            source_raw=source_path.read_bytes()
            if hashlib.sha256(source_raw).hexdigest()!=frame['source_sha256']:raise ValueError('source asset SHA mismatch')
            observation=loads(source_raw)
            if not isinstance(observation,Observation):raise ValueError('source asset is not Observation')
            key=observation.key
            if (key.episode_id!=config['episode']['id'] or key.sensor_id!=config['episode']['primary_sensor_id'] or
                frame['frame_id']!=f'{key.sensor_id}:{key.frame_index}' or frame['frame_index']!=key.frame_index or
                frame['capture_monotonic_ns']!=observation.capture_monotonic_ns or
                frame['geometry_hash']!=observation.geometry_hash or
                observation.rgb.shape!=(frame['height'],frame['width'],3) or
                observation.coordinate_convention!='canonical_z_up_v1' or observation.depth_convention!='metric_axial_v1'):
                raise ValueError('source Observation/frame binding mismatch')
            hfov=validate_calibration(observation.K,frame['width'],frame['height'])
            configured_hfov=config['sensor_config']['primary'].get('hfov_deg',hfov)
            if abs(configured_hfov-hfov)>.0001:raise ValueError('source HFOV differs from frozen config')
            canonical_optical_to_habitat(observation.T_world_camera)
            relative=f'{ordinal:06d}-source.npz'
            np.savez_compressed(stage/relative,rgb=observation.rgb,depth=observation.depth_m,
                valid=observation.valid_depth,K=observation.K,pose=observation.T_world_camera)
            frames.append(dict(frame={name:frame[name] for name in FRAME_FIELDS},
                source=descriptor(source_path),arrays=dict(path=relative,sha256=_sha(stage/relative)),
                hfov_deg=configured_hfov))
        request=dict(schema_version=1,descriptors=descriptors,predictions=predictions,
            taxonomy=json.loads(taxonomy_path.read_text()),frames=frames,
            primary=config['sensor_config']['primary'],alignment_policy=ALIGNMENT_POLICY,
            min_visible_pixels=MIN_VISIBLE_PIXELS)
        _json(stage/'request.json',request)
        if output.exists():raise FileExistsError('request output appeared during preparation')
        stage.rename(output)
    return output/'request.json'


def verify_request(request_path):
    """Rebind every prepared byte to its original typed source before Habitat.

    Direct-file native invocation requires PYTHONPATH=src for the same source
    contract registry used by host preparation; there is no portable decoder.
    """
    from neusymnav.contracts.observations import Observation
    from neusymnav.contracts.serialization import loads
    from neusymnav.evaluation.quality_dataset import _validate_document,FRAME_FIELDS
    request_path=Path(request_path).resolve();request=json.loads(request_path.read_text())
    if (request.get('schema_version')!=1 or request.get('alignment_policy')!=ALIGNMENT_POLICY or
        request.get('min_visible_pixels')!=MIN_VISIBLE_PIXELS or not 1<=len(request['frames'])<=12):
        raise ValueError('unsupported semantic request policy/scope')
    descriptors=request['descriptors']
    for descriptor in descriptors.values():_checked_asset(descriptor)
    config=json.loads(Path(descriptors['config']['path']).read_text())
    _validate_document(request['predictions'],True)
    if json.loads(Path(descriptors['predictions']['path']).read_text())!=request['predictions']:
        raise ValueError('prediction snapshot mismatch')
    if json.loads(Path(descriptors['taxonomy']['path']).read_text())!=request['taxonomy']:
        raise ValueError('taxonomy snapshot mismatch')
    binding=request['predictions']['binding']
    if (request['primary']!=config['sensor_config']['primary'] or
        descriptors['scene']!=config['sensor_config']['scene'] or
        descriptors['dataset']!=config['sensor_config']['scene_dataset'] or
        descriptors['taxonomy']!=config['detector']['taxonomy']):
        raise ValueError('prepared camera/assets differ from frozen config')
    scene=Path(descriptors['scene']['path']).resolve()
    if (Path(descriptors['semantic']['path']).resolve()!=scene.with_name(scene.name.replace('.basis.glb','.semantic.glb')) or
        Path(descriptors['annotation']['path']).resolve()!=Path(descriptors['semantic']['path']).resolve().with_suffix('.txt')):
        raise ValueError('semantic assets do not match frozen scene')
    if binding['taxonomy_sha256']!=descriptors['taxonomy']['sha256']:
        raise ValueError('taxonomy binding mismatch')
    recording=verify_capture_binding(descriptors['recording']['path'],binding['recording_sha256'],
        descriptors['config']['sha256'],request['predictions']['provenance']['kind'])
    if recording['episode_id']!=binding['episode_id'] or binding['episode_id']!=config['episode']['id']:
        raise ValueError('recording/capture episode mismatch')
    if (request['predictions']['provenance']['kind']=='recorded' and binding['scene_id'] not in scene.parts):
        raise ValueError('scene ID does not bind frozen scene')
    prediction_frames=request['predictions']['frames']
    if len(request['frames'])!=len(prediction_frames):raise ValueError('prepared frame count mismatch')
    for item,predicted in zip(request['frames'],prediction_frames):
        frame=item['frame']
        if frame!={name:predicted[name] for name in FRAME_FIELDS}:
            raise ValueError('prepared source frame order/metadata mismatch')
        if item['source']['sha256']!=frame['source_sha256']:
            raise ValueError('source descriptor SHA differs from frame')
        source_path=_checked_asset(item['source'])
        observation=loads(source_path.read_bytes())
        if not isinstance(observation,Observation):raise ValueError('source asset is not typed Observation')
        key=observation.key
        if (key.episode_id!=config['episode']['id'] or key.sensor_id!=config['episode']['primary_sensor_id'] or
            frame['frame_id']!=f'{key.sensor_id}:{key.frame_index}' or frame['frame_index']!=key.frame_index or
            frame['capture_monotonic_ns']!=observation.capture_monotonic_ns or
            frame['geometry_hash']!=observation.geometry_hash or
            observation.rgb.shape!=(frame['height'],frame['width'],3) or
            observation.coordinate_convention!='canonical_z_up_v1' or observation.depth_convention!='metric_axial_v1'):
            raise ValueError('original source Observation/frame binding mismatch')
        hfov=validate_calibration(observation.K,frame['width'],frame['height'])
        configured_hfov=config['sensor_config']['primary'].get('hfov_deg',hfov)
        if abs(configured_hfov-hfov)>.0001 or item['hfov_deg']!=configured_hfov:
            raise ValueError('prepared HFOV differs from frozen source/config')
        canonical_optical_to_habitat(observation.T_world_camera)
        array_path=_checked_asset(dict(path=str(request_path.parent/item['arrays']['path']),sha256=item['arrays']['sha256']))
        originals=dict(rgb=observation.rgb,depth=observation.depth_m,valid=observation.valid_depth,
                       K=observation.K,pose=observation.T_world_camera)
        with np.load(array_path,allow_pickle=False) as archive:
            if len(archive.files)!=len(originals) or set(archive.files)!=set(originals):
                raise ValueError('prepared source arrays have invalid field set')
            for name,original in originals.items():
                prepared=archive[name]
                if (prepared.dtype!=original.dtype or prepared.shape!=original.shape or
                    prepared.tobytes(order='C')!=original.tobytes(order='C')):
                    raise ValueError('prepared source arrays differ from original Observation: '+name)
    return request


def materialize_frame(frame,source,rendered_rgb,rendered_depth,ids,annotations,taxonomy,mask_dir,ordinal):
    alignment=validate_alignment(source['rgb'],source['depth'],source['valid'],rendered_rgb,rendered_depth)
    ids=np.asarray(ids)
    if ids.shape!=source['depth'].shape:raise ValueError('semantic/source shape mismatch')
    objects,excluded=extract_instances(ids,annotations,taxonomy)
    serialized=[]
    for index,item in enumerate(objects):
        path=Path(mask_dir)/f'{ordinal:06d}-{index:04d}.npy'
        with path.open('xb') as stream:np.save(stream,item['mask'],allow_pickle=False)
        serialized.append(dict(id=item['id'],label=item['label'],bbox=item['bbox'],
                               mask=dict(path='masks/'+path.name,sha256=_sha(path))))
    return dict(frame,annotated=True,objects=serialized),dict(frame_id=frame['frame_id'],alignment=alignment,
        included_instances=len(objects),included_pixels=sum(int(item['mask'].sum()) for item in objects),
        excluded=excluded,total_pixels=int(ids.size))


def render_request(request_path,out):
    """One evaluator-owned Habitat simulator, closed even on alignment failure."""
    import tempfile
    request_path=Path(request_path).resolve();request=verify_request(request_path)
    output=Path(out).absolute()
    if output.exists():raise FileExistsError('render output already exists')
    first=request['frames'][0];height,width=first['frame']['height'],first['frame']['width']
    if any((item['frame']['height'],item['frame']['width'],item['hfov_deg'])!=(height,width,first['hfov_deg']) for item in request['frames']):
        raise ValueError('mixed camera calibrations unsupported')
    import habitat_sim
    from habitat_sim.utils.common import quat_from_coeffs
    from scipy.spatial.transform import Rotation
    backend=habitat_sim.SimulatorConfiguration()
    backend.scene_id=request['descriptors']['scene']['path']
    backend.scene_dataset_config_file=request['descriptors']['dataset']['path']
    backend.load_semantic_mesh=True;backend.enable_physics=False;backend.gpu_device_id=0
    specs=[]
    for name,kind in [('rgb',habitat_sim.SensorType.COLOR),('depth',habitat_sim.SensorType.DEPTH),('semantic',habitat_sim.SensorType.SEMANTIC)]:
        spec=habitat_sim.CameraSensorSpec();spec.uuid=name;spec.sensor_type=kind
        spec.sensor_subtype=habitat_sim.SensorSubType.PINHOLE
        spec.resolution=[height,width];spec.position=[0.,0.,0.];spec.orientation=[0.,0.,0.]
        spec.hfov=first['hfov_deg'];spec.near=float(request['primary']['depth_min_m']);spec.far=float(request['primary']['depth_max_m'])
        if name=='depth':spec.normalize_depth=False
        specs.append(spec)
    agent_config=habitat_sim.agent.AgentConfiguration();agent_config.sensor_specifications=specs
    annotations=parse_annotations(request['descriptors']['annotation']['path'])
    output.parent.mkdir(parents=True,exist_ok=True)
    simulator=habitat_sim.Simulator(habitat_sim.Configuration(backend,[agent_config]))
    try:
        if not getattr(simulator.semantic_scene,'objects',None):raise ValueError('no Habitat semantic scene objects')
        agent=simulator.get_agent(0)
        with tempfile.TemporaryDirectory(prefix='semantic-render-',dir=output.parent) as temporary:
            stage=Path(temporary);(stage/'masks').mkdir();frames=[];reports=[]
            for ordinal,item in enumerate(request['frames']):
                with np.load(request_path.parent/item['arrays']['path'],allow_pickle=False) as archive:
                    source={key:archive[key] for key in archive.files}
                validate_calibration(source['K'],width,height)
                for name in ('rgb','depth','semantic'):
                    native=simulator._sensors[name]
                    native=getattr(native,'_sensor_object',native)
                    projection=np.asarray(native.render_camera.projection_matrix,dtype=float)
                    effective=np.array([[projection[0,0]*width/2,0,(width-1)/2],
                        [0,projection[1,1]*height/2,(height-1)/2],[0,0,1.]])
                    if not np.allclose(effective,source['K'],rtol=0,atol=1e-8):
                        raise ValueError('effective rendered K differs from exact source K')
                target=canonical_optical_to_habitat(source['pose'])
                state=habitat_sim.AgentState();state.position=target[:3,3].copy()
                state.rotation=quat_from_coeffs(Rotation.from_matrix(target[:3,:3]).as_quat())
                agent.set_state(state,reset_sensors=True)
                actual=agent.get_state().sensor_states
                for name in ('rgb','depth','semantic'):
                    sensor=actual[name];rotation=sensor.rotation
                    # numpy-quaternion is the Habitat AgentState representation.
                    xyzw=np.r_[np.asarray(rotation.imag),float(rotation.real)]
                    measured=np.eye(4);measured[:3,:3]=Rotation.from_quat(xyzw).as_matrix();measured[:3,3]=sensor.position
                    if not np.allclose(measured,target,rtol=0,atol=1e-5):raise ValueError('rendered sensor pose mismatch')
                rendered=simulator.get_sensor_observations()
                ids=np.asarray(rendered['semantic']).copy()
                if not np.any((ids>0)&(ids!=4294967295)):raise ValueError('semantic renderer returned no positive instance IDs')
                frame,report=materialize_frame(item['frame'],source,np.asarray(rendered['rgb'])[...,:3],
                    np.asarray(rendered['depth']),ids,annotations,request['taxonomy'],stage/'masks',ordinal)
                frames.append(frame);reports.append(report)
            provenance=dict(kind=request['predictions']['provenance']['kind'],
                description='Offline HM3D semantic raster at exact committed source poses; mapped frozen taxonomy, >=100 visible pixels; all prediction outputs retained.',
                scope='mapped_frozen_taxonomy_visible_semantic_instances',min_visible_pixels=MIN_VISIBLE_PIXELS,
                visibility='all semantic raster pixels; no recorded-depth masking or structural exclusions',
                taxonomy_mapping='casefold exact category or frozen taxonomy alias; no scene-specific aliases',
                alignment_policy=ALIGNMENT_POLICY,request_sha256=_sha(request_path),
                assets=request['descriptors'],excluded_instances_report='alignment-exclusions.json',
                unsupported_scope='unmapped/unsupported/background/small semantic IDs are excluded from primary GT; their predictions are retained and may count as false positives')
            gt=dict(schema_version=1,binding=request['predictions']['binding'],provenance=provenance,frames=frames)
            _json(stage/'ground-truth.json',gt)
            _json(stage/'alignment-exclusions.json',dict(frames=reports,policy=provenance,
                included_instances=sum(item['included_instances'] for item in reports),
                excluded_instances=sum(len(item['excluded']) for item in reports)))
            manifest=dict(request_sha256=_sha(request_path),implementation_sha256=_sha(__file__),
                files={str(path.relative_to(stage)):_sha(path) for path in sorted(stage.rglob('*')) if path.is_file()},
                habitat_version=getattr(habitat_sim,'__version__','unknown'),frames=len(frames),alignment_passed=True)
            _json(stage/'manifest.json',manifest)
            if output.exists():raise FileExistsError('render output appeared')
            stage.rename(output)
    finally:simulator.close()
    return output/'ground-truth.json'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare')
    for name in ('predictions','ledger','config','config-sha256','semantic','annotation','out'):prepare.add_argument('--'+name,required=True)
    render=commands.add_parser('render');render.add_argument('--request',required=True);render.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    if args.command=='prepare':
        result=prepare_request(args.predictions,args.ledger,args.config,args.config_sha256,args.semantic,args.annotation,args.out)
    else:result=render_request(args.request,args.out)
    print(json.dumps(dict(result=str(result))))
    return 0


if __name__=='__main__':raise SystemExit(main())
