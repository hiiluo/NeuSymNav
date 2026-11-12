"""Rebuild M1–M5 is the only room source in its hierarchy profile."""
from dataclasses import replace

import numpy as np

from neusymnav.contracts import FrameKey, Region, RegionSnapshot, RoomMapSnapshot, RoomPipelinePublication, dumps, loads
from neusymnav.hierarchy import HierarchyComposer
from test_membership import ALIAS, OID, objects, regions
from test_regions import nav


def _rebuild_publication(*, latest_revision=1, stale=False, episode='e'):
    source_map=RoomMapSnapshot(episode,f'rebuild-m3:{episode}',latest_revision,
        FrameKey(episode,'rgbd',latest_revision-1),100+latest_revision,'clock','cal-v1','a'*64,
        .05,(0.,0.),np.full((4,4),-1,dtype=np.int8),
        np.full((4,4),np.nan),np.full((4,4),np.nan),np.zeros((4,4),bool),np.zeros((4,4),bool),
        latest_revision,latest_revision,'a'*64,'b'*64,'c'*64,'d'*64)
    accepted_map=source_map
    if latest_revision>1:
        accepted_map=replace(source_map,revision=1,m2_revision=1,m3_revision=1,
            source=FrameKey(episode,'rgbd',0),capture_monotonic_ns=101)
    raw=RegionSnapshot(episode,5,1,'f',{
        'm5-raw-1':Region('m5-raw-1',np.asarray([[0.,0.],[2.,0.],[2.,2.],[0.,2.]]))
    },stale)
    return RoomPipelinePublication(episode,f'rebuild-m3:{episode}',latest_revision,source_map,
        1,raw,5,stale,False,accepted_map=accepted_map)


def test_rebuild_m5_regions_and_object_membership_are_the_only_room_projection():
    publication=_rebuild_publication()
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=1,
        now_ns=200,clock_domain='clock',room_pipeline=publication)
    source_nodes=[node for node in hierarchy.nodes.values() if node.kind=='source_region']
    assert len(source_nodes)==1
    source_node=source_nodes[0]
    assert source_node.attributes['map_domain_id']=='rebuild-m3:e'
    assert source_node.attributes['source_map_revision']==1
    assert not any(node.kind=='region' for node in hierarchy.nodes.values())
    assert not any('stable_room_' in key or key=='room_debug'
                   for node in hierarchy.nodes.values() for key in node.attributes)
    assert hierarchy.nodes[OID].attributes['membership_status']=='assigned'
    assert hierarchy.nodes[OID].attributes['rebuild_region_membership_id']=='m5-raw-1'
    assert not any(edge.kind=='in_region' for edge in hierarchy.edges)
    assert any(edge.kind=='in_source_region' and edge.status=='assigned'
               and edge.target_id==source_node.node_id for edge in hierarchy.edges)
    source_edge=next(edge for edge in hierarchy.edges if edge.kind=='in_source_region')
    assert source_edge.source_domain_id=='rebuild-m3:e'
    assert source_edge.source_map_revision==1 and source_edge.region_revision==5
    assert hierarchy.statuses['rebuild_regions']=='assigned'
    restored=loads(dumps(hierarchy))
    restored_source_edge=next(edge for edge in restored.edges if edge.kind=='in_source_region')
    assert restored_source_edge.source_domain_id=='rebuild-m3:e'
    assert restored_source_edge.source_map_revision==1 and restored_source_edge.region_revision==5
    assert restored.nodes[OID].attributes['rebuild_region_membership_id']=='m5-raw-1'
    assert ALIAS not in restored.nodes


def test_stale_m5_regions_are_visible_but_never_assign_membership():
    publication=_rebuild_publication(latest_revision=2,stale=True)
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=1,
        now_ns=200,clock_domain='clock',room_pipeline=publication)
    source_nodes=[node for node in hierarchy.nodes.values() if node.kind=='source_region']
    assert len(source_nodes)==1 and source_nodes[0].attributes['stale']
    assert not any(node.kind=='region' for node in hierarchy.nodes.values())
    assert hierarchy.nodes[OID].attributes['membership_status']=='unavailable'
    assert hierarchy.nodes[OID].attributes['rebuild_region_membership_status']=='unavailable'
    assert not any(edge.kind in {'in_region','in_source_region'} for edge in hierarchy.edges)
    assert hierarchy.statuses['rebuild_regions']=='unavailable'


def test_display_requires_m5_source_hierarchy_to_match_room_publication():
    from types import SimpleNamespace
    import pytest
    from neusymnav.visualization.publisher import DisplayPublisher,DisplaySources
    publication=_rebuild_publication()
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=1,
        now_ns=200,clock_domain='clock',room_pipeline=publication)
    metrics=SimpleNamespace(source_age_ns={'room_map':1,'map':100,'objects':180})
    sources=DisplaySources(nav=nav(),objects=objects(),room_pipeline=publication)
    DisplayPublisher._validate_sources(hierarchy,metrics,sources)
    wrong_map=replace(publication.latest_map,map_domain_id='other-domain')
    wrong_accepted=replace(publication.accepted_map,map_domain_id='other-domain')
    wrong=replace(publication,map_domain_id='other-domain',latest_map=wrong_map,accepted_map=wrong_accepted)
    with pytest.raises(ValueError,match='source-region hierarchy binding mismatch'):
        DisplayPublisher._validate_sources(hierarchy,metrics,
            DisplaySources(nav=nav(),objects=objects(),room_pipeline=wrong))


def test_hierarchy_view_parents_objects_to_rebuild_m5_region():
    from types import SimpleNamespace
    from neusymnav.visualization.hierarchy_view import hierarchy_links,hierarchy_rows
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=1,
        now_ns=200,clock_domain='clock',room_pipeline=_rebuild_publication())
    envelope=SimpleNamespace(hierarchy=hierarchy,
        sources=SimpleNamespace(verification=None,objects=objects()))
    rows=hierarchy_rows(envelope)
    source_row=next(row for row in rows if row.kind=='source_region')
    object_row=next(row for row in rows if row.node_id==OID)
    assert 'Rebuild M5 region m5-raw-1' in source_row.label
    assert 'Rebuild M5 m5-raw-1' in object_row.label
    assert object_row.parent_id==source_row.node_id and object_row.status=='assigned'
    assert (OID,source_row.node_id,'in_source_region') in hierarchy_links(envelope)


def test_non_m5_profile_keeps_legacy_region_membership_without_roomowner_fields():
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=1,
        now_ns=200,clock_domain='clock')
    assert {node.node_id for node in hierarchy.nodes.values() if node.kind=='region'}=={'r1','r2'}
    assert hierarchy.nodes[OID].attributes['membership_status']=='assigned'
    assert any(edge.kind=='in_region' and edge.source_id==OID for edge in hierarchy.edges)
    assert not any('stable_room_' in key or key=='room_debug'
                   for node in hierarchy.nodes.values() for key in node.attributes)
