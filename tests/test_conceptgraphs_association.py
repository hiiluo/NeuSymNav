"""Independent cloud-distance and canonical assignment checks for the opt-in recipe."""

import json

import numpy as np
import pytest

from neusymnav.objects.association import AssociationEngine, AssociationObservation
from neusymnav.objects.association_recipe import AssociationRecipe


def observation(frame, points, *, detection="d", visual=None, floor="f", kind="detected"):
    return AssociationObservation(
        "e", frame, detection, floor, kind, "chair", .9,
        np.asarray(points, dtype=float), (0., 0., 0.),
        visual_embedding=None if visual is None else np.asarray(visual, dtype=float),
    )


def engine(**recipe):
    return AssociationEngine("e", association_recipe={"mode": "conceptgraphs", **recipe})


def planar_cloud():
    return np.array([[x, y, 1.] for x in (.005, .045, .085, .125)
                     for y in (.005, .045, .085, .125)])


def test_directional_overlap_matches_independent_all_pairs_distance_oracle():
    from neusymnav.objects.conceptgraphs import directional_overlap

    rng = np.random.default_rng(723)
    mapped = rng.uniform(-.2, .2, (71, 3))
    observed = np.concatenate((mapped[::3] + .004, rng.uniform(-.2, .2, (29, 3))))
    # Deliberately use all-pairs distances, independent of the scorer's tree.
    nearest = np.sqrt(((observed[:, None] - mapped[None, :]) ** 2).sum(axis=2)).min(axis=1)
    expected = float((nearest < .03).sum() / len(observed))
    assert directional_overlap(observed, mapped, nn_distance_m=.03) == expected


def test_partial_view_after_first_512_map_points_keeps_identity():
    mapped = np.array([[.005 + .035 * x, .005 + .035 * y, 1.]
                       for x in range(27) for y in range(27)])
    e = engine()
    initial = e.ingest((observation(0, mapped),))
    result = e.ingest((observation(1, mapped[-54:]),))
    assert result.object_ids == initial.object_ids
    assert result.diagnostics["map_points"] == 729
    assert result.diagnostics["observation_sample_points"] == 54


def test_deterministic_sampling_ignores_input_order_including_within_voxel():
    from neusymnav.objects.conceptgraphs import sample_observation

    rng = np.random.default_rng(178)
    points = rng.uniform(-2., 2., (17000, 3))
    # Multiple points per voxel expose summation-order dependence as well.
    points = np.concatenate((points, points[:1000] + .0001))
    a = sample_observation(points, AssociationRecipe(mode="conceptgraphs"))
    b = sample_observation(points[rng.permutation(len(points))], AssociationRecipe(mode="conceptgraphs"))
    assert a.capped and b.capped
    assert a.points.shape == (4096, 3)
    np.testing.assert_array_equal(a.points, b.points)


@pytest.mark.parametrize("z", [0., 1.])
def test_planar_cloud_does_not_depend_on_positive_aabb_volume(z):
    cloud = planar_cloud().copy()
    cloud[:, 2] = z
    e = engine()
    first = e.ingest((observation(0, cloud),))
    assert e.ingest((observation(1, cloud[::-1]),)).object_ids == first.object_ids


def test_nearest_neighbor_boundary_is_strict():
    from neusymnav.objects.conceptgraphs import directional_overlap

    mapped = np.array([[0., 0., 0.]])
    observed = np.array([[np.nextafter(.03, 0.), 0., 0.], [.03, 0., 0.], [.031, 0., 0.]])
    assert directional_overlap(observed, mapped, nn_distance_m=.03) == 1 / 3


@pytest.mark.parametrize("visual,expected_match", [([1, 0], True), ([0, 1], False), ([-1, 0], False)])
def test_raw_cosine_utility_preserves_orthogonal_and_negative_scores(visual, expected_match):
    e = engine()
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))
    result = e.ingest((observation(1, planar_cloud(), visual=visual),))
    assert (result.object_ids == first.object_ids) is expected_match
    assert result.diagnostics["visual_pairs"] == 1
    assert result.diagnostics["spatial_only_pairs"] == 0


def test_physical_bias_changes_raw_utility_on_declared_scale():
    # spatial=1, cosine=0: bias0 => .5 (reject), bias.2 => .6 (match).
    e = engine(physical_bias=.2)
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))
    assert e.ingest((observation(1, planar_cloud(), visual=[0, 1]),)).object_ids == first.object_ids


