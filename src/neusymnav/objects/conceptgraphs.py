"""Bounded directional overlap inspired by ConceptGraphs, with exact NN queries.

Reference: concept-graphs commit8aca1172, conceptgraph/slam/{mapping,utils}.py.
This adaptation uses canonical metric clouds, deterministic observation voxels,
the complete bounded map cloud, and Hungarian assignment in our existing owner.

MIT License
Copyright (c) 2023 concept-graphs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .association_recipe import AssociationRecipe


@dataclass(frozen=True)
class ObservationSample:
    points: np.ndarray
    capped: bool


def sample_observation(points: np.ndarray, recipe: AssociationRecipe) -> ObservationSample:
    """One deterministic mean per voxel, evenly capped in canonical voxel order.

    Sort coordinates before summation as well as sorting voxel keys; otherwise
    floating-point summation would still depend on incoming point order.
    Temporary storage scales with the already validated input observation;
    retained samples and all nearest-neighbor queries are bounded by max_points.
    """
    ordered = points[np.lexsort((points[:, 2], points[:, 1], points[:, 0]))]
    keys = np.floor(ordered / recipe.voxel_m).astype(np.int64)
    _, inverse, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    sums = np.zeros((len(counts), 3), dtype=np.float64)
    np.add.at(sums, inverse, ordered)
    centers = sums / counts[:, None]
    capped = len(centers) > recipe.max_points
    if capped:
        indices = np.linspace(0, len(centers) - 1, recipe.max_points, dtype=np.int64)
        centers = centers[indices]
    immutable = np.frombuffer(centers.tobytes(), dtype=np.float64).reshape(centers.shape)
    return ObservationSample(immutable, capped)


def directional_overlap(
    observation_points: np.ndarray,
    map_points: np.ndarray | cKDTree,
    *,
    nn_distance_m: float,
) -> float:
    """Fraction of observation samples strictly within tolerance of the map.

    A tree supplied by the owner contains the entire bounded map cloud and is
    reused for every observation in the batch. eps=0 makes queries exact.
    """
    tree = map_points if isinstance(map_points, cKDTree) else cKDTree(map_points)
    distances = tree.query(observation_points, k=1, eps=0)[0]
    return float(np.mean(distances < nn_distance_m))
