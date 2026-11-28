"""Conservative RGB-D confirmation for active native IDs in a causal sidecar."""

from collections import Counter, defaultdict, deque
from hashlib import sha256

import numpy as np

from .association_receipts import InstanceAnchor, InstanceConfirmation
from .lifecycle import validate_progress


def _pixels(points, observation, *, tolerance):
    camera = (points - observation.T_world_camera[:3, 3]) @ observation.T_world_camera[:3, :3]
    camera = camera[np.isfinite(camera).all(axis=1) & (camera[:, 2] >= .1) & (camera[:, 2] < 5.)]
    height, width = observation.depth_m.shape
    uv = np.rint((camera @ observation.K.T)[:, :2] / camera[:, 2, None]).astype(np.int64)
    inside = (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    u, v = uv[inside].T
    valid = observation.valid_depth[v, u] & (abs(observation.depth_m[v, u] - camera[inside, 2]) <= tolerance)
    return np.unique(v[valid] * width + u[valid])


def native_mesh_claims(observation, detections, meshes):
    pixels = {raw: _pixels(points, observation, tolerance=.15) for raw, points in meshes.items()}
    claims = {}
    for detection in detections:
        mask = detection.mask.ravel()
        ranked = sorted(((float(mask[indices].mean()), raw) for raw, indices in pixels.items()
                         if len(indices) >= 12 and np.count_nonzero(mask[indices]) >= 12), reverse=True)
        if ranked and ranked[0][0] >= .75 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] > .15):
            claims[detection.detection_id] = ranked[0][1]
    counts = Counter(claims.values())
    return {d: raw for d, raw in claims.items() if counts[raw] == 1}


def _sample(observation, mask):
    depth = observation.depth_m
    v, u = np.nonzero(mask & observation.valid_depth & (depth >= .1) & (depth < 5.))
    if len(u) > 512:
        take = np.linspace(0, len(u) - 1, 512, dtype=int)
        v, u = v[take], u[take]
    points = (np.column_stack((u, v, np.ones(len(u)))) @ np.linalg.inv(observation.K).T) * depth[v, u, None]
    return points @ observation.T_world_camera[:3, :3].T + observation.T_world_camera[:3, 3]


def _scores(source, target, masks):
    support = {}
    for name, points in source.items():
        if len(points) < 40:
            continue
        indices = _pixels(points, target, tolerance=.08)
        if len(indices) >= max(40, .2 * len(points)):
            for detection, mask in masks.items():
                support[name, detection] = float(mask.ravel()[indices].mean())
    return support


def _best(scores):
    grouped = defaultdict(list)
    for (first, second), score in scores.items():
        grouped[first].append((score, second))
    result = {}
    for first, choices in grouped.items():
        choices.sort(reverse=True)
        if choices[0][0] >= .75 and (len(choices) == 1 or choices[0][0] - choices[1][0] > .10):
            result[first] = choices[0][1]
    return result


class LiveInstanceConfirmation:
    """Apply the two-intermediate RGB-D rule to a bounded accepted history."""

    def __init__(self):
        self._history = deque()
        self._edges = {}
        self._bytes = 0

    def clear(self):
        self._history.clear()
        self._edges.clear()
        self._bytes = 0

    def observe(self, token, observation, batch, lineage, claims):
        if (lineage is None or lineage.token != token.native or token.source != observation.key
                or len(batch.detections) > 16 or not batch.allows_negative_evidence):
            self.clear()
            return ()
        masks = {d.detection_id: d.mask for d in batch.detections}
        points = {name: _sample(observation, mask) for name, mask in masks.items()}
        charge = sum(a.nbytes for a in (observation.rgb, observation.depth_m, observation.valid_depth,
                    observation.no_return, observation.far_plane, *masks.values(), *points.values()) if a is not None)
        if charge > 48 * 1024**2:
            self.clear()
            return ()
        revision = token.native.graph_revision
        if self._history:
            prior, _, _, _, _, epoch, _ = self._history[-1]
            try:
                validate_progress(prior, token)
            except ValueError:
                self.clear()
                return ()
            if revision != prior.native.graph_revision + 1 or epoch != lineage.epoch:
                self.clear()
        while self._history and (len(self._history) >= 24 or self._bytes + charge > 48 * 1024**2):
            self._bytes -= self._history.popleft()[-1]
        oldest = self._history[0][0].native.graph_revision if self._history else revision
        self._edges = {edge: score for edge, score in self._edges.items() if edge[0][0] >= oldest}
        by_revision = {}
        for prior, obs, prior_masks, prior_points, prior_claims, epoch, _ in self._history:
            r = prior.native.graph_revision
            by_revision[r] = (prior, prior_claims, epoch)
            fw, bw = _scores(prior_points, observation, masks), _scores(points, obs, prior_masks)
            symmetric = {key: min(score, bw[key[::-1]]) for key, score in fw.items() if key[::-1] in bw}
            left = _best(symmetric)
            right = _best({key[::-1]: score for key, score in symmetric.items()})
            for first, second in left.items():
                if right.get(second) == first:
                    self._edges[(r, first), (revision, second)] = symmetric[first, second]
        neighbours = defaultdict(set)
        for left, right in self._edges:
            neighbours[left].add(right)
            neighbours[right].add(left)
        proofs = []
        for detection, endpoint in claims.items():
            if endpoint not in lineage.objects:
                continue
            current = revision, detection
            anchors, owners = [], set()
            for before in sorted(neighbours[current]):
                mids = sorted({p[0] for p in neighbours[before] & neighbours[current] if before[0] < p[0] < revision})
                if len(mids) < 2:
                    continue
                prior, assignments, epoch = by_revision[before[0]]
                raw = assignments.get(before[1])
                if raw is None:
                    continue
                owners.add(raw)
                score = self._edges[before, current]
                proof_hash = sha256(repr((prior.native.input_prefix_sha256, token.native.input_prefix_sha256,
                                          before, current, mids, score)).encode()).hexdigest()
                anchors.append(InstanceAnchor(prior, before[1], raw, epoch, tuple(mids), proof_hash))
            if owners == {endpoint} and len({a.token.native.graph_revision for a in anchors}) >= 2:
                proofs.append(InstanceConfirmation(token, detection, endpoint, tuple(anchors[:2])))
        self._history.append((token, observation, masks, points, dict(claims), lineage.epoch, charge))
        self._bytes += charge
        return tuple(proofs)
