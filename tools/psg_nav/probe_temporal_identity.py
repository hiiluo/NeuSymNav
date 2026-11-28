"""Evaluate cross-revision mesh evidence for native identity in offline replay."""

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


MAX_AGE = 12
MIN_POINTS = 12
MAX_POINTS = 1024
DISTANCE_METRES = .10
MIN_MUTUAL_COVERAGE = .55
MIN_MARGIN = .15


def propose_temporal_links(rows):
    """Return pairs with their first two confirming revisions for adjudication."""
    history = {}
    cannot_link = set()
    confirmations = defaultdict(list)
    previous_revision = 0
    for revision, surfaces, simultaneous_pairs in rows:
        if revision <= previous_revision:
            raise ValueError("replay revisions must strictly increase")
        previous_revision = revision
        cannot_link.update(tuple(sorted(pair)) for pair in simultaneous_pairs)
        history = {key: item for key, item in history.items() if revision - item[0] <= MAX_AGE}
        geometries = {}
        candidates = {}
        for endpoint, points in sorted(surfaces.items()):
            if not MIN_POINTS <= len(points) <= MAX_POINTS:
                continue
            xyz = np.asarray(points, dtype=float)
            if xyz.shape != (len(points), 3) or not np.isfinite(xyz).all():
                raise ValueError("expected finite world-space mesh vertices")
            tree = cKDTree(xyz)
            geometries[endpoint] = revision, xyz, tree
            ranked = []
            for prior, (_, old_xyz, old_tree) in history.items():
                pair = tuple(sorted((prior, endpoint)))
                if prior == endpoint or pair in cannot_link:
                    continue
                coverage = min(float(np.mean(old_tree.query(xyz)[0] <= DISTANCE_METRES)),
                               float(np.mean(tree.query(old_xyz)[0] <= DISTANCE_METRES)))
                ranked.append((coverage, prior))
            ranked.sort(key=lambda item: (-item[0], item[1]))
            if ranked and ranked[0][0] >= MIN_MUTUAL_COVERAGE:
                if len(ranked) == 1 or ranked[0][0] - ranked[1][0] > MIN_MARGIN:
                    candidates[endpoint] = ranked[0][1]
        claims = Counter(candidates.values())
        for endpoint, prior in candidates.items():
            if claims[prior] == 1:
                pair = tuple(sorted((endpoint, prior)))
                votes = confirmations[pair]
                if not votes or votes[-1] != revision:
                    votes.append(revision)
        history.update(geometries)
    return {pair: tuple(revisions[:2]) for pair, revisions in sorted(confirmations.items())
            if len(revisions) >= 2 and pair not in cannot_link}


def load_replay(rows):
    scenes = defaultdict(list)
    pins = {}
    for row in rows:
        scene = row["scene"]
        sequence = scenes[scene]
        native = row["native"]
        scope = tuple(native[key] for key in ("source_sha256", "build_sha256", "config_sha256"))
        if scope != pins.setdefault(scene, scope) or row["revision"] != len(sequence) + 1:
            raise ValueError("expected an unbroken native replay with fixed build and config")
        surfaces = {key: points for key, points in row["mesh_segments"].items()
                    if len(row["visible_pixels"].get(key, ())) >= MIN_POINTS}
        endpoints = sorted(set(row["a1"].values()))
        sequence.append((row["revision"], surfaces, tuple(combinations(endpoints, 2))))
    return scenes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.replay.read_bytes()
    scenes = load_replay(json.loads(raw)["rows"])
    result = {
        "scope": "offline proposals on raw native endpoints, subject to adjudication",
        "replay_sha256": hashlib.sha256(raw).hexdigest(),
        "settings": {"max_age_revisions": MAX_AGE, "minimum_points": MIN_POINTS,
                     "distance_metres": DISTANCE_METRES, "minimum_coverage": MIN_MUTUAL_COVERAGE,
                     "minimum_margin": MIN_MARGIN, "confirmations": 2},
        "scenes": {
            scene: {"revisions": len(rows), "pairs": [
                {"pair": pair, "confirming_revisions": revisions}
                for pair, revisions in propose_temporal_links(rows).items()
            ]} for scene, rows in sorted(scenes.items())
        },
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
