"""Schema-v2 compressed NPZ observations, with bounded non-pickle NPY reads.

Only the array containers change. Scalar fields and FrameKey retain the public
schema-v1 contract; constructors validate the decoded observation as usual.
"""
from __future__ import annotations

from dataclasses import fields
import io
import json
import math
import zipfile
import zlib

import numpy as np

from neusymnav.contracts import FrameKey, Observation

MAX_PAYLOAD_BYTES = 64 * 1024**2
MAX_DECODED_BYTES = 64 * 1024**2
MAX_METADATA_BYTES = 64 * 1024
ARRAY_NAMES = ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera', 'no_return', 'far_plane')


def encode(obs: Observation) -> bytes:
    scalars = {f.name: getattr(obs, f.name) for f in fields(obs) if f.name not in ARRAY_NAMES}
    scalars['key'] = obs.key.to_dict()
    scalars = {k: v.item() if isinstance(v, np.generic) else v for k, v in scalars.items()}
    arrays = [name for name in ARRAY_NAMES if getattr(obs, name) is not None]
    metadata = json.dumps(dict(format_version=2, contract_schema_version=1,
                               fields=scalars, arrays=arrays), sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode()
    if len(metadata) > MAX_METADATA_BYTES:
        raise ValueError('binary metadata exceeds reader bound')
    output = io.BytesIO()
    decoded_size = len(metadata)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr('metadata.json', metadata)
        for name in arrays:
            stream = io.BytesIO()
            np.lib.format.write_array(stream, getattr(obs, name), version=(1, 0), allow_pickle=False)
            raw = stream.getvalue()
            decoded_size += len(raw)
            if decoded_size > MAX_DECODED_BYTES:
                raise ValueError('binary arrays exceed reader bound')
            archive.writestr(name + '.npy', raw)
    payload = output.getvalue()
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError('binary payload exceeds reader bound')
    return payload


def _read_member(archive, info, limit):
    if not 0 <= info.file_size <= limit:
        raise ValueError('binary member exceeds decoded bound')
    with archive.open(info) as stream:
        raw = stream.read(info.file_size + 1)
    if len(raw) != info.file_size:
        raise ValueError('binary member size mismatch')
    return raw


def _array(raw):
    stream = io.BytesIO(raw)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=4096)
    elif version == (2, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream, max_header_size=4096)
    else:
        raise ValueError('unsupported NPY version')
    if (dtype.kind not in 'biuf' or dtype.hasobject or len(shape) > 3
            or any(type(n) is not int or n < 0 for n in shape)):
        raise ValueError('unsafe NPY dtype or shape')
    count = math.prod(shape)
    size = count * dtype.itemsize
    if size > MAX_DECODED_BYTES or len(raw) - stream.tell() != size:
        raise ValueError('NPY data size exceeds bound or disagrees with shape')
    return np.frombuffer(raw, dtype=dtype, count=count, offset=stream.tell()).reshape(shape, order='F' if fortran else 'C')


def decode(payload: bytes) -> Observation:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError('binary payload exceeds reader bound')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (len(infos) > 8 or len(set(names)) != len(names) or 'metadata.json' not in names
                    or any(name not in {'metadata.json', *(name + '.npy' for name in ARRAY_NAMES)} for name in names)
                    or any(info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                           or info.flag_bits & 1 for info in infos)
                    or sum(info.file_size for info in infos) > MAX_DECODED_BYTES):
                raise ValueError('invalid binary members or decoded size bound')
            metadata = json.loads(_read_member(archive, archive.getinfo('metadata.json'), MAX_METADATA_BYTES))
            if (set(metadata) != {'format_version', 'contract_schema_version', 'fields', 'arrays'}
                    or type(metadata['format_version']) is not int or metadata['format_version'] != 2
                    or type(metadata['contract_schema_version']) is not int or metadata['contract_schema_version'] != 1):
                raise ValueError('invalid binary metadata version')
            present = metadata['arrays']
            if (not isinstance(present, list) or any(not isinstance(name, str) for name in present)
                    or len(set(present)) != len(present) or not set(present).issubset(ARRAY_NAMES)
                    or not set(ARRAY_NAMES[:5]).issubset(present)
                    or set(names) != {'metadata.json', *(name + '.npy' for name in present)}):
                raise ValueError('invalid binary array inventory')
            values = metadata['fields']
            scalar_names = {f.name for f in fields(Observation)} - set(ARRAY_NAMES)
            if not isinstance(values, dict) or set(values) != scalar_names:
                raise ValueError('invalid binary metadata fields')
            values['key'] = FrameKey.from_dict(values['key'])
            for name in ARRAY_NAMES:
                values[name] = (_array(_read_member(archive, archive.getinfo(name + '.npy'), MAX_DECODED_BYTES))
                                if name in present else None)
            return Observation(**values)
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, KeyError, TypeError, AttributeError,
            UnicodeError, OverflowError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError(f'invalid binary payload: {exc}') from exc
