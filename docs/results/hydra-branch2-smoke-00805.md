# Hydra branch2 — bounded 00805 smoke

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Result

The first two 30-second attempts did **not** establish a detector failure. They
timed out while the Habitat sensor worker was still initializing: its observed
ready time was 19.635 s, above the profile's 10 s sensor whole-operation
timeout. The detector timeout change from 5 s to 30 s did not address that
startup deadline and has been reverted. No captures or control actions were
recorded in those two attempts.

With the sensor startup timeout set to 30 s, a third run captured 200 frames and
accepted 64 control commands, but Hydra never started: `child.sh` enabled Bash
`nounset` before sourcing ROS Jazzy, whose setup script reads an unset
`AMENT_TRACE_SETUP_FILES`. That run is retained as a failed startup diagnosis.

The child wrapper now sources ROS setup before enabling `nounset`. A fourth,
bounded 30-second run completed without worker failures or pending processes.
Hydra processed both queued graph inputs, exported and hashed a 335,662-byte
Spark-DSG graph at revision 2, and the hierarchy/map publication revision
mismatch seen in the preceding run is gone (`publication_mismatch=0`). Runtime
shutdown and recording cleanup were clean; no replay is required. The launcher
still reports `outcome=incomplete` and `native_runtime_validated=false`: only 2
detector calls/graph inputs were durably accepted, there were no committed
semantic object-evidence records or room-quality evidence, and required
P10/strict actuation evidence is absent. This is a
successful bounded component-path smoke, not H7 runtime acceptance.

## Final smoke measurements

Attempt `9f4dc3ec-bd13-45e6-a860-ad8316f5972c`, artifact
`.runtime/hydra_ws/artifacts/hydra-smoke-00805-30s-revisionfix-20261104T150133/`:

- 168 recorded frames; recording certificate complete, 0 missing frames.
- Detector `capture_to_detector_return`: p50 **14.328 s**, p95 **25.342 s**,
  n=2. This is capture-to-return end-to-end age, not isolated model inference
  service time. No object-commit latency samples exist.
- Control depth age: p50 **105.641 ms**, p95 **300.811 ms**, n=83; two samples
  were stale. All 83 measured control-invocation intervals exceeded 100 ms
  (mean 355.730 ms). These do not meet a 10 Hz cadence target.
- 46 accepted command records, but 31 lack command proofs; aggregate actuation
  is incomplete. Observed body translation lower bound is 0.0534 m, not a full
  coverage or completed-distance measurement.
- Hydra: offered/queued/processed **2/2/2**, rejected/replaced **0/0**; no
  reported worker failure. Exported graph has 2 objects-layer nodes, 25
  places-layer nodes, 1 room-layer node, and 66 edges. The runtime's semantic
  object-evidence commit count remains 0; the native graph node counts alone
  do not certify semantic objects or room quality.
- Sampled process-tree RSS peak **2,243,256,320 B**; GPU sampling unavailable
  (`no_usable_provider`). Resource peaks are sampled, not absolute bounds.

## Changes made

- Increased only the ignored local profile's sensor worker startup/operation
  timeout from 10 s to 30 s, based on the measured 19.635 s ready time. The
  detector timeout remains 5 s; navigation/movement settings are unchanged.
- Changed `src/neusymnav/backends/hydra/child.sh` to source ROS setup before
  enabling `nounset`.
- Added a regression test and changed Hydra display publication to advance its
  own hierarchy revision when the source navigation map advances. This fixes
  the reproduced `one hierarchy revision cannot refer to different source
  revisions` error.

## Verification and artifacts

- `.venv/bin/python -m pytest tests/test_hydra_runtime.py::test_hydra_publication_advances_hierarchy_revision_when_nav_source_advances -q`
  — **1 passed**, exit 0.
- `.venv/bin/python -m pytest tests/test_hydra_runtime.py -q` — **11 passed**,
  exit 0.
- `bash tools/run_hydra_map_demo.sh 00805 --preflight` — exit 0,
  `ready=true`, `issues=[]`, `native_runtime_validated=false`.
- `bash -n src/neusymnav/backends/hydra/child.sh && bash -n tools/run_hydra_map_demo.sh`
  — exit 0.
- `git diff --check` — exit 0. Post-run worker process check found no active
  detector, Habitat, Hydra, or NeuSymNav CLI worker.
- Final profile SHA-256:
  `962cdf6a3f4a549427c88258a36bda2144969913c4792eae6f3e0d161b4c8310`.
- Final summary SHA-256:
  `416371dba72597c92071828008260e28372772c7ff16ff55d647f8ac0c07626e`.
- Final measurement SHA-256:
  `3f1c4c64416a1b47dac0a1fe9b2b18dc52f4e59310b9fcfcd8230ae4427a6106`.
- Native graph SHA-256:
  `78f3fc394395f5d44c182b52e55715cf7d9a4992f6060e31fca41bd7d989374d`.

Earlier attempts and intermediate artifacts remain under
`.runtime/hydra_ws/artifacts/`. The final smoke command was
`bash tools/run_hydra_map_demo.sh 00805 30 "$outdir"`; the wrapper returned
`outcome=incomplete`; its shell exit code was not retained in the artifact
summary. No longer A/B or 300-second run was started. The offline recorded-frame
latency decomposition is in
`docs/results/hydra-branch2-offline-profile-00805.md`; it measured a 22.9 s
detector cold start and ~1.4 s warm CPU round trip while locating the remaining
control-cadence limit at the sensor/update path (sub-stage timing is still
missing). Next gate is to instrument those sensor/update boundaries and address
command-proof completeness, then rerun the acceptance checker on a bounded
smoke before any longer comparison.
