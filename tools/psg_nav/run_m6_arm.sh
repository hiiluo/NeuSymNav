#!/usr/bin/env bash
# Run one guarded ablation arm from the repository root.
set -euo pipefail

arm="${1:?mode off, shadow or probabilistic}"
root="${2:?output root}"
manifest="${3:-configs/objectnav/splits/hm3d_v2-val-test.json}"
profile="${4:-configs/objectnav/lockstep-b0-v3h.json}"
data="${M6_HABITAT_DATA:-local-assets/datasets/hm3d-val}"
habitat_python="${M6_HABITAT_PYTHON:-$PWD/.runtime/sensor/bin/python}"
native_env="${M6_HYDRA_ENV:-runs/reasoninggraph/m1-lineage-ipc-20261127/combined-env.sh}"
native_config="${M6_HYDRA_CONFIG:-runs/psg-nav/m5-target-window-20261128/fast-hydra}"

case "$arm" in
    off) options=() ;;
    shadow|probabilistic)
        options=(--semantic-candidate-mode "$arm" --semantic-native-config "$native_config") ;;
    *) exit 2 ;;
esac

mkdir -p "$root"
lock_file="${M6_GPU_LOCK:-runs/psg-nav/.m6-gpu.lock}"
exec 9>"$lock_file"
flock -n 9 || { echo "Another M6 arm holds $lock_file" >&2; exit 2; }

if [[ "$arm" != off ]]; then
    set +u
    source "$native_env"
    set -u
fi
export EGL_PLATFORM=surfaceless OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2
export PYTHONPATH="$PWD/src:$PWD:${PYTHONPATH:-}"
run_tag="$(basename "$root")-$arm"
rc=0
.venv/bin/python tools/psg_nav/sample_ablation_resources.py "$root/$arm.resources.jsonl" -- \
    .venv/bin/python tools/objectnav/run_episodes.py \
    --set hm3d_v2 --split val --habitat-data "$data" \
    --policy b0 --b0-config configs/objectnav/b0-policy-v3.json \
    --config "$profile" --manifest "$manifest" --habitat-python "$habitat_python" \
    --trace "${options[@]}" --run-id "psg-m6-$run_tag" --out-dir "$root/$arm" \
    > "$root/$arm.log" 2>&1 || rc=$?
echo "$rc" > "$root/$arm.exit"
tail -12 "$root/$arm.log"
exit "$rc"
