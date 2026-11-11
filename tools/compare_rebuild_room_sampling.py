#!/usr/bin/env python3
"""Compare full and FPS-capped Rebuild M1-M5 replay on one raw RGB-D recording."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT/'src'))


def select_fps_frames(frames,fps_cap_hz):
    if type(fps_cap_hz) not in (int,float) or not math.isfinite(fps_cap_hz) or not 0<fps_cap_hz<=20:
        raise ValueError('fps_cap_hz must be positive finite and <= 20')
    period_ns=math.ceil(1_000_000_000/fps_cap_hz)
    selected=[];last=None
    for frame in frames:
        stamp=frame.capture_monotonic_ns
        if last is None or stamp-last>=period_ns:
            selected.append(frame);last=stamp
    return selected


def _ratio(numerator,denominator):
    return None if denominator==0 else float(numerator/denominator)


def compare_m3(full_map,sampled_map):
    resolution=float(full_map.resolution_m)
    if not math.isclose(resolution,float(sampled_map.resolution_m),rel_tol=0.,abs_tol=1e-12):
        raise ValueError('M3 resolutions differ; cannot compare cellwise coverage')
    origins=(tuple(full_map.origin_xy),tuple(sampled_map.origin_xy))
    min_x=min(origin[0] for origin in origins);min_y=min(origin[1] for origin in origins)
    offsets=[]
    for origin in origins:
        col=(origin[0]-min_x)/resolution;row=(origin[1]-min_y)/resolution
        if not math.isclose(col,round(col),rel_tol=0.,abs_tol=1e-6) or not math.isclose(row,round(row),rel_tol=0.,abs_tol=1e-6):
            raise ValueError('M3 origins are not aligned to the shared cell grid')
        offsets.append((round(row),round(col)))
    maps=(np.asarray(full_map.states),np.asarray(sampled_map.states))
    max_rows=max(offset[0]+grid.shape[0] for offset,grid in zip(offsets,maps))
    max_cols=max(offset[1]+grid.shape[1] for offset,grid in zip(offsets,maps))
    aligned=[]
    for (row,col),grid in zip(offsets,maps):
        target=np.full((max_rows,max_cols),-1,dtype=np.int8)
        target[row:row+grid.shape[0],col:col+grid.shape[1]]=grid
        aligned.append(target)
    full,sampled=aligned
    full_known=full!=-1;sampled_known=sampled!=-1
    full_occ=full>0;sampled_occ=sampled>0
    full_free=full==0;sampled_free=sampled==0
    occ_intersection=int(np.count_nonzero(full_occ&sampled_occ))
    return dict(
        full_known_cells=int(full_known.sum()),sampled_known_cells=int(sampled_known.sum()),
        known_recall=_ratio(np.count_nonzero(full_known&sampled_known),int(full_known.sum())),
        full_occupied_cells=int(full_occ.sum()),sampled_occupied_cells=int(sampled_occ.sum()),
        occupied_recall=_ratio(occ_intersection,int(full_occ.sum())),
        occupied_precision=_ratio(occ_intersection,int(sampled_occ.sum())),
        occupied_iou=_ratio(occ_intersection,int(np.count_nonzero(full_occ|sampled_occ))),
        free_recall=_ratio(np.count_nonzero(full_free&sampled_free),int(full_free.sum())),
        resolution_m=resolution,aligned_shape=[int(max_rows),int(max_cols)])


def _yaw(frame):
    forward=np.asarray(frame.T_world_camera,dtype=np.float64)[:2,2]
    if not np.isfinite(forward).all() or np.linalg.norm(forward)<1e-9:return None
    return math.atan2(float(forward[1]),float(forward[0]))


def pose_coverage(all_frames,sampled_frames,*,distance_limit_m=.25,yaw_limit_deg=15.):
    if not all_frames:return dict(total=0,covered=0,fraction=None,p50_nearest_distance_m=None,p95_nearest_distance_m=None,
        trajectory_path_length_m=None,trajectory_displacement_m=None,trajectory_bounds_xy_m=None)
    poses=[np.asarray(frame.T_world_camera,dtype=np.float64)[:2,3] for frame in all_frames]
    path_length=float(sum(np.linalg.norm(b-a) for a,b in zip(poses,poses[1:])))
    displacement=float(np.linalg.norm(poses[-1]-poses[0]))
    bounds=np.asarray(poses)
    sampled=[]
    for frame in sampled_frames:
        position=np.asarray(frame.T_world_camera,dtype=np.float64)[:2,3]
        yaw=_yaw(frame)
        if yaw is not None:sampled.append((position,yaw))
    distances=[];covered=0;yaw_limit=math.radians(yaw_limit_deg)
    for frame in all_frames:
        position=np.asarray(frame.T_world_camera,dtype=np.float64)[:2,3];yaw=_yaw(frame)
        candidates=[]
        for candidate_position,candidate_yaw in sampled:
            distance=float(np.linalg.norm(position-candidate_position))
            dyaw=abs((yaw-candidate_yaw+math.pi)%(2*math.pi)-math.pi) if yaw is not None else math.inf
            if distance<=distance_limit_m and dyaw<=yaw_limit:candidates.append(distance)
        nearest=min(candidates) if candidates else math.inf
        distances.append(nearest)
        if math.isfinite(nearest):covered+=1
    finite=np.asarray([value for value in distances if math.isfinite(value)],dtype=np.float64)
    return dict(total=len(all_frames),covered=covered,fraction=_ratio(covered,len(all_frames)),
        translation_limit_m=distance_limit_m,yaw_limit_deg=yaw_limit_deg,
        interpretation='pose-neighborhood proxy only; not observed-surface coverage',
        trajectory_path_length_m=path_length,trajectory_displacement_m=displacement,
        trajectory_bounds_xy_m=[[float(v) for v in bounds.min(axis=0)],
                                [float(v) for v in bounds.max(axis=0)]],
        p50_nearest_distance_m=None if not len(finite) else float(np.percentile(finite,50)),
        p95_nearest_distance_m=None if not len(finite) else float(np.percentile(finite,95)))


def _polygon_iou(a,b):
    from neusymnav.regions._types import Polygon2D,ring_area
    from neusymnav.regions.geometry import intersection_area
    pa=Polygon2D(tuple(map(tuple,np.asarray(a.polygon,dtype=np.float64).tolist())))
    pb=Polygon2D(tuple(map(tuple,np.asarray(b.polygon,dtype=np.float64).tolist())))
    area_a=ring_area(pa.outer);area_b=ring_area(pb.outer);inter=intersection_area(pa,pb)
    return 0. if area_a+area_b-inter<=0 else inter/(area_a+area_b-inter)


def compare_m5(full_publication,sampled_publication):
    full={} if full_publication.regions is None else full_publication.regions.regions
    sampled={} if sampled_publication.regions is None else sampled_publication.regions.regions
    pairs=sorted(((_polygon_iou(a,b),a.region_id,b.region_id)
                  for a in full.values() for b in sampled.values()),reverse=True)
    used_full=set();used_sampled=set();matches=[]
    for iou,full_id,sampled_id in pairs:
        if full_id in used_full or sampled_id in used_sampled:continue
        used_full.add(full_id);used_sampled.add(sampled_id);matches.append(iou)
    return dict(full_region_count=len(full),sampled_region_count=len(sampled),
        full_regions_stale=full_publication.regions_stale,sampled_regions_stale=sampled_publication.regions_stale,
        full_accepted_m3_revision=full_publication.accepted_map_revision,
        sampled_accepted_m3_revision=sampled_publication.accepted_map_revision,
        greedy_matched_region_count=len(matches),greedy_mean_polygon_iou=None if not matches else float(np.mean(matches)),
        greedy_polygon_ious=matches,
        full_areas_m2=[float(abs(np.cross(np.asarray(r.polygon),np.roll(np.asarray(r.polygon),-1,axis=0)).sum())*.5) for r in full.values()],
        sampled_areas_m2=[float(abs(np.cross(np.asarray(r.polygon),np.roll(np.asarray(r.polygon),-1,axis=0)).sum())*.5) for r in sampled.values()])


def _session(room_config,episode,floor,run_dir):
    from neusymnav.regions.rebuild_rgbd_input import RebuildRGBDConfig
    from neusymnav.regions.rebuild_room_session import RebuildRoomSession
    profile=RebuildRGBDConfig(**{key:room_config[key] for key in
        ('resolution_m','backprojection_stride','min_depth_m','max_depth_m','max_range_m') if key in room_config})
    return RebuildRoomSession(source_root=room_config['source_root'],
        m23_binary=room_config['m23_binary']['path'],m4_binary=room_config['m4_binary']['path'],
        episode_id=episode,floor_id=floor,config=profile,
        ipc_timeout_s=room_config.get('ipc_timeout_s',60.),m23_timeout_s=room_config.get('m23_timeout_s',15.),
        m4_timeout_s=room_config.get('m4_timeout_s',30.),run_dir=run_dir)


def _percentile_summary(values):
    ordered=sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:return dict(samples=0,p50=None,p95=None,max=None,mean=None)
    def percentile(fraction):return ordered[min(len(ordered)-1,math.ceil(fraction*len(ordered))-1)]
    return dict(samples=len(ordered),p50=percentile(.50),p95=percentile(.95),
        max=ordered[-1],mean=float(np.mean(ordered)))


def stage_timing_summary(journal):
    processed=[item for item in journal if item.get('reason')=='processed']
    keys=sorted({key for item in processed for key,value in item.get('timings_ms',{}).items()
                 if isinstance(value,(int,float)) and not isinstance(value,bool)})
    stage={key:_percentile_summary([item['timings_ms'][key] for item in processed
                                    if key in item.get('timings_ms',{})]) for key in keys}
    work_keys=('input_pixel_count','finite_depth_pixel_count','valid_mask_pixel_count',
               'backprojected_hit_count','point_count')
    work={key:_percentile_summary([item['mapping_work'][key] for item in processed
                                   if key in item.get('mapping_work',{})]) for key in work_keys}
    residuals=[]
    for item in processed:
        record=item.get('mapping_work',{})
        required=('m1_m2_m3_runtime_ms','m1_runtime_ms','m2_runtime_ms','m3_runtime_ms')
        if all(key in record for key in required):
            residuals.append(record['m1_m2_m3_runtime_ms']-
                record['m1_runtime_ms']-record['m2_runtime_ms']-record['m3_runtime_ms'])
    work['m1_m2_m3_unattributed_residual_ms']=_percentile_summary(residuals)
    return dict(processed_updates=len(processed),stage_timings_ms=stage,mapping_work=work)


def _run_variant(frames,room_config,episode,floor,run_dir):
    session=_session(room_config,episode,floor,run_dir)
    try:
        for frame in frames:
            admission=session.submit(frame)
            if not admission.accepted:
                if not session.wait_idle(session.ipc_timeout_s):raise TimeoutError('room replay failed to drain')
                admission=session.submit(frame)
            if not admission.accepted:raise RuntimeError('room replay rejected frame: '+admission.reason)
            if not session.wait_idle(session.ipc_timeout_s):raise TimeoutError('room replay update timed out')
            health=session.health
            if health.get('failed'):raise RuntimeError('room worker failed: '+str(health.get('failure_reason')))
        publication=session.snapshot()
        if publication is None:raise RuntimeError('room replay produced no M3/M5 publication')
        return publication
    finally:
        result=session.close()
        if not result['clean_shutdown'] or not result['runtime_complete']:
            raise RuntimeError(f'room replay shutdown/integrity failed: {result}')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording',type=Path,required=True,help='complete raw sensor recording directory')
    parser.add_argument('--config',type=Path,required=True,help='local checked Rebuild RGB-D profile')
    parser.add_argument('--fps-cap-hz',type=float,default=.1)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    from neusymnav.recording.replay import ReplayReader
    from neusymnav.runtime.configuration import load_config
    config=load_config(args.config).data;episode=config['episode'];room=config['workers']['room_pipeline']
    args.out.mkdir(parents=True,exist_ok=False)
    reader=ReplayReader(args.recording)
    frames=[frame for frame in reader.frames() if frame.modality=='rgbd' and frame.key.sensor_id==episode['primary_sensor_id']]
    sampled=select_fps_frames(frames,args.fps_cap_hz)
    if not frames or not sampled:raise ValueError('raw recording has no primary RGB-D frames')
    full_pub=_run_variant(frames,room,episode['id'],episode['floor_id'],args.out/'full'/'session')
    sampled_pub=_run_variant(sampled,room,episode['id'],episode['floor_id'],args.out/'fps-capped'/'session')
    np.savez_compressed(args.out/'full-m3.npz',states=full_pub.latest_map.states,
        origin_xy=np.asarray(full_pub.latest_map.origin_xy),resolution_m=np.asarray(full_pub.latest_map.resolution_m))
    np.savez_compressed(args.out/'fps-capped-m3.npz',states=sampled_pub.latest_map.states,
        origin_xy=np.asarray(sampled_pub.latest_map.origin_xy),resolution_m=np.asarray(sampled_pub.latest_map.resolution_m))
    full_journal=[json.loads(line) for line in (args.out/'full'/'session'/'admission-journal.jsonl').read_text().splitlines()]
    sampled_journal=[json.loads(line) for line in (args.out/'fps-capped'/'session'/'admission-journal.jsonl').read_text().splitlines()]
    report=dict(schema_version=1,recording_manifest_sha256=hashlib.sha256((args.recording/'manifest.json').read_bytes()).hexdigest(),
        episode_id=episode['id'],primary_sensor_id=episode['primary_sensor_id'],fps_cap_hz=args.fps_cap_hz,
        raw_primary_rgbd_frames=len(frames),fps_capped_frames=len(sampled),
        selected_frame_indices=[int(frame.key.frame_index) for frame in sampled],
        pose_coverage=pose_coverage(frames,sampled),m3=compare_m3(full_pub.latest_map,sampled_pub.latest_map),
        m5=compare_m5(full_pub,sampled_pub),
        m3_modes=dict(full=[event.get('m3_projection_mode') for event in full_journal if event.get('reason')=='processed'],
                      fps_capped=[event.get('m3_projection_mode') for event in sampled_journal if event.get('reason')=='processed']),
        timing=dict(full=stage_timing_summary(full_journal),
                    fps_capped=stage_timing_summary(sampled_journal)),
        acceptance_checker='not_run; this replay comparison does not change acceptance')
    (args.out/'comparison.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
