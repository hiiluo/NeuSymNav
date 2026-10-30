"""Optional isolated Triton ray-vote worker; importing this module needs only NumPy.

Wire v1 uses bounded framed JSON and two files inside a private ephemeral IPC
root. The request digest binds canonical geometry metadata and exact binary
rays. GPU failures are fatal to this backend: there is no implicit CPU fallback.
The five raw masks preserve independent free/hit votes; the map owner applies
occupied-wins after union with any other source masks.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys
import time
from typing import BinaryIO
import uuid

import numpy as np

PROTOCOL = 'neusymnav.gpu_raycast.v1'
MAX_FRAME_BYTES = 65536
LIMITS = dict(max_rays=100000, max_grid_cells=1000000, max_height_bins=256,
              max_output_bytes=128 * 1024**2, max_device_bytes=512 * 1024**2,
              max_samples_per_ray=100000, max_total_samples=50000000, max_json_bytes=MAX_FRAME_BYTES)
_GEOMETRY_KEYS = frozenset(('camera_origin_world', 'resolution_m', 'origin_x_m',
                          'origin_z_m', 'floor_y_m', 'robot_height_m', 'height_bin_m', 'ray_step_m'))
_REQUEST_KEYS = frozenset(('protocol', 'id', 'n', 'geometry', 'request_sha256'))


def _number(value, name):
    if type(value) not in (int, float):
        raise ValueError(f'{name} must be a finite number')
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f'{name} must be a finite number') from None
    if not math.isfinite(number):
        raise ValueError(f'{name} must be a finite number')
    return number


def _metadata(request):
    if type(request) is not dict or request.keys() != _REQUEST_KEYS:
        raise ValueError('request keys do not match protocol')
    if request['protocol'] != PROTOCOL:
        raise ValueError('unsupported protocol')
    tag = request['id']
    if type(tag) is not str:
        raise ValueError('id must be a canonical UUID')
    try:
        if str(uuid.UUID(tag)) != tag:
            raise ValueError('id must be a canonical UUID')
    except (ValueError, AttributeError):
        raise ValueError('id must be a canonical UUID') from None
    n = request['n']
    if type(n) is not int or not 0 <= n <= LIMITS['max_rays']:
        raise ValueError('ray count exceeds bounds')
    digest = request['request_sha256']
    if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('invalid request hash')
    g = request['geometry']
    if type(g) is not dict or g.keys() != _GEOMETRY_KEYS:
        raise ValueError('geometry keys do not match protocol')
    origin = g['camera_origin_world']
    if type(origin) is not list or len(origin) != 3:
        raise ValueError('camera origin must be a three-vector')
    geometry = {key: _number(value, key) for key, value in g.items() if key != 'camera_origin_world'}
    geometry['camera_origin_world'] = [_number(v, 'camera origin') for v in origin]
    if any(abs(v) > 1e9 for v in geometry['camera_origin_world']):
        raise ValueError('camera coordinates exceed bounds')
    if any(geometry[key] <= 0 for key in ('resolution_m', 'height_bin_m', 'ray_step_m')):
        raise ValueError('resolution, height bin and ray step must be positive')
    if geometry['robot_height_m'] <= geometry['height_bin_m']:
        raise ValueError('robot height must exceed one height bin')
    ratio = geometry['robot_height_m'] / geometry['height_bin_m']
    if not math.isfinite(ratio) or ratio > LIMITS['max_height_bins']:
        raise ValueError('height bins exceed bounds')
    return n, geometry, math.ceil(ratio)


@dataclass(frozen=True)
class ValidatedRequest:
    request_id: str
    request_sha256: str
    endpoints: np.ndarray
    returns: np.ndarray
    geometry: dict
    min_row: int
    min_col: int
    rows: int
    cols: int
    height_bins: int
    output_bytes: int
    total_samples: int


def validate_request(request: dict, payload: bytes) -> ValidatedRequest:
    """Validate all geometry, work and allocation limits before GPU imports."""
    n, geometry, bins = _metadata(request)
    if len(payload) != n * 25:
        raise ValueError('request binary length does not match ray count')
    endpoints = np.frombuffer(payload, dtype='<f8', count=n*3).reshape(n, 3)
    returns_raw = np.frombuffer(payload, dtype=np.uint8, count=n, offset=n*24)
    if not np.isfinite(endpoints).all() or np.any(np.abs(endpoints) > 1e9):
        raise ValueError('endpoints must contain bounded finite coordinates')
    if np.any(returns_raw > 1):
        raise ValueError('return flags must be zero or one')
    binding = json.dumps({'n': n, 'geometry': request['geometry']}, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    if hashlib.sha256(binding + b'\0' + payload).hexdigest() != request['request_sha256']:
        raise ValueError('request hash does not bind geometry and payload')
    rows = cols = min_row = min_col = total_samples = 0
    if n:
        origin = geometry['camera_origin_world']
        spans = []
        for axis, grid_origin in ((2, geometry['origin_z_m']), (0, geometry['origin_x_m'])):
            lo = (min(float(endpoints[:, axis].min()), origin[axis])-grid_origin)/geometry['resolution_m']
            hi = (max(float(endpoints[:, axis].max()), origin[axis])-grid_origin)/geometry['resolution_m']
            if not math.isfinite(lo) or not math.isfinite(hi) or max(abs(lo), abs(hi)) > 2**30:
                raise ValueError('grid coordinates exceed bounds')
            spans.append((math.floor(lo)-1, math.floor(hi)+1))
        min_row, max_row = spans[0]
        min_col, max_col = spans[1]
        rows, cols = max_row-min_row+1, max_col-min_col+1
        if rows*cols > LIMITS['max_grid_cells']:
            raise ValueError('grid cells exceed bounds')
        delta = endpoints - np.asarray(origin, dtype=np.float64)
        # Match Python's left-associated FP64 distance arithmetic (no reduction).
        distances = np.sqrt(delta[:, 0]*delta[:, 0] + delta[:, 1]*delta[:, 1] + delta[:, 2]*delta[:, 2])
        counts = np.maximum(1., np.ceil(distances / geometry['ray_step_m']))
        if not np.isfinite(counts).all() or counts.max() > LIMITS['max_samples_per_ray']:
            raise ValueError('samples per ray exceed bounds')
        total_samples = int(np.sum(counts.astype(np.int64)+1))
        if total_samples > LIMITS['max_total_samples']:
            raise ValueError('total ray samples exceed bounds')
    output_bytes = rows*cols*(3+2*bins)
    # Output is int32 on device. Count input tensors and parameter buffers too.
    device_bytes = output_bytes*5 + n*25 + 16*8
    if output_bytes > LIMITS['max_output_bytes'] or device_bytes > LIMITS['max_device_bytes']:
        raise ValueError('vote allocation exceeds bounds')
    endpoints.flags.writeable = False
    returns = returns_raw.view(np.bool_)
    returns.flags.writeable = False
    return ValidatedRequest(request['id'], request['request_sha256'], endpoints, returns,
                            geometry, min_row, min_col, rows, cols, bins, output_bytes, total_samples)


class PrivateIPC:
    """Fixed names and descriptor-relative operations inside an owner-only root."""
    def __init__(self, root):
        try:
            self.fd = os.open(os.fspath(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ValueError('IPC root must be a real private directory') from exc
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            os.close(self.fd)
            self.fd = -1
            raise ValueError('IPC root must be owned by current user with mode 0700')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)
        self.fd = -1

    def read_request(self, request):
        n, _, _ = _metadata(request)
        try:
            fd = os.open('request.bin', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        except OSError as exc:
            raise ValueError('request.bin must be a regular unlinked file') from exc
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_size != n*25:
                raise ValueError('request.bin type, owner or size invalid')
            payload = source.read(n*25+1)
        return validate_request(request, payload)

    def write_response(self, payload):
        if len(payload) > LIMITS['max_output_bytes']:
            raise ValueError('response exceeds output bound')
        fd = os.open('response.tmp', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'wb') as target:
                target.write(payload)
            os.replace('response.tmp', 'response.bin', src_dir_fd=self.fd, dst_dir_fd=self.fd)
        finally:
            try:
                os.unlink('response.tmp', dir_fd=self.fd)
            except FileNotFoundError:
                pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_frame(stream: BinaryIO):
    header = stream.read(4)
    if not header:
        raise EOFError('end of input')
    if len(header) != 4:
        raise ValueError('truncated frame header')
    length = struct.unpack('!I', header)[0]
    if not 0 < length <= MAX_FRAME_BYTES:
        raise ValueError('frame length exceeds bound')
    encoded = stream.read(length)
    if len(encoded) != length:
        raise ValueError('truncated frame body')
    def invalid_constant(value):
        raise ValueError('nonfinite JSON number')
    value = json.loads(encoded, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    if type(value) is not dict:
        raise ValueError('JSON frame must be an object')
    return value


def write_frame(stream: BinaryIO, payload):
    encoded = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
    if not 0 < len(encoded) <= MAX_FRAME_BYTES:
        raise ValueError('frame length exceeds bound')
    stream.write(struct.pack('!I', len(encoded)))
    stream.write(encoded)
    stream.flush()


def _make_kernel(triton, language, device_math):
    # Triton resolves JIT dependencies from function globals, not closures.
    global tl, libdevice
    tl, libdevice = language, device_math
    @triton.jit
    def vote_kernel(Points, Returns, FloatParams, IntParams, Output, BLOCK: tl.constexpr):
        lane = tl.program_id(0)*BLOCK + tl.arange(0, BLOCK)
        n = tl.load(IntParams+0)
        min_row = tl.load(IntParams+1)
        min_col = tl.load(IntParams+2)
        rows = tl.load(IntParams+3)
        cols = tl.load(IntParams+4)
        bins = tl.load(IntParams+5)
        ox = tl.load(FloatParams+0)
        oy = tl.load(FloatParams+1)
        oz = tl.load(FloatParams+2)
        resolution = tl.load(FloatParams+3)
        gx = tl.load(FloatParams+4)
        gz = tl.load(FloatParams+5)
        floor_y = tl.load(FloatParams+6)
        robot_height = tl.load(FloatParams+7)
        bin_m = tl.load(FloatParams+8)
        step_m = tl.load(FloatParams+9)
        ex = tl.load(Points+lane*3+0, lane < n, other=0.)
        ey = tl.load(Points+lane*3+1, lane < n, other=0.)
        ez = tl.load(Points+lane*3+2, lane < n, other=0.)
        returned = tl.load(Returns+lane, lane < n, other=0) != 0
        endpoint_height = ey-floor_y
        active = (lane < n) & ~(returned & (endpoint_height < -bin_m))
        er = libdevice.floor(libdevice.div_rn(ez-gz, resolution)).to(tl.int64)-min_row
        ec = libdevice.floor(libdevice.div_rn(ex-gx, resolution)).to(tl.int64)-min_col
        cells = rows*cols
        height_cells = cells*bins
        end_cell = er*cols+ec
        endpoint_valid = active & (er >= 0) & (er < rows) & (ec >= 0) & (ec < cols)
        tl.atomic_or(Output+2*cells+end_cell, 1, endpoint_valid & returned & (tl.abs(endpoint_height) <= bin_m), sem='relaxed')
        obstacle = endpoint_valid & returned & (endpoint_height >= bin_m) & (endpoint_height <= robot_height)
        end_bin = tl.minimum(libdevice.floor(libdevice.div_rn(endpoint_height, bin_m)).to(tl.int64), bins-1)
        dx, dy, dz = ex-ox, ey-oy, ez-oz
        distance = libdevice.sqrt_rn(dx*dx + dy*dy + dz*dz)
        samples = tl.maximum(1, libdevice.ceil(libdevice.div_rn(distance, step_m)).to(tl.int64))
        max_samples = tl.max(tl.where(active, samples, 0), 0)
        pending = tl.full((BLOCK,), False, tl.int1)
        pr = tl.full((BLOCK,), 0, tl.int64)
        pc = tl.full((BLOCK,), 0, tl.int64)
        ph = tl.full((BLOCK,), 0, tl.int64)
        step = tl.full((), 0, tl.int64)
        while step <= max_samples:
            enabled = active & (step <= samples)
            fraction = libdevice.div_rn(step.to(tl.float64), samples.to(tl.float64))
            px, py, pz = ox+dx*fraction, oy+dy*fraction, oz+dz*fraction
            row = libdevice.floor(libdevice.div_rn(pz-gz, resolution)).to(tl.int64)-min_row
            col = libdevice.floor(libdevice.div_rn(px-gx, resolution)).to(tl.int64)-min_col
            relative = py-floor_y
            height = libdevice.floor(libdevice.div_rn(relative, bin_m)).to(tl.int64)
            height = tl.where((relative >= 0.) & (relative <= robot_height), tl.minimum(height, bins-1), height)
            changed = enabled & (~pending | (row != pr) | (col != pc) | (height != ph))
            valid = changed & pending & (ph >= 1) & (ph < bins) & (pr >= 0) & (pr < rows) & (pc >= 0) & (pc < cols)
            pending_cell = pr*cols+pc
            tl.atomic_or(Output+pending_cell, 1, valid, sem='relaxed')
            tl.atomic_or(Output+3*cells+pending_cell*bins+ph, 1, valid, sem='relaxed')
            pr = tl.where(changed, row, pr)
            pc = tl.where(changed, col, pc)
            ph = tl.where(changed, height, ph)
            pending = pending | enabled
            step += 1
        tl.atomic_or(Output+cells+end_cell, 1, obstacle & (end_bin >= 0) & (end_bin < bins), sem='relaxed')
        tl.atomic_or(Output+3*cells+height_cells+end_cell*bins+end_bin, 1, obstacle & (end_bin >= 0) & (end_bin < bins), sem='relaxed')
    return vote_kernel


class GPUExecutor:
    """One FP64 kernel variant; all variable geometry is passed in tensors."""
    def __init__(self):
        import torch
        import triton
        import triton.language as tl
        from triton.language.extra.cuda import libdevice
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable')
        self.torch, self.triton = torch, triton
        self.kernel = _make_kernel(triton, tl, libdevice)
        props = torch.cuda.get_device_properties(0)
        self.execution = dict(torch_version=torch.__version__, triton_version=triton.__version__,
                              device_name=props.name, device_uuid=str(props.uuid),
                              capability=[props.major, props.minor], numeric_policy='fp64_ieee_fma_off')

    @property
    def compiled_variants(self):
        return sum(len(entry[0]) for entry in self.kernel.device_caches.values())

    def warmup(self):
        geometry = dict(camera_origin_world=[0., 1., 0.], resolution_m=.1, origin_x_m=0., origin_z_m=0.,
                        floor_y_m=0., robot_height_m=1.5, height_bin_m=.1, ray_step_m=.05)
        points = np.array([[.2, .1, .3]], dtype='<f8')
        payload = points.tobytes()+b'\1'
        metadata = dict(n=1, geometry=geometry)
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()+b'\0'+payload).hexdigest()
        self.collect(validate_request(dict(protocol=PROTOCOL, id=str(uuid.uuid4()), request_sha256=digest, **metadata), payload))

    def collect(self, value: ValidatedRequest):
        torch = self.torch
        cells, bins = value.rows*value.cols, value.height_bins
        if cells == 0:
            return tuple(np.zeros(shape, dtype=np.bool_) for shape in [(0, 0)]*3+[(0, 0, bins)]*2)
        g = value.geometry
        # Explicit dtypes avoid Triton treating Python floats as FP32 scalars.
        floats = torch.tensor(g['camera_origin_world'] + [g[k] for k in ('resolution_m', 'origin_x_m', 'origin_z_m', 'floor_y_m', 'robot_height_m', 'height_bin_m', 'ray_step_m')], dtype=torch.float64, device='cuda')
        integers = torch.tensor([len(value.endpoints), value.min_row, value.min_col, value.rows, value.cols, bins], dtype=torch.int64, device='cuda')
        points = torch.tensor(value.endpoints.copy(), dtype=torch.float64, device='cuda')
        returns = torch.tensor(value.returns.copy(), dtype=torch.uint8, device='cuda')
        output = torch.zeros(value.output_bytes, dtype=torch.int32, device='cuda')
        self.kernel[(self.triton.cdiv(len(value.endpoints), 128),)](points, returns, floats, integers, output, BLOCK=128, enable_fp_fusion=False)
        # This synchronizing copy includes GPU execution in the caller's timer.
        raw = output.to(torch.bool).cpu().numpy()
        bounds = [0, cells, 2*cells, 3*cells, 3*cells+cells*bins, value.output_bytes]
        return tuple(raw[bounds[i]:bounds[i+1]].reshape((value.rows, value.cols) if i < 3 else (value.rows, value.cols, bins)) for i in range(5))


def serve(root, stdin=None, stdout=None):
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout.buffer if stdout is None else stdout
    with PrivateIPC(root) as ipc:
        executor = GPUExecutor()
        executor.warmup()
        write_frame(stdout, dict(protocol=PROTOCOL, status='ready', backend='triton_cuda', limits=LIMITS, execution=executor.execution))
        while True:
            request = None
            try:
                request = read_frame(stdin)
            except EOFError:
                return 0
            except (ValueError, UnicodeError) as exc:
                write_frame(stdout, dict(protocol=PROTOCOL, id=None, status='error', error=str(exc)[:500]))
                return 2
            try:
                start = time.perf_counter()
                value = ipc.read_request(request)
                validated = time.perf_counter()
                masks = executor.collect(value)
                computed = time.perf_counter()
                payload = b''.join(mask.tobytes() for mask in masks)
                ipc.write_response(payload)
                finished = time.perf_counter()
                write_frame(stdout, dict(protocol=PROTOCOL, id=value.request_id, status='ok',
                            request_sha256=value.request_sha256, response_sha256=hashlib.sha256(payload).hexdigest(),
                            min_row=value.min_row, min_col=value.min_col, rows=value.rows, cols=value.cols,
                            height_bins=value.height_bins, response_bytes=len(payload),
                            timings_ms=dict(validation=(validated-start)*1000, kernel=(computed-validated)*1000,
                                            total=(finished-start)*1000)))
            except Exception as exc:
                tag = request.get('id') if type(request) is dict and type(request.get('id')) is str and len(request['id']) == 36 else None
                write_frame(stdout, dict(protocol=PROTOCOL, id=tag, status='error', error=f'{type(exc).__name__}: {exc}'[:500]))
                return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        return serve(args.root)
    except Exception as exc:
        print(f'GPU raycast worker startup failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
