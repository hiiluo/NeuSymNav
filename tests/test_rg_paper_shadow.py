from dataclasses import replace

from contract_helpers import observation
from neusymnav.contracts import DetectionBatch, FrameKey


def test_shadow_pins_fixed_rig_and_persists_same_sensor_detector_pair(tmp_path):
    from neusymnav.reasoninggraph.paper_shadow import PaperShadowCapture, read_shadow_manifest

    source = observation()
    original = DetectionBatch.from_observation(source, (), vocabulary_id='paper')
    moved = replace(source, key=FrameKey(source.key.episode_id, source.key.sensor_id, 1),
                    calibration_id='changed')
    capture = PaperShadowCapture(tmp_path, max_frames=2)
    assert capture.offer(source, original, robot_xyz=(0., 0., 0.), yaw_rad=0., tilt_rad=0.)
    assert not capture.offer(moved, DetectionBatch.from_observation(moved, (), vocabulary_id='paper'),
                             robot_xyz=(0., 0., 0.), yaw_rad=0., tilt_rad=.5)
    summary = capture.close()
    assert summary['complete'] and summary['written'] == 1
    assert summary['counts']['calibration_changed'] == 1
    samples = tuple(read_shadow_manifest(tmp_path))
    assert len(samples) == 1 and samples[0][0].geometry_hash == source.geometry_hash
    assert samples[0][1].to_dict() == original.to_dict()


def test_shadow_rejects_detector_source_mismatch_and_records_drop(tmp_path):
    from neusymnav.reasoninggraph.paper_shadow import PaperShadowCapture

    source = observation()
    mismatched = replace(source, key=FrameKey(source.key.episode_id, source.key.sensor_id, 99))
    batch = DetectionBatch.from_observation(mismatched, (), vocabulary_id='paper')
    capture = PaperShadowCapture(tmp_path)
    assert not capture.offer(source, batch, robot_xyz=(0., 0., 0.), yaw_rad=0., tilt_rad=0.)
    result = capture.close()
    assert result['written'] == 0 and result['counts']['source_mismatch'] == 1


def test_consistent_but_wrong_body_translation_is_rejected():
    import pytest
    from tools.reasoninggraph.replay_paper_shadow import verify_recorded_pose

    source = observation()
    audited = {source.geometry_hash: dict(input_pose=dict(robot_xy=[1., 2.], z_m=.3,
                                                         yaw_rad=.1, tilt_rad=0.))}
    verify_recorded_pose(source, ((1., 2., .3), .1, 0.), audited)
    with pytest.raises(ValueError, match='body pose'):
        verify_recorded_pose(source, ((2., 2., .3), .1, 0.), audited)


def test_shadow_cadence_preserves_later_keyframes(tmp_path):
    from neusymnav.reasoninggraph.paper_shadow import PaperShadowCapture

    source = observation()
    capture = PaperShadowCapture(tmp_path, min_interval_ns=1_000_000_000)
    for index, delta, accepted in ((0, 0, True), (1, 100_000_000, False), (2, 1_100_000_000, True)):
        frame = replace(source, key=FrameKey(source.key.episode_id, source.key.sensor_id, index),
                        capture_monotonic_ns=source.capture_monotonic_ns + delta)
        batch = DetectionBatch.from_observation(frame, (), vocabulary_id='paper')
        assert capture.offer(frame, batch, robot_xyz=(0., 0., 0.), yaw_rad=0., tilt_rad=0.) is accepted
    report = capture.close()
    assert report['written'] == 2 and report['counts']['cadence'] == 1
