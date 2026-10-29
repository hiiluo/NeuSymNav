import importlib
import pytest


def age(*args):
    return importlib.import_module('neusymnav.contracts.observations').age_ns(*args)


def test_clock_domain_mismatch_rejected():
    with pytest.raises(ValueError, match='domain'):
        age(10, 'host:boot1', 20, 'host:boot2')
    with pytest.raises(ValueError, match='domain'):
        age(10, 'live', 20, 'replay')


def test_future_timestamp_rejected():
    with pytest.raises(ValueError):
        age(21, 'boot', 20, 'boot')


def test_monotonic_age_exact_integer_arithmetic():
    assert age(10**18, 'boot', 10**18 + 7, 'boot') == 7
    assert age(0, 'replay', 0, 'replay') == 0


@pytest.mark.parametrize('capture,domain,now', [(-1, 'boot', 20), (True, 'boot', 20),
                                                (1.5, 'boot', 20), (1, '', 20)])
def test_invalid_clock_values(capture, domain, now):
    with pytest.raises(ValueError):
        age(capture, domain, now, domain)
