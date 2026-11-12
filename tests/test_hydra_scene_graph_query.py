"""Contract tests for read-only, provenance-bounded Hydra object queries."""
from dataclasses import FrozenInstanceError

import pytest

from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
from neusymnav.backends.hydra.labels import HydraLabelRasterizer
from neusymnav.backends.hydra.query import HydraSceneGraphQuery
from neusymnav.contracts.observations import Taxonomy


def _taxonomy():
    return Taxonomy(
        vocabulary_id="fixture:objects:v1",
        categories=("chair", "table", "sofa", "toilet", "bathtub", "shower",
                    "bed", "oven", "stove", "refrigerator", "couch", "coffee table", "fridge"),
        aliases={"seat": "chair"},
        provenance="query fixture; predicted categories only",
    )


def _projection(*, revision=7, stale=False, replay_required=False, nodes=None,
                source_metadata=None):
    if nodes is None:
        nodes = [
            dict(native_id="O(0)", layer_id=2, name="chair", position=[1.0, 2.0, 0.7],
                 parent_native_id="p(0)"),
            dict(native_id="O(1)", layer_id=2, name="chair", position=[2.0, 2.0, 0.5],
                 parent_native_id=None),
            dict(native_id="O(2)", layer_id=2, name="chair", position=[3.0, 2.0, 0.5],
                 parent_native_id=None),
            dict(native_id="O(3)", layer_id=2, name="chair", position=None,
                 parent_native_id=None),
            dict(native_id="O(4)", layer_id=2, name="sofa", position=[4.0, 2.0, 0.5],
                 parent_native_id=None),
            dict(native_id="O(5)", layer_id=2, name="chair", position=None,
                 parent_native_id=None),
            dict(native_id="p(0)", layer_id=3, name="place", position=[1.0, 2.0, 0.0],
                 parent_native_id="R(0)"),
            dict(native_id="R(0)", layer_id=4, name="room", position=[1.0, 2.0, 0.0],
                 parent_native_id="B(0)"),
            dict(native_id="B(0)", layer_id=5, name="building", position=[1.0, 2.0, 0.0],
                 parent_native_id=None),
        ]
    counts = {
        str(layer): sum(node["layer_id"] == layer for node in nodes)
        for layer in (2, 3, 4, 5)
    }
    summary = dict(
        schema_version=1,
        graph_revision=revision,
        input_prefix_sha256="a" * 64,
        layer_counts=counts,
        nodes=nodes,
        edges=[],
    )
    taxonomy = _taxonomy()
    rasterizer = HydraLabelRasterizer(taxonomy)
    source = dict(
        episode_id="episode-1",
        sensor_id="rgbd-primary",
        frame_index=42,
        capture_monotonic_ns=9_000_000_000,
        clock_domain="host_monotonic:boot-1",
        vocabulary_id=taxonomy.vocabulary_id,
        labelspace_id=rasterizer.LABELSPACE_ID,
        labelspace_hash=rasterizer.labelspace_hash,
        source_geometry_hash="b" * 64,
    )
    source.update(source_metadata or {})
    return HydraGraphAdapter.project(
        summary,
        episode_id="episode-1",
        run_id="run-1",
        stale=stale,
        replay_required=replay_required,
        failure_reason="worker restart requires replay" if replay_required else None,
        last_source=source,
        native_metadata=dict(last_transform=dict(
            calibration_id="camera-cal-v1",
            calibration_hash="c" * 64,
            coordinate_convention="canonical_z_up_v1",
        )),
    )


def _query(*, projection=None, semantic_labels=None, labelspace_id=None,
           labelspace_hash=None):
    taxonomy = _taxonomy()
    rasterizer = HydraLabelRasterizer(taxonomy)
    projection = projection or _projection()
    if semantic_labels is None:
        default_labels = {
            "O(0)": 3, "O(1)": 2, "O(2)": 0, "O(3)": None,
            "O(4)": 1, "O(5)": 2,
        }
        projection_native_ids = {node.native_id for node in projection.nodes}
        semantic_labels = {key: value for key, value in default_labels.items()
                           if key in projection_native_ids}
    return HydraSceneGraphQuery(
        projection=projection,
        taxonomy=taxonomy,
        labelspace_id=labelspace_id or rasterizer.LABELSPACE_ID,
        labelspace_hash=labelspace_hash or rasterizer.labelspace_hash,
        semantic_labels=semantic_labels,
        calibration_id="camera-cal-v1",
    )


def test_query_uses_explicit_semantic_ids_and_never_guesses_from_native_names():
    query = _query()

    table = query.objects(category="table")
    chair = query.objects(category="seat")

    assert [candidate.native_id for candidate in table] == ["O(0)"]
    assert table[0].category == "table"
    assert [candidate.native_id for candidate in chair] == ["O(1)", "O(5)"]
    assert chair[0].category == "chair"
    # O(0)'s native display name says chair, but its explicit numeric semantic
    # label (3 -> table in this taxonomy) determines its query category.
    assert table[0].name == "chair"


