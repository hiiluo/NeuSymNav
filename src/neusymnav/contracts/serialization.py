"""Strict schema-v1 JSON wire format; ndarray bytes preserve dtype and NaNs.

Decoding only constructs registered public contracts; no module imports from
wire values, pickle, or writable views are used.
"""
from __future__ import annotations
import base64
from collections.abc import Mapping
from dataclasses import fields
import json
import numpy as np
from ._base import Contract, REGISTRY, SCHEMA_VERSION


def _encode(value):
    if isinstance(value, Contract):
        return {'type': type(value).__name__, 'fields': {f.name: _encode(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, np.ndarray):
        return {'ndarray': {'dtype': value.dtype.str, 'shape': list(value.shape),
                             'data': base64.b64encode(value.tobytes(order='C')).decode('ascii')}}
    if isinstance(value, Mapping):
        return {'mapping': {k: _encode(v) for k, v in value.items()}}
    if isinstance(value, tuple):
        return {'tuple': [_encode(v) for v in value]}
    if isinstance(value, np.generic):
        return value.item()
    return value


def _decode(value):
    if not isinstance(value, dict):
        if isinstance(value, list):
            raise ValueError('unexpected list on wire')
        return value
    if set(value) == {'type', 'fields'}:
        cls = REGISTRY.get(value['type'])
        if cls is None or not isinstance(value['fields'], dict):
            raise ValueError('unknown contract type')
        names = {f.name for f in fields(cls)}
        if set(value['fields']) != names:
            raise ValueError('contract fields do not match schema')
        return cls(**{k: _decode(v) for k, v in value['fields'].items()})
    if set(value) == {'ndarray'}:
        arr = value['ndarray']
        if not isinstance(arr, dict) or set(arr) != {'dtype', 'shape', 'data'}:
            raise ValueError('invalid ndarray wire value')
        dtype = np.dtype(arr['dtype'])
        if dtype.kind not in 'biuf':
            raise ValueError('unsafe ndarray dtype')
        shape = arr['shape']
        if not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape):
            raise ValueError('invalid ndarray shape')
        data = base64.b64decode(arr['data'], validate=True)
        count = 1
        for dimension in shape:
            count *= dimension
        if len(data) != count * dtype.itemsize:
            raise ValueError('ndarray byte size mismatch')
        return np.frombuffer(data, dtype=dtype).reshape(shape)
    if set(value) == {'tuple'} and isinstance(value['tuple'], list):
        return tuple(_decode(v) for v in value['tuple'])
    if set(value) == {'mapping'} and isinstance(value['mapping'], dict):
        return {k: _decode(v) for k, v in value['mapping'].items()}
    raise ValueError('unrecognized wire value')


def to_dict(value: Contract) -> dict:
    if not isinstance(value, Contract):
        raise ValueError('root must be a contract')
    return {'schema_version': SCHEMA_VERSION, 'payload': _encode(value)}


def from_dict(value: dict) -> Contract:
    # Load the fixed registry independent of import order.
    from . import observations, graphs, navigation  # noqa: F401
    if not isinstance(value, dict) or set(value) != {'schema_version', 'payload'} or type(value['schema_version']) is not int or value['schema_version'] != SCHEMA_VERSION:
        raise ValueError('unsupported schema_version or envelope')
    try:
        result = _decode(value['payload'])
    except (TypeError, KeyError, OverflowError) as exc:
        raise ValueError('invalid schema-v1 payload') from exc
    if not isinstance(result, Contract):
        raise ValueError('root must be a contract')
    return result


def dumps(value: Contract) -> str:
    return json.dumps(to_dict(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def loads(value: str) -> Contract:
    def invalid_constant(value):
        raise ValueError(f'invalid JSON constant {value}')
    return from_dict(json.loads(value, parse_constant=invalid_constant))
