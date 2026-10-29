import json
import pytest
from test_launcher import config
from neusymnav.runtime.configuration import load_config
from neusymnav.runtime.launcher import _recording_policy


def test_explicit_archive_allocation_does_not_raise_aggregate_caps(tmp_path):
    path=config(tmp_path);data=json.loads(path.read_text());data['budgets']=dict(raw_cap=2*1024**3,total_cap=8*1024**3,archive_cap=1024**3);path.write_text(json.dumps(data))
    cfg=load_config(path);policy=_recording_policy(cfg)
    assert policy['archive_max_bytes']==1024**3
    assert policy['aggregate_raw_cap']==2*1024**3
    assert cfg.data['budgets']['total_cap']==8*1024**3


@pytest.mark.parametrize('value',[True,0,-1,1.5,2*1024**3,10**1000])
def test_archive_allocation_is_bounded_by_half_raw_budget(tmp_path,value):
    path=config(tmp_path);data=json.loads(path.read_text());data['budgets']=dict(raw_cap=2*1024**3,total_cap=8*1024**3,archive_cap=value);path.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_config(path)


def test_default_archive_allocation_remains_unchanged(tmp_path):
    assert _recording_policy(load_config(config(tmp_path)))['archive_max_bytes']==256*1024**2


def test_explicit_archive_allocation_is_not_a_pipeline_constructor_argument(tmp_path):
    from pathlib import Path
    from neusymnav.runtime.launcher import replay
    fixture=Path(__file__).parent/'fixtures/launcher'
    data=json.loads((fixture/'config.yaml').read_text());data['fixture']['detections']['path']=str(fixture/'batches.json')
    data['budgets']=dict(archive_cap=32*1024**2);path=tmp_path/'config.json';path.write_text(json.dumps(data))
    result=replay(fixture/'recording',path,out=tmp_path/'out')
    assert result['outcome']=='completed'
