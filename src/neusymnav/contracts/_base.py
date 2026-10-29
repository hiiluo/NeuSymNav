"""Validation and owned immutable storage for schema v1 messages."""
from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
import numpy as np

SCHEMA_VERSION = 1
REGISTRY: dict[str, type] = {}


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    return value


def integer(value, name, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return int(value)


def finite(value, name, minimum=None):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f'{name} must be a finite number')
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f'{name} must be finite' + (f' and >= {minimum}' if minimum is not None else ''))
    return result


def boolean(value, name):
    if not isinstance(value, bool):
        raise ValueError(f'{name} must be bool')


def choice(value, allowed, name):
    if value not in allowed:
        raise ValueError(f'{name} must be one of {sorted(allowed)}')


def digest(value, name='geometry_hash'):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError(f'{name} must be lowercase SHA256')
    return value


def array(value, name, *, dtype=None, shape=None, ndim=None, finite_only=True):
    if not isinstance(value, np.ndarray) or value.dtype.kind not in 'biuf':
        raise ValueError(f'{name} must be a numeric ndarray')
    if dtype is not None and value.dtype != np.dtype(dtype):
        raise ValueError(f'{name} must have dtype {np.dtype(dtype)}')
    if shape is not None and (value.ndim != len(shape) or any(want is not None and got != want for got, want in zip(value.shape, shape))):
        raise ValueError(f'{name} has invalid shape; expected {shape}')
    if ndim is not None and value.ndim != ndim:
        raise ValueError(f'{name} must have ndim {ndim}')
    if finite_only and not np.isfinite(value).all():
        raise ValueError(f'{name} must be finite')
    # A bytes-backed buffer cannot be made writeable, unlike a setflags(False) owner.
    return np.frombuffer(value.tobytes(order='C'), dtype=value.dtype).reshape(value.shape)


def coordinates(value, count, name):
    try:
        result = tuple(value)
    except TypeError as exc:
        raise ValueError(f'{name} must have {count} coordinates') from exc
    if len(result) != count:
        raise ValueError(f'{name} must have {count} coordinates')
    return tuple(finite(v, name) for v in result)


def freeze(value):
    if isinstance(value, np.ndarray):
        return array(value, 'value', finite_only=False)
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError('mapping keys must be strings')
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, Contract) or value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f'unsupported immutable value {type(value).__name__}')


def typed_tuple(value, cls, name):
    result = tuple(value)
    if any(not isinstance(v, cls) for v in result):
        raise ValueError(f'{name} must contain {cls.__name__}')
    return result


def string_tuple(value, name):
    if not isinstance(value, (tuple, list)):
        raise ValueError(f'{name} must be a tuple or list of strings')
    result = tuple(value)
    for v in result:
        text(v, name)
    if len(result) != len(set(result)):
        raise ValueError(f'{name} contains duplicates')
    return result


def typed_mapping(value, cls, name):
    if not isinstance(value, Mapping):
        raise ValueError(f'{name} must be a mapping')
    for key, item in value.items():
        text(key, name)
        if not isinstance(item, cls):
            raise ValueError(f'{name} values must be {cls.__name__}')
    return freeze(value)


class Contract:
    schema_version = SCHEMA_VERSION

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        REGISTRY[cls.__name__] = cls

    def to_dict(self):
        from .serialization import to_dict
        return to_dict(self)

    def to_json(self):
        from .serialization import dumps
        return dumps(self)

    @classmethod
    def from_dict(cls, payload):
        from .serialization import from_dict
        result = from_dict(payload)
        if not isinstance(result, cls):
            raise ValueError(f'expected {cls.__name__}')
        return result

    @classmethod
    def from_json(cls, payload):
        from .serialization import loads
        result = loads(payload)
        if not isinstance(result, cls):
            raise ValueError(f'expected {cls.__name__}')
        return result
