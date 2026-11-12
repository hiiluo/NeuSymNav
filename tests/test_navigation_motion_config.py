"""Movement modes are explicit, closed-schema options in launch provenance."""
import pytest
from neusymnav.runtime.configuration import load_config
from test_launcher import config as base_config
from neusymnav.runtime.launcher import _navigation_options


def config(tmp_path, controller):
    return base_config(tmp_path, navigation={'controller': controller})


def test_movement_modes_allow_defaults_without_a_speed_override(tmp_path):
    c = load_config(config(tmp_path, {'discrete_heading_control': True, 'gain_aware': True}))
    assert c.data['navigation']['controller']['discrete_heading_control'] is True


def test_launcher_effective_defaults_and_legacy_override(tmp_path):
    c=load_config(base_config(tmp_path))
    assert _navigation_options(c)==dict(nominal_speed_mps=.15,discrete_heading_control=True,gain_aware=True,acceleration_mps2=.6)
    c=load_config(config(tmp_path,dict(discrete_heading_control=False,gain_aware=False,nominal_speed_mps=.1)))
    assert _navigation_options(c)==dict(nominal_speed_mps=.1,discrete_heading_control=False,gain_aware=False,acceleration_mps2=.15)


@pytest.mark.parametrize('name', ['discrete_heading_control', 'gain_aware','allow_fresh_map_lag'])
def test_movement_modes_require_actual_booleans(tmp_path, name):
    with pytest.raises(ValueError, match='boolean'):
        load_config(config(tmp_path, {name: 1}))
