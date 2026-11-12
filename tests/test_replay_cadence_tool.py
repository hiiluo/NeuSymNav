import pytest


def test_ab_profiles_may_differ_only_by_ui_enabled():
    from neusymnav.runtime.replay_control import assert_ab_profiles_differ_only_by_ui_enabled

    left={'episode':{'id':'e'},'ui':{'enabled':False,'publish_hz':2}}
    right={'episode':{'id':'e'},'ui':{'enabled':True,'publish_hz':2}}
    assert_ab_profiles_differ_only_by_ui_enabled(left,right)
    right['episode']['id']='other'
    with pytest.raises(ValueError,match='differ only'):
        assert_ab_profiles_differ_only_by_ui_enabled(left,right)
