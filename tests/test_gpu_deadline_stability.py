"""The failed request must retain actionable, bounded deadline diagnostics."""
import numpy as np
import pytest

from test_gpu_raycast_client import client, fake_worker, geometry


def test_whole_operation_timeout_records_slow_response_read(tmp_path, fake_worker, monkeypatch):
    import neusymnav.mapping.gpu_raycast_client as module

    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    c = client(tmp_path)
    original = c._read_response

    def slow_read(size):
        result = original(size)
        clock[0] += .251
        return result

    monkeypatch.setattr(c, '_read_response', slow_read)
    with pytest.raises(TimeoutError, match='GPU whole-operation deadline exceeded') as caught:
        c.collect(np.array([[.1, 0., .1]]), np.array([0., 1.5, 0.]), **geometry())
    failure = c.runtime_metadata['last_failure']
    assert failure['error_type'] == 'CompletedRequestDeadline'
    assert failure['stage'] == 'final_deadline'
    assert failure['stage_ms']['response_read'] == pytest.approx(251.)
    assert failure['elapsed_ms'] == pytest.approx(251.)
    assert c.calls == 0 and not c._wire.closed
    assert isinstance(failure['recoverable'], bool) and failure['recoverable']
    assert c.runtime_metadata['completed_deadline_misses'] == 1
    assert type(caught.value) is module.CompletedRequestDeadline
    old_id = c._wire.request['id']
    monkeypatch.setattr(c, '_read_response', original)
    votes = c.collect(np.array([[-.2, .3, -.2]]), np.array([0., 1.5, 0.]), **geometry())
    from neusymnav.mapping._raycast_kernel import collect_ray_votes
    expected = collect_ray_votes(np.array([[-.2, .3, -.2]]), np.array([0., 1.5, 0.]), backend='python', **geometry())
    assert c._wire.request['id'] != old_id
    assert votes.min_row == expected.min_row and votes.min_col == expected.min_col
    for name in ('planar_free', 'planar_hit', 'floor_hit', 'height_free', 'height_hit'):
        assert np.array_equal(getattr(votes, name), getattr(expected, name))
    assert c.calls == 1
    c.close()


def test_receive_timeout_records_inflight_stage_without_worker_timings(tmp_path, fake_worker, monkeypatch):
    import neusymnav.mapping.gpu_raycast_client as module

    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    c = client(tmp_path)

    def timeout(deadline):
        clock[0] = deadline
        raise TimeoutError('GPU response deadline')

    monkeypatch.setattr(c._wire, 'receive', timeout)
    with pytest.raises(TimeoutError, match='GPU response deadline'):
        c.collect(np.array([[.1, 0., .1]]), np.array([0., 1.5, 0.]), **geometry())
    failure = c.runtime_metadata['last_failure']
    assert failure['stage'] == 'receive'
    assert failure['stage_ms']['receive'] == pytest.approx(250.)
    assert 'worker_timings_ms' not in failure
    assert c.calls == 0 and c._wire.closed


@pytest.mark.parametrize('corruption', ['hash', 'shape', 'mask2'])
def test_late_invalid_response_remains_fatal(tmp_path, fake_worker, monkeypatch, corruption):
    import neusymnav.mapping.gpu_raycast_client as module
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    c = client(tmp_path)
    c._wire.corruption = corruption
    original = c._read_response
    def slow_read(size):
        result = original(size)
        clock[0] += .251
        return result
    monkeypatch.setattr(c, '_read_response', slow_read)
    with pytest.raises(ValueError):
        c.collect(np.array([[.1, 0., .1]]), np.array([0., 1.5, 0.]), **geometry())
    assert c._wire.closed and c.calls == 0
    assert not c.runtime_metadata['last_failure']['recoverable']


def test_typed_exception_from_receive_is_not_recoverable(tmp_path, fake_worker, monkeypatch):
    import neusymnav.mapping.gpu_raycast_client as module
    c = client(tmp_path)
    def incomplete(_deadline):
        raise module.CompletedRequestDeadline('unexpected incomplete response')
    monkeypatch.setattr(c._wire, 'receive', incomplete)
    with pytest.raises(TimeoutError) as caught:
        c.collect(np.array([[.1, 0., .1]]), np.array([0., 1.5, 0.]), **geometry())
    assert type(caught.value) is TimeoutError
    assert c._wire.closed and not c.runtime_metadata['last_failure']['recoverable']
