import numpy as np
import pytest
from dataclasses import replace
from neusymnav.regions import geometry


def test_room_center_is_area_centroid_not_vertex_average():
    polygon=np.array([[0.,0.],[4.,0.],[4.,2.],[0.,2.],[0.,1.]])
    assert geometry.room_center(polygon)==pytest.approx((2.,1.))
    assert geometry.room_center(polygon[::-1])==pytest.approx((2.,1.))


def test_concave_room_node_stays_inside_instead_of_empty_courtyard():
    polygon=np.array([[0.,0.],[6.,0.],[6.,6.],[4.,6.],[4.,2.],[2.,2.],[2.,6.],[0.,6.]])
    center=geometry.room_center(polygon)
    assert geometry.ring_covers(center,tuple(map(tuple,polygon)))
    assert center==geometry.room_center(polygon)
    # U legs and bottom are2m thick; keep a useful interior anchor.
    assert min(geometry._distance_segment(center,a,polygon[(i+1)%len(polygon)]) for i,a in enumerate(polygon))>.9


@pytest.mark.parametrize('polygon',[[[0,0],[1,0]],[[0,0],[1,0],[2,0]],[[0,0],[1,float('nan')],[0,1]],[[0,0],[1,1],[0,1],[1,0]]])
def test_invalid_room_center_not_published(polygon):
    with pytest.raises(ValueError):geometry.room_center(polygon)


def test_room_center_tracks_same_region_id_new_geometry_in_composer():
    from test_hierarchy import objects,nav,regions
    from neusymnav.hierarchy.composer import HierarchyComposer
    from neusymnav.contracts import Region
    c=HierarchyComposer();r=regions();first=c.compose(objects(),nav(),r,latest_nav_revision=1,now_ns=200,clock_domain='clock')
    rid=next(iter(r.regions));before=first.nodes[rid].attributes['center_xy']
    polygon=r.regions[rid].polygon+np.array([2.,0.]);updated=replace(r,revision=2,regions={rid:Region(rid,polygon)})
    second=c.compose(objects(),nav(),updated,latest_nav_revision=1,now_ns=200,clock_domain='clock')
    assert np.allclose(second.nodes[rid].attributes['center_xy'],np.asarray(before)+[2.,0.])
    assert second.nodes[rid].attributes['center_method']=='area_centroid_or_interior_clearance_v1'
