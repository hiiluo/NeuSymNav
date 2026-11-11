# Hydra branch2 — local 00805 calibration profile

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Result

Created the ignored, worktree-local profile
`configs/demo-00805.hydra.local.json`. It copies the existing 00805
`navigation` and `sensor_config` sections byte-for-value as parsed JSON, selects
`scene_graph.backend=hydra`, removes the legacy region worker, and pins the
branch2 Hydra interpreter, worker entry script, setup script, Hydra dataset,
labelspace, scene, and detector assets by SHA-256. UI is disabled because this
environment has no reachable X server; the branch2 UI script pin is refreshed
only in this local profile.

Profile SHA-256: `19f91538ed04045b9dc0ea0073aa483f8edb98ed39e57ab3897282214d242e1f`.
Calibration contract SHA-256:
`396cf95dd158659dfcb8954c605049b8bb327d7ef36e414ba370bcdaf4831251`.
Readback artifact SHA-256:
`1f0f82447e845ae525c3a29060c52f04765c27a12ac17f3b7d5fc6c913b87205`.

## Measured calibration

Habitat-Sim 0.3.3 reported the actual primary RGB-D render projection and
sensor state at the profile's initial pose. One primary RGB-D capture was
performed; no simulator action was sent. No semantic annotations or evaluator
ground truth were queried.

- Calibration ID: `habitat:b47b59b1bb57db13cf0639e0a703fbde644c729a8ca73ac122e7c72520c3a9a5`
- `K`: `[[319.99996185302734,0,319.5],[0,319.99998092651367,239.5],[0,0,1]]`
- Canonical `body_T_camera` (metres):
  `[[1,0,0,0],[0,0,1,0],[0,-1,0,1.2000000178813934],[0,0,0,1]]`
- Observed `T_world_camera` at calibration pose:
  `[[1,0,0,-0.8588698506355286],[0,0,1,0.49567723274230957],[0,-1,0,1.3239566087722778],[0,0,0,1]]`
- Transform composition was checked as
  `T_world_body @ body_T_camera == T_world_camera` with `rtol=0`, `atol=1e-9`.

Full readback plus source scene/dataset hashes are stored in the ignored artifact
`.runtime/hydra_ws/artifacts/hydra-calibration-00805.json`.

## Verification

Command:

```bash
bash tools/run_hydra_map_demo.sh 00805 --preflight
```

Exit **0**. The result reported `ready=true`, `issues=[]`, and
`native_runtime_validated=false`. The assets section resolved the branch2 Hydra
interpreter, worker entry, and environment setup, plus scene/model/config pins.
This verifies profile and environment readiness only; it does not launch a
NeuSymNav coordinator or start navigation.

The first preflight attempt exposed that the Hydra probe used Python `-I`,
which ignores `PYTHONPATH` from the pinned setup script where the worktree's
Spark-DSG bindings are located. `src/neusymnav/runtime/launcher.py` now keeps
isolated mode for workers without setup scripts and honors the explicit setup
environment for Hydra. The setup-probe regression expectation was updated in
`tests/test_hydra_runtime.py`. The focused Hydra input test had already passed
after the separate static-calibration/per-frame-pose-version correction.

## Limits and next gate

The original profile snapshot above was `19f91538...`. The ignored local profile
was later adjusted after live diagnosis: `workers.sensor.timeout_s=30` s to
accommodate the observed 19.635 s Habitat worker ready time;
`workers.detector.timeout_s` remains 5 s and navigation/movement settings remain
unchanged. Current profile SHA-256:
`962cdf6a3f4a549427c88258a36bda2144969913c4792eae6f3e0d161b4c8310`.

A bounded live coordinator smoke has now run. It exported a revision-2 Hydra
graph and shut down cleanly, but remained incomplete: capture-to-detector-return
p50/p95 was 14.328/25.342 s (n=2), control cadence missed 100 ms for all 83
measured intervals, and native runtime acceptance remains false. Calibration
readback does not establish pose stability after actions, detector service time,
or room output quality. See the [smoke report](hydra-branch2-smoke-00805.md);
do not proceed to long comparisons until latency and control-cadence gates are
resolved.

No commit, push, publication, or change to the original `Kiet_branch` checkout
was made.
