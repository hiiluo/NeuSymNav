from dataclasses import replace
import json
import pytest
from contract_helpers import observation
from neusymnav.recording.writer import ReplayWriter
from neusymnav.recording.replay import ReplayReader


def recording(tmp_path):
    path=tmp_path/'input'
    writer=ReplayWriter(path)
    obs=observation()
    writer.append(obs)
    assert writer.close()['complete']
    return path,obs


def test_explicit_session_restores_same_domain_and_virtual_clock(tmp_path):
    from neusymnav.recording.replay import ReplaySession
    path,source=recording(tmp_path)
    session=ReplaySession.open(tmp_path/'session.json',path,start_ns=100)
    reader=ReplayReader(path,session=session)
    first=list(reader.frames())[0]
    session.advance(first.capture_monotonic_ns+20)
    restored=ReplaySession.open(tmp_path/'session.json',path)
    again=list(ReplayReader(path,session=restored).frames())[0]
    assert again.clock_domain==first.clock_domain
    assert again.capture_monotonic_ns==first.capture_monotonic_ns==100
    assert restored.now_ns()==120
    assert first.clock_domain.startswith('replay:')
    assert source.clock_domain!=first.clock_domain


def test_session_rejects_changed_input_manifest(tmp_path):
    from neusymnav.recording.replay import ReplaySession
    path,_=recording(tmp_path)
    ReplaySession.open(tmp_path/'session.json',path)
    with (path/'manifest.json').open('a') as stream:stream.write(' ')
    with pytest.raises(ValueError,match='input.*changed|input.*mismatch'):
        ReplaySession.open(tmp_path/'session.json',path)
