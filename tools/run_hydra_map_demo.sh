#!/usr/bin/env bash
# Branch2-only Hydra profile launcher. Provisioning and profile authoring are explicit.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

usage() {
    echo 'Usage: bash tools/run_hydra_map_demo.sh MAP [duration_seconds|--preflight] [new_output_directory]' >&2
    echo 'Set NEUSYMNAV_HYDRA_DEMO_CONFIG to an explicitly calibrated branch2 profile.' >&2
    exit 2
}

(( $# >= 1 && $# <= 3 )) || usage
map="$1"; shift
[[ "$map" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || usage
branch="$(git branch --show-current)"
# Kiet_branch2 holds the frozen 3DSG baseline; objectnav* branches build on it.
[[ "$branch" == Kiet_branch2 || "$branch" =~ ^objectnav([/_-][A-Za-z0-9._/-]+)?$ ]] || {
    echo "Refusing Hydra demo outside Kiet_branch2/objectnav* (active branch: $branch)." >&2
    exit 1
}
worktree="$(git rev-parse --show-toplevel)"
[[ "$(realpath "$worktree")" == "$(realpath "$project_root")" ]] || {
    echo 'Git top-level does not match this NeuSymNav worktree.' >&2; exit 1;
}
config="${NEUSYMNAV_HYDRA_DEMO_CONFIG:-$project_root/configs/demo-${map}.hydra.local.json}"
config="$(realpath -m -- "$config")"
[[ -f "$config" ]] || {
    echo "Hydra profile is missing: $config" >&2
    echo 'Create a local profile with explicit calibration, worker pins, and unchanged navigation settings.' >&2
    exit 1
}
"$project_root/.venv/bin/python" - "$config" <<'PY'
import json,sys
from pathlib import Path
config=Path(sys.argv[1])
try:
    value=json.loads(config.read_text())
except (OSError,ValueError) as exc:
    raise SystemExit(f'Cannot read Hydra profile: {exc}')
if value.get('scene_graph',{}).get('backend')!='hydra':
    raise SystemExit('Selected profile must explicitly set scene_graph.backend=hydra')
PY

# Optional baseline freeze: NEUSYMNAV_BASELINE_LOCK=docs/baselines/<name>.lock.json
# refuses to start when any locked file or pinned asset differs from the lock.
if [[ -n "${NEUSYMNAV_BASELINE_LOCK:-}" ]]; then
    "$project_root/.venv/bin/python" "$project_root/tools/baseline_lock.py" verify "$NEUSYMNAV_BASELINE_LOCK" || {
        echo 'Refusing run: baseline lock verification failed (see above).' >&2
        exit 1
    }
fi

preflight=0
duration=''
output=''
if (( $# > 0 )); then
    if [[ "$1" == --preflight ]]; then preflight=1
    else duration="$1"; fi
fi
if (( $# > 1 )); then output="$2"; fi
if (( $# == 0 )); then preflight=1; fi
if (( preflight == 0 )); then
    [[ "$duration" =~ ^[1-9][0-9]*$ ]] || usage
fi
"$project_root/.venv/bin/python" -m neusymnav.cli preflight --config "$config"
if (( preflight )); then exit 0; fi
export NEUSYMNAV_DEMO_CONFIG="$config"
if [[ -n "$output" ]]; then
    exec bash tools/run_local_demo.sh "$duration" "$output"
fi
exec bash tools/run_local_demo.sh "$duration"
