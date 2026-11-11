# Hydra branch2 H2 — contracts, transform adapter, and native geometry oracle

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` / `.runtime/worktrees/Kiet_branch2`.

## Gate result

**H2 contracts and geometry adapter passed CPU and native correctness checks.** Added CPU-only `HydraCalibration`/`HydraFrame` contracts and `HydraInputAdapter.convert(...)`. The conversion validates primary RGB-D, source/mask/calibration agreement, retains original capture clock and source hashes, converts `T_world_camera` and `T_body_camera` exactly once, emits quaternion wxyz, keeps depth in metres, and maps every invalid depth sample to NaN without changing the source observation.

The frame-order contract rejects duplicate/out-of-order indices, capture times, clock-domain changes, and episode/sensor changes; frame-index gaps remain legal for latest-wins admission. H4 still must call this validator from the actual worker/session offer path.

## CPU verification

Command:

```bash
.venv/bin/python -m pytest tests/test_hydra_contracts.py tests/test_hydra_input.py tests/test_contracts.py -q
```

Result: **120 passed, exit 0**. The tests cover immutable wire roundtrip (including a clean import-order subprocess), source/calibration/mask rejection, future/wrong clock, frame ordering, invalid depth, RGB sentinel preservation, quaternion wxyz, matrix composition, and no mutation of input arrays. A separate import check confirmed `import neusymnav.contracts` does not import `hydra_python` (`native_imported False`). `git diff --check` exited 0.

## Native geometry probe

Command: `source .runtime/hydra_ws/env.sh && PYTHONPATH="$PWD/src:$PYTHONPATH" python .runtime/hydra_ws/probe/h2_native_geometry_probe.py` (exit 0).

The probe reconstructs a synthetic vertical plane from four ordered RGB-D frames. The camera calibration includes a 90° body-to-camera rotation and a 25 cm / −50 cm / 10 cm translation. Each input asserts `world_T_body @ body_T_camera == world_T_camera` within `1e-12`. All four native steps returned true.

Hydra produced a Spark-DSG mesh with **3,485 vertices / 4,774 faces**. The median world-Y coordinate was **2.000078 m** (expected 2 m); measured Z extent was 0.025–1.975 m. This is metre-scale with the expected orientation and camera translation applied once. The first mesh color was `[183, 0, 0]` for a red input sentinel, confirming that channels 1/2 were not swapped at this native boundary. The graph asset reloaded with all 3,485 mesh vertices.

## Invalid-depth native probe

Command: `source .runtime/hydra_ws/env.sh && PYTHONPATH="$PWD/src:$PYTHONPATH" python .runtime/hydra_ws/probe/h2_invalid_depth_probe.py` (exit 0).

An all-NaN float32 depth frame had 0 valid pixels. Hydra returned `step=False` and generated a mesh object with **0 vertices**; Spark-DSG reload also had 0 mesh vertices. This verifies the selected invalid sentinel does not create a measured surface. The false step result is expected for an all-invalid frame; it is not reported as an accepted reconstruction.

## Local 00805 calibration and moving-pose contract

The isolated `configs/demo-00805.hydra.local.json` profile now records the
primary camera calibration read back from Habitat-Sim 0.3.3. One primary RGB-D
capture was made at the configured initial pose; no simulator action was sent
and no semantic annotation or evaluator GT was queried. Measured pinhole
intrinsics are `fx=319.99996185302734`, `fy=319.99998092651367`,
`cx=319.5`, `cy=239.5`. The canonical body-to-camera mount is
`[[1,0,0,0],[0,0,1,0],[0,-1,0,1.2000000178813934],[0,0,0,1]]`.
The observed world-camera transform is consistent with
`T_world_body @ body_T_camera` to absolute tolerance `1e-9`.

This calibration surfaced a contract issue: camera intrinsics and mount remain
static through an episode, but the simulator's per-frame `pose_version`
advances after motion. The adapter had incorrectly required the calibration's
acquisition pose version to equal every later observation. A regression test
reproduced that mismatch; the adapter now validates the static calibration ID,
sensor, and intrinsics while carrying the current observation pose version on
each `HydraFrame`. Focused input tests passed after the correction.

Readback, composition, source/scene hashes and profile hash are recorded in the
[00805 calibration report](hydra-branch2-calibration-00805.md) and the ignored
artifact `.runtime/hydra_ws/artifacts/hydra-calibration-00805.json`. The
computed `HydraCalibration.calibration_hash` is
`396cf95dd158659dfcb8954c605049b8bb327d7ef36e414ba370bcdaf4831251`.

## Artifacts and SHA-256

- CPU test log: `d8e5d032a01131c433bcae3c948478a6603fa6273e577c869e9ce56fa9a9e2ff`
- Native plane probe log: `d806e0e5c6726eaa580a38ca474dd9fc5b071ed7c3acc7759d74f7a34737deef`
- Native plane result JSON: `d457b017f2fcacbe77425e903ed5930f6d496bd5927dee83bfdaa59590e2378a`
- Native plane Spark-DSG asset: `5bcbdc35e1d184f7c8632a4b27bd943426d64dfbc0fd0a9b055a5b3cad67b996`
- All-invalid probe log: `8a7a396e39dc92c1dd5d60babec930aba472a0fa5b3f54356adb2453438464ef`
- All-invalid result JSON: `45435dfda655455b4d66ea4bde2cfb04de009df953b2987a2298db410548e89a`
- All-invalid Spark-DSG asset: `28c5e5f39dd34834521dd6a874153684c154c5b67afa0f68136544bb9318905f`
- Probe source hashes: geometry `b5d4df27a0e1b9d8d0218ad388993addaac76bd9034036568eab6a93732b1bde`; invalid-depth `090a0518deea81fe5715ac7c277b800cb7424f74d614321edf592d879e61a373`.

## Limits and next gate

This proves the adapter/native transform and measured mesh path, not live NeuSymNav runtime, object identity, semantic raster behavior, room generation, or worker backpressure. H3 owns label-raster/object/room checks. H4 wires the tested sequence validator into the worker/session. No movement or `Kiet_branch` source was changed.
