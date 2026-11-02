"""Synthetic room-owner hysteresis tests; not native DuDe/runtime validation."""
from __future__ import annotations

import json
import numpy as np

from neusymnav.contracts import GridState, NavSnapshot, Region, RegionSnapshot
from neusymnav.contracts.observations import FrameKey
from neusymnav.rooms import DoorEvidence, RoomOwner


def _snapshot(revision: int, states: np.ndarray, polygon: tuple[tuple[float, float], ...], *, rid: str = "du-de-a"):
    floor = states == GridState.FREE
    clearance = floor.astype(np.float64) * 1.0
    source = FrameKey("episode-1", "depth", revision)
    nav = NavSnapshot(
        episode_id="episode-1", revision=revision, source=source,
        capture_monotonic_ns=revision * 1_000_000, clock_domain="test-clock",
        resolution_m=1.0, origin_xy=(0.0, 0.0), states=states,
        floor_support=floor, clearance=clearance, robot_geometry_id="robot-v1",
        floor_z_m=0.0, floor_datum_source="fixture", calibration_hash="a" * 64,
    )
    region = Region(rid, np.asarray(polygon, dtype=np.float64))
    regions = RegionSnapshot("episode-1", revision, revision, "floor-1", {rid: region}, False)
    return nav, regions


def _room_states(size: int = 12) -> np.ndarray:
    states = np.full((size, size), GridState.UNKNOWN, dtype=np.int8)
    states[1:11, 1:11] = GridState.OCCUPIED
    states[2:10, 2:10] = GridState.FREE
    return states


def test_static_du_de_id_oscillation_never_advances_confidence_or_changes_room_id():
    owner = RoomOwner()
    polygon = ((2, 2), (10, 2), (10, 10), (2, 10))
    nav, regions = _snapshot(1, _room_states(), polygon, rid="left")
    first = owner.update(nav, regions)
    assert len(first.rooms) == 1
    room_id, support = first.rooms[0].room_id, first.rooms[0].support_count
    assert first.rooms[0].status == "tentative"
    # DuDe raw IDs and publication revision may change while the underlying
    # measured geometry remains identical.
    for revision, rid in ((2, "right"), (3, "left"), (4, "right")):
        nav, regions = _snapshot(revision, _room_states(), polygon, rid=rid)
        result = owner.update(nav, regions)
        assert result.rooms[0].room_id == room_id
        assert result.rooms[0].support_count == support
        assert result.rooms[0].status == "tentative"


def test_expansion_keeps_stable_id_and_confirms_after_distinct_measured_support():
    owner = RoomOwner()
    states = np.full((14, 14), GridState.UNKNOWN, dtype=np.int8)
    states[1:13, 1:13] = GridState.OCCUPIED
    states[3:8, 3:8] = GridState.FREE
    nav, regions = _snapshot(1, states, ((3, 3), (8, 3), (8, 8), (3, 8)))
    first = owner.update(nav, regions)
    assert first.rooms[0].status == "tentative"
    room_id = first.rooms[0].room_id

    expanded = states.copy()
    expanded[3:10, 3:10] = GridState.FREE
    nav, regions = _snapshot(2, expanded, ((3, 3), (10, 3), (10, 10), (3, 10)), rid="oscillated")
    result = owner.update(nav, regions)
    assert result.rooms[0].room_id == room_id
    assert result.rooms[0].status == "confirmed"
    assert result.rooms[0].support_count == 2


def test_unknown_boundary_and_small_furniture_like_patch_do_not_confirm():
    owner = RoomOwner()
    states = np.full((10, 10), GridState.UNKNOWN, dtype=np.int8)
    states[4:6, 4:6] = GridState.FREE
    nav, regions = _snapshot(1, states, ((4, 4), (6, 4), (6, 6), (4, 6)))
    result = owner.update(nav, regions)
    assert all(room.status != "confirmed" for room in result.rooms)


def test_open_free_portal_is_reported_as_candidate_not_traversability():
    owner = RoomOwner()
    size, res = 48, 0.05
    states = np.full((size, size), GridState.FREE, dtype=np.int8)
    # A thick occupied wall at x=24 has a 0.60m measured free opening.
    states[:, 22:27] = GridState.OCCUPIED
    states[14:26, 22:27] = GridState.FREE
    floor = states == GridState.FREE
    nav = NavSnapshot("episode-1", 1, FrameKey("episode-1", "depth", 1), 1_000_000,
                      "test-clock", res, (0.0, 0.0), states, floor, floor.astype(np.float64),
                      "robot-v1", 0.0, "fixture", "a" * 64)
    # A single broad DuDe proposal covers both sides of the opening. Portal
    # detection must come from occupancy, not from a region boundary.
    whole = ((0.0, 0.0), (2.4, 0.0), (2.4, 2.4), (0.0, 2.4))
    regs = {"one": Region("one", np.asarray(whole, dtype=np.float64))}
    regions = RegionSnapshot("episode-1", 1, 1, "floor-1", regs, False)
    result = owner.update(nav, regions)
    assert result.portals
    assert "0.60 m" in result.portals[0].reason
    assert "unverified" in result.portals[0].reason


