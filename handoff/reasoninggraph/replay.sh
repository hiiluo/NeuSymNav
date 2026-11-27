#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
if (( $# != 1 )); then
    echo 'Usage: bash handoff/reasoninggraph/replay.sh NEW_OUTPUT_DIRECTORY' >&2
    exit 2
fi
out="$1"
mkdir -- "$out"
export PYTHONPATH=src:. OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2
scope=runs/reasoninggraph/m1-live-20261127
checkpoint=()
if [[ -n "${REASONINGGRAPH_CLIP_CHECKPOINT:-}" ]]; then
    checkpoint=(--checkpoint "$REASONINGGRAPH_CLIP_CHECKPOINT")
fi
.runtime/detector26/bin/python tools/reasoninggraph/handoff_semantics.py object \
    --revision 9 --query 'kitchen island' "${checkpoint[@]}" > "$out/object.json"
.runtime/detector26/bin/python tools/reasoninggraph/handoff_semantics.py object \
    --revision 26 --query 'mirror' "${checkpoint[@]}" > "$out/object-no-evidence.json"
.venv/bin/python tools/reasoninggraph/handoff_semantics.py rooms \
    --id 5908722711110090752 > "$out/room.json"
.venv/bin/python tools/reasoninggraph/handoff_semantics.py rooms \
    --id 1 > "$out/room-no-evidence.json"
.venv/bin/python tools/reasoninggraph/evaluate_relation_images.py \
    --report "$scope/annotation-probe/report.json" \
    --report-sha256 2f2c0b96323a14dd9f9884d975a8950ad309bdbdd4a1842189a40bf2befc4d60 \
    --review "$scope/annotations-ai-reviewed.json" \
    --review-sha256 8aa8b2955b40a631f39c9e6c6a53c2844a01bac212b429b7ad695039acfd0e94 \
    --recording runs/hydra-attribute-query/hna-live-00806-8yoan0t4/host-off/keyframes/recording \
    --geometry-only --frames 2 --out "$out/relation"
echo "$out"
