import numpy as np


def observation(**changes):
    from neusymnav.contracts.observations import FrameKey, Observation
    values = dict(key=FrameKey('episode', 'rgbd', 0), capture_monotonic_ns=100,
                  clock_domain='host:boot1', sim_time_s=0.,
                  rgb=np.zeros((2, 3, 3), np.uint8), depth_m=np.ones((2, 3), np.float32),
                  valid_depth=np.ones((2, 3), bool),
                  K=np.array([[2., 0., 1.], [0., 2., .5], [0., 0., 1.]]),
                  T_world_camera=np.eye(4), calibration_id='calibration:v1', pose_version=0,
                  modality='rgbd')
    values.update(changes)
    return Observation(**values)
