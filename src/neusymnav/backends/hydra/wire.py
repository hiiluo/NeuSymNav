"""Fast byte-identical HydraFrame serialization for the trusted worker wire."""
from __future__ import annotations

import json

from ...contracts.hydra_graph import HydraFrame
from ...contracts.serialization import to_dict


_BASE64_ALPHABET=b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='


def _token(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=True,allow_nan=False).encode('ascii')


def _append_string(value,raw,escaped):
    token=_token(value)
    raw.append(token)
    # The outer value is a JSON string containing the raw JSON bytes. Escaping
    # this small metadata token with stdlib semantics preserves the old oracle.
    outer=json.dumps(token.decode('ascii'),separators=(',',':'),
        ensure_ascii=True,allow_nan=False).encode('ascii')
    escaped.append(outer[1:-1])


def _append_base64(value,raw,escaped):
    if type(value) is not str:
        raise ValueError('trusted ndarray data string required')
    try:data=value.encode('ascii')
    except UnicodeEncodeError as exc:raise ValueError('ndarray data must be ASCII base64') from exc
    if data.translate(None,_BASE64_ALPHABET):
        raise ValueError('unexpected character in trusted ndarray base64')
    padding=len(data)-len(data.rstrip(b'='))
    first_padding=data.find(b'=')
    if (len(data)%4 or padding>2 or
            (first_padding>=0 and first_padding<len(data)-padding)):
        raise ValueError('malformed trusted ndarray base64')
    # Base64 has no quote, backslash, or control bytes, so its content is safe
    # and identical in both JSON layers. Only the surrounding quotes differ.
    raw.extend((b'"',data,b'"'))
    escaped.extend((b'\\"',data,b'\\"'))


def _append_ndarray(node,raw,escaped):
    if type(node) is not dict or set(node)!={'dtype','shape','data'}:
        raise ValueError('unexpected ndarray wire fields')
    if type(node['dtype']) is not str or type(node['shape']) is not list:
        raise ValueError('invalid ndarray wire metadata')
    if any(type(size) is not int or size<0 for size in node['shape']):
        raise ValueError('invalid ndarray wire shape')
    raw.append(b'{');escaped.append(b'{')
    for index,key in enumerate(sorted(node)):
        if index:raw.append(b',');escaped.append(b',')
        _append_string(key,raw,escaped)
        raw.append(b':');escaped.append(b':')
        if key=='data':_append_base64(node[key],raw,escaped)
        else:_append(node[key],raw,escaped)
    raw.append(b'}');escaped.append(b'}')


def _append(value,raw,escaped):
    if type(value) is dict:
        if set(value)=={'ndarray'}:
            raw.extend((b'{',));escaped.extend((b'{',))
            _append_string('ndarray',raw,escaped)
            raw.append(b':');escaped.append(b':')
            _append_ndarray(value['ndarray'],raw,escaped)
            raw.append(b'}');escaped.append(b'}')
            return
        if any(type(key) is not str for key in value):
            raise ValueError('trusted contract object keys must be strings')
        raw.append(b'{');escaped.append(b'{')
        for index,key in enumerate(sorted(value)):
            if index:raw.append(b',');escaped.append(b',')
            _append_string(key,raw,escaped)
            raw.append(b':');escaped.append(b':')
            _append(value[key],raw,escaped)
        raw.append(b'}');escaped.append(b'}')
        return
    if type(value) is list or type(value) is tuple:
        raw.append(b'[');escaped.append(b'[')
        for index,item in enumerate(value):
            if index:raw.append(b',');escaped.append(b',')
            _append(item,raw,escaped)
        raw.append(b']');escaped.append(b']')
        return
    if isinstance(value,str):
        _append_string(value,raw,escaped)
        return
    token=_token(value)
    raw.append(token)
    escaped.append(token)


def serialize_frame_buffers(frame: HydraFrame) -> tuple[bytes,bytes]:
    """Return canonical raw frame JSON and its outer JSON-string literal.

    The only raw-injected bytes are base64 values produced by the public
    ``to_dict`` encoder. All metadata and scalar tokens use stdlib JSON rules.
    """
    if not isinstance(frame,HydraFrame):
        raise ValueError('HydraFrame required')
    packet=to_dict(frame)
    raw=[];escaped=[]
    _append(packet,raw,escaped)
    return b''.join(raw),b''.join((b'"',*escaped,b'"'))
