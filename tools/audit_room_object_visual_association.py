#!/usr/bin/env python3
"""Project final Hydra native-object mesh support into its recorded RGB-D frames.

Geometric projection is only an audit aid. The output explicitly leaves the
human semantic-category review pending; a high depth match is not a room label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def sha256_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def project_support_points(points_world, depth_m, valid_depth, intrinsics,
        T_world_camera, *, tolerance_m: float = 0.15) -> dict:
    """Project object mesh points into one captured axial-depth image."""
    points=np.asarray(points_world,dtype=np.float64)
    depth=np.asarray(depth_m)
    valid=np.asarray(valid_depth,dtype=bool)
    K=np.asarray(intrinsics,dtype=np.float64)
    T=np.asarray(T_world_camera,dtype=np.float64)
    if points.ndim!=2 or points.shape[1]!=3 or depth.ndim!=2 or valid.shape!=depth.shape:
        raise ValueError('invalid points/depth dimensions')
    if K.shape!=(3,3) or T.shape!=(4,4) or not np.isfinite(points).all() or not np.isfinite(K).all() or not np.isfinite(T).all():
        raise ValueError('invalid camera geometry')
    if not math.isfinite(tolerance_m) or tolerance_m<=0:
        raise ValueError('tolerance_m must be positive and finite')
    camera=(np.linalg.inv(T)@np.c_[points,np.ones(len(points))].T).T[:,:3]
    front=camera[:,2]>1e-4
    camera=camera[front]
    if not len(camera):
        return {'pixels':[],'inliers':[],'observed_depth_m':[],'projected_count':0,
            'inlier_count':0,'inlier_ratio':0.0,'median_abs_depth_error_m':None}
    homogeneous=(K@camera.T).T
    u=np.rint(homogeneous[:,0]/homogeneous[:,2]).astype(np.int64)
    v=np.rint(homogeneous[:,1]/homogeneous[:,2]).astype(np.int64)
    inside=(u>=0)&(u<depth.shape[1])&(v>=0)&(v<depth.shape[0])
    u,v,z=u[inside],v[inside],camera[inside,2]
    if not len(u):
        return {'pixels':[],'inliers':[],'observed_depth_m':[],'projected_count':0,
            'inlier_count':0,'inlier_ratio':0.0,'median_abs_depth_error_m':None}
    observed=depth[v,u].astype(np.float64)
    pixel_valid=valid[v,u]&np.isfinite(observed)&(observed>0)
    errors=np.full(len(u),np.inf,dtype=np.float64)
    errors[pixel_valid]=np.abs(observed[pixel_valid]-z[pixel_valid])
    inliers=pixel_valid&(errors<=tolerance_m)
    good_errors=errors[pixel_valid]
    return {'pixels':np.c_[u,v].tolist(),'inliers':inliers.tolist(),
        'observed_depth_m':[float(x) if math.isfinite(x) else None for x in observed],
        'projected_count':int(len(u)),'inlier_count':int(inliers.sum()),
        'inlier_ratio':float(inliers.sum()/len(u)),
        'median_abs_depth_error_m':None if not len(good_errors) else float(np.median(good_errors))}


def _room_ancestor(graph,node):
    current=node; seen=set()
    while current.has_parent():
        parent=graph.get_node(current.get_parent())
        if parent is None or parent.id in seen: return None
        seen.add(parent.id)
        if str(parent.id).startswith('R('): return str(parent.id)
        current=parent
    return None


def audit(graph_path: Path, graph_manifest_path: Path, recording_dir: Path,
        recording_certificate_path: Path, taxonomy_path: Path, output_dir: Path,
        *, tolerance_m: float=.15, min_projected_points: int=20,
        allow_incomplete_run: bool=False) -> dict:
    from spark_dsg import DynamicSceneGraph

    graph_path=graph_path.resolve(); graph_manifest_path=graph_manifest_path.resolve()
    recording_dir=recording_dir.resolve(); cert_path=recording_certificate_path.resolve()
    manifest=json.loads(graph_manifest_path.read_text()); cert=json.loads(cert_path.read_text())
    recording_path=recording_dir/'manifest.json'; recording=json.loads(recording_path.read_text())
    graph_hash=sha256_file(graph_path); recording_file_hash=sha256_file(recording_path)
    if (graph_hash!=manifest.get('graph_sha256') or graph_path.stat().st_size!=manifest.get('graph_bytes')
            or not manifest.get('complete')):
        raise ValueError('native graph export is incomplete or its hash differs')
    embedded=recording.get('certificate',{})
    manifest_payload=dict(recording); manifest_payload.pop('manifest_sha256',None)
    recording_hash=hashlib.sha256(json.dumps(manifest_payload,sort_keys=True,
        separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if (recording.get('manifest_sha256')!=recording_hash or not embedded.get('complete')
            or embedded.get('missing_count')!=0
            or embedded.get('written_count')!=embedded.get('expected_count')
            or embedded.get('written_count')!=len(recording.get('records',[]))):
        raise ValueError('RGB-D recording certificate is incomplete')
    if not cert.get('complete') and not allow_incomplete_run:
        raise ValueError('run recording certificate is incomplete')
    taxonomy=json.loads(taxonomy_path.read_text())
    labels={index+2:name for index,name in enumerate(taxonomy['categories'])}
    graph=DynamicSceneGraph.load(str(graph_path)); mesh=np.asarray(graph.mesh.get_vertices(),dtype=np.float64)
    if mesh.ndim!=2 or mesh.shape[0]<3: raise ValueError('native mesh vertex layout unsupported')
    vertices=mesh[:3,:].T
    objects=[]
    for node in graph.get_layer(2).nodes:
        attrs=node.attributes
        raw=getattr(attrs,'mesh_connections',None)
        indices=np.asarray([] if raw is None else list(raw),dtype=np.int64)
        if not len(indices) or np.any(indices<0) or np.any(indices>=len(vertices)):
            objects.append({'native_id':str(node.id),'semantic_id':int(attrs.semantic_label),
                'category':labels.get(int(attrs.semantic_label),'unknown_semantic_id'),
                'room_native_id':_room_ancestor(graph,node),'mesh_support_count':int(len(indices)),
                'status':'no_valid_mesh_support','manual_category_review':'pending'})
            continue
        objects.append({'native_id':str(node.id),'semantic_id':int(attrs.semantic_label),
            'category':labels.get(int(attrs.semantic_label),'unknown_semantic_id'),
            'room_native_id':_room_ancestor(graph,node),'mesh_support_count':int(len(indices)),
            '_points':vertices[indices],'_best':None})

    frame_count=0; rgb_cache={}
    for row in recording.get('records',[]):
        key=row.get('source_key',{}).get('payload',{}).get('fields',{})
        if key.get('sensor_id')!='primary-rgbd': continue
        frame_path=recording_dir/row['file']
        if sha256_file(frame_path)!=row.get('sha256'): raise ValueError(f'frame hash mismatch: {row["file"]}')
        with np.load(frame_path,allow_pickle=True) as z:
            meta=json.loads(bytes(z['metadata.json']).decode('utf-8'))
            fields=meta.get('fields',{}); recorded_key=fields.get('key',{}).get('payload',{}).get('fields',{})
            if recorded_key!=key: raise ValueError(f'frame source identity mismatch: {row["file"]}')
            if fields.get('coordinate_convention')!='canonical_z_up_v1': raise ValueError('frame coordinate convention is unsupported')
            frame={'frame_index':key.get('frame_index'),'path':str(frame_path),
                'sha256':row['sha256'],'rgb':z['rgb'].copy(),'depth_m':z['depth_m'].copy(),
                'valid_depth':z['valid_depth'].copy(),'K':z['K'].copy(),'T_world_camera':z['T_world_camera'].copy(),
                'calibration_id':fields.get('calibration_id')}
            frame_count+=1
            for item in objects:
                if '_points' not in item: continue
                score=project_support_points(item['_points'],frame['depth_m'],frame['valid_depth'],
                    frame['K'],frame['T_world_camera'],tolerance_m=tolerance_m)
                if score['projected_count']<min_projected_points: continue
                rank=(score['inlier_ratio'],score['inlier_count'],-(score['median_abs_depth_error_m'] or 999.0))
                if item['_best'] is None or rank>item['_best']['rank']:
                    item['_best']={'rank':rank,'score':score,'frame':frame.copy()}

    output_dir.mkdir(parents=True,exist_ok=True)
    report={'schema_version':1,'source':{'graph_sha256':graph_hash,
        'graph_manifest_sha256':sha256_file(graph_manifest_path),
        'recording_manifest_sha256':recording_hash,'recording_manifest_file_sha256':recording_file_hash,
        'recording_certificate_sha256':sha256_file(cert_path),
        'outer_run_certificate_complete':bool(cert.get('complete')),
        'episode_id':manifest.get('episode_id'),'run_id':manifest.get('run_id'),
        'graph_revision':manifest.get('graph_revision'),'recording_id':recording.get('recording_id'),
        'primary_rgbd_frame_count':frame_count,'tolerance_m':tolerance_m,
        'projection_rule':'native mesh_connections projected using recorded K/T_world_camera; compare captured metric axial depth'},
        'objects':[]}
    tiles=[]
    for item in objects:
        if '_points' not in item or item['_best'] is None:
            row={k:v for k,v in item.items() if not k.startswith('_')}
            row.update(status='no_frame_support_projection',manual_category_review='pending')
            report['objects'].append(row);continue
        best=item['_best']; score=best['score']; frame=best['frame']
        out_path=output_dir/f'{item["native_id"].replace("(","-").replace(")","")}-{item["category"].replace(" ","_")}.png'
        image=Image.fromarray(frame['rgb']);draw=ImageDraw.Draw(image)
        for (u,v),is_inlier in zip(score['pixels'],score['inliers']):
            color=(20,235,80) if is_inlier else (255,60,60)
            draw.ellipse((u-2,v-2,u+2,v+2),fill=color)
        draw.rectangle((0,0,640,34),fill=(0,0,0));draw.text((6,8),
            f'{item["native_id"]} {item["category"]} room={item["room_native_id"]} '
            f'depth-match={score["inlier_ratio"]:.3f} ({score["inlier_count"]}/{score["projected_count"]})',fill=(255,255,255))
        image.save(out_path)
        row={k:v for k,v in item.items() if not k.startswith('_')}
        row.update(status='geometry_projection_candidate' if score['inlier_ratio']>=.5 else 'weak_geometry_projection',
            best_frame_index=frame['frame_index'],frame_sha256=frame['sha256'],
            calibration_id=frame['calibration_id'],projected_count=score['projected_count'],
            depth_inlier_count=score['inlier_count'],depth_inlier_ratio=score['inlier_ratio'],
            median_abs_depth_error_m=score['median_abs_depth_error_m'],overlay_path=out_path.name,
            manual_category_review='pending')
        report['objects'].append(row)
        thumb=image.resize((320,240));tiles.append((item['native_id'],item['category'],thumb))
    columns=4; rows=math.ceil(len(tiles)/columns)
    sheet=Image.new('RGB',(columns*320,max(1,rows)*240),(32,32,32))
    for index,(_,_,image) in enumerate(tiles): sheet.paste(image,((index%columns)*320,(index//columns)*240))
    contact=output_dir/'object-association-contact-sheet.png';sheet.save(contact)
    report['contact_sheet']=contact.name
    report['summary']={'object_count':len(objects),
        'geometry_projection_candidate_count':sum(x.get('status')=='geometry_projection_candidate' for x in report['objects']),
        'manual_category_review_pending_count':len(objects)}
    result=output_dir/'association-audit.json';result.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'report':str(result),'objects':len(objects),**report['summary']},sort_keys=True))
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',type=Path,required=True)
    parser.add_argument('--graph-manifest',type=Path,required=True)
    parser.add_argument('--recording-dir',type=Path,required=True)
    parser.add_argument('--recording-certificate',type=Path,required=True)
    parser.add_argument('--taxonomy',type=Path,default=Path('configs/taxonomy-v1.json'))
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--tolerance-m',type=float,default=.15)
    parser.add_argument('--min-projected-points',type=int,default=20)
    parser.add_argument('--allow-incomplete-run',action='store_true',
        help='accept only a complete self-hashed frame manifest from a run whose outer certificate is incomplete; report that status')
    args=parser.parse_args(argv)
    audit(args.graph,args.graph_manifest,args.recording_dir,args.recording_certificate,
        args.taxonomy,args.out_dir,tolerance_m=args.tolerance_m,
        min_projected_points=args.min_projected_points,
        allow_incomplete_run=args.allow_incomplete_run)
    return 0


if __name__=='__main__': raise SystemExit(main())
