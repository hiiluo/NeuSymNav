"""The GPU worker's trust boundary is CPU-testable without Torch or CUDA."""
import builtins
import hashlib
import io
import json
import os
import struct
import uuid

import numpy as np
import pytest

from neusymnav.mapping import gpu_raycast_worker as worker


def request(endpoints=None, returns=None, **geometry_changes):
    endpoints = np.asarray([[.2, .5, .3]] if endpoints is None else endpoints, dtype='<f8').reshape(-1, 3)
    returns = np.ones(len(endpoints), dtype=np.uint8) if returns is None else np.asarray(returns, dtype=np.uint8)
    geometry = dict(camera_origin_world=[0., 1., 0.], resolution_m=.1, origin_x_m=0.,
                    origin_z_m=0., floor_y_m=0., robot_height_m=1.5, height_bin_m=.1, ray_step_m=.05)
    geometry.update(geometry_changes)
    payload = endpoints.tobytes() + returns.tobytes()
    metadata = dict(n=len(endpoints), geometry=geometry)
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\0' + payload).hexdigest()
    return dict(protocol=worker.PROTOCOL, id=str(uuid.uuid4()), request_sha256=digest, **metadata), payload


def test_request_geometry_matches_cpu_window_and_keeps_fp64():
    req, payload = request([[-.1, .1, -.2], [.2, 1.5, .3]])
    value = worker.validate_request(req, payload)
    assert (value.min_row, value.min_col, value.rows, value.cols, value.height_bins) == (-3, -2, 7, 6, 15)
    assert value.endpoints.dtype == np.float64
    assert value.endpoints.flags.writeable is False
    assert value.output_bytes == value.rows * value.cols * 33


@pytest.mark.parametrize('change', [dict(n=True), dict(n=100001), dict(id='not-a-uuid'), dict(extra=1), dict(protocol='old'), dict(request_sha256='0'*64)])
def test_bad_metadata_rejected_before_gpu_import(change, monkeypatch):
    req, payload = request()
    req.update(change)
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split('.')[0] in {'torch', 'triton'}:
            raise AssertionError('invalid input imported GPU dependencies')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    with pytest.raises(ValueError):
        worker.validate_request(req, payload)


@pytest.mark.parametrize('geometry', [dict(resolution_m=0.), dict(ray_step_m=1e-100), dict(height_bin_m=1e-100), dict(robot_height_m=True), dict(camera_origin_world=[0, 0]), dict(origin_x_m=float('inf')), dict(origin_x_m=10**1000), dict(resolution_m=1e-10)])
def test_unbounded_geometry_rejected_before_allocation(geometry):
    req, payload = request()
    req['geometry'].update(geometry)
    # Validation must reject malformed geometry before its binding digest.
    with pytest.raises(ValueError):
        worker.validate_request(req, payload)


@pytest.mark.parametrize('payload_change', [lambda p: p[:-1], lambda p: p+b'\0', lambda p: p[:-1]+b'\2', lambda p: np.array([[np.nan, 0., 0.]], dtype='<f8').tobytes()+b'\1'])
def test_binary_payload_is_exact_finite_and_bound_to_geometry(payload_change):
    req, payload = request()
    with pytest.raises(ValueError):
        worker.validate_request(req, payload_change(payload))


def test_changing_geometry_invalidates_request_binding():
    req, payload = request()
    req['geometry']['origin_x_m'] = .01
    with pytest.raises(ValueError, match='hash'):
        worker.validate_request(req, payload)


def test_empty_request_has_empty_window():
    req, payload = request([])
    value = worker.validate_request(req, payload)
    assert (value.rows, value.cols, value.output_bytes, value.total_samples) == (0, 0, 0, 0)


def test_private_root_rejects_symlinks_world_access_and_request_links(tmp_path):
    root = tmp_path / 'ipc'
    root.mkdir(mode=0o700)
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        worker.PrivateIPC(link)
    root.chmod(0o755)
    with pytest.raises(ValueError):
        worker.PrivateIPC(root)
    root.chmod(0o700)
    req, payload = request()
    outside = tmp_path / 'outside'
    outside.write_bytes(payload)
    (root / 'request.bin').symlink_to(outside)
    with worker.PrivateIPC(root) as ipc:
        with pytest.raises(ValueError):
            ipc.read_request(req)


