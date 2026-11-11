# Hydra branch2 — bounded live stage profile, map 00805

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Method

Added best-effort, bounded, source-bound monotonic stage records for sensor
request/response and decode, Habitat draw/readback/normalize, simulator action
and step, NavMap update, exact-navigation wait, and the control/actuation path.
These records are diagnostic only and do not feed freshness or control. Existing
capture cadence, movement profile, safety settings, and timeouts were retained.
The only local profile edit refreshed the pinned SHA-256 for the modified sensor
worker script.

One 30 s bounded live smoke ran against the existing calibrated local profile.
It recorded 168 RGB-D frames, 83 primary captures, 84 navigation captures, 82
NavMap updates, and 83 control-loop invocations. The trace has 2,069 records,
including 1,565 stage records, with zero dropped trace records and zero observer
errors. No additional simulator run was started.

## Stage timings

Times are milliseconds. Percentiles are computed from the retained per-source
stage records; counts differ where a lane was skipped or did not execute.

| Stage | n | p50 | p95 | max |
|---|---:|---:|---:|---:|
| Primary sensor request/response | 83 | 171.6 | 309.7 | 429.5 |
| Navigation sensor request/response | 84 | 29.8 | 71.3 | 147.8 |
| Sensor worker draw observations | 167 | 48.8 | 102.9 | 231.7 |
| Sensor worker readback | 167 | 8.4 | 17.6 | 54.3 |
| Sensor packet normalize/encode | 167 | 29.1 | 62.4 | 79.7 |
| Primary host decode | 83 | 23.7 | 40.7 | 88.9 |
| Navigation host decode | 84 | 6.0 | 16.6 | 26.8 |
| Worker IPC dispatch | 247 | 0.08 | 0.13 | 0.27 |
| NavMap update | 82 | 73.5 | 166.6 | 2,102.2 |
| Wait for exact navigation map | 83 | 73.6 | 206.4 | 272.2 |
| Control loop | 83 | 14.1 | 34.6 | 56.3 |
| Actuation request/response | 80 | 7.1 | 15.9 | 17.4 |
| Simulator action API | 52 | 0.20 | 0.62 | 0.77 |
| Simulator physics step | 52 | 0.009 | 0.014 | 0.016 |
| Whole simulator step | 52 | 0.21 | 0.63 | 0.79 |

The dominant consistent intervals are primary sensor capture/response and
NavMap production. The exact-map wait median almost matches the NavMap update
median, so most of that wait is explained by map construction rather than a
long separate scheduler delay. Simulator stepping and actuation IPC are small
in the observed sample. The 2.10 s NavMap maximum is a large outlier and should
be investigated against that source's surrounding CPU load and trace events;
the aggregate alone cannot assign its cause. The primary host request/response
encloses worker work and host decode, so those nested times must not be added as
independent costs.

The run's 82 control invocation intervals all exceeded 100 ms; mean was 361.1
ms and max 861.0 ms. This is consistent with the capture/map cadence evidence.
No movement or map freshness policy was changed based on these measurements.

## Runtime outcome and limits

The CLI exited **1** with `outcome=incomplete`, `error=null`, and
`export_issue="coherent hierarchy/map unavailable; replay accepted evidence to
rebuild"`. Hydra processed two offered inputs and saved a revision-2 graph; the
run had no worker failure, replay requirement, publication mismatch, cap breach,
or cleanup error. All 168 frames were durably recorded. Only two Hydra inputs
were offered/processed and no coherent exported hierarchy/map was available,
so this does not pass the live acceptance gate. `native_runtime_validated` is
false. GPU utilization/resource support was unavailable in this run; RSS was
sampled but does not prove an absolute peak.

## Verification and artifacts

- Focused correctness command:
  `.venv/bin/python -m pytest tests/test_runtime_measurement_wiring.py::test_navigation_worker_records_navmap_update_interval tests/test_runtime_measurement_wiring.py::test_sensor_timing_wiring_records_host_and_worker_intervals tests/test_runtime_measurement_wiring.py::test_every_control_stop_reason_has_support_without_invented_depth tests/test_sensor_execution_metadata.py::test_seeded_real_ipc_ack_and_actual_decoded_resolution_per_lane -q`
  — **4 passed**, exit 0.
- `bash tools/run_hydra_map_demo.sh 00805 --preflight` — ready, no issues, exit 0.
- `bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-stage-profile-00805-30s-20261104`
  — **exit 1**, incomplete outcome; clean shutdown.
- Smoke summary SHA-256:
  `f76baa809d404f0e2888c5bbb9c34a543c4062a274a58fed0ab5fd8d7d7e35e5`.
- Measurements trace SHA-256:
  `8fcba7153f72f9a7315a7fc7c6528c7347e68cc5956edb0c6ad72c4eb59078d1`.
- Control invocation record SHA-256:
  `d5c13dc6b508393a83dfb280611024d17d0bf4aa8685f7e50a6662d6037c9ae3`.
- Artifact directory:
  `.runtime/hydra_ws/artifacts/hydra-stage-profile-00805-30s-20261104/`.

Implemented instrumentation and focused-test correctness are verified. Runtime
stage timing is observed for this one bounded sample, while overall Hydra live
acceptance remains unverified. The follow-up inspection reproduces the 2.10 s
NavMap delay offline as a cold Numba JIT first call; the live artifact does not
retain timestamped CPU/RSS samples for direct host-load attribution. See
[the outlier investigation](hydra-branch2-navmap-outlier-00805.md). No longer
run or movement/configuration change has been made.
