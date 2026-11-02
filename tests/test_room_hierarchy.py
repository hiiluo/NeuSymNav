"""Stable-room projection into the compatible hierarchy region lane."""
from dataclasses import replace
import json

import numpy as np
from neusymnav.contracts import ObjectSnapshot, Region, RegionSnapshot
from neusymnav.contracts import FrameKey, RoomMapSnapshot, RoomPipelinePublication, dumps, loads
from neusymnav.hierarchy import HierarchyComposer
from neusymnav.rooms.owner import RoomPublication, RoomRecord
from test_membership import ALIAS, OID, objects, regions
from test_regions import nav


def _debug(snapshot):
    floor = next(node for node in snapshot.nodes.values() if node.kind == "floor")
    return floor.attributes["room_debug"]


def _rebuild_publication(*, latest_revision=1, stale=False):
    from dataclasses import replace
    source_map=RoomMapSnapshot('e','rebuild-m3:e',latest_revision,
        FrameKey('e','rgbd',latest_revision-1),100+latest_revision,'clock','cal-v1','a'*64,
        .05,(0.,0.),np.full((4,4),-1,dtype=np.int8),
        np.full((4,4),np.nan),np.full((4,4),np.nan),np.zeros((4,4),bool),np.zeros((4,4),bool),
        latest_revision,latest_revision,'a'*64,'b'*64,'c'*64,'d'*64)
    accepted_map=source_map
    if latest_revision>1:
        accepted_map=replace(source_map,revision=1,m2_revision=1,m3_revision=1,
            source=FrameKey('e','rgbd',0),capture_monotonic_ns=101)
    raw=RegionSnapshot('e',5,1,'f',{
        'm5-raw-1':Region('m5-raw-1',np.asarray([[0.,0.],[2.,0.],[2.,2.],[0.,2.]]))
    },stale)
    return RoomPipelinePublication('e','rebuild-m3:e',latest_revision,source_map,
        1,raw,5,stale,False,accepted_map=accepted_map)


def test_room_publication_is_debug_projection_and_repeat_is_idempotent():
    composer = HierarchyComposer()
    first = composer.compose(objects(), nav(), regions(), latest_nav_revision=1,
                              now_ns=200, clock_domain="clock")
    first_debug = _debug(first)

    assert first_debug["episode_id"] == "e"
    assert first_debug["source_map_revision"] == 1
    assert first_debug["stale"] is False
    assert first_debug["rooms"]
    json.dumps(composer._room_publication.to_debug(), allow_nan=False)
    assert all(room["status"] in {"tentative", "confirmed", "disputed", "retired"}
               for room in first_debug["rooms"])
    assert {node.kind for node in first.nodes.values()} >= {"floor", "region", "object"}
    assert not any(node.kind == "room" for node in first.nodes.values())
    assert OID in first.nodes and ALIAS not in first.nodes

    # Refreshing hierarchy publication age/latest nav over the same immutable
    # room sources does not add room support or duplicate event evidence.
    second = composer.compose(objects(), nav(), regions(), latest_nav_revision=3,
                              now_ns=250, clock_domain="clock")
    second_debug = _debug(second)
    assert second_debug == first_debug
    assert [(r["room_id"], r["support_count"]) for r in second_debug["rooms"]] == [
        (r["room_id"], r["support_count"]) for r in first_debug["rooms"]
    ]


