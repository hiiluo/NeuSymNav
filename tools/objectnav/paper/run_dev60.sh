#!/usr/bin/env bash
# Paper-protocol DEV60 run (docs/objectnav/paper-protocol-plan.md P6): provenance, tests, run, score,
# offline evidence, summary (paired with REF when given). Resumable: rerun the same command.
#   bash tools/objectnav/paper/run_dev60.sh <name> <explore|b0|b1|b3> [policy-config.json] [REF run name]
# Writes runs/objectnav/<name>/REPORT.txt.
set -u
cd "$(dirname "$0")/../../.." || exit 1
NAME=${1:?run name}; POLICY=${2:?explore|b0|b1|b3}; PCFG=${3:-}; REF=${4:-}
OUT=runs/objectnav/$NAME; HAB="$HOME/miniconda3/envs/habitat/bin/python"
FILTER='^\[[0-9:]+\]|^(I|W)[0-9]{4} |GL_|mesa-|no-layout|^Using |^Renderer|^OpenGL'
# NSNAV_PARALLEL=1: the user allows a second concurrent run (workers use pipes; never two VLM configs at once)
if [ "${NSNAV_PARALLEL:-0}" != 1 ] && pgrep -f "python.*(run_episodes|run_paper_episodes).py" >/dev/null; then echo "another ObjectNav run is active; stop"; exit 1; fi
mkdir -p "$OUT/provenance"
{
  echo "== $(date -Is) paper run $NAME: policy $POLICY ${PCFG:+config $PCFG} branch $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
  if [ ! -f "$OUT/provenance/head.txt" ]; then
    git rev-parse HEAD > "$OUT/provenance/head.txt"
    git status --short > "$OUT/provenance/status.txt"
    git diff HEAD > "$OUT/provenance/tracked.diff"
    git ls-files --others --exclude-standard -- src configs/objectnav tools/objectnav tests docs/objectnav \
      | sort | xargs -r sha256sum > "$OUT/provenance/untracked.sha256"
    echo "snapshot written: $(wc -l < "$OUT/provenance/untracked.sha256") untracked files"
  else
    git diff HEAD | cmp -s - "$OUT/provenance/tracked.diff" || echo "WARNING: tracked code changed since the first start"
  fi
  echo "== 1. tests"
  .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_objectnav_paper.py tests/test_objectnav_paper_b0.py 2>&1 | tail -1
  echo "== 2. run ($(date -Is))"
  cp -n configs/objectnav/splits/hm3d_v2-val-dev.json "$OUT/manifest.json" 2>/dev/null || true
  .venv/bin/python tools/objectnav/run_paper_episodes.py --set hm3d_v2 --split val --manifest "$OUT/manifest.json" \
      --run-id "$NAME" --out-dir "$OUT" --policy "$POLICY" ${PCFG:+--policy-config "$PCFG"}
  RC=$?; echo "== run exit $RC ($(date -Is))"
  [ "$RC" -eq 0 ] || { echo "run did not finish; rerun to resume"; exit "$RC"; }
  echo "== 3. score"
  rm -f "$OUT"/trajectories*-outcomes.jsonl "$OUT"/trajectories*-summary.json
  PYTHONPATH=src "$HAB" tools/objectnav/score_trajectories.py "$OUT/trajectories.jsonl" --set hm3d_v2 --split val
  if [ "$POLICY" != explore ]; then
    echo "== 4. offline failure evidence (paper camera)"
    PYTHONPATH=src "$HAB" tools/objectnav/paper/failure_evidence.py "$OUT" --set hm3d_v2 --split val | tail -2
    PYTHONPATH=src "$HAB" tools/objectnav/score_trajectories.py "$OUT/trajectories+evidence.jsonl" --set hm3d_v2 --split val
  fi
  echo "== 5. summary"
  python3 tools/objectnav/paper/summary.py "$OUT" ${REF:+--ref runs/objectnav/$REF}
  echo "DONE ($(date -Is))"
} 2>&1 | grep -v -E "$FILTER" | tee -a "$OUT/REPORT.txt"
