#!/usr/bin/env bash
# Paper protocol P6, part A (docs/objectnav/paper-protocol-plan.md): stop calibration for the 0.88 m camera
# (DEV, evaluator-only) + explore-only on DEV60. B0/B1R-paper come after the stop distances are set from
# the calibration (part B). Writes runs/objectnav/paper-p6a-REPORT.txt.
#   bash tools/objectnav/paper/run_p6a.sh
set -u
cd "$(dirname "$0")/../../.." || exit 1
HAB="$HOME/miniconda3/envs/habitat/bin/python"
REPORT=runs/objectnav/paper-p6a-REPORT.txt
FILTER='^\[[0-9:]+\]|^(I|W)[0-9]{4} |GL_|mesa-|no-layout|^Using |^Renderer|^OpenGL'
mkdir -p runs/objectnav
{
  echo "== $(date -Is) P6a: stop calibration (paper camera)"
  if [ ! -f runs/objectnav/paper-stop-calibration.json ]; then
    PYTHONPATH=src "$HAB" tools/objectnav/paper/stop_calibration.py \
        --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --out runs/objectnav/paper-stop-calibration.json
    echo "stop calibration exit $?"
  else
    echo "already done: runs/objectnav/paper-stop-calibration.json"
  fi
  echo "== $(date -Is) P6a: explore-only DEV60"
} 2>&1 | grep -v -E "$FILTER" | tee -a "$REPORT"
bash tools/objectnav/paper/run_dev60.sh paper-explore-dev60 explore
{ echo "== explore report: runs/objectnav/paper-explore-dev60/REPORT.txt"; tail -8 runs/objectnav/paper-explore-dev60/REPORT.txt
  echo "DONE P6a ($(date -Is))"; } | tee -a "$REPORT"
