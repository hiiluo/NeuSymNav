"""Offline RGB-D observation links for native identity experiments."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

import numpy as np


MAX_SAMPLES = 512
MIN_VISIBLE_PIXELS = 40
MIN_VISIBLE_FRACTION = .20
DEPTH_TOLERANCE_METRES = .08
MIN_MASK_AGREEMENT = .75
MIN_MARGIN = .10


@dataclass(frozen=True)
class DepthView:
    depth: np.ndarray
    intrinsics: np.ndarray
    world_from_camera: np.ndarray


def _projected_support(source, masks, target):
    source_to_target = np.linalg.solve(target.world_from_camera, source.world_from_camera)
    inverse = np.linalg.inv(source.intrinsics)
    height, width = target.depth.shape
    support = {}
    valid = np.isfinite(source.depth) & (source.depth >= .1) & (source.depth < 5.)
    for name, mask in masks.items():
        if mask.shape != source.depth.shape or mask.dtype != np.bool_:
            raise ValueError("expected an aligned boolean instance mask")
        v, u = np.nonzero(mask & valid)
        if len(u) < MIN_VISIBLE_PIXELS:
            continue
        if len(u) > MAX_SAMPLES:
            samples = np.linspace(0, len(u)-1, MAX_SAMPLES, dtype=int)
            v, u = v[samples], u[samples]
        camera = np.column_stack((u, v, np.ones(len(u)))) @ inverse.T
        points = camera * source.depth[v, u, None]
        points = points @ source_to_target[:3, :3].T + source_to_target[:3, 3]
        forward = (points[:, 2] >= .1) & (points[:, 2] < 5.)
        pixels = points[forward] @ target.intrinsics.T
        z = pixels[:, 2]
        uv = np.rint(pixels[:, :2] / z[:, None]).astype(int)
        inside = (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
        col, row = uv[inside].T
        measured = target.depth[row, col]
        visible = ((measured >= .1) & (measured < 5.)
                   & (np.abs(measured-z[inside]) <= DEPTH_TOLERANCE_METRES))
        indices, first_sample = np.unique(row[visible]*width + col[visible], return_index=True)
        if len(indices) >= max(MIN_VISIBLE_PIXELS, MIN_VISIBLE_FRACTION*len(u)):
            source_indices = v * source.depth.shape[1] + u
            support[name] = indices, source_indices[forward][inside][visible][first_sample]
    return support


def _unique_best(scores):
    by_source = defaultdict(list)
    for (source, target), score in scores.items():
        by_source[source].append((score, target))
    best = {}
    for source, candidates in by_source.items():
        candidates.sort(reverse=True)
        score, target = candidates[0]
        if score >= MIN_MASK_AGREEMENT and (len(candidates) == 1 or score-candidates[1][0] > MIN_MARGIN):
            best[source] = target
    return best


def match_views(first, first_masks, second, second_masks):
    """Find mutual unique mask matches using visible depth reprojection in both directions."""
    forward = _projected_support(first, first_masks, second)
    reverse = _projected_support(second, second_masks, first)
    scores = {
        (a, b): min(float(second_masks[b].ravel()[pixels_a].mean()),
                    float(first_masks[a].ravel()[pixels_b].mean()))
        for a, (pixels_a, _) in forward.items() for b, (pixels_b, _) in reverse.items()
    }
    left = _unique_best(scores)
    right = _unique_best({(b, a): score for (a, b), score in scores.items()})
    return {(a, b): scores[a, b] for a, b in left.items() if right.get(b) == a}


def measure_link_colour(first, first_masks, first_rgb, second, second_masks, second_rgb, links):
    """Measure the worse directional median RGB error on depth-supported mask matches."""
    if not links:
        return {}
    for view, rgb in ((first, first_rgb), (second, second_rgb)):
        if rgb.shape != (*view.depth.shape, 3) or rgb.dtype != np.uint8:
            raise ValueError("expected aligned uint8 RGB")
    forward = _projected_support(first, {a: first_masks[a] for a, _ in links}, second)
    reverse = _projected_support(second, {b: second_masks[b] for _, b in links}, first)

    def residual(indices, mask, source, target):
        destination, origin = indices
        keep = mask.ravel()[destination]
        if np.count_nonzero(keep) < MIN_VISIBLE_PIXELS:
            return None
        difference = (source.reshape(-1, 3)[origin[keep]].astype(np.int16)
                      - target.reshape(-1, 3)[destination[keep]].astype(np.int16))
        return float(np.median(np.abs(difference).max(axis=1)))

    errors = {}
    for a, b in links:
        if a not in forward or b not in reverse:
            continue
        x = residual(forward[a], second_masks[b], first_rgb, second_rgb)
        y = residual(reverse[b], first_masks[a], second_rgb, first_rgb)
        if x is not None and y is not None:
            errors[a, b] = max(x, y)
    return errors


def corroborated_links(links):
    """Keep observed links with matching intermediates at two distinct earlier frames."""
    links = tuple(links)
    neighbours = defaultdict(set)
    for earlier, later in links:
        if earlier[0] >= later[0]:
            raise ValueError("observation links must point forward within one episode")
        neighbours[earlier].add(later)
        neighbours[later].add(earlier)

    corroborated = {}
    for earlier, later in links:
        revisions = {middle[0] for middle in neighbours[earlier] & neighbours[later]
                     if earlier[0] < middle[0] < later[0]}
        if len(revisions) >= 2:
            corroborated[earlier, later] = tuple(sorted(revisions))
    return corroborated


def supported_links(links, cannot_link):
    """Require two witnesses with no shared frame."""
    supported = {}
    for pair, witnesses in sorted(links.items()):
        if pair in cannot_link:
            continue
        for a, b in combinations(sorted(set(witnesses)), 2):
            if len({*a, *b}) == 4:
                supported[pair] = (a, b)
                break
    return supported


def borrow_native_anchors(history, current_nodes, current_assignments, *, revision):
    """Propose only unclaimed endpoints unanimously supported by two prior revisions."""
    used = set(current_assignments.values())
    candidates = {}
    for detection, anchors in sorted(history.items()):
        if detection in current_assignments or any(stamp >= revision for stamp, _ in anchors):
            continue
        owners = {owner for _, owner in anchors}
        if len(owners) != 1 or len({stamp for stamp, _ in anchors}) < 2:
            continue
        owner, = owners
        if owner in current_nodes and owner not in used:
            candidates[detection] = owner
    counts = Counter(candidates.values())
    return {detection: owner for detection, owner in candidates.items() if counts[owner] == 1}
