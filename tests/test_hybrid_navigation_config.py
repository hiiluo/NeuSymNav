"""Hybrid steering is explicit and cannot select two competing drive modes."""
import pytest
from test_launcher import config
from neusymnav.runtime.configuration import load_config
from neusymnav.runtime.launcher import _navigation_options


def test_hybrid_request_selects_its_controller_and_fast_ramp(tmp_path):
    value=load_config(config(tmp_path,navigation={'controller':{'hybrid_pulse_control':True}}))
    options=_navigation_options(value)
    assert options['hybrid_pulse_control'] is True
    assert options['discrete_heading_control'] is False
    assert options['acceleration_mps2'] == .6


def test_conflicting_steering_modes_fail_configuration(tmp_path):
    with pytest.raises(ValueError,match='exclusive'):
        load_config(config(tmp_path,navigation={'controller':{
            'hybrid_pulse_control':True,'discrete_heading_control':True}}))


@pytest.mark.parametrize('value',[1,'true',None])
def test_hybrid_mode_requires_boolean(tmp_path,value):
    with pytest.raises(ValueError,match='boolean'):
        load_config(config(tmp_path,navigation={'controller':{'hybrid_pulse_control':value}}))
