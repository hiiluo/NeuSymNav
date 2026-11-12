# Hydra branch2 — OpenVINO UHD worker integration and bounded smoke

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Implemented

Added optional `openvino_gpu` support to the detector worker. The recipe pins
the static OpenVINO XML/BIN and export metadata by SHA-256, checks that model
provenance matches the detector checkpoint, encoder, and taxonomy, and checks
the static class-name order against the taxonomy. The worker compiles the model
on Intel UHD before the pipeline becomes ready. A profile may explicitly select
`torch_cpu` fallback for initialization failures or `fail`; prediction-time
failures do not silently switch backends. Existing profiles still default to
Torch. The launcher exposes active/requested backend, fallback reason, OpenVINO
version, and warm-up time.

The ignored, machine-local profile is
`configs/demo-00805.hydra-openvino.local.json`; its SHA-256 is
`899b13d778ef9d41d2c35e094dbe4cec6e6fef97afc2b9c4ab6d8d80bbc8adac`. It points
to local IR artifacts and is intentionally not portable without those assets.

## Recorded-frame worker replay

The same 95 primary RGB-D frames from the existing 30 s recording were run
through the actual detector worker IPC, sequentially on Torch CPU and OpenVINO
UHD. Warm-up and process startup are excluded from steady-state percentiles.

| Backend | First worker round trip | Steady p50 | Steady p95 | Calls | Clean close |
| --- | ---: | ---: | ---: | ---: | --- |
| Torch CPU | 18,698 ms | 1,362 ms | 1,470 ms | 94 | yes |
| OpenVINO UHD | 11,046 ms | 372 ms | 432 ms | 94 | yes |

The replay shows about 3.7x lower p50 and 3.4x lower p95 worker round-trip
latency on UHD. The replay's UHD backend was confirmed active with no fallback;
model compile/warm-up took 1,652 ms. Against Torch CPU's 314 detections, UHD
produced 431 candidates and matched 296 by same label and binary-mask IoU >=
0.5 (mean matched mask IoU 0.976). The additional and unmatched candidates
mean this is output agreement only, not a quality or accuracy result. No
ground-truth annotations were used.

## Bounded live smoke

After offline replay, ran one 30 s smoke on pinned scene 00805 with the optional
profile and no UI. The detector runtime reported `backend_active=openvino_gpu`,
no fallback, OpenVINO 2026.4.1, and 1,687 ms warm-up. Eager startup worked:
capture-to-detector-return was 669 ms p50 / 910 ms p95 over 7 calls, compared
with 14.3 s / 25.3 s in the earlier un-prewarmed smoke. The p95 still exceeds
the 750 ms semantic TTL. This smoke recorded 271 captures, 110 primary samples,
8 durable detector inputs offered and accepted, zero stale semantic results,
and zero live detector/object evidence commits. Sampled body poses show 0.708 m
net translation; control recorded 103 executed and 54 `expired_or_zero`
outcomes, so motion occurred but command usefulness remains unresolved.

Five native Hydra inputs were accepted, with service times 2.51–5.38 s. The
next input (frame 78) failed because the child worker stdout closed with exit
`-9`. The run exported no coherent hierarchy/map, and `native_runtime_validated`
is false. Projection also reported `Hydra node parent endpoint is missing`.
The evidence does not establish whether the projection failure caused or
followed the child exit, or why the OS terminated the process. The runtime
shutdown was not clean for the Hydra child; sensor/resource cleanup completed,
but GPU resource sampling was unavailable. The smoke command exited 1 and
summary outcome is `incomplete`. The measured process-tree RSS peak was about
1.69 GB, but the workspace cannot read the host cgroup memory counters or
kernel log, so an out-of-memory kill is unconfirmed.

The earlier un-prewarmed 30 s smoke also exited 1. Its detector's first live
frame included lazy initialization: capture-to-return p50/p95 was 14.3/25.3 s.
The new eager worker startup addressed that startup penalty, but did not resolve
Hydra export or command outcomes. No longer simulator run was started.

