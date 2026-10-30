#!/usr/bin/env bash
# Local Intel/Mesa + CPU setup; generated configs/demo.local.json is checksum-pinned.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
export EGL_PLATFORM=surfaceless
# Keep the local 1080p dashboard at native pixel size. Allow an explicit zoom.
export QT_SCALE_FACTOR="${NEUSYMNAV_UI_SCALE:-1.0}" QT_AUTO_SCREEN_SCALE_FACTOR=0
unset QT_SCREEN_SCALE_FACTORS
export PYTHONPATH="$project_root/src" PYTHONDONTWRITEBYTECODE=1 YOLO_AUTOINSTALL=false
export XDG_CACHE_HOME="$project_root/.runtime/cache"
export YOLO_CONFIG_DIR="$project_root/.runtime/config/ultralytics"
export MPLCONFIGDIR="$project_root/.runtime/cache/matplotlib" TORCH_HOME="$project_root/.runtime/cache/torch"
if [[ "${HABITAT_FORCE_SOFTWARE:-0}" == 1 || ! -r /dev/dri/renderD128 ]]; then
    export LIBGL_ALWAYS_SOFTWARE=1 MESA_LOADER_DRIVER_OVERRIDE=llvmpipe
fi
demo_config="${NEUSYMNAV_DEMO_CONFIG:-configs/demo.local.json}"
if [[ "${1:-}" == --preflight && $# == 1 ]]; then
    exec .venv/bin/python -m neusymnav.cli preflight --config "$demo_config"
fi
if (( $# > 2 )); then
    echo 'Usage: bash tools/run_local_demo.sh [duration_seconds] [new_output_directory]' >&2
    exit 2
fi
exec .venv/bin/python -m neusymnav.cli run --config "$demo_config" \
    --duration-s "${1:-600}" --out "${2:-runs/demo-local-$(date +%Y%m%d-%H%M%S-%N)}"
