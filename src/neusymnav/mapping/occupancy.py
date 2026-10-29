"""Canonical NavMap adapter over the pinned NewOH3DSG occupancy kernels.

Private kernels index coordinates (planar-x, height, planar-y). This adapter
permutes scalar axes to (x,z,y); it does NOT publish a reflected world pose.
Public observations and snapshots always retain canonical Z-up coordinates.
See runs/p03/source-provenance.json for the exact upstream hashes.
"""
from __future__ import annotations
from dataclasses import dataclass
from types import SimpleNamespace
import math
import numpy as np
from ..contracts import Observation, NavSnapshot, GridState
from ._grid import GridSpec
from ._occupancy_core import OccupancyMapper, DuplicateFrameError


@dataclass(frozen=True)
class RobotGeometry:
    geometry_id: str
    radius_m: float
    height_m: float
    margin_m: float = .05
    near_ground_tolerance_m: float = .05

    def __post_init__(self):
        if not self.geometry_id or any(not math.isfinite(v) for v in (self.radius_m,self.height_m,self.margin_m,self.near_ground_tolerance_m)):
            raise ValueError('explicit finite robot geometry required')
        if self.radius_m<=0 or self.height_m<=self.near_ground_tolerance_m or self.margin_m<0 or self.near_ground_tolerance_m<=0:
            raise ValueError('invalid cylindrical robot geometry')


@dataclass(frozen=True)
class BootstrapResult:
    ready: bool
    reason: str
    required_cells: int
    observed_cells: int
    source: object


def capsule_cells(origin_xy, resolution_m, start, end, radius):
    """Closed squares intersecting a world-space swept circular footprint.

    Enumerate in column/row order, in batches of at most 4096 candidates. The
    segment-to-square distance is exact geometry (slabs, endpoints, corners),
    with the original scalar arithmetic retained near the floating boundary.
    """
    # Translate once before adding a radius or constructing cell edges. World
    # arithmetic can erase sub-ULP radii/edges at large translated origins.
    origin=np.asarray(origin_xy,float)
    a=np.asarray(start,float)-origin;b=np.asarray(end,float)-origin;d=b-a
    length2=d@d;threshold=radius+1e-12
    # A closed square can touch the lower capsule bound with its HIGH edge.
    # Include the comparison epsilon on both sides; outward rounding retains
    # grid-boundary tangencies after division. Python bounds avoid overflow for
    # public lazy calls whose epsilon spans more than int64 cells.
    lower=np.nextafter((np.minimum(a,b)-threshold)/resolution_m,-math.inf)
    upper=np.nextafter((np.maximum(a,b)+threshold)/resolution_m,math.inf)
    lo=tuple(math.ceil(x)-1 for x in lower);hi=tuple(math.floor(x) for x in upper)
    rows=hi[1]-lo[1]+1;cols=hi[0]-lo[0]+1
    if rows<=0 or cols<=0:return
    index_dtype=np.int64 if min(lo)>=np.iinfo(np.int64).min and max(hi)<=np.iinfo(np.int64).max else object

    def scalar_intersects(low,high):
        # np.linalg.norm(vector) and batched norms can round differently at a
        # tangent. Preserve the old arithmetic there, including degenerate
        # segments and its strict parallel-slab threshold.
        t0,t1=0.,1.
        for axis in (0,1):
            if abs(d[axis])<1e-15:
                if a[axis]<low[axis] or a[axis]>high[axis]:t1=-1.;break
            else:
                u,v=(low[axis]-a[axis])/d[axis],(high[axis]-a[axis])/d[axis]
                t0=max(t0,min(u,v));t1=min(t1,max(u,v))
        distance=0. if t0<=t1 else math.inf
        for point in (a,b):
            distance=min(distance,float(np.linalg.norm(np.maximum(np.maximum(low-point,point-high),0))))
        for corner in (low,high,np.array([low[0],high[1]]),np.array([high[0],low[1]])):
            t=0. if length2==0 else min(1.,max(0.,float((corner-a)@d/length2)))
            distance=min(distance,float(np.linalg.norm(corner-(a+t*d))))
        return distance<=threshold

    for offset in range(0,rows*cols,4096):
        count=min(4096,rows*cols-offset)
        col_offset,row_offset=divmod(offset,rows)
        # Local offsets avoid allocating a raster or an array spanning a long
        # corridor. The flattened order matches the original nested loops.
        offsets=np.arange(count)
        if rows<=4096:
            offsets+=row_offset
            indices=np.column_stack((int(lo[0])+col_offset+offsets//rows,
                                     int(lo[1])+offsets%rows))
        else:
            # Even the candidate row count may exceed int64 for arbitrary
            # public calls. Only actual cell indices need fit the old bounds.
            first=min(count,rows-row_offset)
            indices=np.empty((count,2),dtype=index_dtype)
            indices[:,0]=int(lo[0])+col_offset
            indices[:first,1]=offsets[:first]+(int(lo[1])+row_offset)
            if first<count:
                indices[first:,0]+=1
                indices[first:,1]=offsets[:count-first]+int(lo[1])
        low=np.asarray(indices,float)*resolution_m;high=low+resolution_m
        t0=np.zeros(count);t1=np.ones(count)
        for axis in (0,1):
            if abs(d[axis])<1e-15:
                t1[(a[axis]<low[:,axis])|(a[axis]>high[:,axis])]=-1.
            else:
                u=(low[:,axis]-a[axis])/d[axis];v=(high[:,axis]-a[axis])/d[axis]
                t0=np.maximum(t0,np.minimum(u,v));t1=np.minimum(t1,np.maximum(u,v))
        distance=np.where(t0<=t1,0.,math.inf)
        for point in (a,b):
            delta=np.maximum(np.maximum(low-point,point-high),0)
            distance=np.fmin(distance,np.linalg.norm(delta,axis=1))
        for corner in (low,high,np.column_stack((low[:,0],high[:,1])),
                       np.column_stack((high[:,0],low[:,1]))):
            t=np.zeros(count) if length2==0 else np.clip(np.sum((corner-a)*d,axis=1)/length2,0.,1.)
            distance=np.fmin(distance,np.linalg.norm(corner-(a+t[:,None]*d),axis=1))
        included=distance<=threshold
        # Bound floating-point error by coordinate magnitude, then use the
        # scalar oracle only for ambiguous cells. This is a rounding guard,
        # never a relaxation of the footprint or its 1e-12 boundary epsilon.
        scale=np.maximum(np.max(np.maximum(np.abs(low),np.abs(high)),axis=1),
                         max(1.,float(np.max(np.abs(a))),float(np.max(np.abs(b))),abs(radius)))
        ambiguous=np.abs(distance-threshold)<=64*np.finfo(float).eps*scale
        if not math.isfinite(length2):ambiguous[:]=True
        for index in np.flatnonzero(ambiguous):
            included[index]=scalar_intersects(low[index],high[index])
        for index in np.flatnonzero(included):
            yield int(indices[index,1]),int(indices[index,0])