def test_door_evidence_is_episode_bound_deduplicated_and_never_passage_proof():
    owner = RoomOwner()
    states = _room_states()
    polygon = ((2, 2), (10, 2), (10, 10), (2, 10))
    nav, regions = _snapshot(1, states, polygon)
    door = DoorEvidence("event-1", "episode-1", FrameKey("episode-1", "rgb", 1),
                        ((5, 5), (6, 5), (6, 6), (5, 6)), "committed door observation")
    first = owner.update(nav, regions, door_evidence=(door,))
    repeated = owner.update(nav, regions, door_evidence=(door,))
    assert repeated.rooms[0].support_count == first.rooms[0].support_count
    assert all("passage" not in p.reason.lower() for p in repeated.portals)


def test_stale_mismatch_retains_geometry_without_support_progress_and_debug_is_json():
    owner = RoomOwner()
    nav, regions = _snapshot(1, _room_states(), ((2, 2), (10, 2), (10, 10), (2, 10)))
    accepted = owner.update(nav, regions)
    wrong = RegionSnapshot("episode-1", 2, 0, "floor-1", {}, False)
    stale = owner.update(_snapshot(2, _room_states(), ((2, 2), (10, 2), (10, 10), (2, 10)))[0], wrong)
    assert stale.stale
    assert stale.rooms == accepted.rooms
    assert stale.rooms[0].support_count == accepted.rooms[0].support_count
    json.dumps(stale.to_debug())


def test_repeated_identical_inputs_are_deterministic():
    outputs = []
    for _ in range(2):
        owner = RoomOwner()
        nav, regions = _snapshot(1, _room_states(), ((2, 2), (10, 2), (10, 10), (2, 10)))
        outputs.append(owner.update(nav, regions).to_debug())
    assert outputs[0] == outputs[1]


def _metric(revision, states, polygons, origin=(0., 0.)):
    res = .05
    free = states == GridState.FREE
    nav = NavSnapshot("episode-1", revision, FrameKey("episode-1", "depth", revision),
                      revision * 1000000, "test-clock", res, origin, states, free,
                      free.astype(float), "robot-v1", 0., "fixture", "a" * 64)
    rs = {str(i): Region(str(i), np.asarray(p, dtype=float)) for i, p in enumerate(polygons)}
    return nav, RegionSnapshot("episode-1", revision, revision, "floor-1", rs, False)


def test_metric_split_requires_two_distinct_interface_changes_and_retains_lineage():
    owner = RoomOwner()
    states = np.full((44, 44), GridState.OCCUPIED, dtype=np.int8)
    states[2:42, 2:42] = GridState.FREE
    whole = ((.1,.1),(2.1,.1),(2.1,2.1),(.1,2.1))
    left = ((.1,.1),(1.1,.1),(1.1,2.1),(.1,2.1))
    right = ((1.1,.1),(2.1,.1),(2.1,2.1),(1.1,2.1))
    first = owner.update(*_metric(1, states, [whole])); parent = first.rooms[0].room_id
    for revision in (2, 3):
        pub = owner.update(*_metric(revision, states, [left, right]))
        assert [r.room_id for r in pub.rooms] == [parent]
        assert len(pub.rooms[0].region_ids) == 2
    states[2:22, 21:23] = GridState.OCCUPIED
    pub = owner.update(*_metric(4, states, [left, right]))
    assert [r.room_id for r in pub.rooms] == [parent]
    states[22:42, 21:23] = GridState.OCCUPIED
    pub = owner.update(*_metric(5, states, [left, right]))
    assert len(pub.rooms) == 2 and all(r.predecessors == (parent,) for r in pub.rooms)
    assert any(e.kind == "split" for e in pub.events)
    assert all(not r.room_id.startswith("pending:") for r in pub.rooms)


