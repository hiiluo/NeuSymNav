"""Bootstrap the NeuSymNav Hydra protocol module under the Hydra-only venv."""
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[3]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from neusymnav.backends.hydra.worker import main

if __name__ == '__main__':
    raise SystemExit(main())
