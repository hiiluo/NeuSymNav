"""Convert canonical observations into immutable, pinned Hydra frame inputs."""
from __future__ import annotations

import numpy as np

from ...contracts.hydra_graph import (HydraCalibration, HydraFrame,
                                      _rotation_to_quaternion_wxyz)
from ...contracts.observations import (DetectionBatch, Observation, geometry_hash,
                                       require_rgbd, validate_detection_batch)
from ...geometry.frames import validate_pose


class HydraInputAdapter:
    @staticmethod
    def convert(observation: Observation, batch: DetectionBatch,
                calibration: HydraCalibration, labels: np.ndarray, *,
                detector_profile_id: str, labelspace_id: str,
                labelspace_hash: str) -> HydraFrame:
        require_rgbd(observation)
        if not isinstance(calibration, HydraCalibration):
            raise ValueError('calibration must be HydraCalibration')
        if calibration.calibration_id != observation.calibration_id:
            raise ValueError('calibration id mismatch')
        if calibration.sensor_id != observation.key.sensor_id:
            raise ValueError('calibration source sensor mismatch')
        if not np.array_equal(calibration.K, observation.K):
            raise ValueError('calibration intrinsics mismatch')
        validate_detection_batch(observation, batch)
        label_values = np.asarray(labels)
        if label_values.dtype != np.dtype(np.int32) or label_values.shape != observation.depth_m.shape:
            raise ValueError('semantic labels must be int32 and match source image shape')

        # T_world_camera = T_world_body @ T_body_camera; invert the extrinsics once.
        world_T_body = validate_pose(observation.T_world_camera) @ np.linalg.inv(calibration.body_T_camera)
        world_T_body = validate_pose(world_T_body)
        world_t_body = world_T_body[:3, 3].copy()
        world_R_body_wxyz = _rotation_to_quaternion_wxyz(world_T_body[:3, :3])

        # Hydra's float depth parser reads metres verbatim. Unknown/no-return/far-plane
        # samples stay NaN and are never converted into free space or a measured surface.
        depth = np.asarray(observation.depth_m, dtype=np.float32).copy()
        depth[~observation.valid_depth] = np.nan
        return HydraFrame(
            source_key=observation.key,
            capture_monotonic_ns=observation.capture_monotonic_ns,
            clock_domain=observation.clock_domain,
            sim_time_s=observation.sim_time_s,
            source_geometry_hash=geometry_hash(observation),
            calibration_id=calibration.calibration_id,
            calibration_version=calibration.version,
            calibration_hash=calibration.calibration_hash,
            detector_profile_id=detector_profile_id,
            vocabulary_id=batch.vocabulary_id,
            pose_version=observation.pose_version,
            coordinate_convention=calibration.coordinate_convention,
            camera_convention=calibration.camera_convention,
            depth_convention=calibration.depth_convention,
            rgb=observation.rgb,
            depth_m=depth,
            valid_depth=observation.valid_depth,
            labels=label_values,
            K=calibration.K,
            body_T_camera=calibration.body_T_camera,
            world_T_body=world_T_body,
            world_t_body=world_t_body,
            world_R_body_wxyz=world_R_body_wxyz,
            labelspace_id=labelspace_id,
            labelspace_hash=labelspace_hash,
            no_return=observation.no_return,
            far_plane=observation.far_plane,
            no_return_range_m=observation.no_return_range_m,
            far_plane_range_m=observation.far_plane_range_m,
        )