def test_rejected_input_does_not_consume_measured_history_or_advance_clock():
    owner = RoomOwner(max_cells=2000)
    states = np.full((20,20), GridState.UNKNOWN, dtype=np.int8)
    states[2:18,2:18] = GridState.FREE
    poly = ((2,2),(18,2),(18,18),(2,18))
    nav, regs = _snapshot(1, states, poly)
    accepted = owner.update(nav, regs)
    bad = RegionSnapshot("episode-1", 2, 2, "other-floor", regs.regions, False)
    nav2, _ = _snapshot(2, states, poly)
    assert owner.update(nav2, bad).stale
    assert owner.update(nav2, _snapshot(2, states, poly)[1]).rooms == accepted.rooms


def test_origin_alignment_and_negative_grid_offsets():
    owner = RoomOwner()
    states = np.full((20,20), GridState.FREE, dtype=np.int8)
    poly = ((-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5))
    first = owner.update(*_metric(1, states, [poly], (-.5,-.5)))
    assert first.rooms
    assert owner.update(*_metric(2, states, [poly], (-.499,-.5))).stale
    shifted = np.full((20,21), GridState.UNKNOWN, dtype=np.int8)
    shifted[:,1:] = states
    pub = owner.update(*_metric(2, shifted, [poly], (-.55,-.5)))
    assert not pub.stale and pub.rooms[0].room_id == first.rooms[0].room_id
    assert pub.rooms[0].support_count == first.rooms[0].support_count


def test_metric_merge_requires_distinct_boundary_corrections():
    owner = RoomOwner()
    states = np.full((44,44), GridState.OCCUPIED, dtype=np.int8)
    states[2:42,2:42] = GridState.FREE
    states[2:42,21:23] = GridState.OCCUPIED
    left = ((.1,.1),(1.1,.1),(1.1,2.1),(.1,2.1))
    right = ((1.1,.1),(2.1,.1),(2.1,2.1),(1.1,2.1))
    whole = ((.1,.1),(2.1,.1),(2.1,2.1),(.1,2.1))
    first = owner.update(*_metric(1, states, [left,right]))
    parents = tuple(r.room_id for r in first.rooms)
    assert len(parents) == 2
    assert len(owner.update(*_metric(2, states, [whole])).rooms) == 2
    states[5:10,21:23] = GridState.FREE
    assert len(owner.update(*_metric(3, states, [whole])).rooms) == 2
    states[12:17,21:23] = GridState.FREE
    assert len(owner.update(*_metric(4, states, [whole])).rooms) == 2
    states[2:42,21:23] = GridState.FREE
    merged = owner.update(*_metric(5, states, [whole]))
    assert len(merged.rooms) == 1
    assert merged.rooms[0].predecessors == parents
    assert any(e.kind == "merge" for e in merged.events)


def test_unrelated_growth_and_repeated_toggle_cannot_support_split():
    owner = RoomOwner()
    states = np.full((44,44), GridState.UNKNOWN, dtype=np.int8)
    states[2:42,2:42] = GridState.FREE
    whole = ((.1,.1),(2.1,.1),(2.1,2.1),(.1,2.1))
    left = ((.1,.1),(1.1,.1),(1.1,2.1),(.1,2.1))
    right = ((1.1,.1),(2.1,.1),(2.1,2.1),(1.1,2.1))
    parent = owner.update(*_metric(1, states, [whole])).rooms[0].room_id
    states[5:10,21] = GridState.OCCUPIED
    assert owner.update(*_metric(2, states, [left,right])).rooms[0].room_id == parent
    states[5:10,21] = GridState.FREE
    assert owner.update(*_metric(3, states, [left,right])).rooms[0].room_id == parent
    states[5:10,21] = GridState.OCCUPIED
    states[0,0:10] = GridState.FREE
    pub = owner.update(*_metric(4, states, [left,right]))
    assert len(pub.rooms) == 1 and pub.rooms[0].room_id == parent


def test_failed_new_episode_does_not_publish_previous_episode_rooms():
    from dataclasses import replace
    owner = RoomOwner()
    nav, regions = _snapshot(1, _room_states(), ((2,2),(10,2),(10,10),(2,10)))
    assert owner.update(nav, regions).rooms
    other = replace(nav, episode_id="episode-2", source=FrameKey("episode-2", "depth", 1))
    stale = owner.update(other, regions)
    assert stale.stale and stale.episode_id == "episode-2" and not stale.rooms


def test_exterior_growth_near_partition_corner_is_not_divider_evidence():
    owner = RoomOwner()
    states = np.full((44,44), GridState.UNKNOWN, dtype=np.int8)
    states[2:42,2:42] = GridState.FREE
    whole = ((.1,.1),(2.1,.1),(2.1,2.1),(.1,2.1))
    left = ((.1,.1),(1.1,.1),(1.1,2.1),(.1,2.1))
    right = ((1.1,.1),(2.1,.1),(2.1,2.1),(1.1,2.1))
    parent = owner.update(*_metric(1, states, [whole])).rooms[0].room_id
    states[0,18:26] = GridState.OCCUPIED
    owner.update(*_metric(2, states, [left,right]))
    states[1,18:26] = GridState.OCCUPIED
    result = owner.update(*_metric(3, states, [left,right]))
    assert len(result.rooms) == 1 and result.rooms[0].room_id == parent


