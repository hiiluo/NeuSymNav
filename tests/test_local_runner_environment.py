"""Let EGL select a device unless software rendering was explicitly requested."""
import json
import os
from pathlib import Path
import subprocess
import pytest


@pytest.mark.parametrize('force', [False, True])
def test_local_runner_does_not_force_software_from_missing_dri_alone(tmp_path, force):
    tools = tmp_path / 'tools'
    tools.mkdir()
    source = Path(__file__).parents[1] / 'tools/run_local_demo.sh'
    script = tools / source.name
    script.write_bytes(source.read_bytes())
    binary = tmp_path / '.venv/bin/python'
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/usr/bin/env python3\nimport os,json\nprint(json.dumps({k:os.environ.get(k) for k in ("LIBGL_ALWAYS_SOFTWARE","MESA_LOADER_DRIVER_OVERRIDE")}))\n')
    binary.chmod(0o755)
    env = dict(os.environ, HABITAT_FORCE_SOFTWARE='1' if force else '0')
    env.pop('LIBGL_ALWAYS_SOFTWARE', None)
    env.pop('MESA_LOADER_DRIVER_OVERRIDE', None)
    result = subprocess.run(['bash', str(script), '--preflight'], env=env,
                            capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)
    assert actual['LIBGL_ALWAYS_SOFTWARE'] == ('1' if force else None)
    assert actual['MESA_LOADER_DRIVER_OVERRIDE'] == ('llvmpipe' if force else None)
