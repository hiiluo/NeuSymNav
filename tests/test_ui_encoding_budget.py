"""The UI publication fast path must preserve the capped wire contract."""

import json

import pytest

from test_display_snapshot import make_publisher
from neusymnav.runtime import ui_transport


def _streaming_wire(envelope):
    packet = dict(
        wire_version=1,
        projection=dict(
            object_history="last32_plus_displayed_evidence",
            object_geometry="centroid_bounds_only",
            complete_object_history=False,
        ),
        payload=ui_transport._encode_value(ui_transport._compact(envelope)),
    )
    encoder = json.JSONEncoder(separators=(",", ":"), allow_nan=False)
    return b"".join(chunk.encode() for chunk in encoder.iterencode(packet))


def test_normal_publication_uses_one_shot_encoder_with_identical_wire_bytes(monkeypatch):
    envelope = make_publisher()[0].read_latest()
    expected = _streaming_wire(envelope)
    modes = []
    original_iterencode = json.JSONEncoder.iterencode

    def track_iterencode(self, value, _one_shot=False):
        modes.append(_one_shot)
        return original_iterencode(self, value, _one_shot=_one_shot)

    monkeypatch.setattr(json.JSONEncoder, "iterencode", track_iterencode)

    actual = ui_transport.encode_publication(envelope)

    assert actual == expected
    assert modes == [True]


def test_size_estimate_bounds_ascii_unicode_escapes_and_large_integers():
    value = {
        "ascii": "plain\nslash/quote\"",
        "unicode": "café 🚀",
        "large_positive": (1 << 3000) - 1,
        "large_negative": -(1 << 3000),
        "float": -1.2345678901234567e+200,
        "items": [None, True, False, 0],
    }
    wire = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    cap = len(wire) + 4096

    upper_bound = ui_transport._json_ascii_upper_bound(value, cap)

    assert b"\\u00e9" in wire
    assert b"\\ud83d\\ude80" in wire
    assert json.loads(wire) == value
    assert len(wire) <= upper_bound <= cap
    assert ui_transport._json_ascii_upper_bound({"unsupported": object()}, cap) is None


def test_oversized_escaped_string_skips_escape_copy(monkeypatch):
    calls = []
    original = json.encoder.encode_basestring_ascii

    def track_escape(value):
        calls.append(len(value))
        return original(value)

    monkeypatch.setattr(json.encoder, "encode_basestring_ascii", track_escape)

    result = ui_transport._json_ascii_upper_bound("\u0001" * 100_000, 1024)

    assert result == 1025
    assert calls == []


def test_exact_cap_falls_back_to_stream_and_one_byte_below_rejects(monkeypatch):
    envelope = make_publisher()[0].read_latest()
    expected = _streaming_wire(envelope)
    modes = []
    original_iterencode = json.JSONEncoder.iterencode

    def track_iterencode(self, value, _one_shot=False):
        modes.append(_one_shot)
        return original_iterencode(self, value, _one_shot=_one_shot)

    monkeypatch.setattr(json.JSONEncoder, "iterencode", track_iterencode)

    assert ui_transport.encode_publication(envelope, max_bytes=len(expected)) == expected
    assert modes == [False]
    with pytest.raises(ValueError, match="byte cap exceeded"):
        ui_transport.encode_publication(envelope, max_bytes=len(expected) - 1)
    assert modes == [False, False]


def test_bounded_ascii_estimate_does_not_allocate_an_escaped_copy(monkeypatch):
    def unexpected(_):
        raise AssertionError('size preflight must not encode a large string twice')
    monkeypatch.setattr(json.encoder,'encode_basestring_ascii',unexpected)
    text='a'*100_000
    estimate=ui_transport._json_ascii_upper_bound(text,1_000_000)
    assert len(text)+2<=estimate<=1_000_000
