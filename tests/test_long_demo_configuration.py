import json
from pathlib import Path
import pytest
from neusymnav import cli
from neusymnav.runtime.configuration import load_config


def profile(tmp_path, **updates):
    data=json.loads(Path('configs/p10/demo-yoloe26m-640x480-00861.json').read_text())
    data['long_demo']={'max_duration_s':600,'payload_format':'npz_v2'}
    data['runtime']={'primary_hz':5,'navigation_hz':20,'control_sample_cap':20000}
    data['measurements'].update(trace_byte_cap=512*1024**2,proof_record_cap=20000)
    data['budgets'].update(archive_cap=12*1024**3,raw_cap=24*1024**3,total_cap=32*1024**3)
    data.update(updates)
    path=tmp_path/'long.json';path.write_text(json.dumps(data));return path


def test_explicit_long_profile_has_bounded_extended_budget(tmp_path):
    cfg=load_config(profile(tmp_path))
    assert cfg.data['budgets']['archive_cap']==12*1024**3
    assert cfg.data['long_demo']['max_duration_s']==600


def test_cli_accepts600_and_rejects_beyond():
    assert cli._duration('600')==600
    with pytest.raises(Exception):cli._duration('600.001')


@pytest.mark.parametrize('change',[
    {'long_demo':{'max_duration_s':601,'payload_format':'npz_v2'}},
    {'long_demo':{'max_duration_s':600,'payload_format':'json_v1'}},
    {'long_demo':{'max_duration_s':600,'payload_format':'npz_v2','typo':True}},
    {'long_demo':None},
    {'runtime':{'primary_hz':21,'navigation_hz':20,'control_sample_cap':20000}},
    {'runtime':{'primary_hz':5,'navigation_hz':float('nan'),'control_sample_cap':20000}},
    {'runtime':{'primary_hz':5,'navigation_hz':20,'control_sample_cap':True}},
    {'runtime':{'primary_hz':5,'navigation_hz':20,'control_sample_cap':20001}},
    {'runtime':{'primary_hz':5,'navigation_hz':20,'typo':1}},
    {'budgets':{'archive_cap':12*1024**3,'raw_cap':25*1024**3,'total_cap':32*1024**3}},
])
def test_extended_profile_rejects_unbounded_or_unknown_policy(tmp_path,change):
    with pytest.raises(ValueError):load_config(profile(tmp_path,**change))


def test_legacy_budget_cannot_implicitly_opt_in(tmp_path):
    path=profile(tmp_path);data=json.loads(path.read_text());del data['long_demo'];path.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_config(path)


def test_long_measurement_caps_do_not_leak_to_legacy_profile(tmp_path):
    path=profile(tmp_path);data=json.loads(path.read_text());del data['long_demo']
    data['budgets']={'archive_cap':1024**3,'raw_cap':2*1024**3,'total_cap':8*1024**3}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_config(path)


@pytest.mark.parametrize('field,value',[('trace_byte_cap',512*1024**2+1),('proof_record_cap',20001),('proof_record_cap',True)])
def test_long_measurement_caps_remain_bounded(tmp_path,field,value):
    path=profile(tmp_path);data=json.loads(path.read_text());data['measurements'][field]=value;path.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_config(path)


def test_ui_cadence_is_explicit_and_bounded(tmp_path):
    path=profile(tmp_path,ui={'enabled':True,'publish_hz':2})
    assert load_config(path).data['ui']['publish_hz']==2


@pytest.mark.parametrize('value',[0,-1,True,float('nan'),21])
def test_ui_cadence_rejects_invalid_value(tmp_path,value):
    with pytest.raises(ValueError):load_config(profile(tmp_path,ui={'enabled':True,'publish_hz':value}))