## Verification and artifacts

- `.venv/bin/python -m pytest tests/test_openvino_detector.py tests/test_detector_worker.py tests/test_projection.py tests/test_hydra_runtime.py -q` — **45 passed**, exit **0**.
- `.venv/bin/python -m pytest tests/test_launcher.py -q -k 'not shipped_ui_script_sha_matches_local_package'` — **26 passed, 3 deselected**, exit **0**. This check exposed a missing-backend default regression in an existing appearance profile; launcher now treats an absent backend as Torch. Its focused regression passed (**1 passed**, exit **0**).
- A prior broader suite had 70 passes and 3 pre-existing UI script SHA mismatches (expected `2e6cec…`, got `310ae1…`).
- Local profile preflight: `NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-openvino.local.json" bash tools/run_hydra_map_demo.sh 00805 --preflight` — exit **0**, ready, no issues.
- 95-frame worker replay: `.runtime/detector26/bin/python .runtime/hydra_ws/artifacts/hydra-cpu-resolution-ab-00805-20261104/replay_worker_openvino_ab.py` with `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1` and access to `/dev/dri` — exit **0**.
- Prewarmed 30 s smoke: `NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-openvino.local.json" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-openvino-smoke-prewarmed-00805-30s-20261104` — exit **1**, outcome incomplete.
- Replay result: `.runtime/hydra_ws/artifacts/hydra-cpu-resolution-ab-00805-20261104/openvino-worker-replay-ab.json`, SHA-256 `30515399f0f7edea2582ba001ef5390c73590d1abea5a8191e15cca76a2260af`.
- Smoke summary SHA-256 `6e12f1aa1625ec5f1c92942d90fdfda803df16f3a19feeb9aa29d41608eada5b`; measurements SHA-256 `d13e2ae2aca55243d3363ca246b462dc35bc7ff9f1ed41984cbe3227e912e43c`.
- OpenVINO model XML SHA-256 `b68fcd9c1537c0461bf8a7a49b47afb513bc2a400a925b43f3d941c45109169b`; BIN SHA-256 `03a705c35ba6c23515d0cbc7f448da339bd2bb35035b71d62917bc335c1c5a69`.

## Status and next work

- **Implemented:** optional pinned OpenVINO backend, worker warm-up/eager startup, explicit initialization fallback, runtime backend metadata, local profile, and canonical Spark-DSG node/parent/edge ID serialization (follow-up).
- **Correctness-verified:** backend/config contracts and fallback tests; six retained Hydra inputs replayed through the actual worker and graph projection after the ID fix; relevant Hydra/projection suite passes.
- **Runtime-validated:** detector offline on 95 recorded frames and Hydra offline on six retained inputs; live only in one bounded 30 s attempt. Full live Hydra map/hierarchy acceptance is not demonstrated.
- **Open:** confirm the graph fix in a future bounded live run, trace the exact navigation grid cells behind the blocked goal, assess UHD output differences with labeled or visually reviewed frames, and address detector p95 above semantic TTL. Keep Torch default; do not increase simulator duration before these gates are reviewed.

## Follow-up diagnosis from the same artifacts

No simulator was run for this diagnosis. The existing journal retained selected
serialized frames for each native input, allowing offline replay of the five
accepted inputs (frames 0, 37, 45, 51, 64) and the in-flight frame 78.

The parent error is a serialization bug, not a missing native graph node.
Spark-DSG `node.id` stringifies to a display symbol such as `R(0)` or `p(20)`,
but `node.get_parent()` and `edge.source/target` return packed numeric
`NodeSymbol.value`s. Before the fix, graph revision 5 had 29 nodes and 28
apparent dangling parents; those numeric values resolve to nodes already in
that same graph. Its summary also contained zero edges although the native graph
contained edges. `_graph_summary` now maps packed symbol values back to the
display IDs for parent references and edge endpoints. A regression test covers
both conversions.