def test_disjoint_region_on_same_measured_map_does_not_mint_room():
    owner = RoomOwner()
    states = np.full((44,44), GridState.FREE, dtype=np.int8)
    left = ((.1,.1),(.9,.1),(.9,2.1),(.1,2.1))
    right = ((1.2,.1),(2.1,.1),(2.1,2.1),(1.2,2.1))
    parent = owner.update(*_metric(1, states, [left])).rooms[0].room_id
    pub = owner.update(*_metric(2, states, [right]))
    assert [r.room_id for r in pub.rooms] == [parent]


def test_candidate_budget_rejection_does_not_consume_new_evidence():
    owner = RoomOwner(max_cells=500)
    states = np.full((20, 20), GridState.FREE, dtype=np.int8)
    whole = ((0.,0.),(1.,0.),(1.,1.),(0.,1.))
    nav, duplicate = _metric(1, states, [whole, whole])
    assert owner.update(nav, duplicate).stale
    accepted = owner.update(*_metric(1, states, [whole]))
    assert not accepted.stale and len(accepted.rooms) == 1
    assert accepted.rooms[0].support_count == 1


def test_portal_ids_are_unique_and_stable_across_aligned_origin_shift():
    states = np.full((48,48), GridState.FREE, dtype=np.int8)
    states[:,22:27] = GridState.OCCUPIED
    states[14:26,22:27] = GridState.FREE
    whole = ((0.,0.),(2.4,0.),(2.4,2.4),(0.,2.4))
    owner = RoomOwner()
    first = owner.update(*_metric(1, states, [whole]))
    ids = [p.portal_id for p in first.portals]
    assert len(ids) >= 2 and len(ids) == len(set(ids))
    shifted = np.full((48,49), GridState.UNKNOWN, dtype=np.int8)
    shifted[:,1:] = states
    second = owner.update(*_metric(2, shifted, [whole], (-.05,0.)))
    assert not second.stale
    assert {p.portal_id for p in second.portals} == set(ids)


def test_horizontal_portal_ids_use_correct_world_axes():
    states = np.full((48,48), GridState.FREE, dtype=np.int8)
    states[22:27,:] = GridState.OCCUPIED
    states[22:27,14:26] = GridState.FREE
    whole = ((0.,0.),(2.4,0.),(2.4,2.4),(0.,2.4))
    owner = RoomOwner()
    first = owner.update(*_metric(1, states, [whole]))
    ids = [p.portal_id for p in first.portals]
    assert len(ids) >= 2 and len(ids) == len(set(ids))
    for portal in first.portals:
        orient, col, row = portal.portal_id.split(":")[1:]
        if orient == "y":
            midpoint = tuple((a+b)/2 for a,b in zip(*portal.endpoints))
            assert abs((int(col)+.5)*.05 - midpoint[0]) < 1e-9
            assert abs((int(row)+.5)*.05 - midpoint[1]) < 1e-9


def test_reused_region_id_on_disjoint_proposal_clears_old_room_association():
    owner = RoomOwner()
    states = np.full((44, 44), GridState.FREE, dtype=np.int8)
    left = ((.1,.1),(.9,.1),(.9,2.1),(.1,2.1))
    right = ((1.2,.1),(2.1,.1),(2.1,2.1),(1.2,2.1))
    first = owner.update(*_metric(1, states, [left]))
    assert first.rooms[0].region_ids == ("0",)
    second = owner.update(*_metric(2, states, [right]))
    assert len(second.rooms) == 1
    assert second.rooms[0].room_id == first.rooms[0].room_id
    assert second.rooms[0].polygons == first.rooms[0].polygons
    assert second.rooms[0].region_ids == ()


def test_repeated_initial_stale_input_has_same_diagnostic():
    owner = RoomOwner()
    nav, regions = _snapshot(1, _room_states(), ((2,2),(10,2),(10,10),(2,10)))
    stale_regions = RegionSnapshot("episode-1", 1, 1, "floor-1", {}, True)
    first = owner.update(nav, stale_regions)
    second = owner.update(nav, stale_regions)
    assert first.stale and first.to_debug() == second.to_debug()
    assert first.events and first.events[-1].reason
