from dataclasses import replace
import numpy as np
import pytest
from neusymnav.contracts import FrameKey, Observation
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry
from neusymnav.mapping.overview import build_overview


def observation(i, x=0., valid=True):
    pose=np.eye(4); pose[:3,:3]=np.diag([1.,-1.,-1.]); pose[:3,3]=[x,0,2.]
    return Observation(FrameKey('ep','nav',i),1_000_000_000+i,'host:test',float(i),
        np.zeros((21,21,3),np.uint8),np.full((21,21),2,np.float32),np.full((21,21),valid,bool),
        np.array([[10.,0,10],[0,10.,10],[0,0,1.]]),pose,'cal',1,'depth_only')


def value(view,x,y=0.):
    return view.states[int(np.floor((y-view.origin_xy[1])/view.resolution_m)),int(np.floor((x-view.origin_xy[0])/view.resolution_m))]


def test_global_history_survives_movement_eviction_and_reset(tmp_path):
    m=NavMapper(robot=RobotGeometry('r',.1,1.),floor_z_m=0.,floor_datum_source='fixture',calibration_hash='a'*64,
        resolution_m=.1,tile_size_cells=16,sampling_stride=1,snapshot_radius_m=1.,tile_archive_dir=tmp_path,max_active_tiles=16)
    m.update(observation(0)); m.update(observation(1)); old=m.overview_tiles(); first=build_overview(old)
    m.update(observation(2,10.)); nav=m.update(observation(3,10.)); view=build_overview(m.overview_tiles())
    assert view.source_nav is nav and value(view,0.05)==0 and value(view,10.05)==0 and value(view,5.05)==-1
    assert value(build_overview(old),.05)==0 and np.array_equal(first.states,build_overview(old).states)
    assert not view.states.flags.writeable
    m.reset('ep'); m.update(observation(0,valid=False)); assert np.all(build_overview(m.overview_tiles()).states==-1)


def test_coarse_cells_are_conservative_and_bounded(tmp_path):
    m=NavMapper(robot=RobotGeometry('r',.1,1.),floor_z_m=0.,floor_datum_source='fixture',calibration_hash='a'*64,
        resolution_m=.1,tile_size_cells=16,sampling_stride=1,snapshot_radius_m=1.,tile_archive_dir=tmp_path)
    m.update(observation(0)); m.update(observation(1)); m.update(observation(2,10.)); m.update(observation(3,10.))
    view=build_overview(m.overview_tiles(),max_cells=16)
    assert view.states.size<=16 and view.resolution_m>.1 and np.any(view.states==-1)


def test_dirty_cell_corrections_and_conservative_coarsening(tmp_path):
    from types import SimpleNamespace
    from neusymnav.mapping.overview import update_tiles
    m=NavMapper(robot=RobotGeometry('r',.1,1.),floor_z_m=0.,floor_datum_source='fixture',calibration_hash='a'*64,
        resolution_m=.1,tile_size_cells=16,sampling_stride=1,snapshot_radius_m=1.,tile_archive_dir=tmp_path)
    nav=m.update(observation(0,valid=False)); grid=m._core.grid
    def cells(rows,cols,planar):
        return SimpleNamespace(rows=np.array(rows),cols=np.array(cols),planar_log_odds=np.array(planar),
            height_log_odds=np.full((len(rows),2),-2.),floor_supported=np.ones(len(rows),bool))
    initial=update_tiles(None,nav,grid,cells([0,0,1,1,0],[0,1,0,1,4],[-2,-2,-2,-2,2]),-1,1)
    coarse=build_overview(initial,max_cells=3)
    assert coarse.resolution_m==pytest.approx(.2)
    assert coarse.states.tolist()==[[0,-1,100]]
    changed=update_tiles(initial,nav,grid,cells([0],[0],[0]),-1,1)
    assert build_overview(changed,max_cells=3).states.tolist()==[[-1,-1,100]]
    assert build_overview(initial,max_cells=3).states.tolist()==[[0,-1,100]]
    capped=update_tiles(None,nav,grid,cells([0,0],[0,16],[-2,-2]),-1,1,max_tiles=1)
    assert not capped.complete and not build_overview(capped).complete
    empty=update_tiles(None,nav,grid,cells([0,0],[0,16],[0,-2]),-1,1,max_tiles=1)
    assert empty.complete and len(empty.tiles)==1 and value(build_overview(empty),1.65,.05)==0


def test_every_dirty_cell_matches_canonical_classification(tmp_path):
    m=NavMapper(robot=RobotGeometry('r',.1,1.),floor_z_m=0.,floor_datum_source='fixture',calibration_hash='a'*64,
        resolution_m=.1,tile_size_cells=16,sampling_stride=1,snapshot_radius_m=1.,tile_archive_dir=tmp_path)
    for i,x in enumerate((0.,0.,10.,10.)):
        m.update(observation(i,x))
        cells=m._core.snapshot()._cell_arrays; overview=m.overview_tiles()
        for row,col,p,h,f in zip(cells.rows,cells.cols,cells.planar_log_odds,cells.height_log_odds,cells.floor_supported):
            occupied=p>=m._core.occupied_threshold or np.any(h[1:]>=m._core.occupied_threshold)
            free=p<=m._core.free_threshold and np.all(h[1:]<=m._core.free_threshold) and f and not occupied
            tile=overview.tiles.get((row//16,col//16))
            actual=-1 if tile is None else tile[row%16,col%16]
            assert actual==(100 if occupied else 0 if free else -1)


def test_overview_failure_keeps_old_source_and_marks_later_history_incomplete(tmp_path, monkeypatch):
    import neusymnav.mapping.overview as module
    m=NavMapper(robot=RobotGeometry('r',.1,1.),floor_z_m=0.,floor_datum_source='fixture',calibration_hash='a'*64,
        resolution_m=.1,tile_size_cells=16,sampling_stride=1,snapshot_radius_m=1.,tile_archive_dir=tmp_path)
    first=m.update(observation(0)); old=m.overview_tiles(); update=module.update_tiles
    def fail(*args,**kwargs): raise RuntimeError('overview failure')
    monkeypatch.setattr(module,'update_tiles',fail)
    second=m.update(observation(1))
    assert second.revision>first.revision and m.overview_tiles() is old and old.source_nav is first
    assert isinstance(m.overview_error,RuntimeError)
    monkeypatch.setattr(module,'update_tiles',update)
    m.update(observation(2)); assert not m.overview_tiles().complete
