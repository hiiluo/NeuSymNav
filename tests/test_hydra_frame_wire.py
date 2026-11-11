"""Byte-for-byte oracle tests for the optimized trusted HydraFrame codec."""
from dataclasses import replace
import json

import numpy as np
import pytest

from neusymnav.contracts import FrameKey
from neusymnav.contracts.serialization import dumps, loads
from test_hydra_session import frame


def _assert_oracle(value):
    from neusymnav.backends.hydra.wire import serialize_frame_buffers
    raw,literal=serialize_frame_buffers(value)
    expected_raw=dumps(value).encode('utf-8')
    expected_literal=json.dumps(expected_raw.decode('utf-8'),separators=(',',':'),
        allow_nan=False).encode('utf-8')
    assert raw==expected_raw
    assert literal==expected_literal
    decoded=loads(raw.decode('utf-8'))
    assert dumps(decoded).encode('utf-8')==expected_raw
    return raw,literal,decoded


def test_metadata_escaping_and_scientific_float_match_contract_encoder():
    value=replace(frame(),source_key=FrameKey('episode"\\ café\x01','rgbd',2),
        clock_domain='host_monotonic:"\\ café\n\t\x02',sim_time_s=1e-200,
        calibration_id='calibration:"\\ café\r\n',
        calibration_version='version:\x00\x1f',
        detector_profile_id='detector/quote"\\/snowman-☃',
        vocabulary_id='taxonomy:"\\\n\t',labelspace_id='labels:\x01é')
    _assert_oracle(value)


def test_string_subclass_metadata_uses_exact_json_string_escaping():
    class TextSubclass(str):
        pass
    value=replace(frame(),detector_profile_id=TextSubclass('detector:"\\ café'))
    _assert_oracle(value)


@pytest.mark.parametrize('sim_time_s',[-0.0,1e-200,1e20,0.12345678901234568])
def test_float_tokens_keep_stdlib_format_and_signed_zero(sim_time_s):
    _assert_oracle(replace(frame(),sim_time_s=sim_time_s))


def test_random_rgb_all_bytes_nan_payloads_labels_and_optional_masks_roundtrip():
    shape=(16,16)
    rgb=np.resize(np.arange(256,dtype=np.uint8),(*shape,3))
    valid=np.ones(shape,dtype=np.bool_)
    labels=np.arange(256,dtype=np.int32).reshape(shape)
    depth_bits=np.full(shape,np.asarray(2.,dtype=np.float32).view(np.uint32),dtype=np.uint32)
    depth_bits[0,0]=np.uint32(0x7fc01234)
    depth_bits[0,1]=np.uint32(0xffc00001)
    valid[0,0]=valid[0,1]=False
    depth=depth_bits.view(np.float32)
    no_return=np.zeros(shape,dtype=np.bool_);no_return[0,0]=True
    far_plane=np.zeros(shape,dtype=np.bool_);far_plane[0,1]=True
    value=replace(frame(),rgb=rgb,depth_m=depth,valid_depth=valid,labels=labels,
        no_return=no_return,far_plane=far_plane,no_return_range_m=4.,far_plane_range_m=5.)
    rgb_before=rgb.copy();depth_before=depth.view(np.uint32).copy();labels_before=labels.copy()
    raw,_,decoded=_assert_oracle(value)
    assert np.array_equal(rgb,rgb_before)
    assert np.array_equal(depth.view(np.uint32),depth_before)
    assert np.array_equal(labels,labels_before)
    assert np.array_equal(decoded.rgb,rgb_before)
    assert np.array_equal(decoded.depth_m.view(np.uint32),depth_before)
    assert decoded.labels.dtype==np.dtype(np.int32)
    assert decoded.no_return is not None and decoded.far_plane is not None
    assert raw


def test_noncontiguous_input_arrays_are_normalized_without_mutation():
    rgb_base=np.resize(np.arange(256,dtype=np.uint8),(8,32,3))
    depth_base=np.full((8,32),2.,np.float32)
    valid_base=np.ones((8,32),np.bool_)
    labels_base=np.arange(8*32,dtype=np.int32).reshape(8,32)
    rgb=rgb_base[:,::2,:];depth=depth_base[:,::2];valid=valid_base[:,::2];labels=labels_base[:,::2]
    originals=(rgb.copy(),depth.view(np.uint32).copy(),valid.copy(),labels.copy())
    assert not rgb.flags.c_contiguous and not depth.flags.c_contiguous and not labels.flags.c_contiguous
    value=replace(frame(),rgb=rgb,depth_m=depth,valid_depth=valid,labels=labels)
    _assert_oracle(value)
    assert value.rgb.flags.c_contiguous and value.depth_m.flags.c_contiguous and value.labels.flags.c_contiguous
    assert np.array_equal(rgb,originals[0])
    assert np.array_equal(depth.view(np.uint32),originals[1])
    assert np.array_equal(valid,originals[2]) and np.array_equal(labels,originals[3])


def test_full_640x480_frame_matches_contract_oracle():
    rng=np.random.default_rng(20261105)
    shape=(480,640)
    value=replace(frame(),rgb=rng.integers(0,256,size=(*shape,3),dtype=np.uint8),
        depth_m=np.full(shape,2.,np.float32),valid_depth=np.ones(shape,np.bool_),
        labels=np.zeros(shape,np.int32))
    _assert_oracle(value)


def test_large_base64_string_never_enters_stdlib_string_encoder(monkeypatch):
    from neusymnav.backends.hydra import wire
    shape=(80,96)
    value=replace(frame(),rgb=np.zeros((*shape,3),np.uint8),
        depth_m=np.full(shape,2.,np.float32),valid_depth=np.ones(shape,np.bool_),
        labels=np.zeros(shape,np.int32))
    expected_raw=dumps(value).encode('utf-8')
    expected_literal=json.dumps(expected_raw.decode('utf-8'),separators=(',',':'),
        allow_nan=False).encode('utf-8')
    original=wire.json.dumps;large_string_arguments=[]
    def spy(item,*args,**kwargs):
        if isinstance(item,str) and len(item)>1000:large_string_arguments.append(len(item))
        return original(item,*args,**kwargs)
    monkeypatch.setattr(wire.json,'dumps',spy)
    assert wire.serialize_frame_buffers(value)==(expected_raw,expected_literal)
    assert large_string_arguments==[]


@pytest.mark.parametrize('array_node',[
    {'dtype':'|u1','shape':[1],'data':'AAAA','extra':'bad'},
    {'dtype':'|u1','shape':[1],'data':'AAAA"\\injected'},
])
def test_unexpected_or_unsafe_ndarray_wire_node_fails_closed(monkeypatch,array_node):
    from neusymnav.backends.hydra import wire
    monkeypatch.setattr(wire,'to_dict',lambda value:{'schema_version':1,
        'payload':{'ndarray':array_node}})
    with pytest.raises(ValueError):wire.serialize_frame_buffers(frame())


def test_nonfinite_contract_scalar_still_fails_like_allow_nan_false():
    from neusymnav.backends.hydra.wire import serialize_frame_buffers
    value=frame()
    object.__setattr__(value,'sim_time_s',float('nan'))
    with pytest.raises(ValueError):serialize_frame_buffers(value)
