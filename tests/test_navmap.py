"""P03 CPU measured-ray mapping gates; no simulator or semantic ground truth."""
from dataclasses import replace
import numpy as np
import pytest
from neusymnav.contracts import FrameKey, Observation, GridState
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry, DuplicateFrameError


def geometry(radius=.10, tolerance=.05):
    return RobotGeometry('cylinder-v1', radius, 1., .0, tolerance)


def down(index=0, *, valid=True, size=81, focal=40., x=0., stamp=1_000_000_000, domain='host_monotonic:test'):
    pose = np.eye(4)
    pose[:3,:3] = np.diag([1.,-1.,-1.])
    pose[:3,3] = [x,0,5.]
    return Observation(FrameKey('ep','navigation',index),stamp,domain,float(index),
        np.zeros((size,size,3),np.uint8),np.full((size,size),2,np.float32),
        np.full((size,size),valid,bool),np.array([[focal,0,size//2],[0,focal,size//2],[0,0,1.]],float),
        pose,'down-calibration-v1',1,'depth_only')


def mapper(tmp_path, **kwargs):
    return NavMapper(robot=geometry(tolerance=kwargs.get('height_bin_m',.05)), floor_z_m=3., floor_datum_source='scene-calibration:v1',
        calibration_hash='a'*64,resolution_m=.1, tile_size_cells=16, sampling_stride=1,
        snapshot_radius_m=3.,tile_archive_dir=tmp_path,**kwargs)


def test_measured_floor_nonzero_and_immutable_publication(tmp_path):
    m=mapper(tmp_path)
    a=m.update(down())
    assert not np.any(a.states==GridState.FREE)  # source log-odds threshold needs unique frames
    b=m.update(down(1))
    r,c = m.world_to_snapshot(b, (.05,.05))
    assert b.floor_z_m==3 and b.floor_datum_source=='scene-calibration:v1'
    assert b.states[r,c]==GridState.FREE and b.floor_support[r,c] and b.clearance[r,c]>=1
    assert not b.states.flags.writeable and np.all(a.states!=GridState.FREE)
    with pytest.raises(DuplicateFrameError): m.update(down(1))


def test_invalid_unknown_and_certified_no_return_cannot_seed_floor(tmp_path):
    m=mapper(tmp_path)
    obs=down(valid=False)
    assert np.all(m.update(obs).states==GridState.UNKNOWN)
    certified=replace(down(1,valid=False),no_return=np.ones((81,81),bool),no_return_range_m=2.)
    nav=m.update(certified)
    assert not nav.floor_support.any() and np.all(nav.states!=GridState.FREE)


def test_one_vote_per_frame_and_occupied_wins(tmp_path):
    from neusymnav.mapping._raycast_kernel import collect_ray_votes
    rays=np.array([[.2,.5,.0]]*100+[[.4,.5,.0]]) # private x,height,planar-y indexing
    votes=collect_ray_votes(rays,np.array([0.,.5,0.]),resolution_m=.1,origin_x_m=0.,origin_z_m=0.,floor_y_m=0.,robot_height_m=1.,height_bin_m=.2,ray_step_m=.05,backend='python')
    assert not np.any(votes.planar_free & votes.planar_hit)
    assert not np.any(votes.height_free & votes.height_hit)
    m=mapper(tmp_path,height_bin_m=.2)  # exact source-oracle bin profile
    core=m._core
    core._integrate_votes(votes)
    assert core.log_odds_at(0,2)==pytest.approx(core.hit_log_odds)
    assert core.log_odds_at(0,1)==pytest.approx(core.free_log_odds)


def test_bootstrap_requires_measured_footprint_and_forward_corridor(tmp_path):
    m=mapper(tmp_path)
    assert m.bootstrap(down(),robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.3).ready
    assert not m.bootstrap(down(valid=False),robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.3).ready
    narrow=m.bootstrap(down(size=9,focal=150.),robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.3)
    assert not narrow.ready and narrow.reason=='bootstrap_blocked'


def cell_vote(row,col, *, occupied=False):
    from neusymnav.mapping._raycast_kernel import RaycastVotes
    free=np.full((1,1),not occupied,bool);hit=~free
    return RaycastVotes(row,col,free,hit,np.ones((1,1),bool),
        np.repeat(free[:,:,None],5,axis=2),np.repeat(hit[:,:,None],5,axis=2))


def test_eviction_restores_exact_odds_and_archive_failure_cannot_clear(tmp_path):
    from neusymnav.mapping.tiles import TileArchiveError
    m=mapper(tmp_path,max_active_tiles=1,height_bin_m=.2)
    core=m._core
    core._integrate_votes(cell_vote(0,0,occupied=True))
    old=core.log_odds_at(0,0)
    core._integrate_votes(cell_vote(16,0))
    assert core.cell_state(0,0).value=='unknown' # evicted never becomes free
    assert core.archived_tile_keys==((0,0),)
    core._integrate_votes(cell_vote(0,0,occupied=True))
    assert core.log_odds_at(0,0)==pytest.approx(old*2)
    core._integrate_votes(cell_vote(16,0))
    path=core._tile_archive.path_for((0,0))
    with np.load(path,allow_pickle=False) as payload:
        data={key:payload[key].copy() for key in payload.files}
    data['planar_log_odds'][0,0]=-4 # same valid dtype/range, invalid digest
    with path.open('wb') as stream:np.savez_compressed(stream,**data)
    with pytest.raises(TileArchiveError,match='checksum'):core._integrate_votes(cell_vote(0,0))
    assert core.active_tile_keys==((1,0),) and core.cell_state(0,0).value=='unknown'


def test_episode_reset_empty_and_sensor_identity_independent(tmp_path):
    m=mapper(tmp_path)
    m.update(down());m.update(replace(down(),key=FrameKey('ep','primary',0)))
    with pytest.raises(ValueError,match='different episode'):
        m.update(replace(down(1),key=FrameKey('new','navigation',1)))
    m.reset('new')
    n=m.update(replace(down(valid=False),key=FrameKey('new','navigation',0)))
    assert np.all(n.states==GridState.UNKNOWN) and not n.floor_support.any()


def test_body_clearance_obstacle_blocks_bootstrap(tmp_path):
    m=mapper(tmp_path)
    # Raised measured surface is body-height evidence, never a floor substitute.
    obs=down()
    obstacle=replace(obs,depth_m=np.full(obs.depth_m.shape,1.5,np.float32))
    assert not m.bootstrap(obstacle,robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.3).ready


def test_bootstrap_requires_navigation_depth_orientation(tmp_path):
    m=mapper(tmp_path)
    assert not m.bootstrap(replace(down(),modality='rgbd'),robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.3).ready


def test_vote_bin_mismatch_rejected_before_tile_mutation(tmp_path):
    m=mapper(tmp_path)
    with pytest.raises(ValueError,match='vote.*shape'):
        m._core._integrate_votes(cell_vote(0,0))
    assert m._core.active_tile_keys==()


@pytest.mark.parametrize('height,floor_hit,obstacle_hit',[(.049,True,False),(.05,True,True),(.051,False,True)])
def test_explicit_near_ground_threshold(height,floor_hit,obstacle_hit):
    from neusymnav.mapping._raycast_kernel import collect_ray_votes
    votes=collect_ray_votes(np.array([[0.,height,0.]]),np.array([0.,1.5,0.]),
        resolution_m=.1,origin_x_m=0.,origin_z_m=0.,floor_y_m=0.,robot_height_m=1.,
        height_bin_m=.05,ray_step_m=.025,backend='python')
    assert votes.floor_hit.any()==floor_hit
    assert votes.planar_hit.any()==obstacle_hit
    assert not np.any(votes.planar_free & votes.planar_hit)


def test_teleport_snapshot_stays_bounded_and_unknown(tmp_path):
    m=mapper(tmp_path,max_active_tiles=100)
    m.update(down());m.update(down(1))
    nav=m.update(down(2,x=1_000_000.,valid=False))
    assert nav.states.shape==(61,61)
    assert np.all(nav.states==GridState.UNKNOWN)


def test_extreme_intrinsics_rejected_before_dense_ray_allocation(tmp_path):
    m=mapper(tmp_path)
    with pytest.raises(MemoryError,match='raster extent'):
        m.update(down(size=9,focal=.0001))
    assert m._revision==0 and m._core.active_tile_keys==()


def test_extreme_height_profile_rejected_before_vote_buffer_allocation(tmp_path):
    m=mapper(tmp_path,height_bin_m=.00001)
    with pytest.raises(MemoryError,match='vote buffer'):
        m._check_ray_budget(down())
