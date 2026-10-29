"""Deterministic CPU-only encoder used to exercise crop and normalization code."""
from __future__ import annotations

import numpy as np


def encode(crop_rgb: np.ndarray) -> np.ndarray:
    means = np.asarray(crop_rgb, dtype=np.float64).mean(axis=(0, 1)).astype(np.float32)
    vector = np.zeros(512, dtype=np.float32)
    vector[:3] = means
    return vector
