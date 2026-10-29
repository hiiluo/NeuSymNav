"""Conservative negative visibility, ported from NewOH3DSG unchanged geometry gates."""
import itertools
import numpy as np
from ..perception.projector import Projector


def negative_visibility(source, batch, snapshot, *, current):
    if not current or not batch.allows_negative_evidence:
        return ()
    height,width=source.depth_m.shape
    occupied=np.zeros((height,width),bool)
    for detection in batch.detections:
        occupied |= detection.mask
    rotation=source.T_world_camera[:3,:3]
    position=source.T_world_camera[:3,3]
    events=[]
    for object_id,obj in sorted(snapshot.objects.items())[:128]:
        if obj.lifecycle in {'retired','merged'}:
            continue
        corners=np.array(list(itertools.product(*zip(obj.bounds[0],obj.bounds[1]))))
        camera=(corners-position) @ rotation
        z=camera[:,2]
        if np.any(z<Projector.MIN_DEPTH_M) or np.any(z>=Projector.MAX_DEPTH_M):
            continue
        projected=camera @ source.K.T
        uv=projected[:,:2]/projected[:,2,None]
        if not np.isfinite(uv).all():
            continue
        x0,y0=np.floor(uv.min(axis=0)).astype(int)
        x1,y1=np.floor(uv.max(axis=0)).astype(int)+1
        if x0<2 or y0<2 or x1>width-2 or y1>height-2:
            continue
        area=(x1-x0)*(y1-y0)
        if area<16 or area>16384:
            continue
        region=np.s_[y0:y1,x0:x1]
        if occupied[region].any():
            continue
        depths=source.depth_m[region]
        if (not source.valid_depth[region].all() or not np.isfinite(depths).all()
            or np.any(depths<Projector.MIN_DEPTH_M) or np.any(depths>=Projector.MAX_DEPTH_M)
            or np.any(depths<=float(z.max())+.08)):
            continue
        events.append(dict(object_id=object_id,object_revision=obj.revision,
            projected_bbox_xyxy=[int(x0),int(y0),int(x1),int(y1)],
            camera_position=position.tolist(),geometry_hash=source.geometry_hash,
            source_map_revision=None))
    return tuple(events)