def test_binary_files_are_atomic_and_size_bound(tmp_path):
    tmp_path.chmod(0o700)
    req, payload = request()
    (tmp_path / 'request.bin').write_bytes(payload)
    with worker.PrivateIPC(tmp_path) as ipc:
        assert ipc.read_request(req).output_bytes > 0
        ipc.write_response(b'\1\0')
        assert (tmp_path / 'response.bin').read_bytes() == b'\1\0'
        (tmp_path / 'request.bin').write_bytes(payload+b'\0')
        with pytest.raises(ValueError):
            ipc.read_request(req)


def test_framing_is_bounded_closed_and_duplicate_free():
    target = io.BytesIO()
    worker.write_frame(target, {'status': 'ok'})
    assert worker.read_frame(io.BytesIO(target.getvalue())) == {'status': 'ok'}
    for body in [b'{"x":1,"x":2}', b'{"x":NaN}', b'[]']:
        with pytest.raises(ValueError):
            worker.read_frame(io.BytesIO(struct.pack('!I', len(body))+body))
    for encoded in [b'\0', struct.pack('!I', 65537), struct.pack('!I', 5)+b'{}']:
        with pytest.raises((ValueError, EOFError)):
            worker.read_frame(io.BytesIO(encoded))


@pytest.mark.skipif(os.environ.get('NEUSYMNAV_RUN_GPU_TESTS') != '1', reason='requires explicit single GPU-slot authorization')
def test_gpu_exact_reference_parity_and_single_kernel_variant():
    from neusymnav.mapping._raycast_kernel import _collect_votes_impl
    executor = worker.GPUExecutor()
    executor.warmup()
    rng = np.random.default_rng(19)
    cases = [np.array([[.2, .1, -.3], [0., 1.5, 0.], [.01, -.2, .01], [0., 0., 0.]]),
             rng.uniform([-1., -.2, -1.], [1., 2., 1.], (137, 3)), np.empty((0, 3))]
    for points in cases:
        for step in [.05, .13]:
            req, payload = request(points, rng.choice([0, 1], len(points)), ray_step_m=step, origin_x_m=-.03, origin_z_m=.07)
            value = worker.validate_request(req, payload)
            actual = executor.collect(value)
            g = value.geometry
            expected = _collect_votes_impl(value.endpoints, value.returns, np.asarray(g['camera_origin_world']), g['resolution_m'], g['origin_x_m'], g['origin_z_m'], g['floor_y_m'], g['robot_height_m'], g['height_bin_m'], g['ray_step_m'], value.min_row, value.min_col, value.rows, value.cols, value.height_bins)
            for got, want in zip(actual, expected):
                assert np.array_equal(got, want)
    assert executor.compiled_variants == 1


@pytest.mark.parametrize('points, geometry, expected', [
    ([[1000., 1., 1000.]], {}, 'grid cells'),
    ([[50., 1., 50.]], dict(robot_height_m=25.6), 'allocation'),
    (np.tile([[1., 1., 0.]], (600, 1)), dict(ray_step_m=.00001), 'total ray samples'),
])
def test_each_independent_work_and_memory_budget_is_enforced(points, geometry, expected):
    req, payload = request(points, **geometry)
    with pytest.raises(ValueError, match=expected):
        worker.validate_request(req, payload)


def test_request_rejects_hard_link_and_fifo_without_blocking(tmp_path):
    tmp_path.chmod(0o700)
    req, payload = request()
    original = tmp_path / 'original'
    original.write_bytes(payload)
    source = tmp_path / 'request.bin'
    os.link(original, source)
    with worker.PrivateIPC(tmp_path) as ipc:
        with pytest.raises(ValueError):
            ipc.read_request(req)
        source.unlink()
        os.mkfifo(source)
        with pytest.raises(ValueError):
            ipc.read_request(req)


def test_existing_response_tmp_symlink_is_not_followed(tmp_path):
    tmp_path.chmod(0o700)
    victim = tmp_path / 'victim'
    victim.write_bytes(b'unchanged')
    (tmp_path / 'response.tmp').symlink_to(victim)
    with worker.PrivateIPC(tmp_path) as ipc:
        with pytest.raises(OSError):
            ipc.write_response(b'new')
    assert victim.read_bytes() == b'unchanged'


def test_import_has_no_gpu_dependency_side_effects():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c', "import sys; import neusymnav.mapping.gpu_raycast_worker; assert 'torch' not in sys.modules and 'triton' not in sys.modules"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