def test_negative_cosine_is_not_clamped_to_zero_before_weighting():
    # With bias.8, spatial1 and cosine-1 give .8; clipping cosine to0 gives .9.
    e = engine(physical_bias=.8, match_threshold=.85)
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))
    result = e.ingest((observation(1, planar_cloud(), visual=[-1, 0]),))
    assert result.object_ids != first.object_ids


@pytest.mark.parametrize("overlapping,expected_match", [(11, True), (10, False)])
def test_spatial_fallback_uses_declared_point_fraction_threshold(overlapping, expected_match):
    observed = np.array([[.005 + .04 * x, .005, 1.] for x in range(20)])
    mapped = observed.copy()
    mapped[overlapping:, 1] += .08
    e = engine()
    first = e.ingest((observation(0, mapped),))
    result = e.ingest((observation(1, observed),))
    assert (result.object_ids == first.object_ids) is expected_match


def test_recipe_ambiguity_margin_controls_spatial_fallback():
    observed, a, b = mixed_clouds()
    e = engine(ambiguity_margin=.04)
    first = e.ingest((observation(0, a, detection="a", visual=[.5, np.sqrt(.75)]),
                      observation(0, b, detection="b")))
    result = e.ingest((observation(1, observed, visual=[1, 0]),))
    assert result.object_ids == (first.object_ids[0],)
    assert result.ambiguous_indices == ()


@pytest.mark.parametrize("first_visual,next_visual", [(None, [1, 0]), ([1, 0], None), (None, None)])
def test_missing_features_use_overlap_without_dividing_by_two(first_visual, next_visual):
    e = engine()
    first = e.ingest((observation(0, planar_cloud(), visual=first_visual),))
    result = e.ingest((observation(1, planar_cloud(), visual=next_visual),))
    assert result.object_ids == first.object_ids
    assert result.diagnostics["fallback_rows"] == 1
    assert result.diagnostics["spatial_only_pairs"] == 1
    assert result.diagnostics["visual_pairs"] == 0


def mixed_clouds():
    observed = np.array([[.005 + .04 * x, .005, 1.] for x in range(20)])
    a = observed.copy()
    b = observed.copy()
    a[-4:, 1] += .08  # observation overlap .8 with A
    b[-5:, 1] += .08  # observation overlap .75 with B
    return observed, a, b


def test_mixed_row_fallback_avoids_rewarding_missing_candidate_feature():
    observed, a, b = mixed_clouds()
    e = engine()
    e.ingest((observation(0, a, detection="a", visual=[.5, np.sqrt(.75)]),
              observation(0, b, detection="b")))
    # .8 vs .75 is ambiguous on the configured .08 margin. Mixed .65 vs .75
    # would spuriously choose B; missing features must not change the scale.
    result = e.ingest((observation(1, observed, visual=[1, 0]),))
    assert result.object_ids == (None,)
    assert result.ambiguous_indices == (0,)
    assert result.diagnostics["fallback_rows"] == 1
    assert result.diagnostics["spatial_only_pairs"] == 2
    assert result.diagnostics["visual_pairs"] == 0


def test_missing_feature_on_ineligible_candidate_does_not_force_fallback():
    cloud = planar_cloud()
    e = engine()
    first = e.ingest((observation(0, cloud, detection="a", visual=[1, 0]),
                      observation(0, cloud + [0., 0., 2.], detection="b")))
    result = e.ingest((observation(1, cloud, visual=[0, 1]),))
    assert result.object_ids[0] not in first.object_ids
    assert result.diagnostics["fallback_rows"] == 0
    assert result.diagnostics["visual_pairs"] == 1


def test_dimension_mismatch_rejects_even_when_another_candidate_lacks_features():
    e = engine()
    e.ingest((observation(0, planar_cloud(), detection="a", visual=[1, 0, 0]),
              observation(0, planar_cloud(), detection="b")))
    before = e.export_active_state()
    with pytest.raises(ValueError, match="dimension"):
        e.ingest((observation(1, planar_cloud(), visual=[1, 0]),))
    assert e.export_active_state() == before


def test_visual_similarity_cannot_join_disjoint_geometry_with_low_spatial_score():
    e = engine(match_threshold=.45)
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))
    # Centroid and AABB gates allow this 4cm offset in Z, but overlap is zero.
    result = e.ingest((observation(1, planar_cloud() + [0., 0., .04], visual=[1, 0]),))
    assert result.object_ids != first.object_ids


