"""P08 publication tests use fixed CPU snapshots, never a native runtime."""
from dataclasses import replace

import numpy as np
import pytest

from neusymnav.contracts import FrameKey, ObjectSnapshot
from neusymnav.hierarchy import HierarchyComposer
from neusymnav.visualization.hierarchy_view import hierarchy_rows, resolve_object_selection
from neusymnav.visualization.publisher import (
    DisplayImage, DisplayPublisher, DisplaySources, DisplayVerificationEvidence,
    DisplayVerificationRecord, DisplayVerificationSnapshot, UiCommandAck, UiControlClient,
)
from test_membership import ALIAS, OID, objects, regions
from test_regions import nav


CANDIDATE = "00000000-0000-0000-0000-000000000003"
VERIFIED = "00000000-0000-0000-0000-000000000004"


def object_snapshot():
    original = objects().objects[OID]
    candidate = replace(
        original, object_id=CANDIDATE, lifecycle="candidate", evidence_refs=("evidence-candidate",),
        centroid=np.array([1.5, .5, .5]), bounds=np.array([[1.2, .2, 0.], [1.8, .8, 1.]]),
    )
    unverified_active = replace(
        original, object_id=VERIFIED, lifecycle="active", evidence_refs=("evidence-unverified",),
        centroid=np.array([2.5, .5, .5]), bounds=np.array([[2.2, .2, 0.], [2.8, .8, 1.]]),
    )
    source = original.source
    return ObjectSnapshot("e", 1, source, {OID: original, CANDIDATE: candidate, VERIFIED: unverified_active}, {ALIAS: OID})


def verification_snapshot(objects_value, *, stale_object_revision=False, stale_bundle_revision=False):
    active = objects_value.objects[OID]
    unverified = objects_value.objects[VERIFIED]
    return DisplayVerificationSnapshot(
        episode_id=objects_value.episode_id,
        object_revision=objects_value.revision - (1 if stale_bundle_revision else 0),
        objects={
            OID: DisplayVerificationRecord(
                episode_id=objects_value.episode_id, object_id=OID,
                object_revision=active.revision + (1 if stale_object_revision else 0),
                status="verified", evidence=(
                    DisplayVerificationEvidence(FrameKey("e", "camA", 0), active.revision, 20, "clock", "event-1"),
                    DisplayVerificationEvidence(FrameKey("e", "camB", 1), active.revision, 30, "clock", "event-2"),
                ),
            ),
            VERIFIED: DisplayVerificationRecord(
                episode_id=objects_value.episode_id, object_id=VERIFIED,
                object_revision=unverified.revision, status="unverified",
                evidence=(DisplayVerificationEvidence(
                    FrameKey("e", "camC", 2), unverified.revision, 40, "clock", "event-3",
                ),),
            ),
        },
    )


def make_publisher(*, stale=False, with_images=True, verification=None):
    objects_value = object_snapshot()
    nav_value = nav()
    region_value = regions(stale=stale)
    hierarchy = HierarchyComposer().compose(
        objects_value, nav_value, region_value, latest_nav_revision=2,
        now_ns=200, clock_domain="clock",
    )
    metrics = {
        "captured_frame_id": FrameKey("e", "rgbd", 2),
        "processed_frame_id": FrameKey("e", "rgbd", 1),
        "published_frame_id": FrameKey("e", "rgbd", 0),
        "source_age_ns": {"rgb": 50, "map": 100, "objects": 180, "verification": 120},
        "dropped_count": 2,
        "replaced_count": 4,
        "actual_profile": "cpu-fixture-v1",
        "sources": DisplaySources(
            nav=nav_value,
            objects=objects_value,
            verification=verification if verification is not None else verification_snapshot(objects_value),
            rgb=DisplayImage("rgb", FrameKey("e", "rgbd", 2), 150, "clock",
                             np.full((8, 12, 3), 120, dtype=np.uint8)) if with_images else None,
            best_views=(DisplayImage(
                "best_view", FrameKey("e", "rgbd", 0), 20, "clock",
                np.full((5, 7, 3), 210, dtype=np.uint8), ALIAS, 1, "evidence",
            ),) if with_images else (),
        ),
    }
    now = [200]
    publisher = DisplayPublisher(clock_domain="clock", now_ns=lambda: now[0])
    publisher.publish(hierarchy, metrics)
    return publisher, hierarchy, metrics, objects_value, nav_value, now


def test_publication_is_atomic_and_all_source_revisions_are_pinned():
    publisher, hierarchy, metrics, objects_value, nav_value, now = make_publisher()
    envelope = publisher.read_latest()
    assert envelope is not None
    assert envelope.hierarchy is hierarchy
    assert envelope.sources.nav is nav_value
    assert envelope.sources.objects is objects_value
    assert envelope.metrics.source_age_ns["map"] == hierarchy.source_map_age_ns
    assert envelope.publication_age_ns(250, "clock") == 50
    assert envelope.sources.rgb.pixels.flags.writeable is False

    before = publisher.read_latest()
    with pytest.raises(ValueError, match="pinned episode/map revision"):
        publisher.publish(hierarchy, {**metrics, "sources": DisplaySources(nav=nav(2), objects=objects_value)})
    with pytest.raises(ValueError, match="pinned episode/object revision"):
        publisher.publish(hierarchy, {**metrics, "sources": DisplaySources(
            nav=nav_value, objects=replace(objects_value, revision=2),
        )})
    assert publisher.read_latest() is before


