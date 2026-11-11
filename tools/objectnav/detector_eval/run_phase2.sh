#!/usr/bin/env bash
# Phase 2 detector measurement on the DEV scenes: sample views -> run YOLOE-26m -> score.
# Usage: bash tools/objectnav/detector_eval/run_phase2.sh [OUT_DIR]   (resumable; step 1 is skipped once done)
set -euo pipefail
cd "$(dirname "$0")/../../.."
OUT=${1:-runs/objectnav/detector_eval}
HAB=${HAB:-$HOME/miniconda3/envs/habitat/bin/python}
DET=${DET:-$HOME/Desktop/test_Room_segmentation/NeuSymNav/.runtime/detector26/bin/python}
mkdir -p "$OUT"
LOG="$OUT/run_phase2.log"
exec > >(tee -a "$LOG") 2>&1
echo "== $(date '+%F %T') branch $(git branch --show-current) commit $(git rev-parse --short HEAD)"

echo "== 0. tests"
PYTHONPATH=src:.:tests .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_objectnav_detector_eval.py 2>&1 | tail -1

echo "== 1. sample views (Habitat)"
if [[ -s "$OUT/views/scenes.json" ]]; then
  echo "views already sampled, keeping them"
else
  rm -rf "$OUT/views"
  PYTHONPATH=src "$HAB" tools/objectnav/detector_eval/sample_views.py \
    --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --out-dir "$OUT/views" 2>&1 \
    | { grep -v '^\[\|^I[0-9]\{4\}\|^W[0-9]\{4\}' || true; }
fi

echo "== 2. run detector (YOLOE-26m, runtime profile)"
PYTHONPATH=src "$DET" tools/objectnav/detector_eval/run_detector.py \
  --views "$OUT/views" --out "$OUT/predictions.jsonl" 2>&1 | { grep -v '^\[' || true; }

echo "== 3. score"
rm -rf "$OUT/report"
PYTHONPATH=src .venv/bin/python tools/objectnav/detector_eval/score_detector.py \
  --views "$OUT/views" --predictions "$OUT/predictions.jsonl" --out-dir "$OUT/report" | sed -n '1,20p'
du -sh "$OUT/views" "$OUT/predictions.jsonl" 2>/dev/null || true
echo "DONE"
