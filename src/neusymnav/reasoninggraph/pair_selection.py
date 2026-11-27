"""Bounded selection of ordered, exact-frame relationship crops."""
from dataclasses import dataclass
from itertools import combinations
import math

from ..contracts.reasoninggraph import DetectionGeometry


@dataclass(frozen=True)
class PairCrop:
    subject: str
    object: str
    crop_xyxy: tuple[int, int, int, int]
    subject_xyxy: tuple[int, int, int, int]
    object_xyxy: tuple[int, int, int, int]
    distance_m: float


def _source(item):
    ref = item.evidence
    return (ref.source, ref.clock_domain, ref.capture_monotonic_ns, ref.pose_version, ref.calibration_hash,
            item.geometry_sha256, item.labelspace_hash, ref.vocabulary_id, ref.detector_hash,
            ref.detector_profile_id, ref.input_prefix_sha256)


def _clip(box, width, height):
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, width), min(y1, height)
    if x0 >= x1 or y0 >= y1:
        return None
    return x0, y0, x1, y1


def _relative(box, x, y):
    x0, y0, x1, y1 = box
    return x0-x, y0-y, x1-x, y1-y


def select_pairs(evidence, *, width, height, max_pairs=32, max_area_fraction=.5,
                 max_distance_m=5., allow_same_class=True):
    """Rank nearby co-visible detections with both subject/object roles preserved."""
    if any(type(value) is not int or not 1 <= value <= 8192 for value in (width, height)):
        raise ValueError('invalid source image size')
    if type(max_pairs) is not int or not 1 <= max_pairs <= 128 or len(evidence) > 128:
        raise ValueError('invalid relation pair budget')
    if (not 0 < max_area_fraction <= 1 or not math.isfinite(max_distance_m) or max_distance_m <= 0
            or type(allow_same_class) is not bool):
        raise ValueError('invalid relation selection policy')
    groups = {}
    for item in evidence:
        if not isinstance(item, DetectionGeometry):
            raise TypeError('pairs require per-instance detection geometry')
        lo, hi = item.bounds
        box = _clip(item.evidence.bbox_xyxy, width, height)
        if lo == hi or box is None:
            continue
        center = tuple((a+b)/2 for a,b in zip(lo,hi))
        group = groups.setdefault(_source(item), {})
        detection = item.evidence.detection_id
        if detection in group:
            raise ValueError('duplicate detection ID in relation frame')
        group[detection] = (box, center, item.category)
    if len(groups) != 1:
        return ()
    pairs = []
    detections = next(iter(groups.values()))
    for (a, (box_a, center_a, category_a)), (b, (box_b, center_b, category_b)) in combinations(sorted(detections.items()), 2):
        if not allow_same_class and category_a == category_b:
            continue
        distance = math.dist(center_a, center_b)
        union = (min(box_a[0],box_b[0]), min(box_a[1],box_b[1]), max(box_a[2],box_b[2]), max(box_a[3],box_b[3]))
        x0, y0, x1, y1 = union
        if distance > max_distance_m or (x1-x0)*(y1-y0) > max_area_fraction*width*height:
            continue
        relative_a, relative_b = _relative(box_a,x0,y0), _relative(box_b,x0,y0)
        pairs.append(PairCrop(a, b, union, relative_a, relative_b, distance))
        pairs.append(PairCrop(b, a, union, relative_b, relative_a, distance))
    return tuple(sorted(pairs, key=lambda pair: (pair.distance_m, pair.subject, pair.object))[:max_pairs])
