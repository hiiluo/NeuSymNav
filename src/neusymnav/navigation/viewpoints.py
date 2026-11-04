"""Bounded fixed-mount viewpoint proposals; visibility is a prediction only."""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from ..contracts import GridState
from ..contracts.observations import age_ns
from ..geometry.frames import validate_intrinsics, validate_pose
from ..mapping.occupancy import capsule_cells
from .planner import Planner, PlanResult


def _owned(value, shape):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError('invalid finite geometry')
    return np.frombuffer(a.tobytes(), dtype=np.float64).reshape(shape)


def _body_pose(xy, yaw, z):
    x, y = _owned(xy, (2,)); yaw = float(yaw); z = float(z)
    if not math.isfinite(yaw) or not math.isfinite(z): raise ValueError('invalid body pose')
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c,-s,0,x],[s,c,0,y],[0,0,1,z],[0,0,0,1.]], dtype=float)


@dataclass(frozen=True, eq=False)
class CameraModel:
    K: np.ndarray
    image_shape_hw: tuple[int, int]
    T_body_camera: np.ndarray
    body_z_m: float
    calibration_id: str

    def __post_init__(self):
        k = _owned(self.K, (3,3)); pose = _owned(self.T_body_camera, (4,4))
        validate_intrinsics(k); validate_pose(pose)
        shape = tuple(self.image_shape_hw)
        if len(shape) != 2 or any(isinstance(v,bool) or not isinstance(v,(int,np.integer)) or v <= 0 for v in shape):
            raise ValueError('invalid image shape')
        if not math.isfinite(float(self.body_z_m)) or not isinstance(self.calibration_id,str) or not self.calibration_id:
            raise ValueError('invalid camera provenance or body height')
        object.__setattr__(self, 'K', k); object.__setattr__(self, 'T_body_camera', pose)
        object.__setattr__(self, 'image_shape_hw', tuple(int(v) for v in shape))
        object.__setattr__(self, 'body_z_m', float(self.body_z_m))

    @classmethod
    def from_observation(cls, obs, robot_xy, yaw_rad, body_z_m):
        body = _body_pose(robot_xy, yaw_rad, body_z_m)
        return cls(obs.K, obs.rgb.shape[:2], np.linalg.inv(body) @ obs.T_world_camera,
                   body_z_m, obs.calibration_id)


@dataclass(frozen=True)
class ViewpointCandidate:
    world_xy: tuple[float, float]
    yaw_rad: float
    path: PlanResult
    map_revision: int
    predicted_visibility: bool
    diversity_angle_deg: float
    baseline_m: float


@dataclass(frozen=True)
class ViewpointPlan:
    candidates: tuple[ViewpointCandidate, ...]
    reason: str


