"""Native interpreter discovery uses an explicit bounded startup budget."""
import json
import subprocess

import pytest

from neusymnav.runtime.launcher import _probe_interpreter


def test_native_probe_honors_startup_budget_without_changing_default(monkeypatch):
    budgets = []

    def run(command, **options):
        budgets.append(options['timeout'])
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'version': [3, 12, 0], 'missing': [], 'executable': '/worker/python',
            'prefix': '/worker',
        }).encode())

    monkeypatch.setattr(subprocess, 'run', run)
    _probe_interpreter('/worker/python', ['numpy'], 'hydra', timeout_s=10.)
    _probe_interpreter('/worker/python', ['numpy'], 'sensor')
    assert budgets == [10., 3.]


@pytest.mark.parametrize('budget', [True, 0, -1, float('inf'), float('nan')])
def test_probe_rejects_invalid_budget_before_launch(monkeypatch, budget):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid budget must not start an interpreter')

    monkeypatch.setattr(subprocess, 'run', forbidden)
    with pytest.raises(ValueError, match='timeout'):
        _probe_interpreter('/worker/python', [], 'hydra', timeout_s=budget)


def test_hydra_asset_probe_uses_declared_worker_startup_budget(tmp_path, monkeypatch):
    from test_hydra_runtime import _hydra_profile
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import load_config

    path = _hydra_profile(tmp_path)
    data = json.loads(path.read_text())
    data['workers']['hydra']['startup_timeout_s'] = 10.
    path.write_text(json.dumps(data))
    budgets = {}

    def probe(python, modules, label, **options):
        budgets[label] = options.get('timeout_s', 3.)
        return {'missing': [], 'version': [3, 12, 0]}

    monkeypatch.setattr(launcher, '_probe_interpreter', probe)
    launcher._assets(load_config(path))
    assert budgets['hydra'] == 10.


def test_probe_rejects_failed_setup_script(tmp_path):
    import sys
    import pytest
    from neusymnav.runtime.launcher import _probe_interpreter
    setup=tmp_path/'failed-setup.sh'
    setup.write_text('return 7\n')
    with pytest.raises(ValueError,match='probe failed'):
        _probe_interpreter(sys.executable,(),'hydra',setup_script=setup)


def test_probe_aborts_on_failure_inside_setup_before_later_success(tmp_path):
    import sys
    import pytest
    from neusymnav.runtime.launcher import _probe_interpreter
    setup=tmp_path/'failed-inside-setup.sh'
    setup.write_text('false\nexport NEUSYMNAV_SETUP_AFTER_FAILURE=1\n')
    with pytest.raises(ValueError,match='probe failed'):
        _probe_interpreter(sys.executable,(),'hydra',setup_script=setup)
