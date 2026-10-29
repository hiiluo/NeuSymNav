"""Synthetic composition: pinned revisions, aliases and structural edges."""
from dataclasses import replace
import pytest
from test_regions import nav
from test_membership import objects,regions,OID,ALIAS
from neusymnav.hierarchy import HierarchyComposer


def test_composer_pins_source_and_latest_does_not_starve():
    h=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=8,now_ns=200,clock_domain='clock')
    assert (h.object_revision,h.map_revision,h.region_revision,h.latest_nav_revision)==(1,1,1,8)
    assert h.source_map_age_ns==100 and h.statuses[OID]=='assigned'
    assert OID in h.nodes and ALIAS not in h.nodes
    assert any(e.kind=='in_region' and e.source_id==OID for e in h.edges)
    adjacency=[e for e in h.edges if e.kind=='region_adjacent_to']
    assert adjacency and all(e.provenance['motion_certificate'] is False for e in adjacency)
    assert {n.kind for n in h.nodes.values()}>={'building','floor','object','region'}


def test_stale_disables_membership_and_mismatch_rejected():
    c=HierarchyComposer()
    h=c.compose(objects(),nav(),regions(True),latest_nav_revision=2,now_ns=200,clock_domain='clock')
    assert h.statuses[OID]=='unavailable' and not any(e.kind=='in_region' for e in h.edges)
    with pytest.raises(ValueError,match='source map'):c.compose(objects(),nav(2),regions(),latest_nav_revision=2,now_ns=200,clock_domain='clock')
    with pytest.raises(ValueError):c.compose(objects(),nav(),regions(),latest_nav_revision=2,now_ns=200,clock_domain='wrong')


def test_places_require_measured_footprint_and_revalidate_connections():
    import numpy as np
    from neusymnav.mapping.occupancy import RobotGeometry
    c=HierarchyComposer(robot=RobotGeometry('robot',.15,1.,0.))
    n=nav()
    c.observe_place(n,(.25,.25),pose_source=n.source,capture_monotonic_ns=n.capture_monotonic_ns,clock_domain=n.clock_domain)
    c.observe_place(nav(2),(1.25,.25),pose_source=nav(2).source,capture_monotonic_ns=100,clock_domain="clock")
    r=replace(regions(),source_map_revision=2)
    h=c.compose(objects(),nav(2),r,latest_nav_revision=2,now_ns=200,clock_domain='clock')
    assert sum(node.kind=='place' for node in h.nodes.values())==2
    assert any(e.kind=='place_connected_to' and e.provenance['footprint_validated'] for e in h.edges)
    unsafe=replace(nav(3),clearance=np.zeros(n.states.shape))
    h=c.compose(objects(),unsafe,replace(r,source_map_revision=3),latest_nav_revision=3,now_ns=200,clock_domain='clock')
    assert not any(node.kind=='place' for node in h.nodes.values())
    assert not any(e.kind=='place_connected_to' for e in h.edges)


def test_place_admission_requires_nav_bound_pose_provenance():
    from neusymnav.mapping.occupancy import RobotGeometry
    c=HierarchyComposer(robot=RobotGeometry('robot',.15,1.,0.))
    with pytest.raises(ValueError,match='pose provenance'):
        c.observe_place(nav(),(.25,.25))
    with pytest.raises(ValueError,match='pose provenance'):
        c.observe_place(nav(),(.25,.25),pose_source=nav(2).source,capture_monotonic_ns=100,clock_domain='clock')


def test_composer_rejects_namespace_collision_and_input_regression():
    from neusymnav.contracts import Region,RegionSnapshot
    r=RegionSnapshot('e',1,1,'f',{'floor:f':Region('floor:f',regions().regions['r1'].polygon)},False)
    with pytest.raises(ValueError,match='namespace'):HierarchyComposer().compose(objects(),nav(),r,latest_nav_revision=1,now_ns=200,clock_domain='clock')
    c=HierarchyComposer();c.compose(objects(),nav(),regions(),latest_nav_revision=1,now_ns=200,clock_domain='clock')
    with pytest.raises(ValueError,match='backward'):
        c.compose(replace(objects(),revision=0,objects={},aliases={}),nav(),regions(),latest_nav_revision=1,now_ns=200,clock_domain='clock')
