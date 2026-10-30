"""GPU mapping is explicit, provenance-pinned, live-only and not a fallback."""
import hashlib,json
from pathlib import Path
import pytest
from neusymnav.runtime.configuration import load_config


def profile(tmp_path,backend='triton_cuda',worker=True,mode='live'):
    source=Path(__file__).resolve().parents[1]/'configs/p10/demo-yoloe26m-640x480-long-ui2-00861.json'
    d=json.loads(source.read_text());d['navigation']['mapper']['raycast_backend']=backend;d['mode']=mode
    if worker:d['workers']['raycast']=d['workers']['detector'].copy()
    p=tmp_path/'profile.json';p.write_text(json.dumps(d));return p


def test_explicit_gpu_worker_configuration_is_accepted_without_framework_import(tmp_path):
    c=load_config(profile(tmp_path))
    assert c.data['navigation']['mapper']['raycast_backend']=='triton_cuda'


@pytest.mark.parametrize('backend',['cuda','auto',None,False,42])
def test_undefined_gpu_backend_never_falls_back_to_cpu(tmp_path,backend):
    with pytest.raises(ValueError,match='raycast_backend'):load_config(profile(tmp_path,backend))


def test_gpu_requires_explicit_worker_and_live_mode(tmp_path):
    with pytest.raises(ValueError,match='raycast'):load_config(profile(tmp_path,worker=False))
    with pytest.raises(ValueError,match='live'):load_config(profile(tmp_path,mode='fixture_cpu_no_models'))


def test_navigation_capture_request_can_be_30hz_while_primary_stays_bounded(tmp_path):
    path=profile(tmp_path);d=json.loads(path.read_text())
    d['runtime']['navigation_hz']=30;path.write_text(json.dumps(d))
    assert load_config(path).data['runtime']['navigation_hz']==30
    d['runtime']['navigation_hz']=31;path.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='navigation_hz'):load_config(path)
    d['runtime']['navigation_hz']=30;d['runtime']['primary_hz']=21;path.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='primary_hz'):load_config(path)