Replaying all six journal inputs through the actual Hydra child after the fix
accepted frame 78, generated a 33-node/114-edge revision 6 summary, projected
all six summaries as `available`, found no dangling parents, and closed with
return code 0. The child RSS after frame 78 was about 230 MB. This shows the
input and native worker can complete in offline replay; it does not prove why
the live child received signal 9.

The best-supported live failure chain is: projection of revision 5 raised the
parent-ID validation error; `_graph_run` catches that failure and enters its
cleanup path while frame 78 can still be in flight; cleanup passes only the
remaining run budget to `HydraSession.close`, which sends SIGKILL when its join
timeout expires. The resulting session-thread error is recorded as `worker
stdout closed (exit=-9)`. The journal has no timestamp for close-request versus
child death, so the cleanup-timeout link is strongly consistent with the code
and artifact but is not independently timestamp-proven. An OOM kill remains
unconfirmed; the workspace cannot access host cgroup counters or kernel logs.
The smoke's sampled process-tree RSS peak was 1.69 GB, but that aggregate alone
does not identify the signal sender.

The 54 `expired_or_zero` results are a count-for-count match to 54 zero-output
navigation decisions: 53 `committed_goal_blocked:goal_not_traversable` and one
`goal_failed_no_progress:committed_goal_blocked:goal_not_traversable`. Those
54 events are the contiguous depth-frame range 3–56, all at pose version 1,
with source depth age 69–232 ms (under the 300 ms freshness limit). The other
103 decisions are exactly 53 `tracking` plus 50 `align_heading`, matching 103
executed-command proofs; the 54 no-motion results match 54 missing proofs.
`Navigator` returns a zero command when the committed goal has no traversable
path, and the actuator labels a zero command `expired_or_zero`. Thus the
primary supported cause is a geometrically blocked committed goal, rather than
slow object detection or stale depth. Since the measurement artifact does not
retain those 54 commands' linear/yaw values or their issue/deadline times, a
deadline expiry coincident with a zero command cannot be excluded per event.

The artifact records the failed target and watchdog result, but not the
per-revision navigation grid cells that made the goal non-traversable. It
therefore cannot distinguish unknown cells, occupied cells, clearance, or a
path-planning defect. Diagnose that from offline navigation replay or add
source-bound decision/command fields to telemetry before another live run.

### Follow-up verification and artifacts

- `.venv/bin/python -m pytest tests/test_hydra_projection.py tests/test_hydra_session.py tests/test_hydra_runtime.py tests/test_hydra_acceptance.py tests/test_hydra_input.py tests/test_hydra_contracts.py tests/test_hydra_labels.py tests/test_projection.py -q` — **49 passed**, exit **0**.
- The new numeric-parent/edge regression first failed on the old serializer, then passed with the fix; all 6 `tests/test_hydra_projection.py` tests pass.
- Offline replayer: `.runtime/hydra_ws/artifacts/hydra-openvino-smoke-prewarmed-00805-30s-20261104/diagnose_hydra_accepted_replay.py`; output `hydra-offline-accepted-replay.json`.
- Control analysis: `.runtime/hydra_ws/artifacts/hydra-openvino-smoke-prewarmed-00805-30s-20261104/diagnose_control_no_motion.py`; output `control-no-motion-diagnosis.json`.
- Offline replay JSON SHA-256: `5559182ece9fe19cca51e25defe4cc2c9ed61ad9b37e2038adbcc570829e9261`; control diagnosis JSON SHA-256: `92df14c3ed554e462d831ccefb359d51b6823943dd788105b30f176518c22c3b`.
- The child replay is runtime-validated only on retained frames. The serializer fix has not been live-validated. Keep UHD optional; no longer simulator run was performed.

**Updated status:** implemented — canonical Spark-DSG node/parent/edge ID conversion; correctness-verified — regression suite and real-worker offline replay of the six journal frames; runtime-validated — offline recorded inputs only. The live Hydra worker exit is explained by a corrected upstream projection failure with a likely cleanup-timeout consequence, but a fresh bounded simulator confirmation remains outstanding. The blocked-goal reason is identified; its exact occupancy/clearance cause is unavailable from this artifact.
