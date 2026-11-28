import numpy as np

from tools.psg_nav.probe_rgbd_continuity import (
    DepthView, borrow_native_anchors, corroborated_links, match_views, measure_link_colour,
    supported_links,
)


def view(depth=None, translation=0.0):
    transform = np.eye(4)
    transform[0, 3] = translation
    return DepthView(np.full((40, 40), 2.0) if depth is None else depth,
                     np.array([[40., 0., 19.5], [0., 40., 19.5], [0., 0., 1.]]),
                     transform)


def mask(x, width=12):
    result = np.zeros((40, 40), dtype=bool)
    result[10:22, x:x+width] = True
    return result


def test_pose_compensation_preserves_instance_and_rejects_adjacent_mask():
    original = view()
    shifted = view(translation=.2)
    links = match_views(original, {"a": mask(14)}, shifted,
                        {"b": mask(10), "other": mask(24)})
    assert list(links) == [("a", "b")]
    assert links["a", "b"] == 1.0


def test_occlusion_and_competing_masks_abstain():
    original = view()
    blocked = view(depth=np.ones((40, 40)))
    assert not match_views(original, {"a": mask(14)}, blocked, {"b": mask(14)})
    assert not match_views(original, {"a": mask(14)}, original,
                           {"b": mask(14), "c": mask(14)})


def test_support_needs_distinct_frames_and_respects_cannot_link():
    links = {("O(1)", "O(2)"): [(1, 2), (1, 3)],
             ("O(3)", "O(4)"): [(1, 2), (3, 4)],
             ("O(5)", "O(6)"): [(1, 2), (2, 3), (3, 4)],
             ("O(7)", "O(8)"): [(1, 2), (2, 3)]}
    assert supported_links(links, {("O(3)", "O(4)")}) == {
        ("O(5)", "O(6)"): ((1, 2), (3, 4))
    }


def test_anchor_consensus_requires_older_distinct_revisions_and_present_endpoint():
    history = {"a": [(1, "O(1)"), (2, "O(1)")],
               "same_frame": [(1, "O(2)"), (1, "O(2)")],
               "gone": [(1, "O(3)"), (2, "O(3)")],
               "conflict": [(1, "O(2)"), (2, "O(4)"), (3, "O(2)")],
               "future": [(1, "O(4)"), (4, "O(4)")]}
    assert borrow_native_anchors(history, {"O(1)", "O(2)", "O(4)"}, {}, revision=4) == {
        "a": "O(1)"
    }


def test_anchor_consensus_abstains_when_detections_compete():
    prior = [(1, "O(1)"), (2, "O(1)")]
    assert not borrow_native_anchors({"a": prior, "b": prior}, {"O(1)"}, {}, revision=3)
    assert not borrow_native_anchors({"a": prior}, {"O(1)"}, {"b": "O(1)"}, revision=3)


def test_colour_residual_uses_corresponding_pixels_after_pose_compensation():
    first, second = view(), view(translation=.2)
    rgb = np.zeros((40, 40, 3), dtype=np.uint8)
    rgb[mask(14)] = (20, 130, 50)
    shifted = np.zeros_like(rgb)
    shifted[mask(10)] = (25, 130, 43)
    a, b = {"a": mask(14)}, {"b": mask(10)}
    candidates = match_views(first, a, second, b)
    assert measure_link_colour(first, a, rgb, second, b, shifted, candidates) == {("a", "b"): 7.0}


def test_corroboration_requires_two_intermediate_revisions_and_ignores_future():
    a, b = (1, "a"), (4, "b")
    middle, other, repeated, future = (2, "c"), (3, "d"), (2, "e"), (5, "f")
    links = [(a, b), (a, middle), (middle, b), (a, repeated), (repeated, b),
             (a, future), (b, future)]
    assert (a, b) not in corroborated_links(links)
    assert corroborated_links(links + [(a, other), (other, b)])[(a, b)] == (2, 3)