class ViewpointPlanner:
    def __init__(self, robot, camera_model, max_poses=12, max_nav_age_ns=300_000_000, *,
                 min_distance_m=.5, max_distance_m=3., baseline_m=.3, angle_deg=15.):
        if not isinstance(camera_model, CameraModel): raise ValueError('camera model required')
        if isinstance(max_poses,bool) or not isinstance(max_poses,int) or not 1 <= max_poses <= 12:
            raise ValueError('max_poses must be between 1 and 12')
        if isinstance(max_nav_age_ns,bool) or not isinstance(max_nav_age_ns,int) or max_nav_age_ns < 0:
            raise ValueError('invalid nav age')
        if not all(math.isfinite(float(x)) for x in (min_distance_m,max_distance_m,baseline_m,angle_deg)) or not 0 < min_distance_m < max_distance_m or baseline_m < 0 or not 0 <= angle_deg <= 180:
            raise ValueError('invalid range or diversity thresholds')
        self.robot=robot; self.camera_model=camera_model; self.max_poses=max_poses
        self.max_nav_age_ns=max_nav_age_ns; self.min_distance_m=float(min_distance_m)
        self.max_distance_m=float(max_distance_m); self.baseline_m=float(baseline_m); self.angle_deg=float(angle_deg)
        self.planner=Planner(robot)

    def visible(self, nav, xy, yaw, target):
        """Recheck fixed-mount geometric prediction on the current map."""
        model=self.camera_model
        target=_owned(target,(3,))
        pose=_body_pose(xy,yaw,model.body_z_m) @ model.T_body_camera
        delta=target-pose[:3,3]
        point=pose[:3,:3].T @ delta
        if not self.min_distance_m<=np.linalg.norm(delta)<=self.max_distance_m or point[2]<=0:return False
        uv=model.K @ point;u,v=uv[:2]/uv[2]
        if not (0<=u<model.image_shape_hw[1] and 0<=v<model.image_shape_hw[0]):return False
        end=(math.floor((target[1]-nav.origin_xy[1])/nav.resolution_m),
             math.floor((target[0]-nav.origin_xy[0])/nav.resolution_m))
        h,w=nav.states.shape
        if not (0<=end[0]<h and 0<=end[1]<w):return False
        return all((r,c)==end or (0<=r<h and 0<=c<w and nav.states[r,c]==GridState.FREE)
                   for r,c in capsule_cells(nav.origin_xy,nav.resolution_m,pose[:2,3],target[:2],0.))

    def plan(self, nav, robot_xy, object_centroid_world, previous_views=(), *, now_ns, clock_domain):
        try: age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,clock_domain)
        except ValueError: return ViewpointPlan((), 'nav_clock_invalid')
        if age > self.max_nav_age_ns: return ViewpointPlan((), 'nav_stale')
        start=_owned(robot_xy,(2,)); target=_owned(object_centroid_world,(3,))
        views=tuple(previous_views)
        radius=(self.min_distance_m+self.max_distance_m)/2
        goals=[]; seen=set(); h,w=nav.states.shape
        for i in range(self.max_poses):
            angle=2*math.pi*i/self.max_poses
            desired=target[:2]+radius*np.array([math.cos(angle),math.sin(angle)])
            col=math.floor((desired[0]-nav.origin_xy[0])/nav.resolution_m)
            row=math.floor((desired[1]-nav.origin_xy[1])/nav.resolution_m)
            if 0 <= row < h and 0 <= col < w and (row,col) not in seen:
                seen.add((row,col)); goals.append((row,col))
        if not goals: return ViewpointPlan((), 'unknown_or_outside_map')
        paths=self.planner.plan_many(nav,tuple(start),tuple(goals))
        candidates=[]; reasons=set(); model=self.camera_model
        for row,col in goals:
            path=paths[(row,col)]
            if not path.success:
                reasons.add('unknown' if nav.states[row,col] == GridState.UNKNOWN else 'unreachable'); continue
            xy=(nav.origin_xy[0]+(col+.5)*nav.resolution_m,nav.origin_xy[1]+(row+.5)*nav.resolution_m)
            yaw=math.atan2(target[1]-xy[1],target[0]-xy[0])
            f=model.T_body_camera[:2,2]
            if np.linalg.norm(f)<1e-9:
                reasons.add('fov'); continue
            # Iteration accounts for camera translation rotating with the body.
            for _ in range(20):
                pose=_body_pose(xy,yaw,model.body_z_m) @ model.T_body_camera
                d=target[:2]-pose[:2,3]
                new=math.atan2(d[1],d[0])-math.atan2(f[1],f[0])
                if abs(math.atan2(math.sin(new-yaw),math.cos(new-yaw))) < 1e-12: break
                yaw=new
            yaw=math.atan2(math.sin(new),math.cos(new))
            pose=_body_pose(xy,yaw,model.body_z_m) @ model.T_body_camera
            camera_point=pose[:3,:3].T @ (target-pose[:3,3])
            distance=float(np.linalg.norm(target-pose[:3,3]))
            if not self.min_distance_m <= distance <= self.max_distance_m or camera_point[2] <= 0:
                reasons.add('fov'); continue
            uv=model.K @ camera_point; u,v=uv[:2]/uv[2]
            if not (0 <= u < model.image_shape_hw[1] and 0 <= v < model.image_shape_hw[0]):
                reasons.add('fov'); continue
            target_cell=(math.floor((target[1]-nav.origin_xy[1])/nav.resolution_m),math.floor((target[0]-nav.origin_xy[0])/nav.resolution_m))
            blocked=None
            for r,c in capsule_cells(nav.origin_xy,nav.resolution_m,pose[:2,3],target[:2],0.):
                if (r,c)==target_cell: continue
                if not (0 <= r < h and 0 <= c < w) or nav.states[r,c]==GridState.UNKNOWN:
                    blocked='unknown'; break
                if nav.states[r,c]!=GridState.FREE:
                    blocked='occluded'; break
            if blocked: reasons.add(blocked); continue
            baselines=[]; angles=[]
            direction=pose[:3,3]-target; direction=direction/np.linalg.norm(direction)
            for view in views:
                old=np.asarray(view.camera_pose_world,dtype=float)[:3,3]
                old_target=np.asarray(view.object_centroid_world,dtype=float)
                old_dir=old-old_target; norm=np.linalg.norm(old_dir)
                if norm <= 1e-9: continue
                baselines.append(float(np.linalg.norm(old-pose[:3,3])))
                angles.append(math.degrees(math.acos(float(np.clip(direction @ (old_dir/norm),-1,1)))))
            baseline=min(baselines,default=2*self.max_distance_m); angle=min(angles,default=180.)
            candidates.append(ViewpointCandidate(xy,yaw,path,nav.revision,True,angle,baseline))
        candidates.sort(key=lambda c: (-(c.baseline_m>=self.baseline_m and c.diversity_angle_deg>=self.angle_deg),
                                       -c.diversity_angle_deg, -c.baseline_m, c.path.cost_m, c.world_xy, c.yaw_rad))
        if candidates: return ViewpointPlan(tuple(candidates),'ok')
        for reason in ('unknown','occluded','fov','unreachable'):
            if reason in reasons: return ViewpointPlan((),reason)
        return ViewpointPlan((),'unknown_or_outside_map')