def test_rebuild_regions_and_membership_join_hierarchy_in_independent_domain():
    publication=_rebuild_publication()
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),
        latest_nav_revision=1,now_ns=200,clock_domain='clock',room_pipeline=publication)
    source_nodes=[node for node in hierarchy.nodes.values() if node.kind=='source_region']
    assert len(source_nodes)==1
    source_node=source_nodes[0]
    assert source_node.attributes['map_domain_id']=='rebuild-m3:e'
    assert source_node.attributes['source_map_revision']==1
    assert hierarchy.nodes[OID].attributes['rebuild_region_membership_status']=='assigned'
    assert hierarchy.nodes[OID].attributes['rebuild_region_membership_id']=='m5-raw-1'
    assert any(edge.kind=='in_source_region' and edge.status=='assigned'
               and edge.target_id==source_node.node_id for edge in hierarchy.edges)
    source_edge=next(edge for edge in hierarchy.edges if edge.kind=='in_source_region')
    assert source_edge.source_domain_id=='rebuild-m3:e'
    assert source_edge.source_map_revision==1 and source_edge.region_revision==5
    assert any(edge.kind=='in_region' and edge.source_id==OID for edge in hierarchy.edges)
    assert hierarchy.statuses['rebuild_regions']=='assigned'
    restored=loads(dumps(hierarchy))
    restored_source_edge=next(edge for edge in restored.edges if edge.kind=='in_source_region')
    assert restored_source_edge.source_domain_id=='rebuild-m3:e'
    assert restored_source_edge.source_map_revision==1 and restored_source_edge.region_revision==5
    assert restored.nodes[OID].attributes['rebuild_region_membership_id']=='m5-raw-1'


def test_stale_rebuild_regions_are_visible_but_never_assign_membership():
    publication=_rebuild_publication(latest_revision=2,stale=True)
    hierarchy=HierarchyComposer().compose(objects(),nav(),regions(),
        latest_nav_revision=1,now_ns=200,clock_domain='clock',room_pipeline=publication)
    source_nodes=[node for node in hierarchy.nodes.values() if node.kind=='source_region']
    assert len(source_nodes)==1 and source_nodes[0].attributes['stale']
    assert hierarchy.nodes[OID].attributes['rebuild_region_membership_status']=='unavailable'
    assert not any(edge.kind=='in_source_region' for edge in hierarchy.edges)
    assert hierarchy.statuses['rebuild_regions']=='unavailable'


def test_display_requires_source_region_hierarchy_to_match_room_publication():
    from dataclasses import replace
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


def test_hierarchy_view_lists_rebuild_regions_and_source_membership():
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
    assert (OID,source_row.node_id,'in_source_region') in hierarchy_links(envelope)


def test_stale_room_source_keeps_raw_regions_without_new_assignment():
    composer = HierarchyComposer()
    accepted = composer.compose(objects(), nav(), regions(), latest_nav_revision=1,
                                now_ns=200, clock_domain="clock")
    assert _debug(accepted)["rooms"]

    stale_regions = replace(regions(stale=True), revision=2)
    stale = composer.compose(objects(), nav(), stale_regions, latest_nav_revision=2,
                             now_ns=220, clock_domain="clock")
    assert _debug(stale)["stale"] is True
    assert _debug(stale)["rooms"]
    raw_regions = [node for node in stale.nodes.values() if node.kind == "region"]
    assert len(raw_regions) == 2
    assert all(node.attributes["stable_room_id"] is None for node in raw_regions)
    assert all(node.attributes["stable_room_status"] == "unavailable" for node in raw_regions)
    assert all(node.attributes["stable_room_stale"] for node in raw_regions)


def test_room_ids_and_geometry_survive_alternating_raw_region_partitions():
    composer = HierarchyComposer()
    first = composer.compose(objects(), nav(), regions(), latest_nav_revision=1,
                             now_ns=200, clock_domain="clock")
    first_rooms = _debug(first)["rooms"]
    first_geometry = {room["room_id"]: room["polygons"] for room in first_rooms}

    # Same measured map, new DuDe partition: one proposal boundary moves and
    # the proposal IDs change. Room identity and accepted outline stay bound
    # to measured world cells, while raw region IDs remain independently named.
    alternate = RegionSnapshot("e", 2, 1, "f", {
        "ra": Region("ra", np.asarray(((0., 0.), (.5, 0.), (.5, 1.), (0., 1.)))),
        "rb": Region("rb", np.asarray(((.5, 0.), (2., 0.), (2., 1.), (.5, 1.)))),
    }, False)
    second = composer.compose(objects(), nav(), alternate, latest_nav_revision=1,
                              now_ns=220, clock_domain="clock")
    second_rooms = _debug(second)["rooms"]
    assert {room["room_id"] for room in second_rooms} == set(first_geometry)
    assert {room["room_id"]: room["polygons"] for room in second_rooms} == first_geometry
    raw_regions = [node for node in second.nodes.values() if node.kind == "region"]
    assert {node.node_id for node in raw_regions} == {"ra", "rb"}
    raw_by_id = {node.node_id: node for node in raw_regions}
    assert raw_by_id["ra"].attributes["stable_room_id"] is None
    assert raw_by_id["ra"].attributes["stable_room_status"] == "unassigned"
    assert raw_by_id["rb"].attributes["stable_room_id"] is None
    assert raw_by_id["rb"].attributes["stable_room_status"] == "ambiguous"
    assert set(raw_by_id["rb"].attributes["stable_room_candidates"]) == set(first_geometry)


