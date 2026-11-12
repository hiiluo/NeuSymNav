from types import SimpleNamespace

import numpy as np


def test_fps_selection_uses_source_capture_timestamps_and_keeps_first_frame():
    from tools.compare_rebuild_room_sampling import select_fps_frames
    frames=[SimpleNamespace(capture_monotonic_ns=value) for value in
            (1_000_000_000,1_100_000_000,1_500_000_000,1_900_000_000,2_000_000_000)]
    selected=select_fps_frames(frames,2.0)
    assert [frame.capture_monotonic_ns for frame in selected]==[
        1_000_000_000,1_500_000_000,2_000_000_000]


def test_m3_coverage_reports_known_and_occupied_retention():
    from tools.compare_rebuild_room_sampling import compare_m3
    full=SimpleNamespace(origin_xy=(0.,0.),resolution_m=.1,
                         states=np.array([[-1,0,100],[0,100,100]],np.int8))
    sampled=SimpleNamespace(origin_xy=(.1,0.),resolution_m=.1,
                            states=np.array([[0,100],[100,100]],np.int8))
    result=compare_m3(full,sampled)
    assert result['full_known_cells']==5
    assert result['known_recall']==.8
    assert result['occupied_recall']==1.
    assert result['occupied_precision']==1.


def test_stage_summary_preserves_native_stage_timing_and_unattributed_gap():
    from tools.compare_rebuild_room_sampling import stage_timing_summary
    journal=[dict(reason='processed',timings_ms={'m4_runtime_ms':4.},mapping_work={
        'input_pixel_count':10,'valid_mask_pixel_count':8,'backprojected_hit_count':7,
        'point_count':7,'m1_runtime_ms':1.,'m2_runtime_ms':2.,'m3_runtime_ms':3.,
        'm1_m2_m3_runtime_ms':8.5})]
    result=stage_timing_summary(journal)
    assert result['stage_timings_ms']['m4_runtime_ms']['p50']==4.
    assert result['mapping_work']['point_count']['p50']==7.
    assert result['mapping_work']['m1_m2_m3_unattributed_residual_ms']['p50']==2.5
