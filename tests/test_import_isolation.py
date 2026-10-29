"""The installed namespace must resolve without either source repository."""
import os
from pathlib import Path
import subprocess
import sys


def test_import_from_arbitrary_cwd_without_source_roots(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    result = subprocess.run(
        [sys.executable, '-I', '-c',
         "import neusymnav; from pathlib import Path; "
         "assert 'NewOH3DSG' not in str(neusymnav.__file__); "
         "assert '/3DSG/' not in str(neusymnav.__file__); "
         "assert neusymnav.__version__ == '0.1.0'"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
