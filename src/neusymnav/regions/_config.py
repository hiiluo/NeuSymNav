"""Pinned source algorithm parameters; schema-v1 raster policy is fixed."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class RegionTrackerConfig:
    enabled: bool = True
    min_bbox_iou: float = .20
    max_centroid_distance_m: float = 1.5
    min_area_ratio: float = .25
    max_area_ratio: float = 4.
    max_missed_updates: int = 3

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.max_missed_updates) is not int or self.max_missed_updates<0:
            raise ValueError('invalid tracker configuration')
        values=(self.min_bbox_iou,self.max_centroid_distance_m,self.min_area_ratio,self.max_area_ratio)
        if any(isinstance(v,bool) or not math.isfinite(v) for v in values) or not 0<=self.min_bbox_iou<=1 or self.max_centroid_distance_m<0 or not 0<self.min_area_ratio<=self.max_area_ratio:
            raise ValueError('invalid tracker gates')

@dataclass(frozen=True)
class RegionGuardConfig:
    preserve_previous_on_invalid_update: bool = True
    publish_stale_regions_on_reject: bool = True
    min_valid_region_count: int = 1
    max_unknown_ratio_for_update: float = .98
    max_region_area_drop_ratio: float = .85
    max_region_count_drop_ratio: float = .85

    def __post_init__(self):
        if type(self.preserve_previous_on_invalid_update) is not bool or type(self.publish_stale_regions_on_reject) is not bool or type(self.min_valid_region_count) is not int or self.min_valid_region_count<0:
            raise ValueError('invalid guard configuration')
        if any(isinstance(v,bool) or not math.isfinite(v) or not 0<=v<=1 for v in (self.max_unknown_ratio_for_update,self.max_region_area_drop_ratio,self.max_region_count_drop_ratio)):
            raise ValueError('invalid guard ratios')
