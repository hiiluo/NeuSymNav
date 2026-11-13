#!/usr/bin/env bash
# Run a policy on the 60 DEV episodes and score it with scorer v3 (docs/objectnav/b0-baseline-handoff.md).
# The official B0 baseline (13/11/2026, runs/objectnav/b0/dev60-v3h, SR 0.283) was produced by
# this script with the defaults below (then at runs/_phase3/step9_dev60_official.sh).
# About 5 h 20 min for B0 on CPU + iGPU. Resumable: Ctrl-C and rerun the same command,
# finished episodes are skipped. Run once per policy version; do not tune on TEST.
#   bash tools/objectnav/b0/run_dev60.sh                       # B0 baseline
#   OUT=runs/objectnav/<id> RUN_ID=<id> POLICY=<name> bash tools/objectnav/b0/run_dev60.sh
cd "$(dirname "$0")/../../.." || exit 1
if pgrep -f "python.*[r]un_episodes.py" >/dev/null; then echo "another run_episodes.py is running; stop"; exit 1; fi
CFG=${CFG:-lockstep-b0-v3h}; POL=${POL:-b0-policy-v3}; POLICY=${POLICY:-b0}
OUT=${OUT:-runs/objectnav/b0/dev60-v3h}; RUN_ID=${RUN_ID:-b0dev60v3h}
HAB="$HOME/miniconda3/envs/habitat/bin/python"
mkdir -p "$OUT/provenance"
LOG="$OUT/run_dev60.log"
{
  echo "== $(date -Is) branch $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)  config $CFG + $POL"
  echo "== 0. provenance (snapshot of the code this run uses, also uncommitted changes)"
  if [ ! -f "$OUT/provenance/head.txt" ]; then
    git rev-parse HEAD > "$OUT/provenance/head.txt"
    git status --short > "$OUT/provenance/status.txt"
    git diff HEAD > "$OUT/provenance/tracked.diff"
    git ls-files --others --exclude-standard -- src configs/objectnav tools/objectnav tests docs/objectnav \
      | sort | xargs -r sha256sum > "$OUT/provenance/untracked.sha256"
    tar -czf "$OUT/provenance/untracked.tgz" $(git ls-files --others --exclude-standard -- src configs/objectnav tools/objectnav tests docs/objectnav)
    sha256sum configs/objectnav/$CFG.json configs/objectnav/$POL.json configs/objectnav/splits/hm3d_v2-val-dev.json \
      > "$OUT/provenance/configs.sha256"
    echo "snapshot written: HEAD $(cut -c1-7 "$OUT/provenance/head.txt"), $(wc -l < "$OUT/provenance/untracked.sha256") untracked files, diff $(wc -l < "$OUT/provenance/tracked.diff") lines"
  else
    echo "resume: snapshot from first start kept (HEAD $(cut -c1-7 "$OUT/provenance/head.txt"))"
    git diff HEAD | cmp -s - "$OUT/provenance/tracked.diff" || echo "WARNING: tracked code changed since the first start of this run"
  fi
  echo "== 1. ObjectNav tests"
  PYTHONPATH=src:.:tests .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_objectnav_*.py \
      tests/test_sim_lockstep_safety.py tests/test_escape_guard.py 2>&1 | tail -2
  echo "== 2. run $POLICY on 60 DEV episodes ($(date -Is))"
  cp configs/objectnav/splits/hm3d_v2-val-dev.json "$OUT/manifest.json"
  PYTHONPATH=src .venv/bin/python tools/objectnav/run_episodes.py --set hm3d_v2 --split val \
      --manifest "$OUT/manifest.json" --policy "$POLICY" --run-id "$RUN_ID" --out-dir "$OUT" \
      --config configs/objectnav/$CFG.json --b0-config configs/objectnav/$POL.json
  RC=$?
  echo "== run exit $RC ($(date -Is))"
  [ "$RC" -eq 0 ] || { echo "run did not finish; rerun this script to resume"; exit "$RC"; }
  echo "== 3. score (scorer v3)"
  rm -f "$OUT"/trajectories-outcomes.jsonl "$OUT"/trajectories-summary.json \
        "$OUT"/trajectories+evidence-outcomes.jsonl "$OUT"/trajectories+evidence-summary.json
  PYTHONPATH=src "$HAB" tools/objectnav/score_trajectories.py "$OUT/trajectories.jsonl" --set hm3d_v2 --split val
  echo "== 4. offline failure evidence"
  PYTHONPATH=src "$HAB" tools/objectnav/b0/failure_evidence.py "$OUT" --set hm3d_v2 --split val | tail -5
  PYTHONPATH=src "$HAB" tools/objectnav/score_trajectories.py "$OUT/trajectories+evidence.jsonl" --set hm3d_v2 --split val
  echo "== 5. stuck / no-motion diagnosis"
  PYTHONPATH=src "$HAB" tools/objectnav/b0/diagnose_stuck.py "$OUT" --set hm3d_v2 --split val \
      --runner-config configs/objectnav/$CFG.json | tail -1
  PYTHONPATH=src "$HAB" tools/objectnav/b0/diagnose_no_motion.py "$OUT" --set hm3d_v2 --split val \
      --runner-config configs/objectnav/$CFG.json | tail -1
  echo "== 6. report"
  PYTHONPATH=src .venv/bin/python tools/objectnav/b0/summarize_run.py "$OUT"
  echo "DONE ($(date -Is))"
} 2>&1 | grep -v -E '^\[[0-9:]+\]|^(I|W)[0-9]{4} |GL_|mesa-|no-layout|^Using |^Renderer|^OpenGL' | tee -a "$LOG"
