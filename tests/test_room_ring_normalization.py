"""Remove only zero-area wire spikes; non-simple room interiors still reject."""
import pytest
from neusymnav.regions import geometry


def test_exact_collinear_backtracking_spike_can_publish_valid_room():
    raw=((0.,0.),(4.,0.),(4.,4.),(2.,4.),(2.,5.),(2.,4.5),(1.,4.),(0.,4.))
    normalized,removed=geometry.normalize_room_ring(raw)
    assert removed==1
    assert normalized==((0.,0.),(4.,0.),(4.,4.),(2.,4.),(2.,4.5),(1.,4.),(0.,4.))
    assert geometry.valid_ring(normalized)
    from neusymnav.regions._types import ring_area
    assert ring_area(normalized)==ring_area(raw)


def test_real_crossing_not_repaired_or_accepted():
    raw=((0.,0.),(4.,4.),(0.,4.),(4.,0.))
    normalized,removed=geometry.normalize_room_ring(raw)
    assert removed==0 and normalized==raw
    assert not geometry.valid_ring(normalized)


def test_near_collinear_geometry_is_not_rounded_into_new_polygon():
    raw=((0.,0.),(4.,0.),(4.,4.),(2.,4.),(2.+1e-8,5.),(2.,4.5),(1.,4.),(0.,4.))
    assert geometry.normalize_room_ring(raw)==(raw,0)


def test_closed_and_duplicate_points_are_zero_length_not_fake_room_area():
    raw=((0.,0.),(4.,0.),(4.,0.),(4.,4.),(0.,4.),(0.,0.))
    normalized,removed=geometry.normalize_room_ring(raw)
    assert normalized==((0.,0.),(4.,0.),(4.,4.),(0.,4.)) and removed==2


def test_normalized_geometry_enters_real_client_with_provenance(monkeypatch,tmp_path):
    import numpy as np
    from neusymnav.contracts import RegionGrid
    from neusymnav.regions.dude_client import DuDeWorkerClient,DuDeConfig
    import threading
    client=object.__new__(DuDeWorkerClient);client.config=DuDeConfig();client._lock=threading.Lock()
    raw=[[0.,0.],[4.,0.],[4.,4.],[2.,4.],[2.,5.],[2.,4.5],[1.,4.],[0.,4.]]
    client._exchange=lambda request:dict(protocol_status='ok',status='success',input_revision=1,request_id='revision-1',frame_id='canonical_world_z_up:e',units='meters',coordinate_convention='world_x=origin_x+col*resolution; world_y=origin_y+row*resolution',diagnostics={'preprocessing_policy':'extended_unknown_boundary'},regions=[dict(raw_id=0,outer=raw,centroid_xy=[2.,2.],area_m2=16.25,adjacent_raw_ids=[],holes_supported=False,holes=[])])
    client._fail=lambda reason:pytest.fail('validschema zeroareaspike mustnotpoisonworker')
    response,observations=client.integrate(RegionGrid('e',1,.1,(0.,0.),np.zeros((45,45),np.int8)))
    assert len(observations)==1 and geometry.valid_ring(observations[0].polygon.outer)
    assert observations[0].metadata['ring_normalization']=='exact_collinear_zero_area_v1'
    assert observations[0].metadata['removed_vertices']==1
