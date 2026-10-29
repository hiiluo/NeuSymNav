"""Synthetic polygon membership fixtures, independent of native extraction."""
import numpy as np
from neusymnav.contracts import ObjectState,ObjectSnapshot,FrameKey,Region,RegionSnapshot
from neusymnav.hierarchy import MembershipResolver

OID='00000000-0000-0000-0000-000000000001'
ALIAS='00000000-0000-0000-0000-000000000002'

def objects(bounds=((.2,.2,0.),(.8,.8,1.)), floor='f', footprint=None):
    bounds=np.array(bounds,float)
    o=ObjectState(OID,floor,bounds.mean(0),bounds,'active',('evidence',),1,FrameKey('e','rgbd',0),10,20,'clock',footprint_xy=footprint)
    return ObjectSnapshot('e',1,o.source,{OID:o},{ALIAS:OID})

def regions(stale=False):
    return RegionSnapshot('e',1,1,'f',{'r1':Region('r1',np.array([[0.,0.],[1.,0.],[1.,1.],[0.,1.]]),adjacency=('r2',)),
        'r2':Region('r2',np.array([[1.,0.],[2.,0.],[2.,1.],[1.,1.]]),adjacency=('r1',))},stale)

def test_inside_cross_boundary_outside_and_floor():
    r=MembershipResolver()
    a=r.resolve(objects(),regions())[0]
    assert (a.object_id,a.region_id,a.status)==(OID,'r1','assigned')
    a=r.resolve(objects(((.8,.2,0.),(1.2,.8,1.))),regions())[0]
    assert a.status=='ambiguous' and a.candidates==('r1','r2')
    assert r.resolve(objects(((3.,3.,0.),(4.,4.,1.))),regions())[0].status=='unassigned'
    assert r.resolve(objects(floor='other'),regions())[0].status=='unavailable'
    assert r.resolve(objects(),regions(True))[0].status=='unavailable'

def test_touching_boundary_and_polygon_footprint():
    r=MembershipResolver()
    assert r.resolve(objects(((0.,.2,0.),(.8,.8,1.))),regions())[0].status=='ambiguous'
    # Explicit narrow footprint beats its loose AABB, while actual footprint crossing does not.
    a=r.resolve(objects(((.2,.2,0.),(1.2,.8,1.)),footprint=np.array([[.2,.2],[.8,.2],[.8,.8],[.2,.8]])),regions())[0]
    assert a.status=='assigned'


def test_concave_region_and_invalid_footprint_fail_closed():
    from dataclasses import replace
    # Concave U notch contains no object vertices but enters its interior.
    concave=Region('u',np.array([[0.,0.],[3.,0.],[3.,3.],[2.,3.],[2.,1.],[1.,1.],[1.,3.],[0.,3.]]))
    r=RegionSnapshot('e',1,1,'f',{'u':concave},False)
    a=MembershipResolver().resolve(objects(((.5,.5,0.),(2.5,2.5,1.))),r)[0]
    assert a.status=='ambiguous'
    bow=np.array([[.2,.2],[.8,.8],[.2,.8],[.8,.2]])
    assert MembershipResolver().resolve(objects(footprint=bow),regions())[0].status=='unavailable'


def test_actual_polygon_without_overlap_is_unassigned():
    # AABB overlaps r1, triangle lies wholly beyond its upper-right corner.
    tri=np.array([[.9,1.2],[1.2,.9],[1.2,1.2]])
    assert MembershipResolver().resolve(objects(((.9,.9,0.),(1.2,1.2,1.)),footprint=tri),RegionSnapshot('e',1,1,'f',{'r1':Region('r1',regions().regions['r1'].polygon)},False))[0].status=='unassigned'


def test_unmodified_unified_source_membership_parity_fixture():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/regions/source-membership-parity-v1.json').read_text())
    for case in fixture['steps']:
        x0,y0,x1,y1=case['bounds']
        actual=MembershipResolver().resolve(objects(((x0,y0,0.),(x1,y1,1.))),regions())[0]
        assert (actual.status,actual.region_id,actual.candidates)==(case['status'],case['region_id'],tuple(case['candidates']))
