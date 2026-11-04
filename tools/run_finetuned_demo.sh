#!/usr/bin/env bash
# Explicit experimental model; the standard GPU demo keeps its baseline model.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
demo_map="${1:-00861}"
case "$demo_map" in 00861|00802|00770) ;; *) echo "Map must be 00861, 00802 or 00770" >&2; exit 2;; esac
demo_duration="${2:-300}"
demo_output="${3:-runs/finetuned-${demo_map}-$(date +%Y%m%d-%H%M%S-%N)}"
if (( $# > 3 )); then echo "Usage: bash tools/run_finetuned_demo.sh [map] [seconds] [new_output_directory]" >&2; exit 2; fi
export NEUSYMNAV_DEMO_CONFIG="$project_root/configs/p10/demo-finetuned-conceptgraphs-visual-gpu-${demo_map}.json"
exec bash "$project_root/tools/run_gpu_demo.sh" "$demo_duration" "$demo_output"
