import json
from pathlib import Path
import pytest


def profile(tmp_path, room_options=None):
    project=Path(__file__).resolve().parents[1]
    data=json.loads((project/'configs/p10/demo-yoloe26m-640x480-00861.json').read_text())
    source_root=next((ancestor/'Rebuild_3DScene_OccuSG' for ancestor in project.parents
                      if (ancestor/'Rebuild_3DScene_OccuSG').is_dir()),
                     project.parent/'Rebuild_3DScene_OccuSG')
    data['workers']['room_pipeline']={
        'source_root':str(source_root),
        'm23_binary':{'path':'/tmp/m23','sha256':'a'*64},
        'm4_binary':{'path':'/tmp/m4','sha256':'b'*64},
        **(room_options or {}),
    }
    path=tmp_path/'profile.json';path.write_text(json.dumps(data));return path


def test_room_admission_defaults_to_bounded_fifo(tmp_path):
    from neusymnav.runtime.configuration import load_config
    data=load_config(profile(tmp_path)).data['workers']['room_pipeline']
    assert data.get('queue_policy','bounded_fifo')=='bounded_fifo'
    assert data.get('fps_cap_hz') is None


def test_latest_wins_requires_explicit_fps_cap(tmp_path):
    from neusymnav.runtime.configuration import load_config
    with pytest.raises(ValueError,match='fps_cap_hz'):
        load_config(profile(tmp_path,{'queue_policy':'latest_wins'}))


def test_explicit_local_fps_cap_latest_wins_is_accepted(tmp_path):
    from neusymnav.runtime.configuration import load_config
    data=load_config(profile(tmp_path,{'fps_cap_hz':0.1,'queue_policy':'latest_wins'})).data
    assert data['workers']['room_pipeline']['fps_cap_hz']==0.1
    assert data['workers']['room_pipeline']['queue_policy']=='latest_wins'


@pytest.mark.parametrize('options',[
    {'fps_cap_hz':0}, {'fps_cap_hz':-0.1}, {'fps_cap_hz':21},
    {'fps_cap_hz':True}, {'queue_policy':'drop_oldest'},
])
def test_room_fps_cap_rejects_invalid_values(tmp_path,options):
    from neusymnav.runtime.configuration import load_config
    with pytest.raises(ValueError):load_config(profile(tmp_path,options))