def test_query_excludes_reserved_and_missing_semantics_and_non_object_layers():
    query = _query()

    all_labeled_objects = query.objects()

    assert [candidate.native_id for candidate in all_labeled_objects] == ["O(0)", "O(1)", "O(5)"]
    assert all(candidate.layer_id == 2 for candidate in all_labeled_objects)
    assert all_labeled_objects[-1].position_xyz_m is None
    assert all_labeled_objects[-1].usable_for_targeting is False


def test_missing_semantic_label_never_falls_back_to_a_node_name():
    candidates = _query(semantic_labels={"O(0)": 3}).objects()

    assert [candidate.native_id for candidate in candidates] == ["O(0)"]


def test_candidate_keeps_graph_provenance_and_marks_missing_object_evidence_unavailable():
    candidate = _query().objects(category="table")[0]

    assert candidate.node_id == "hydra:run-1:2:O(0)"
    assert candidate.position_xyz_m == (1.0, 2.0, 0.7)
    assert candidate.graph_revision == 7
    assert candidate.input_prefix_sha256 == "a" * 64
    assert candidate.last_source["frame_index"] == 42
    assert candidate.calibration_id == "camera-cal-v1"
    assert candidate.coordinate_convention == "canonical_z_up_v1"
    assert candidate.provenance_scope == "graph_input_prefix_only"
    assert candidate.confidence is None
    assert candidate.verified is None
    assert candidate.lifecycle is None
    assert candidate.per_object_evidence_refs is None
    assert candidate.navigability == "unvalidated"
    with pytest.raises((FrozenInstanceError, AttributeError)):
        candidate.category = "chair"
    with pytest.raises(TypeError):
        candidate.last_source["frame_index"] = 100


def test_complete_parent_chain_reports_structural_room_membership_only():
    candidate = _query().objects(category="table")[0]

    assert candidate.parent_id == "hydra:run-1:3:p(0)"
    assert candidate.parent_chain == (
        "hydra:run-1:3:p(0)",
        "hydra:run-1:4:R(0)",
        "hydra:run-1:5:B(0)",
    )
    assert candidate.room_id == "hydra:run-1:4:R(0)"
    assert candidate.membership_status == "assigned"
    assert candidate.membership_kind == "structural_not_navigation"


def test_incomplete_or_cyclic_parent_chain_never_invents_room_membership():
    incomplete = [
        dict(native_id="O(0)", layer_id=2, name="chair", position=[1.0, 2.0, 0.5],
             parent_native_id="p(0)"),
        dict(native_id="p(0)", layer_id=3, name="place", position=[1.0, 2.0, 0.0],
             parent_native_id=None),
    ]
    incomplete_candidate = _query(projection=_projection(nodes=incomplete)).objects()[0]
    assert incomplete_candidate.room_id is None
    assert incomplete_candidate.membership_status == "unavailable"

    cyclic = [
        dict(native_id="O(0)", layer_id=2, name="chair", position=[1.0, 2.0, 0.5],
             parent_native_id="p(0)"),
        dict(native_id="p(0)", layer_id=3, name="place", position=[1.0, 2.0, 0.0],
             parent_native_id="R(0)"),
        dict(native_id="R(0)", layer_id=4, name="room", position=[1.0, 2.0, 0.0],
             parent_native_id="p(0)"),
    ]
    cyclic_candidate = _query(projection=_projection(nodes=cyclic)).objects()[0]
    assert cyclic_candidate.room_id is None
    assert cyclic_candidate.membership_status == "unavailable"


def test_stale_or_replay_required_graph_candidates_are_not_targetable():
    query = _query(projection=_projection(stale=True, replay_required=True))

    candidates = query.objects(category="table")

    assert query.status == "stale"
    assert candidates
    assert all(candidate.usable_for_targeting is False for candidate in candidates)
    assert all(candidate.graph_status == "stale" for candidate in candidates)


def test_get_is_revision_bound_and_fails_closed_for_removed_or_stale_ids():
    query = _query()
    node_id = "hydra:run-1:2:O(0)"

    assert query.get(node_id, expected_revision=7).native_id == "O(0)"
    with pytest.raises(ValueError, match="revision"):
        query.get(node_id, expected_revision=6)
    with pytest.raises(ValueError, match="not found"):
        query.get("hydra:run-1:2:O(removed)")


def test_query_rejects_labelspace_mismatch_and_unmapped_numeric_semantics():
    with pytest.raises(ValueError, match="labelspace"):
        _query(labelspace_hash="0" * 64)

    with pytest.raises(ValueError, match="semantic label"):
        _query(semantic_labels={"O(0)": 999})


def test_query_rejects_semantic_mapping_for_native_ids_absent_from_snapshot():
    with pytest.raises(ValueError, match="native ID"):
        _query(semantic_labels={"O(removed)": 2})


def test_query_rejects_projection_source_with_different_pinned_vocabulary_or_labelspace():
    bad_vocabulary = _projection(source_metadata={"vocabulary_id": "fixture:other:v1"})
    with pytest.raises(ValueError, match="vocabulary"):
        _query(projection=bad_vocabulary)

    bad_labelspace = _projection(source_metadata={"labelspace_hash": "0" * 64})
    with pytest.raises(ValueError, match="labelspace"):
        _query(projection=bad_labelspace)

