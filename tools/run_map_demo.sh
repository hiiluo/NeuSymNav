#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"
if [[ "${1:-}" == --list ]]; then
    for map in 00800 00801 00802 00803 00804 00805 00806 00807 00808 00809; do
        if [[ -f "configs/demo-${map}.local.json" ]]; then echo "$map"; fi
    done
    exit 0
fi
if (( $# < 1 || $# > 3 )); then
    echo 'Usage: bash tools/run_map_demo.sh MAP [duration_seconds|--preflight] [new_output_directory]' >&2
    echo 'List prepared maps: bash tools/run_map_demo.sh --list' >&2
    exit 2
fi
map="$1"; shift
case "$map" in
    0080[0-9]) ;;
    apt_[0-5]) echo 'ReplicaCAD requires articulated objects; the current live sensor disables physics. Full-scene demo is not ready.' >&2; exit 1 ;;
    *) echo "Unknown map: $map" >&2; exit 2 ;;
esac
export NEUSYMNAV_DEMO_CONFIG="$project_root/configs/demo-${map}.local.json"
if [[ ! -f "$NEUSYMNAV_DEMO_CONFIG" ]]; then
    echo "Map $map has not been calibrated; see tools/prepare_local_maps.py --help." >&2
    exit 1
fi
exec bash tools/run_local_demo.sh "$@"
