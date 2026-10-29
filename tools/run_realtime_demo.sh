#!/usr/bin/env bash
# Current high-resolution YOLOE-26m UI demo; 20s fits the unchanged recording cap.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
export CUDA_CACHE_PATH="$project_root/.runtime/cache/cuda"
export XDG_CACHE_HOME="$project_root/.runtime/cache"
export YOLO_CONFIG_DIR="$project_root/.runtime/config/ultralytics"
export MPLCONFIGDIR="$project_root/.runtime/cache/matplotlib"
export TORCH_HOME="$project_root/.runtime/cache/torch"
export PYTHONPATH="$project_root/src"
export PYTHONDONTWRITEBYTECODE=1 YOLO_AUTOINSTALL=false
demo_config="$project_root/configs/p10/demo-yoloe26m-640x480-00861.json"
if [[ "${1:-}" == "--preflight" && $# == 1 ]]; then
    exec "$project_root/.runtime/host/bin/python" -m neusymnav.cli preflight --config "$demo_config"
fi
if (( $# > 2 )); then
    echo "Usage: bash tools/run_realtime_demo.sh [duration_seconds] [new_output_directory]" >&2
    exit 2
fi
demo_duration="${1:-20}"
demo_output="${2:-runs/demo-yoloe26m-640x480-$(date +%Y%m%d-%H%M%S-%N)}"
exec "$project_root/.runtime/host/bin/python" -m neusymnav.cli run \
    --config "$demo_config" --duration-s "$demo_duration" --out "$demo_output"
