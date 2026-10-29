"""Selected ConceptGraphs count-weighted normalized feature fusion.

Source: ref_ConceptGraph/concept-graphs/conceptgraph/slam/utils.py,
merge_obj2_into_obj1 clip_ft branch (pinned in runs/p05-owner/source-hashes.json).
Only accepted unique DETECTED events receive weight. Event uniqueness belongs
in the durable owner ledger, not in an unbounded in-memory event set.
"""
from __future__ import annotations
import numpy as np

AGGREGATION_ID = 'conceptgraphs-count-normalize:v1'


def normalize_visual(value):
    """Normalize finite input without overflowing its squared L2 norm."""
    vector=np.asarray(value,dtype=np.float64)
    if vector.ndim!=1 or not len(vector) or not np.isfinite(vector).all():
        raise ValueError('visual embedding must be a finite vector')
    scale=float(np.max(np.abs(vector)))
    if scale==0:
        raise ValueError('visual embedding must be nonzero')
    scaled=vector/scale
    normalized=scaled/np.linalg.norm(scaled)
    return np.frombuffer(normalized.tobytes(),dtype=normalized.dtype)


def fuse_visual(left, left_weight, right, right_weight):
    """Return (unit vector or unavailable, total event weight).

    None with positive weight represents the source's zero vector after exact
    cancellation. It remains unavailable for scoring, retaining its vote count.
    Memory is one vector and one event count per live canonical object.
    """
    if any(type(n) is not int or n < 0 for n in (left_weight,right_weight)):
        raise ValueError('appearance weights must be nonnegative event counts')
    values=[]
    for value in (left,right):
        if value is not None:
            vector=np.asarray(value,dtype=np.float64)
            if vector.ndim!=1 or not len(vector) or not np.isfinite(vector).all():
                raise ValueError('appearance aggregate must be a finite vector')
            values.append(vector)
    if len(values)==2 and values[0].shape!=values[1].shape:
        raise ValueError('appearance feature space/dimension mismatch')
    total=left_weight+right_weight
    if not values or not total:
        return None,total
    combined=np.zeros_like(values[0])
    if left is not None: combined+=np.asarray(left)*left_weight
    if right is not None: combined+=np.asarray(right)*right_weight
    combined/=total
    norm=float(np.linalg.norm(combined))
    if norm<=1e-12:
        return None,total
    result=combined/norm
    return np.frombuffer(result.tobytes(),dtype=result.dtype),total
