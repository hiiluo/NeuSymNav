"""The real checked launcher accepts only the versioned precision request."""
import json
from pathlib import Path
import pytest
from neusymnav.runtime.configuration import load_config

PROFILE=Path(__file__).resolve().parents[1]/'configs/p10/demo-yoloe11s-qualified-conceptgraphs-visual-gpu-00802.json'


def test_qualified_profile_reaches_real_launcher_configuration():
    result=load_config(PROFILE)
    assert result.data['sensor_config']['navmesh_precision']['cell_height_m']==.01


@pytest.mark.parametrize('precision',[{}, {'schema_version':True,'cell_height_m':.01},
    {'schema_version':1,'cell_height_m':.02}, {'schema_version':1,'cell_height_m':.01,'extra':0}])
def test_bad_precision_configuration_fails_before_native_start(tmp_path,precision):
    data=json.loads(PROFILE.read_text());data['sensor_config']['navmesh_precision']=precision
    path=tmp_path/'config.json';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='navmesh_precision'):
        load_config(path)
