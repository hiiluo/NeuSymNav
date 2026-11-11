"""Bounded streaming regressions for Hydra selected-input export manifests."""
import hashlib
import json
from pathlib import Path
import tracemalloc

import pytest

from neusymnav.backends.hydra.runtime import _selected_accepted_inputs


def _line(run_id,event,**fields):
    return (json.dumps({'run_id':run_id,'event':event,**fields},ensure_ascii=False,
        separators=(',',':')).encode('utf-8')+b'\n')


def _selected(source,payload,revision,prefix):
    encoded=payload.encode('utf-8')
    return dict(source=source,payload_sha256=hashlib.sha256(encoded).hexdigest(),
        payload_bytes=len(encoded),graph_revision=revision,input_prefix_sha256=prefix)


def test_streaming_selection_matches_mixed_journal_order_and_hash_semantics(tmp_path):
    path=tmp_path/'journal.jsonl'
    s0={'episode_id':'episode-0','sensor_id':'rgbd','frame_index':0}
    s1={'episode_id':'épisode-1','sensor_id':'导航','frame_index':1}
    s2={'episode_id':'episode-0','sensor_id':'rgbd','frame_index':2}
    p0='{"label":"café\"\\\\\n"}'
    p1='{"label":"雪\"\\"}'
    records=[
        _line('foreign','started',source=s0,selected_frame='foreign payload'),
        _line('foreign','accepted',source=s0,accepted=True,graph_revision=9,input_prefix_sha256='f'*64),
        _line('run-1','batch',events=[
            {'event':'started','source':s0,'selected_frame':p0},
            {'event':'accepted','source':s0,'accepted':True,'graph_revision':2,
             'input_prefix_sha256':'b'*64},
            {'event':'accepted','source':{'frame_index':99},'accepted':True,
             'graph_revision':3,'input_prefix_sha256':'c'*64},
        ]),
        _line('run-1','started',source=s1,selected_frame=p1),
        _line('run-1','step_rejected',source=s1,accepted=False),
        _line('run-1','replaced',source=s1,replaced_source=s0),
        _line('run-1','started',source=s2,selected_frame='discarded duplicate'),
        _line('run-1','started',source=s2,selected_frame='accepted duplicate'),
        _line('run-1','accepted',source=s2,accepted=True,graph_revision=1,
            input_prefix_sha256='a'*64),
    ]
    path.write_bytes(b''.join(records))
    selected=_selected_accepted_inputs(path,'run-1')
    assert selected==[
        _selected(s2,'accepted duplicate',1,'a'*64),
        _selected(s0,p0,2,'b'*64),
    ]
    assert all(set(item)=={'source','payload_sha256','payload_bytes','graph_revision',
        'input_prefix_sha256'} for item in selected)


def test_streaming_selection_never_calls_path_read_text(tmp_path,monkeypatch):
    path=tmp_path/'journal.jsonl'
    source={'episode_id':'episode','sensor_id':'rgbd','frame_index':4}
    payload='{"selected":"café"}'
    path.write_bytes(_line('run','started',source=source,selected_frame=payload)+
        _line('run','accepted',source=source,accepted=True,graph_revision=1,
            input_prefix_sha256='a'*64))
    def forbidden(*args,**kwargs):pytest.fail('whole-file Path.read_text is forbidden')
    monkeypatch.setattr(Path,'read_text',forbidden)
    assert _selected_accepted_inputs(path,'run')==[_selected(source,payload,1,'a'*64)]


@pytest.mark.parametrize('contents',[
    b'{"run_id":"run","event":"batch","events":[\n',
    b'\xff\n',
    b'[]\n',
])
def test_malformed_or_nonobject_journal_fails_closed(tmp_path,contents):
    path=tmp_path/'journal.jsonl';path.write_bytes(contents)
    assert _selected_accepted_inputs(path,'run')==[]


def test_oversized_physical_line_fails_closed_without_accepting_truncated_json(tmp_path,monkeypatch):
    from neusymnav.backends.hydra import runtime
    path=tmp_path/'journal.jsonl'
    source={'episode_id':'episode','sensor_id':'rgbd','frame_index':0}
    oversized=_line('run','started',source=source,selected_frame='x'*512)
    valid=_line('run','started',source=source,selected_frame='short')+_line('run','accepted',
        source=source,accepted=True,graph_revision=1,input_prefix_sha256='a'*64)
    path.write_bytes(oversized+valid)
    monkeypatch.setattr(runtime,'HYDRA_JOURNAL_MAX_LINE_BYTES',128,raising=False)
    assert _selected_accepted_inputs(path,'run')==[]


def test_memory_use_is_bounded_by_one_large_journal_line_not_whole_file(tmp_path):
    path=tmp_path/'journal.jsonl';payload='x'*(1024*1024)
    source_template={'episode_id':'episode','sensor_id':'rgbd'}
    expected=[]
    with path.open('wb') as stream:
        for index in range(20):
            source={**source_template,'frame_index':index}
            stream.write(_line('run','started',source=source,selected_frame=payload))
            stream.write(_line('run','accepted',source=source,accepted=True,
                graph_revision=index+1,input_prefix_sha256=f'{index:064x}'))
            expected.append(_selected(source,payload,index+1,f'{index:064x}'))
    tracemalloc.start()
    selected=_selected_accepted_inputs(path,'run')
    _,peak=tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert selected==expected
    assert path.stat().st_size>=20*1024*1024
    assert peak<12*1024*1024