class NavMapper:
    def __init__(self, *, robot: RobotGeometry, floor_z_m: float, floor_datum_source: str,
                 calibration_hash: str, resolution_m: float=.05, origin_xy=(0.,0.),
                 tile_size_cells: int=64, height_bin_m: float | None=None,
                 min_depth_m: float=.15,max_depth_m: float=5.,sampling_stride: int=4,
                 snapshot_radius_m: float=8., max_snapshot_cells: int=1_000_000,
                 tile_archive_dir=None, max_active_tiles: int | None=None, raycast_workers: int=1):
        if not isinstance(robot,RobotGeometry) or not floor_datum_source or not math.isfinite(floor_z_m):
            raise ValueError('explicit geometry and calibrated floor datum required')
        if len(calibration_hash)!=64 or any(c not in '0123456789abcdef' for c in calibration_hash):
            raise ValueError('floor calibration SHA-256 required')
        if snapshot_radius_m<=0 or not math.isfinite(snapshot_radius_m):raise ValueError('invalid snapshot radius')
        cells=2*math.ceil(snapshot_radius_m/resolution_m)+1
        if cells*cells>max_snapshot_cells:raise ValueError('snapshot exceeds bounded raster budget')
        if height_bin_m is None: height_bin_m=robot.near_ground_tolerance_m
        if height_bin_m>robot.near_ground_tolerance_m:raise ValueError('height bin exceeds declared near-ground tolerance')
        self.robot=robot;self.floor_z_m=float(floor_z_m);self.floor_datum_source=floor_datum_source
        self.calibration_hash=calibration_hash;self.snapshot_radius_m=snapshot_radius_m
        self._core=OccupancyMapper(GridSpec(resolution_m,tile_size_cells,*origin_xy,floor_z_m),
            robot_height_m=robot.height_m,height_bin_m=height_bin_m,min_depth_m=min_depth_m,
            max_depth_m=max_depth_m,sampling_stride=sampling_stride,tile_archive_dir=tile_archive_dir,raycast_workers=raycast_workers)
        if max_active_tiles is not None:
            if type(max_active_tiles) is not int or max_active_tiles<1:raise ValueError('invalid tile cap')
            n=tile_size_cells**2
            self._core.MAX_PLANAR_MEMORY_BYTES=max_active_tiles*n*5
            self._core.MAX_HEIGHT_MEMORY_BYTES=max_active_tiles*n*self._core.height_bin_count*4
        self._revision=0;self._clock_domain=None;self._frame_watermarks={};self._current_coverage=None

    def bind_archive_reservation(self, factory):
        """Bind the run owner's budget to actual tile archive transactions."""
        if not callable(factory) or self._core._archive_reservation is not None:
            raise ValueError('one archive reservation owner required')
        self._core._archive_reservation = factory

    def reset(self, episode_id=None):
        self._core.reset(episode_id);self._revision=0;self._clock_domain=None;self._frame_watermarks={};self._current_coverage=None

    @staticmethod
    def _adapt(obs):
        # A private array-index layout, never a canonical Observation or pose.
        pose=obs.T_world_camera[[0,2,1,3],:]
        return SimpleNamespace(episode_id=obs.key.episode_id,frame_id=(obs.key.sensor_id,obs.key.frame_index),
            capture_wall_ns=obs.capture_monotonic_ns,sim_time_s=obs.sim_time_s,K=obs.K,
            T_world_camera_cv=pose,depth_m=obs.depth_m,valid_depth=obs.valid_depth,
            no_return=obs.no_return,no_return_range_m=obs.no_return_range_m)

    def update(self, observation: Observation) -> NavSnapshot:
        if not isinstance(observation,Observation):raise ValueError('Observation required')
        if self._clock_domain is not None and observation.clock_domain!=self._clock_domain:
            raise ValueError('map clock domain mismatch; reset required')
        previous=self._frame_watermarks.get(observation.key.sensor_id)
        if previous is not None and observation.key.frame_index<=previous:
            raise DuplicateFrameError('duplicate or replayed sensor frame')
        self._check_ray_budget(observation)
        delta=self._core.integrate(self._adapt(observation))
        self._frame_watermarks[observation.key.sensor_id]=observation.key.frame_index
        self._clock_domain=observation.clock_domain;self._revision+=1
        # Only measured rays can certify current-frame bootstrap. Certified
        # no-return rays in the historical map must never enter this proof.
        self._current_coverage=None
        if observation.no_return is None or not observation.no_return.any():
            coverage=self._coverage_from_votes(observation,delta.frame_votes)
            self._current_coverage=(observation.geometry_hash,coverage)
        return self._snapshot(observation)

    def _coverage_from_votes(self,obs,votes):
        """Fresh-frame classification, equivalent to a new one-frame mapper.

        Uses unaccumulated measured votes, never historical tile log odds.
        One immutable snapshot is retained; temporary dense votes are released
        after update. Occupied votes win exactly as in the selected kernel.
        """
        grid=self._core.grid;res=grid.resolution_m
        center=grid.world_to_grid(float(obs.T_world_camera[0,3]),float(obs.T_world_camera[1,3]))
        half=math.ceil(self.snapshot_radius_m/res);min_r,min_c=center[0]-half,center[1]-half
        size=2*half+1;shape=(size,size)
        states=np.full(shape,GridState.UNKNOWN,np.int8);floor=np.zeros(shape,bool);clear=np.zeros(shape,np.float32)
        rows,cols=votes.planar_free.shape
        r0,r1=max(min_r,votes.min_row),min(min_r+size,votes.min_row+rows)
        c0,c1=max(min_c,votes.min_col),min(min_c+size,votes.min_col+cols)
        if r0<r1 and c0<c1:
            src=np.s_[r0-votes.min_row:r1-votes.min_row,c0-votes.min_col:c1-votes.min_col]
            dst=np.s_[r0-min_r:r1-min_r,c0-min_c:c1-min_c]
            supported=votes.floor_hit[src]
            body_free=np.all(votes.height_free[src][:,:,1:],axis=2)
            occupied=votes.planar_hit[src]|np.any(votes.height_hit[src][:,:,1:],axis=2)
            free=votes.planar_free[src]&body_free&supported&~occupied
            floor[dst]=supported;clear[dst]=np.where(body_free,self.robot.height_m,0.)
            local=states[dst];local[free]=GridState.FREE;local[occupied]=GridState.OCCUPIED
        return NavSnapshot(obs.key.episode_id,0,obs.key,obs.capture_monotonic_ns,obs.clock_domain,
            res,(grid.origin_x_m+min_c*res,grid.origin_z_m+min_r*res),states,floor,clear,
            self.robot.geometry_id,self.floor_z_m,self.floor_datum_source,self.calibration_hash)

    def _check_ray_budget(self, obs):
        # Axial clipping alone cannot bound oblique rays from extreme intrinsics.
        # Check the actual projected box before the dense per-frame vote buffers.
        core=self._core;stride=core.sampling_stride
        vv,uu=np.mgrid[0:obs.depth_m.shape[0]:stride,0:obs.depth_m.shape[1]:stride]
        depths=obs.depth_m[::stride,::stride]
        use=obs.valid_depth[::stride,::stride] & (depths>=core.min_depth_m)&(depths<core.max_depth_m)
        if use.sum()>100_000:raise MemoryError('per-frame ray count budget exceeded')
        points=[]
        if use.any():
            rays=np.stack((uu[use],vv[use],np.ones(use.sum())),axis=1)@np.linalg.inv(obs.K).T
            rays/=rays[:,2:3]
            points.append((rays*depths[use,None])@obs.T_world_camera[:3,:3].T+obs.T_world_camera[:3,3])
        if obs.no_return is not None and obs.no_return.any():
            mask=obs.no_return[::stride,::stride]
            if mask.sum()>100_000:raise MemoryError('per-frame ray count budget exceeded')
            rays=np.stack((uu[mask],vv[mask],np.ones(mask.sum())),axis=1)@np.linalg.inv(obs.K).T
            rays/=np.linalg.norm(rays,axis=1)[:,None]
            points.append(rays@obs.T_world_camera[:3,:3].T*min(obs.no_return_range_m,core.max_depth_m)+obs.T_world_camera[:3,3])
        if points:
            points=np.vstack((obs.T_world_camera[None,:2,3],*(p[:,:2] for p in points)))
            extent=np.floor((points.max(axis=0)-np.array([core.grid.origin_x_m,core.grid.origin_z_m]))/core.grid.resolution_m)-np.floor((points.min(axis=0)-np.array([core.grid.origin_x_m,core.grid.origin_z_m]))/core.grid.resolution_m)+3
            if not np.isfinite(extent).all() or extent[0]*extent[1]>1_000_000:
                raise MemoryError('per-frame ray raster extent budget exceeded')
            vote_bytes=int(extent[0])*int(extent[1])*(3+2*core.height_bin_count)
            if vote_bytes>128*1024*1024:
                raise MemoryError('per-frame vote buffer budget exceeded')

    def _snapshot(self, obs, *, single_frame=False):
        grid=self._core.grid;res=grid.resolution_m
        center=grid.world_to_grid(float(obs.T_world_camera[0,3]),float(obs.T_world_camera[1,3]))
        half=math.ceil(self.snapshot_radius_m/res);min_r,min_c=center[0]-half,center[1]-half
        size=2*half+1;shape=(size,size)
        states=np.full(shape,GridState.UNKNOWN,np.int8);floor=np.zeros(shape,bool);clear=np.zeros(shape,np.float32)
        # Evicted data is conservative unknown until admitted through validated IO.
        for (tr,tc),tile in self._core._tiles.items():
            row,col=tr*grid.tile_size_cells,tc*grid.tile_size_cells
            r0,r1=max(row,min_r),min(row+grid.tile_size_cells,min_r+size)
            c0,c1=max(col,min_c),min(col+grid.tile_size_cells,min_c+size)
            if r0>=r1 or c0>=c1:continue
            src=np.s_[r0-row:r1-row,c0-col:c1-col];dst=np.s_[r0-min_r:r1-min_r,c0-min_c:c1-min_c]
            planar=tile.planar_log_odds[src];height=tile.height_log_odds[src]
            supported=tile.floor_support[src];floor[dst]=supported
            threshold=0. if single_frame else self._core.free_threshold
            body_free=np.all(height[:,:,1:]<threshold if single_frame else height[:,:,1:]<=threshold,axis=2)
            clear[dst]=np.where(body_free,self.robot.height_m,0.)
            occupied=(planar>=self._core.occupied_threshold)|np.any(height[:,:,1:]>=self._core.occupied_threshold,axis=2)
            free=(planar<0 if single_frame else planar<=threshold)&body_free&supported&~occupied
            local=states[dst];local[free]=GridState.FREE;local[occupied]=GridState.OCCUPIED
        return NavSnapshot(obs.key.episode_id,self._revision,obs.key,obs.capture_monotonic_ns,obs.clock_domain,
            res,(grid.origin_x_m+min_c*res,grid.origin_z_m+min_r*res),states,floor,clear,
            self.robot.geometry_id,self.floor_z_m,self.floor_datum_source,self.calibration_hash)

    @staticmethod
    def world_to_snapshot(nav, xy):
        return math.floor((xy[1]-nav.origin_xy[1])/nav.resolution_m),math.floor((xy[0]-nav.origin_xy[0])/nav.resolution_m)

    def measured_coverage(self, observation):
        """Current measured returns only; no historical/no-return floor substitution."""
        cached=self._current_coverage
        if cached is not None and observation.geometry_hash==cached[0]:return cached[1]
        from dataclasses import replace
        core=self._core
        current=NavMapper(robot=self.robot,floor_z_m=self.floor_z_m,floor_datum_source=self.floor_datum_source,
            calibration_hash=self.calibration_hash,resolution_m=core.grid.resolution_m,
            origin_xy=(core.grid.origin_x_m,core.grid.origin_z_m),tile_size_cells=core.grid.tile_size_cells,
            height_bin_m=core.height_bin_m,min_depth_m=core.min_depth_m,max_depth_m=core.max_depth_m,
            sampling_stride=core.sampling_stride,snapshot_radius_m=self.snapshot_radius_m)
        measured=replace(observation,no_return=None,no_return_range_m=None,far_plane=None,far_plane_range_m=None)
        current._check_ray_budget(measured)
        current._core.integrate(current._adapt(measured))
        return current._snapshot(measured,single_frame=True)

    def bootstrap(self, observation, *, robot_xy, yaw_rad, corridor_m, swept_margin_m=0.):
        if not math.isfinite(corridor_m) or corridor_m<0:raise ValueError('invalid bootstrap corridor')
        if not math.isfinite(swept_margin_m) or swept_margin_m<0:raise ValueError('invalid swept margin')
        if observation.modality!='depth_only' or not np.allclose(observation.T_world_camera[:3,2],(0.,0.,-1.),atol=1e-5,rtol=0):
            return BootstrapResult(False,'bootstrap_blocked',0,0,observation.key)
        if not all(math.isfinite(v) for v in (*robot_xy,yaw_rad)):raise ValueError('invalid bootstrap robot pose')
        nav=self.measured_coverage(observation)
        end=(robot_xy[0]+corridor_m*math.cos(yaw_rad),robot_xy[1]+corridor_m*math.sin(yaw_rad))
        radius=self.robot.radius_m+self.robot.margin_m+swept_margin_m
        # Bound work before enumerating capsule cells, including invalid robot
        # positions or extremely long requested corridors.
        lo=np.minimum(robot_xy,end)-radius
        hi=np.maximum(robot_xy,end)+radius
        map_hi=np.asarray(nav.origin_xy)+np.asarray(nav.states.shape[::-1])*nav.resolution_m
        if np.any(lo<=np.asarray(nav.origin_xy)) or np.any(hi>=map_hi):
            return BootstrapResult(False,'bootstrap_blocked',0,0,observation.key)
        cells=tuple(capsule_cells(nav.origin_xy,nav.resolution_m,robot_xy,end,radius))
        count=sum(0<=r<nav.states.shape[0] and 0<=c<nav.states.shape[1] and nav.states[r,c]==GridState.FREE for r,c in cells)
        ready=count==len(cells) and bool(cells)
        return BootstrapResult(ready,'bootstrap_ready' if ready else 'bootstrap_blocked',len(cells),count,observation.key)
