"""Strict portable payload for split relationship encoder/decoder fixtures."""
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json

import numpy as np

from ..contracts._base import choice, digest, text


MAX_TOKEN_BYTES = 8 * 1024**2


@dataclass(frozen=True)
class RelFeatureSpec:
    encoder_sha256: str
    decoder_sha256: str
    tokenizer_sha256: str
    prompt_sha256: str
    cut_point: str
    tile_layout: str
    token_count: int
    dimension: int
    dtype: str = '<f2'
    schema_version: int = 1

    def __post_init__(self):
        for name in ('encoder_sha256', 'decoder_sha256', 'tokenizer_sha256', 'prompt_sha256'):
            digest(getattr(self, name), name)
        for name in ('cut_point', 'tile_layout'):
            if len(text(getattr(self, name), name)) > 128:
                raise ValueError('invalid visual token layout')
        choice(self.dtype, {'<f2', '<f4'}, 'visual token dtype')
        if (type(self.schema_version) is not int or self.schema_version != 1
                or type(self.token_count) is not int or type(self.dimension) is not int
                or not 1 <= self.token_count <= 16384 or not 1 <= self.dimension <= 8192
                or self.nbytes > MAX_TOKEN_BYTES):
            raise ValueError('invalid visual token shape or schema')

    @property
    def nbytes(self):
        return self.token_count * self.dimension * np.dtype(self.dtype).itemsize


@dataclass(frozen=True)
class RelationTokens:
    spec: RelFeatureSpec
    subject: str
    object_id: str
    payload: bytes
    sha256: str


def _validate_endpoints(subject, object_id):
    if (len(text(subject, 'subject')) > 256 or len(text(object_id, 'object_id')) > 256
            or subject == object_id):
        raise ValueError('invalid ordered relationship endpoints')


def _checksum(spec, subject, object_id, payload):
    header = json.dumps((asdict(spec), subject, object_id), sort_keys=True, separators=(',', ':')).encode()
    value = hashlib.sha256(header + b'\0')
    value.update(payload)
    return value.hexdigest()


def pack_tokens(spec, array, *, subject, object_id):
    if not isinstance(spec, RelFeatureSpec):
        raise TypeError('expected RelFeatureSpec')
    _validate_endpoints(subject, object_id)
    if (not isinstance(array, np.ndarray) or array.shape != (spec.token_count, spec.dimension)
            or array.dtype != np.dtype(spec.dtype)):
        raise ValueError('visual token shape or dtype mismatch')
    if not np.isfinite(array).all():
        raise ValueError('visual tokens must be finite')
    payload = array.tobytes(order='C')
    return RelationTokens(spec, subject, object_id, payload, _checksum(spec, subject, object_id, payload))


def decode_tokens(asset, expected):
    if not isinstance(asset, RelationTokens) or not isinstance(expected, RelFeatureSpec) or asset.spec != expected:
        raise ValueError('visual encoder, decoder or token layout mismatch')
    _validate_endpoints(asset.subject, asset.object_id)
    if (not isinstance(asset.payload, bytes) or len(asset.payload) != expected.nbytes
            or not isinstance(asset.sha256, str)
            or not hmac.compare_digest(_checksum(expected, asset.subject, asset.object_id, asset.payload),
                                       asset.sha256)):
        raise ValueError('visual token integrity mismatch')
    result = np.frombuffer(asset.payload, dtype=expected.dtype).reshape(expected.token_count, expected.dimension)
    if not np.isfinite(result).all():
        raise ValueError('visual tokens must be finite')
    return result