def test_duplicate_room_claims_are_ambiguous_and_retired_claims_are_ignored(monkeypatch):
    composer = HierarchyComposer()
    publication = RoomPublication("e", 1, False, (
        RoomRecord("room-a", "tentative", (((10., 10.), (11., 10.), (11., 11.), (10., 11.)),),
                   ("r1",), "retained disjoint proposal", 1),
        RoomRecord("room-b", "confirmed", (((0., 0.), (1., 0.), (1., 1.), (0., 1.)),),
                   ("r1",), "current overlapping proposal", 2),
        RoomRecord("room-retired", "retired", (), ("r2",), "retired proposal", 1),
    ), (), ())
    monkeypatch.setattr(composer.rooms, "update", lambda *args, **kwargs: publication)

    hierarchy = composer.compose(objects(), nav(), regions(), latest_nav_revision=1,
                                 now_ns=200, clock_domain="clock")
    raw_regions = {node.node_id: node for node in hierarchy.nodes.values()
                   if node.kind == "region"}
    assert raw_regions["r1"].attributes["stable_room_id"] is None
    assert raw_regions["r1"].attributes["stable_room_status"] == "ambiguous"
    assert raw_regions["r1"].attributes["stable_room_candidates"] == ("room-a", "room-b")
    assert raw_regions["r2"].attributes["stable_room_id"] is None
    assert raw_regions["r2"].attributes["stable_room_status"] == "unassigned"
    # Room annotation cannot change canonical object footprint membership.
    assert hierarchy.statuses[OID] == "assigned"
    assert any(edge.kind == "in_region" and edge.source_id == OID for edge in hierarchy.edges)


def test_door_evidence_uses_committed_source_and_no_fabricated_score():
    snapshot = objects()
    state = next(iter(snapshot.objects.values()))
    door = replace(state, category="door", raw_label="door",
                   footprint_xy=np.asarray(((.2, .2), (.8, .2), (.8, .8), (.2, .8))))
    with_door = ObjectSnapshot(snapshot.episode_id, snapshot.revision, snapshot.source,
                               {door.object_id: door}, snapshot.aliases)
    evidence = HierarchyComposer._door_evidence(with_door, nav(), regions())

    assert len(evidence) == 1
    assert evidence[0].source_frame == door.source
    assert evidence[0].score is None
    provenance = json.loads(evidence[0].provenance)
    assert provenance["object_id"] == door.object_id
    assert provenance["evidence_refs"] == list(door.evidence_refs)
    assert provenance["source_last_seen_ns"] == door.last_seen_ns

    future = replace(door, last_seen_ns=nav().capture_monotonic_ns + 1)
    future_snapshot = ObjectSnapshot(snapshot.episode_id, snapshot.revision, snapshot.source,
                                     {door.object_id: future}, snapshot.aliases)
    assert HierarchyComposer._door_evidence(future_snapshot, nav(), regions()) == ()

    retired = replace(door, lifecycle="retired")
    retired_snapshot = ObjectSnapshot(snapshot.episode_id, snapshot.revision, snapshot.source,
                                      {door.object_id: retired}, snapshot.aliases)
    assert HierarchyComposer._door_evidence(retired_snapshot, nav(), regions()) == ()

    no_committed_evidence = replace(door, evidence_refs=())
    without_refs = ObjectSnapshot(snapshot.episode_id, snapshot.revision, snapshot.source,
                                  {door.object_id: no_committed_evidence}, snapshot.aliases)
    assert HierarchyComposer._door_evidence(without_refs, nav(), regions()) == ()
