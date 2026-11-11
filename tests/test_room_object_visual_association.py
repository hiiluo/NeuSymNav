import numpy as np

from tools.audit_room_object_visual_association import project_support_points


def test_projects_native_mesh_support_and_checks_captured_depth():
    points=np.array([[0.,0.,2.],[0.1,0.,2.]])
    depth=np.full((5,5),2.,dtype=np.float32)
    valid=np.ones((5,5),dtype=bool)
    K=np.array([[1.,0.,2.],[0.,1.,2.],[0.,0.,1.]])
    result=project_support_points(points,depth,valid,K,np.eye(4),tolerance_m=.01)
    assert result['projected_count']==2
    assert result['inlier_count']==2
    assert result['inlier_ratio']==1.
    assert result['median_abs_depth_error_m']==0.
    assert [tuple(p) for p in result['pixels']]==[(2,2),(2,2)]


def test_rejects_points_behind_camera_outside_image_and_invalid_depth():
    points=np.array([[0.,0.,-1.],[20.,0.,2.],[0.,0.,2.]])
    depth=np.full((5,5),2.,dtype=np.float32)
    valid=np.ones((5,5),dtype=bool);valid[2,2]=False
    K=np.array([[1.,0.,2.],[0.,1.,2.],[0.,0.,1.]])
    result=project_support_points(points,depth,valid,K,np.eye(4),tolerance_m=.01)
    assert result['projected_count']==1
    assert result['inlier_count']==0
    assert result['inlier_ratio']==0.
    assert result['median_abs_depth_error_m'] is None

