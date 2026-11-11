"""Rolling-map memory age is explicit and distinct from control freshness."""
import pytest
from test_launcher import config
from neusymnav.runtime.configuration import load_config


def test_explicit_local_retention_is_accepted_without_changing_controller(tmp_path):
    value=load_config(config(tmp_path,navigation={'mapper':{
        'snapshot_radius_m':2.,'local_retention_s':10.}}))
    assert value.data['navigation']['mapper']['local_retention_s']==10.
    assert value.data['navigation'].get('controller',{})=={}


@pytest.mark.parametrize('seconds',[0,-1,True,None,float('nan'),float('inf'),301,'10'])
def test_local_retention_rejects_invalid_or_unbounded_age(tmp_path,seconds):
    with pytest.raises(ValueError,match='local_retention_s'):
        load_config(config(tmp_path,navigation={'mapper':{'local_retention_s':seconds}}))
