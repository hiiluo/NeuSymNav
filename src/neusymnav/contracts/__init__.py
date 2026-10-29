"""Public schema-v1 contracts (CPU-only; no model/simulator imports)."""
from .observations import (AppearanceBatch, AppearanceEncoder, AppearanceFeature, Detection,
    DetectionBatch, Detector, FrameKey, ObjectObservation, Observation, PoseSource, Projector,
    Taxonomy, age_ns, geometry_hash, require_rgbd, validate_appearance_batch,
    validate_detection_batch, validate_object_observations)
from .graphs import (CommitResult, GridState, HierarchyComposer, HierarchyEdge, HierarchyNode,
    HierarchySnapshot, NavMapper, NavSnapshot, ObjectOwner, ObjectSnapshot, ObjectState,
    Region, RegionBackend, RegionGrid, RegionSnapshot, VerificationOwner)
from .navigation import MotionCommand, MotionGuard, NavigationDecision, Navigator
from .serialization import dumps, from_dict, loads, to_dict
