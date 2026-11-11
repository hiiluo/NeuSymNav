# Hydra branch2 H7 — fail-closed acceptance scaffolding

Date: 2026-11-04. H7 is **partially implemented** in the isolated worktree.

## Implemented

- Added `tools/run_hydra_map_demo.sh`. It refuses execution outside the exact
  `Kiet_branch2` branch/worktree, requires an explicit local Hydra profile,
  requires `scene_graph.backend=hydra`, delegates asset/interpreter/native
  checks to the existing launcher preflight, and runs the existing local demo
  entry point without changing navigation configuration.
- Added independent `tools/check_hydra_acceptance.py`. Exit 0 requires a complete
  native export/journal with verifiable hashes and selected inputs, three
  complete same-input 90-second baseline/Hydra pairs, at least 90% baseline
  translation and no more than five percentage points of pending-source
  regression, matching source/navigation pins, and the H3 native object/open-room/
  two-room reload evidence. Missing or malformed evidence exits 1.
- Added CPU tests for valid synthetic acceptance evidence and fail-closed behavior
  on missing room evidence or mismatched ordered inputs. Hydra interpreter
  preflight now probes after sourcing the same setup script used by the child,
  with a command-construction regression test.

## Verification

- RED/GREEN: `.venv/bin/python -m pytest tests/test_hydra_acceptance.py -q` —
  first failed because the checker API did not exist; after implementation **2
  passed**, exit 0.
- Initial branch2 live runner preflight exited 1 because the local profile was
  absent. After creating the calibrated profile and correcting the Hydra
  interpreter probe to preserve the sourced setup's `PYTHONPATH`,
  `bash tools/run_hydra_map_demo.sh 00805 --preflight` exits 0 with
  `ready=true`, `issues=[]`, and `native_runtime_validated=false`. The profile
  pins the local Hydra interpreter/script/setup, dataset and labelspace; the UI
  is disabled for this headless preflight.
  Calibration details and hashes: [00805 profile report](hydra-branch2-calibration-00805.md).
- Acceptance checker against H4's isolated native child artifact directory —
  exit 1, expected because that artifact has no NeuSymNav coordinator runtime
  record or A/B pairs. It reported no H3 fixture gate errors; H3's native
  object/two-room/open-room evidence was found.
- Focused CPU/UI/runtime command including acceptance and setup-probe tests:
  **54 passed**,
  exit 0; `bash -n tools/run_hydra_map_demo.sh` exit 0; `git diff --check` exit 0.
- Final full CPU suite: **2416 passed, 10 skipped, 3 failed**, exit 1 in 186.54
  s. The three failures are the existing legacy UI worker checksum assertions
  recorded in H5.

## Not validated

One bounded post-fix live NeuSymNav coordinator smoke has now run; see the
[smoke results](hydra-branch2-smoke-00805.md). It processed two Hydra inputs
and shut down cleanly, but returned `incomplete` with
`native_runtime_validated=false`. Detector capture-to-return p50/p95 was
14.328/25.342 s (n=2), every measured control interval exceeded 100 ms, and
strict actuation evidence is incomplete. No same-input RGB-D/pose A/B, three
90-second pairs, 300-second run, local-scene run, or acceptance pass exists.
The local profile now exists at the
ignored path `configs/demo-00805.hydra.local.json`. Its calibration was read back
from one actual Habitat primary capture without an action; this validates static
camera calibration and transform composition, not coordinator runtime behavior.
No GPU or live demo workload was started by preflight.

**Implemented:** branch/worktree-safe runner and independent fail-closed acceptance
checker.

**Correctness-verified:** checker positive and negative unit cases; real H3 fixture
evidence accepted by its H3 sub-gates; full checker correctly rejects the isolated
H4 artifact for missing coordinator/A-B evidence.

**Runtime-validated:** bounded component-path smoke only; H7 acceptance is not
runtime-validated.

Longer runtime evaluation remains closed until detector/capture latency and
control cadence are made acceptable, strict actuation evidence is complete, and
the acceptance checker passes on a bounded smoke.