def test_display_image_owns_pixels_and_best_view_requires_pinned_evidence():
    source_pixels = np.zeros((2, 3, 3), dtype=np.uint8)
    image = DisplayImage("rgb", FrameKey("e", "rgbd", 1), 10, "clock", source_pixels)
    source_pixels[:] = 255
    assert int(image.pixels.max()) == 0
    assert not image.pixels.flags.writeable

    publisher, hierarchy, metrics, _objects, _nav, _now = make_publisher()
    invalid = DisplayImage("best_view", FrameKey("e", "rgbd", 0), 20, "clock",
                           np.ones((2, 2, 3), np.uint8), OID, 1, "missing-evidence")
    with pytest.raises(ValueError, match="absent from the pinned object history"):
        publisher.publish(hierarchy, {**metrics, "sources": DisplaySources(
            nav=metrics["sources"].nav, objects=metrics["sources"].objects, best_views=(invalid,),
        )})


def test_hierarchy_rows_keep_lifecycle_membership_staleness_and_alias_distinct():
    publisher, _hierarchy, _metrics, _objects, _nav, _now = make_publisher(stale=True)
    envelope = publisher.read_latest()
    assert envelope is not None
    rows = hierarchy_rows(envelope)
    object_rows = {row.node_id: row for row in rows if row.kind == "object"}
    assert {row.lifecycle for row in object_rows.values()} == {"active", "candidate"}
    assert object_rows[OID].lifecycle == "active"
    assert object_rows[CANDIDATE].lifecycle == "candidate"
    assert object_rows[VERIFIED].lifecycle == "active"
    assert object_rows[OID].verification == "verified"
    assert object_rows[VERIFIED].verification == "unverified"
    assert object_rows[CANDIDATE].verification == "unavailable"
    assert object_rows[OID].status == "unavailable"
    assert any(row.kind == "room" and row.stale and "STALE" in row.label for row in rows)
    assert resolve_object_selection(envelope, ALIAS) == (OID, True)


@pytest.mark.parametrize("stale_object_revision,stale_bundle_revision", [(True, False), (False, True)])
def test_verification_mismatched_revision_is_unavailable(stale_object_revision, stale_bundle_revision):
    objects_value = object_snapshot()
    verification = verification_snapshot(
        objects_value, stale_object_revision=stale_object_revision,
        stale_bundle_revision=stale_bundle_revision,
    )
    publisher, *_ = make_publisher(verification=verification)
    rows = {row.node_id: row for row in hierarchy_rows(publisher.read_latest()) if row.kind == "object"}
    assert rows[OID].lifecycle == "active"
    assert rows[OID].verification == "unavailable"


def test_control_client_never_reports_success_without_matching_ack():
    now = [1_000]
    commands = []
    client = UiControlClient(
        command_source="desktop-ui", submit=lambda command: commands.append(command),
        clock_domain="host:boot1", ack_timeout_s=1.0, now_ns=lambda: now[0],
    )
    pending = client.request("pause")
    assert pending.state == "pending"
    assert commands[0].request_uuid == pending.request_uuid
    assert commands[0].source == "desktop-ui"
    now[0] += 1_000_000_000
    assert client.status(pending.request_uuid).state == "timed_out"
    with pytest.raises(ValueError, match="pause and stop only"):
        client.request("resume")

    accepted = UiControlClient(
        command_source="desktop-ui",
        submit=lambda command: UiCommandAck(command.request_uuid, "accepted", None, now[0], "host:boot1"),
        clock_domain="host:boot1", now_ns=lambda: now[0],
    ).request("stop")
    assert accepted.state == "acknowledged"

    submitted = []
    async_client = UiControlClient(
        command_source="desktop-ui", submit=lambda command: submitted.append(command),
        clock_domain="host:boot1", now_ns=lambda: now[0],
    )
    waiting = async_client.request("pause")
    rejected = async_client.accept_ack(UiCommandAck(
        submitted[0].request_uuid, "rejected", "runtime is already stopping", now[0], "host:boot1",
    ))
    assert waiting.state == "pending"
    assert rejected.state == "rejected"
    assert rejected.reason == "runtime is already stopping"

    late_commands = []
    late_client = UiControlClient(
        command_source="desktop-ui", submit=lambda command: late_commands.append(command),
        clock_domain="host:boot1", ack_timeout_s=1.0, now_ns=lambda: now[0],
    )
    late_request = late_client.request("stop")
    assert late_request.request_uuid == late_commands[0].request_uuid
    now[0] += 1_000_000_000
    late_ack = UiCommandAck(late_commands[0].request_uuid, "accepted", None, now[0] - 1, "host:boot1")
    assert late_client.accept_ack(late_ack).state == "timed_out"