def test_one_to_one_assignment_retains_cannot_link_history():
    e = engine()
    cloud = planar_cloud()
    first = e.ingest((observation(0, cloud, detection="a"),
                      observation(0, cloud + [.5, 0., 0.], detection="b")))
    result = e.ingest((observation(1, cloud + [.5, 0., 0.], detection="a"),
                       observation(1, cloud, detection="b")))
    assert result.object_ids == first.object_ids[::-1]
    assert not e.can_merge(*first.object_ids)
    with pytest.raises(ValueError, match="simultaneous"):
        e.merge_tracks(*first.object_ids)


@pytest.mark.parametrize("is_blocked", [False, True])
def test_wall_predicate_is_called_once_per_candidate_before_row_fallback(is_blocked):
    calls = []
    e = engine()
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))

    def blocked(start, end):
        calls.append((start, end))
        return is_blocked

    result = e.ingest((observation(1, planar_cloud(), visual=[1, 0]),), blocked_by_wall=blocked)
    assert (result.object_ids != first.object_ids) is is_blocked
    assert len(calls) == 1
    assert result.diagnostics["candidate_pairs"] == int(not is_blocked)


def test_floor_gate_prevents_cross_floor_identity():
    e = engine()
    first = e.ingest((observation(0, planar_cloud()),))
    assert e.ingest((observation(1, planar_cloud(), floor="other"),)).object_ids != first.object_ids


@pytest.mark.parametrize("offset", [[0., 0., .11], [1.6, 0., 0.]])
def test_aabb_and_radius_gates_are_retained_even_with_perfect_visual_features(offset):
    e = engine(physical_bias=-1., min_spatial=0.)
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))
    result = e.ingest((observation(1, planar_cloud() + offset, visual=[1, 0]),))
    assert result.object_ids != first.object_ids
    assert result.diagnostics["candidate_pairs"] == 0


def test_fork_keeps_recipe_and_rolls_back_cloud_and_feature_updates():
    e = engine(physical_bias=.2)
    first = e.ingest((observation(0, planar_cloud(), visual=[1, 0]),))
    before = e.export_active_state()
    trial = e.fork()
    result = trial.ingest((observation(1, planar_cloud(), visual=[0, 1]),))
    assert result.object_ids == first.object_ids
    assert trial.association_recipe == e.association_recipe
    assert e.export_active_state() == before
    assert trial.export_active_state() != before


def test_diagnostics_are_per_ingest_bounded_scalars_and_legacy_is_empty():
    e = engine(max_points=4)
    first = e.ingest((observation(0, planar_cloud()),))
    assert first.diagnostics["new_ids"] == 1
    assert first.diagnostics["capped_observations"] == 1
    assert first.diagnostics["observation_sample_points"] == 4
    result = e.ingest((observation(1, planar_cloud()),))
    assert result.diagnostics["matches"] == 1
    assert result.diagnostics["new_ids"] == 0
    assert result.diagnostics["recipe_id"] == "neusymnav:association:conceptgraphs:v1"
    assert len(json.dumps(dict(result.diagnostics))) < 2048
    assert all(type(v) in (str, int, float, bool, type(None)) for v in result.diagnostics.values())
    assert result.diagnostics["ambiguous"] == result.diagnostics["visual_pairs"] == 0
    assert result.diagnostics["fallback_observation_missing"] == 1
    duplicate = e.ingest((observation(1, planar_cloud()),))
    assert duplicate.diagnostics["matches"] == duplicate.diagnostics["new_ids"] == 0
    assert duplicate.diagnostics["observation_sample_points"] == 0
    with pytest.raises(TypeError):
        result.diagnostics["matches"] = 12
    assert AssociationEngine("e").ingest(()).diagnostics == {}


@pytest.mark.parametrize("mode", ["semantic", "geometry", "geometry_appearance"])
def test_explicit_legacy_recipe_keeps_original_assignment_and_checkpoint(mode):
    implicit = AssociationEngine("e", association_mode=mode)
    explicit = AssociationEngine("e", association_mode=mode, association_recipe={"mode": "legacy"})
    for frame in range(3):
        observations = (observation(frame, planar_cloud(), visual=[1, 0]),
                        observation(frame, planar_cloud() + [.5, 0., 0.], detection="other"))
        a, b = implicit.ingest(observations), explicit.ingest(observations)
        assert a == b
        assert implicit.export_active_state() == explicit.export_active_state()
        assert implicit._digest(observations[0]) == explicit._digest(observations[0])
