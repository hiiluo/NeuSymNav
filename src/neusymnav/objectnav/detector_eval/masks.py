"""Compact, exact boolean-mask run-length encoding (row-major, starts with a 0-run)."""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np


def rle_encode(mask: np.ndarray) -> dict:
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError('mask must be 2-D')
    flat = mask.ravel()
    change = np.flatnonzero(np.diff(flat.astype(np.int8))) + 1
    edges = np.concatenate(([0], change, [flat.size]))
    runs = np.diff(edges).tolist()
    if flat.size and flat[0]:
        runs = [0] + runs
    return {'shape': [int(mask.shape[0]), int(mask.shape[1])], 'runs': [int(r) for r in runs]}


def rle_decode(rle: dict) -> np.ndarray:
    h, w = (int(v) for v in rle['shape'])
    runs = np.asarray(rle['runs'], dtype=np.int64)
    if runs.sum() != h * w or np.any(runs < 0):
        raise ValueError('RLE runs do not cover the mask')
    values = np.zeros(len(runs), dtype=bool)
    values[1::2] = True
    return np.repeat(values, runs).reshape(h, w)


def bbox_xyxy(mask: np.ndarray) -> List[int]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError('empty mask has no box')
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.count_nonzero(a & b)
    if not inter:
        return 0.0
    return inter / float(np.count_nonzero(a | b))


def dominant_instance(ids: np.ndarray, mask: np.ndarray, ignore: Sequence[int] = (0,)) -> Tuple[int, float]:
    """Semantic instance covering most of ``mask`` and its share of the mask."""
    values = np.asarray(ids)[np.asarray(mask, dtype=bool)]
    total = values.size
    if not total:
        return 0, 0.0
    values = values[~np.isin(values, list(ignore) + [4294967295])]
    if not values.size:
        return 0, 0.0
    uniques, counts = np.unique(values, return_counts=True)
    best = int(np.argmax(counts))
    return int(uniques[best]), float(counts[best]) / total
