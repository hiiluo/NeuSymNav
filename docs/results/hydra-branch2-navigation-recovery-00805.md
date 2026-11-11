# Hydra branch2 — blocked-goal recovery — 2026-11-04

## Finding

Offline replay of the prewarmed 30 s capture showed a committed frontier target
was blocked by a neighboring unknown cell that later became occupied. The
target's center cell remained free, but the robot footprint included the
blocker. The planner and motion guard correctly returned zero motion. The
recovery watchdog retained that failed target for about 8 s and 54 map
revisions before selecting another goal.

## Change

`Navigator.observe_navigation_result()` now uses a targeted threshold for the
exact reason `committed_goal_blocked:goal_not_traversable`: abandon the current
goal after at least 1 s and 6 distinct map revisions. This only records a
failed goal and clears the commitment so frontier selection can run again. It
does not make the blocked target traversable. Other eligible geometric stop
reasons retain the existing 8 s / 20 revision threshold. Stale observations,
tracking, pauses and errors still do not count as geometric failure evidence.

The regression test proves that five revisions inside 0.8 s do not clear the
goal, but the sixth revision at 1 s does. The existing failure-feedback tests
also remain green.

## Offline recorded-frame replay

Artifact: `.runtime/hydra_ws/artifacts/hydra-openvino-smoke-prewarmed-00805-30s-20261104/`.
The replay used the recorded downward depth, calibration, pose, profile and
control timestamps; no simulator was started.

- Rebuilt 160 NavMap updates; map revision mismatches: 0.
- Counterfactual recovery fired at depth frame 8, after 6 revisions.
- The original policy's first blocked decision was frame 3; it remained on the
  same goal until its watchdog fired at frame 56.
- The replay diverges from the old control trace at frame 8, so later controls
  were not compared. The old artifact does not preserve enough actuator command
  data to distinguish a zero command from a nonzero command that expired.

The replay result is saved as
`navigation-offline-replay.json` in that artifact directory.

## Bounded live smoke

Ran exactly one 30 s smoke with the same pinned scene and local OpenVINO UHD
profile used by the previous run. No longer simulator run was started.

- Command: `NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-openvino.local.json" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-openvino-navigation-recovery-00805-30s-20261104`
- The controller recorded 5 `committed_goal_blocked:goal_not_traversable` decisions, then `goal_failed_no_progress:committed_goal_blocked:goal_not_traversable` after **1.383 s / 6 revisions**. It selected a different goal `[-0.175, 0.075]`, for which a route was available.
- Control outcomes: **97 executed**, **6 expired_or_zero**, **1 navigation_source_pending**. The prior same-profile smoke recorded 54 expired_or_zero outcomes.
- 105 measured body poses span 0.703 m net translation. This is consistent with the executed-control records; it is not a goal-completion metric.
- Hydra processed 8 inputs without worker failure or exit `-9`; shutdown was clean. Its runtime snapshot reached revision 7 with 74 edges and was not marked stale or replay-required. The Hydra-native graph file is 420,728 bytes; its `hydra-export-manifest.json` is `complete=true` with a verified SHA-256, seven selected inputs, revision 7 and matching input-prefix hash.
- The smoke still exited 1 with `outcome=incomplete` because the generic final exporter requires a canonical hierarchy/NavMap/object bundle, while this Hydra-only profile deliberately does not instantiate the legacy `ObjectOwner` or room pipeline. The Hydra-native export itself is complete; the generic summary does not represent it as a substitute for that legacy bundle. GPU resource sampling had no usable provider. This run validates the navigation recovery and clean Hydra process exit plus native graph export, not H7 end-to-end acceptance.

Artifacts are in
`.runtime/hydra_ws/artifacts/hydra-openvino-navigation-recovery-00805-30s-20261104/`.

## Collision-wait and final-alignment forensic follow-up — 2026-11-05

### Original 60 s artifact: exact trigger chain

Artifact: `.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-60s/`.

Offline replay of source frame 179's recorded depth and pose, using the matching
profile geometry, localized the first stop. The active goal
`frontier-a0782d8528ca` was about 0.058 m away. The controller requested
0.15 m/s, but `MotionGuard`'s bootstrap check used the configured 0.10 m minimum
corridor (`src/neusymnav/navigation/safety.py:72`). It saw 123/124 required
cells; the one deficient cell was `OCCUPIED` at the edge of the larger capsule.
The actual 100 ms pulse covers 0.015 m and its own swept path was clear (105/105
cells). So this stop is caused by the conservative bootstrap probe reaching
beyond the command's actual swept distance, not by an obstacle in that short
pulse.

The coordinator feeds `bootstrap_blocked` back as a goal failure
(`src/neusymnav/runtime/coordinator.py:1236`). Commit-goal policy retains the
goal, and `_select_committed` emits `committed_goal_waiting_after_collision`
while the goal is inside its failure region. In the original artifact, this
continued across 46 successive source/map revisions with matching map source;
it was not `navigation_source_pending`. The generic recovery watch then cleared
the goal after 8.19 s / 47 revisions. This explains the observed long zero-motion
interval.

The later alignment is a separate sequence after a new goal was selected. Its
12 `turn_right` pulses lasted about 2.38 s; heading error decreased monotonically
from −0.618 to −0.124 rad. The controller then entered tracking and produced
forward pulses. This is slow one-direction alignment from sparse control ticks,
not alternating left/right oscillation. The roughly 10 s final near-stationary
window therefore combined the earlier 7.91 s policy WAIT and a shorter alignment
plus forward movement; it was not a continuous spin.

### Bounded confirmation smoke

Only after the above frame-level chain was understood, one same-profile UI-on
60 s confirmation was run at scene 00805, seed 0 and the same initial pose. The
temporary launch profile updated the pinned sensor/UI hashes; the repository
profile was not changed.

- Preflight: `ready=true`, `issues=[]`, exit 0. Smoke CLI: exit 0,
  `outcome=completed`; 393/393 recording frames durable; Hydra native export
  revision 10 complete; UI publication 119 with zero drops; clean shutdown.
- Control result counts: 175 `executed`, 15 `expired_or_zero`, 6
  `navigation_source_pending`, 1 `expired_before_step`. Body translation lower
  bound: 1.367 m.
- One `bootstrap_blocked` recurred at frame 194 for the same goal, followed by
  three `committed_goal_waiting_after_collision` ticks (about 0.30 s). This is
  too short to exercise the 8 s generic watchdog; final runtime reason still
  reports that goal waiting. The last control segment included three monotonic
  right-turn pulses, then forward pulses, then the bootstrap stop. There was no
  prolonged or alternating spin in this short confirmation.
- Completion has limits: actuation proof telemetry is incomplete (15 missing
  proofs; `actuation.complete=false`), resource boundedness is uncertified, and
  GPU resource sampling reports `no_usable_provider`. The run validates the
  bounded runtime path and clean shutdown, not complete command attribution or
  long-run progress.

### Gate

The trigger is understood, but the control behavior is not fixed: an edge cell
outside the 1.5 cm pulse still blocks because bootstrap demands a 10 cm corridor;
then commit-goal policy can keep selecting WAIT. Keep the 120 s and longer gates
closed. Next, align the bootstrap probe with the actual swept command distance
without weakening the footprint/clearance check, add a regression using recorded
frame 179, and run another bounded smoke. Advance only after it shows a released
goal, a new safe executed translation and no growing WAIT tail. No code change
or tests were made in this forensic follow-up.

Confirmation artifact:
`.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-60s-root-cause-confirmation/`.

## Bootstrap command-sweep correction and bounded live confirmation — 2026-11-05

### Change

`MotionGuard` now derives the measured bootstrap distance from the command's
forward speed and the maximum duration still permitted by the command horizon
and remaining depth/map TTL. The curved-pulse margin uses that same duration.
There is no additional fixed minimum corridor. The measured-depth bootstrap
still requires fresh FREE floor-supported evidence for its capsule; `_clear`
still checks actual swept cells and intended path for bounds, FREE state, floor
support and robot-height clearance. Unknown or occupied cells in the actual
footprint still fail closed. The obsolete `bootstrap_corridor_m` setting was
removed from the safety constructor and `configs/navigation.yaml`.

### Correctness verification

The new `tests/test_guard_forward_corridor.py` regression first failed against
the old behavior: a 0.2 m/s, 100 ms command supplied 0.10 m to bootstrap instead
of 0.02 m, and a measured obstacle outside the actual swept footprint blocked
the command. After the change:

- A measured hit inside the short pulse footprint remains `bootstrap_blocked`.
- Invalid current depth remains `bootstrap_blocked`.
- A hit outside the short pulse footprint no longer blocks solely because it
  lies inside the old 10 cm extra lookahead.
- The longer command-horizon case is capped by the remaining 300 ms source TTL.
- Safety/navigation/map/goal-feedback tests: 88 passed, exit 0; the final set
  including robot-geometry checks passed 101 tests, exit 0.

Recorded source frame 179 was replayed from its original `downward-depth`
recording with the same recorded profile geometry and pose. A 0.10 m corridor
reproduced the old stop at 123/124 cells; the actual 0.015 m pulse corridor
returned `bootstrap_ready` at 105/105 cells. The pinned frame/profile hashes
and both outcomes are saved in
`.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/frame179-verification.json`.

### UI-on live smoke — same scene, seed, start and profile

Host preflight reported `ready=true`, `issues=[]` (exit 0). OpenVINO listed
`CPU` and `GPU`, and `xdpyinfo -display :0` connected (both exit 0 in host
context). One 60 s run used scene 00805, seed 0, the recorded initial position,
UI-on and the same UHD detector/navigation profile; only the temporary profile
file supplied pinned script hashes. The detector worker reported
`backend_active=openvino_gpu` with no fallback. Command exited 0.

- Outcome `completed`; recording 459/459 frames; Hydra native export revision
  14 complete; final UI publication 122 rendered; clean shutdown.
- No `bootstrap_blocked` or `committed_goal_waiting_after_collision` occurred.
- The previously committed goal `frontier-a0782d8528ca` produced executed
  forward commands at source frames 178, 179 and 180 (0.06, 0.12 and 0.15 m/s).
  Frame 181 returned `frontier_viewpoint_reached`, then frame 182 selected a new
  goal with a route. This directly confirms the frame-179 bootstrap case no
  longer stops the robot and that progress continues past the prior target.
- Control outcomes: 228 executed and 11 `expired_or_zero`; zero
  `navigation_source_pending` and zero `expired_before_step`. Body translation
  lower bound is 1.927 m.
- Limits: `actuation.complete=false` with 11 missing proofs, resource
  boundedness is uncertified, and GPU resource sampling has no usable provider.
  These prevent treating this bounded run as a long-run qualification.

### Broader verification and gate

The full non-native suite returned 2,426 passed, 1 skipped, 9 deselected and 32
failed (exit 1, 186.45 s). Failures are in evaluation-measurement/execution-proof,
global/live-map publication, shipped UI source hashes, navigation display and UI
publication cadence; the guard-focused set above passes. Those broader failures
were not investigated here.

The specific bootstrap failure and progress stall were reproduced offline,
corrected, and absent in the matching 60 s UI-on smoke. Keep the duration at
60 s until command-proof completeness and resource telemetry are repaired and
audited; do not infer 120/300/600 s stability from this artifact.

Smoke artifact:
`.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/ui-on-60s/`.
Runtime log:
`/tmp/neusymnav-bootstrap-command-sweep-00805-ui-on-60s.log`.

## Verification

- `.venv/bin/python -m pytest -q tests/test_guard_goal_feedback.py` — **45 passed**, exit 0.
- `.venv/bin/python -m pytest tests -q -m 'not native'` — **2,435 passed, 1 skipped, 9 deselected, 3 failed**, exit 1 after 149.11 s. All three failures are the already-known UI script checksum mismatch: configs expect `2e6cec…`; bundled source hashes to `310ae171…`.
- `.venv/bin/python .runtime/hydra_ws/artifacts/hydra-openvino-smoke-prewarmed-00805-30s-20261104/replay_navigation_offline.py` — exit 0; 160/160 map revisions match.

## Status and next work

- **Implemented:** targeted failed-goal recovery; robot safety gates unchanged.
- **Correctness-verified:** targeted tests and exact recorded-map replay.
- **Runtime-validated:** one bounded 30 s live smoke demonstrated earlier goal
  release, subsequent executed controls, and clean Hydra shutdown.
- **Still open:** H7 end-to-end acceptance remains incomplete even though the
  native graph manifest passes its own completeness check. The generic run
  summary still requires a legacy hierarchy/NavMap/object bundle that Hydra
  mode intentionally omits. Decide whether the fail-closed H7 checker should
  consume the verified Hydra-native manifest as its completion contract; do not
  synthesize legacy IDs or revisions. Keep UHD optional and the simulator
  duration at 30 s until that gate is explicitly resolved.

## Four-direction follow-up — 2026-11-04

### Native export and UI path

Coordinator close metrics now retain Hydra's native export result. The launcher
verifies and promotes `hydra-export-manifest.json` to the run root while
keeping the generic outcome incomplete when legacy hierarchy/NavMap/object
exports are unavailable. A recorded revision-7 Spark-DSG graph was loaded,
projected and rendered through the offscreen UI path: 30 nodes and 102 edges,
with all 30 node items visible. The graph-topology widget does not render the
native mesh/cloud. At that check, sandbox X11 access failed, so UI validation
was offscreen only. A later host-session probe reached the running X server and
opened a desktop viewer from the same recorded graph; details are in
`hydra-recorded-graph-desktop.png` and `show_recorded_graph.py` in the artifact
directory. This confirms visible, interactive recorded-graph UI, not live
coordinator updates.

### Detector replay and truthful GPU selection

The first replay ran in a sandbox without `/dev/dri`; OpenVINO selected CPU
through AUTO while the worker metadata echoed the requested GPU backend. That
result was discarded. A device-access check confirmed `GPU Intel UHD Graphics`,
and the replay was rerun over 104 recorded primary RGB-D frames with log evidence
of actual `GPU.0` execution. With 103 steady-state worker IPC samples, CPU
p50/p95 was 1357.5/1494.4 ms and UHD was 402.4/470.3 ms (3.37x/3.18x faster).
The UHD first roundtrip was 12.252 s, including startup; its reported model
warmup was 2.746 s. CPU's first roundtrip was 18.286 s.

Output agreement remains a limitation: 509 UHD detections matched CPU by label
and mask IoU >= 0.5, among 779 UHD candidates and 570 CPU references. UHD's
candidate match rate was 65.3%; mean IoU among matched masks was 0.974. These
are backend agreement figures, not ground-truth accuracy. The 8 live calls in
the preceding smoke had capture-to-return p50/p95 1394.8/1452.3 ms, leaving
additional capture/scheduling/queue stages to instrument.

The detector now enumerates OpenVINO devices before loading static IR and fails
with a specific initialization error if no GPU is exposed. The configured CPU
fallback can then report the actual active backend instead of falsely claiming
UHD.

### Final bounded same-profile smoke

Exactly one new 30 s run used the pinned OpenVINO UHD profile:

```bash
NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-openvino.local.json" \
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
bash tools/run_hydra_map_demo.sh 00805 30 \
  .runtime/hydra_ws/artifacts/hydra-openvino-four-directions-00805-30s-20261104
```

The preflight was ready with no issues. The run recorded 285 frames and the
detector worker reported `backend_active=openvino_gpu`, no fallback, and 1.337 s
warmup. Control results were 164 `executed`, 10 `expired_or_zero`, and 1
`navigation_source_pending`; observed body translation lower bound was 1.304 m.
The blocked goal watchdog released its goal after 1.079 s and 9 map revisions,
then retained an available route. Hydra processed 12 inputs and closed cleanly
at graph revision 9 (50 nodes, 120 edges); the non-stale graph manifest is
complete and hash-verified with 9 selected inputs. No worker `-9` occurred.

The run command exited **1** and the overall outcome remains **incomplete**:
Hydra's native graph export is complete, but the generic acceptance contract
still lacks the legacy hierarchy/NavMap/object bundle. The GPU resource sampler
had no usable provider. The simulator profile kept its UI disabled; the
recorded graph was opened separately in a desktop viewer. Artifact:
`.runtime/hydra_ws/artifacts/hydra-openvino-four-directions-00805-30s-20261104/`.

### Follow-up verification

- `.venv/bin/python -m pytest -q tests/test_openvino_detector.py` — 7 passed,
  exit 0, including the CPU-only GPU fail-closed test.
- `.venv/bin/python -m pytest -q tests/test_openvino_detector.py tests/test_hydra_runtime.py tests/test_hydra_projection.py tests/test_launcher.py -k 'openvino or hydra_native_export or graph or launcher'`
  — 42 passed, 10 deselected, 3 failed, exit 1. The failures are the existing
  three shipped UI-script checksum mismatches: `2e6cec…` expected,
  `310ae171…` actual.
- Actual graph UI projection/filter/selection tests: 6 passed, exit 0. A live
  X11 viewer window was subsequently opened and confirmed as the active window;
  it displays the recorded snapshot, not a simulator-fed live stream.

## Live goal-recovery confirmation — 2026-11-05

The blocked target's center cell remained free, but a neighboring cell inside
the robot's full footprint became occupied as the map incorporated new depth.
That invalidated the old target's traversability, so planner and MotionGuard
correctly stopped. The bounded recovery already implemented for this exact
reason releases the commitment only after at least 1 s and 6 distinct fresh map
revisions, then allows a new reachable frontier to be selected. It does not
weaken the unknown/free or footprint checks.

The earlier 15 s UI-on diagnostic smoke ended after 35 in-place heading actions,
just before the first movement tick. A matched 30 s smoke on the same UI-on
profile, scene 00805, seed 0 and initial pose confirmed the expected sequence:
the blocked goal was released after 1.297 s / 6 map revisions; 48 commands
aligned heading; then 46 accepted `move_forward` actions produced a measured
actuation/pose translation lower bound of 0.602 m. All 94 accepted actuation
proofs were complete, command speed stayed at or below 0.15 m/s, command
horizon stayed at or below 100 ms, and maximum source age at command issue was
286 ms. Nine safe zero commands were recorded (six blocked-goal, three stale
depth); five navigation-source pending outcomes remain a latency limitation.

The 30 s command exited 0; outcome `completed`; 214/214 frames durably recorded;
Hydra-native graph revision 7 complete; sensor/runtime/UI shutdown clean; final
UI publication sequence 67 rendered with zero drops. OpenVINO used the UHD GPU.
Control interval mean/p50/p95/max was 277.3/252.6/489.3/570.8 ms. Artifact:
`.runtime/hydra_ws/artifacts/hydra-goal-recovery-smoke-00805-20261105/ui-on-30s/`.
Resource GPU peak remains unavailable and `native_runtime_validated=false`.
This confirms safe, measurable short-run translation and blocked-goal recovery;
it does not establish long-run stability or P10 coverage. Keep longer duration
gated on additional cadence and resource evidence.

Regression command: `PYTHONPATH=src:tests .venv/bin/pytest -q
tests/test_guard_goal_feedback.py tests/test_navigation.py
tests/test_controller_corner_pulse.py tests/test_navigation_motion_continuity.py`
— 72 passed, exit 0.

## UI-on duration ladder — 2026-11-05

The 60 s and 120 s runs used the exact same profile SHA
`8470a61a3586e50c7fb47c76b9f0e472017a320f0403ded02c7d150fdaae43c8`, scene
00805, seed 0 and initial pose as the 30 s run. UHD was active, X11 `:0` was
connected, and UI was enabled in all three runs.

| Duration | CLI / outcome | Body translation lower bound | Goal IDs / reached viewpoints | `executed` / `expired_or_zero` / pending | Control interval mean / p95 | NavMap update p50 / p95 | Exact-map wait p50 / p95 | UI final / drops |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 30 s | 0 / completed | 0.602 m | 2 / 0 | 94 / 9 / 5 | 277 / 489 ms | 83 / 256 ms | 83 / 250 ms | seq 67 / 0 |
| 60 s | 0 / completed | 1.473 m | 4 / 2 | 196 / 11 / 2 | 286 / 445 ms | 90 / 187 ms | 91 / 189 ms | seq 120 / 0 |
| 120 s | 1 / incomplete | 2.906 m | 6 / 4 | 384 / 15 / 11 | 291 / 453 ms | 86 / 203 ms | 87 / 203 ms | seq 249 / 0 |

Each run released the initial blocked goal after six new map revisions and
roughly 1.25–1.65 s. The 60 s run had no sampled 10 s stationary interval after
initial heading alignment. The 120 s run did: its final 10 s window recorded
only 0.017 m translation, with 25 of 29 control proofs issuing `turn_right` for
the same goal. That is a renewed in-place alignment/stall signal requiring
offline inspection before another longer run.

Latency did not degrade sharply through 60 s, but the 120 s trace shows a
late-run tail regression. From the first to second half, NavMap update p95/max
rose 175/274 → 222/597 ms; exact-map wait p95/max rose 186/275 → 223/322 ms;
control interval p95/max rose 445/702 → 477/740 ms. Pending-source outcomes rose
from 2 in 60 s to 11 in 120 s. The 120 s trace also has one
`expired_before_step` and one `yaw_preflight_unavailable`; both fail closed, and
no freshness or motion bound was relaxed. The 15 `expired_or_zero` results were
6 blocked-goal safe stops, 5 depth-stale stops and 4 reached-viewpoint stops.

The 60 s artifact completed: recording 419/419, Hydra graph revision 12, clean
runtime/sensor/UI shutdown and final UI render. The 120 s artifact exits 1 with
`outcome=incomplete`, although recording 817/817, Hydra graph revision 23,
final UI render and runtime/sensor/UI shutdown are complete. Its measurement /
resource certificate is incomplete: RSS sampling reports 1 truncated sample,
1 deadline exhaustion and 3 read errors. Sampled RSS peak was about 1.997 GB
with no resource cap breach; GPU memory still has no usable provider. Exit codes
are retained in sibling `cli-exit-code.txt` files in the artifact directory.

**Gate:** do not advance to 300 s. First analyze the incomplete resource sample,
late NavMap/service tail and final goal alignment from the saved 120 s artifact
offline. Retry 60–120 s only after the measurement/resource completeness issue
is understood and the stationary tail is addressed; require a complete artifact
and non-degrading late-run cadence before reopening the 300 s step.

## Offline forensic analysis — 120 s

Date: 2026-11-05. Inputs were the existing `ui-on-120s` artifact only. No
simulator, sensor worker, detector workload or GPU workload was started. The
trace and proof artifacts are complete enough for stage timings and executed
actuation, but they do not preserve per-sample RSS errors or the selected
frontier's world-space path.

### Resource sampler

Evidence from `summary.json` and `measurements.json`:

- RSS: 1029 samples, 1028 supported, 1 truncated; sampled peak 1,996,857,344 B
  (~1.997 GB), no cap breach. GPU memory had no provider, so it is unavailable.
- Provider diagnostics: 1030 calls, 1058 attempts, 28 retries, 29 failed
  attempts, 25 missing-process observations, 3 read errors, and 1 deadline
  exhaustion. There were no identity changes, scope truncations or retry-limit
  exhaustions.
- Sampling interval was 100 ms; each rooted process-tree trial had a shared
  1.0 s deadline and up to 3 attempts with 200 ms retry waits. The maximum
  recorded sample timestamp gap was 766.8 ms.

The direct cause of the resource-completeness failure is established in code:
`ProcTreeProvider.__call__` catches `ScopeDeadlineError`, returns an RSS-less
`ResourceReading(scope_truncated=true)`, and the `ResourceSampler.snapshot`
contract sets `complete=false` unless every accepted RSS sample has support.
The one deadline failure is therefore sufficient to make the run incomplete;
this is a certificate rule, not evidence that RAM exceeded its cap. The 25
process disappearance and 3 `/proc` read errors are transient failed attempts
that are mostly recovered by a fresh retry.

The artifact does **not** record which PID, census phase or individual `/proc`
read consumed the one-second deadline. The provider performs two rooted thread
child censuses, validates identities around RSS reads, and may inspect task
threads for a zombie leader; any deadline check in those paths can produce the
same counter. The 1030 provider calls versus 1029 sampler-accepted samples is
consistent with one response arriving after stop and being discarded by
`_run_rss`; this is a code-path inference, not an independently recorded event.
The sample-level phase/time must be added before attributing the timeout to a
particular child or syscall.

### NavMap latency tail

Stage distributions from all 413 updates in `measurements.json`:

| Stage | p50 | p95 | max |
| --- | ---: | ---: | ---: |
| `navmap_update` | 86.0 ms | 202.8 ms | 597.4 ms |
| `control_navigation_wait` | 87.3 ms | 203.4 ms | 321.5 ms |
| `sensor_navigation_roundtrip` | 18.1 ms | 48.2 ms | 131.9 ms |
| `sensor_worker_handler` | 12.0 ms | 60.5 ms | 112.3 ms |
| `actuation_roundtrip` | 10.2 ms | 21.4 ms | 79.6 ms |

The conspicuous map outliers were depth frames 132 (273.8 ms), 284 (291.1 ms),
323 (368.1 ms), 387 (527.3 ms), 397 (567.7 ms), 406 (597.4 ms), and 407
(307.1 ms). At frame 406, sensor navigation roundtrip was only 25.1 ms while
NavMap update took 597.4 ms and source age reached 627.2 ms by update completion.
Frame 397 had a slower 115.9 ms sensor roundtrip, but NavMap still took 567.7 ms.
Thus sensor transport contributes in some cases, but does not explain the largest
tail by itself; the measured time is concentrated in the mapping update stage.

`NavMapper.update` currently times one broad operation containing ray-budget and
projection preparation, core integrate/raycast, fresh-coverage and snapshot
work, then tile-overview update. Its trace has no spans for those sub-operations,
so the artifact cannot tell which is responsible. The profile reports the NavMap
raycast backend as CPU with Numba warmed; UHD is used by the detector and does
not accelerate this navigation mapping lane. First-half versus second-half
NavMap p95/max regressed 174.8/273.8 → 222.2/597.4 ms, consistent with a late
mapping tail, but the trace does not establish whether map growth, a particular
ray workload, memory pressure or OS scheduling caused it.

### Final goal and in-place rotation

The last goal ID in the actuation proof records is
`frontier-3c50d0f61d33-view-34--20`. For it, the artifact contains 39 executed
`turn_right` proofs over frames 363–405, followed by 5 `move_forward` proofs over
frames 408–412. Yaw progresses monotonically from 0.254 rad to -1.494 rad
(about 1.75 rad / 100 degrees); the recorded turn direction never reverses.
The requested turn command is -0.524 rad/s, linear speed is zero, and the
profile's `discrete_heading_control` is enabled. Each action changes yaw by
roughly 0.05 rad, which matches the 100 ms command horizon at 30 degrees/s.

This is evidence of a long one-direction heading alignment, not a left/right
oscillation or proof of an unreachable goal. After the turns, five forward
actions were accepted for that same goal. In the sampled final 10 s window the
robot translated only 0.01699 m, below the 0.1 m movement threshold; 25/29
proofs in that window were turns. The control interval is roughly 0.3 s while a
turn pulse is valid for 0.1 s, and several exact-map waits/pending results occur
in the late sequence. This leaves most of each interval without a new turn pulse
and plausibly explains the low effective angular progress. The command horizon
was left unchanged because it is a safety bound.

Important unknowns: proofs preserve the goal ID but not its exact world XY,
current path, lookahead point or per-tick heading error. Therefore we cannot
establish why this viewpoint ranked first, whether map replanning moved the
desired bearing during those turns, or whether a different reachable viewpoint
would reduce the rotation. The monotonic yaw and subsequent forward actions make
“stuck in a spin loop” too strong; “slow alignment caused a >10 s low-translation
window” is supported.

### Replay attempt and gate

The existing full offline replay script was pointed at this artifact/profile to
rebuild all 412 map/control steps. It ran for more than three minutes without
producing output or an analysis file, so it was stopped manually (exit 130). No
result is claimed from that replay. Findings above were computed directly from
the complete saved stage/control/proof records and read-only source inspection;
they are not a successful NavMap reconstruction or policy counterfactual.

**Decision:** do not run a longer simulator yet. Before retrying 60–120 s, add
bounded per-sample RSS diagnostics (attempt duration, phase/error class, process
count, timestamp, and whether close discarded a result); split NavMap timing into
the internal update phases; and persist goal XY/path/lookahead plus heading error
for each control decision. Then replay or inspect the same recorded window and
produce a new 60–120 s artifact whose resource certificate is complete, with no
10 s near-stationary tail and no worsening late-run NavMap/control latency. Keep
300/600 s gated until those conditions are demonstrated.

### Forensic telemetry implementation — 2026-11-05

Implemented the requested bounded telemetry in the runtime sources. RSS sample
records retain start/end/receive timestamps, duration, process count, support and
error fields, provider attempt count, failure phase/class/PID, retry attempts and
whether the sampler accepted or discarded a result after stop. Provider records
are capped at 8192 and report dropped-record counts. `proc_scope` deadline errors
now carry a phase and PID where available.

NavMap now records per-source spans for preparation, core integration, endpoint
projection, raycast, vote integration, core snapshot publication, fresh coverage,
NavSnapshot creation, overview snapshot and tile update. The detailed spans nest
inside their broader update/core envelopes. Control trace schema v1 captures the
selected goal ID/XY, path point count and up to64 evenly spaced world-space path
points, lookahead XY, wrapped heading error and decision reason. These diagnostics
do not change motion, safety, completion or map policy.

Verification status: implementation is complete; correctness and runtime
validation are pending. Static checks `python3 -m py_compile` for modified
runtime/mapping/navigation modules and `git diff --check` both exit 0. No tests or
simulator were run. No new run artifact exists yet, so serialization under runtime
load, actual phase totals, and whether the new heading/path data explains the late
rotation remain unverified. The 120 s artifact remains incomplete and the long-run
gate remains closed.

### Bounded forensic telemetry smoke — 2026-11-05

**Preflight/run:** existing UI-on Intel profile had stale sensor/UI worker SHA
pins because those workers had since changed. A temporary `/tmp` copy updated
only those two script hashes to the current source. Scene 00805, seed 0, starting
pose, UHD detector, UI-on and movement settings were retained. Preflight reported
`ready=true`, `issues=[]` (exit 0). The final 20 s live smoke exited 0 with
`outcome=completed`; recording/resource certificates and Hydra export completed,
UI rendered final publication sequence 45 with zero drops, and shutdown was clean.
`native_runtime_validated=false` remains unchanged.

An initial 30 s completed smoke exposed that the NavMap spans were not reaching
the collector because `NavMapper` lacked the accessor the coordinator queried.
That accessor was added. It also exposed accumulated phase labels in retry
diagnostics; phase context is now reset at each `/proc` operation. A 20 s attempt
inside the restricted sandbox fell back to CPU because OpenVINO could not see the
GPU and was marked incomplete; it is retained as an environment-fallback attempt,
not used as the final runtime result. The final 20 s run used the verified
desktop/device-access session.

**RSS:** sampler trace and provider attempt records each contain 358 records,
with no drops. All 358 accepted samples have valid RSS and support; there were 6
transient failed attempts that recovered (five `FileNotFoundError` in initial or
final `children_read` and one `ValueError` in `thread_rss_file_read`). There was
no `ScopeDeadlineError`, truncation, unsupported accepted sample or late result
discard. Thus the earlier 120 s certificate failure's RSS deadline did not
recur; the new artifact cannot identify its historical PID/phase, though it will
record them if the timeout happens again.

**NavMap:** the collector trace is complete (2,855 records, zero drops). All 82
updates have all expected source-bound phase spans. Across the 20 s run,
`navmap_update` p50/p95/max is 75.5/186.3/278.2 ms. The maximum is frame 34:
`navmap_prepare` 32.1 ms, `navmap_core_integrate` 137.6 ms (projection 3.7,
raycast 104.5, vote integration 29.3, core snapshot publish 0.05), fresh
coverage 4.0 ms, NavSnapshot 99.2 ms, and tile overview 3.2 ms. This explains the
current bounded-run outlier as combined ray integration and NavSnapshot work.
It does not prove why old frame 406 reached 597.4 ms; that frame was not replayed
through the new instrumentation, and this 20 s sample is not a late-run tail test.

**Goal/control:** 80/80 control diagnostics contain all required fields and no
path sample is truncated. The final control sequence holds goal
`frontier-f0c3d91d422b`; its path has eight points and the heading error converges
from about -0.22 to -0.108 rad, with decision changing from `align_heading` to
`tracking`. No left/right oscillation or prolonged spin appears in this smoke.
The 120 s artifact's final goal was different and had no saved goal/path/heading
fields, so the historical rotation remains unexplained rather than disproved.

**Gate:** this verifies the telemetry path under a short completed GPU/UI run.
The historical RSS deadline and 120 s map/rotation tail remain unresolved. Do
not infer long-run stability or start 300/600 s from this smoke; next inspect the
existing 120 s recording against this attribution or use a bounded 60 s run with
telemetry and inspect its late half.

Artifact:
`.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-20s-gpu/`.

### UI-on 60 s telemetry smoke — 2026-11-05

The final preflight reported `ready=true`, `issues=[]` (exit 0); a prior
preflight attempt transiently exceeded the 3 s Hydra interpreter probe and was
retried before launch. The temporary profile updated only the sensor/UI script
hashes. Scene 00805, seed 0, initial pose, UI-on, navigation settings and UHD
detector were retained. The live 60 s command exited 0. Artifact outcome is
`completed`, 455 recording frames, all completion certificates true, Hydra graph
revision 11 complete, UI final publication 121 rendered with zero drops, and
clean shutdown. The detector reports `openvino_gpu`; seed 0 is applied.

#### RSS by run half

Provider calls were 348 in the first half and 290 in the second (638 total).
All 637 sampler-accepted samples are valid; a single final response after close
is retained in telemetry as `discarded_after_stop`. No unsupported sample,
deadline timeout, truncation, provider-record cap drop or sampler-trace drop
occurred. The provider recorded 6 first-half and 12 second-half recoverable
attempt failures. The first half had three `FileNotFoundError` in each initial
and final children census. The second had nine initial-census and one final-census
children `FileNotFoundError`, one `ValueError` in `thread_rss_file_read`, and one
`FileNotFoundError` at `rss_identity_before:proc_stat_read`. All recovered with a
fresh bounded retry. Thus the historical 120 s deadline did not recur and cannot
be attributed from this run.

#### NavMap and control latency by run half

All 242 NavMap updates have every expected timing span. Collector trace is
complete with 0 drops. Values below are p95/max milliseconds:

| Phase | First half | Second half |
| --- | ---: | ---: |
| `navmap_update` | 161.7 / 216.0 | 172.2 / 241.4 |
| `navmap_prepare` | 51.3 / 90.7 | 49.3 / 83.5 |
| `navmap_core_integrate` | 130.0 / 171.0 | 139.7 / 172.4 |
| `navmap_projection` | 5.1 / 28.0 | 4.3 / 28.7 |
| `navmap_raycast` | 81.0 / 142.3 | 90.8 / 149.0 |
| `navmap_vote_integration` | 19.7 / 91.4 | 48.0 / 82.9 |
| `navmap_core_snapshot_publish` | 0.1 / 0.1 | 0.1 / 0.1 |
| `navmap_fresh_coverage` | 3.0 / 23.3 | 3.9 / 28.2 |
| `navmap_snapshot` | 9.4 / 27.7 | 7.7 / 61.2 |
| `navmap_overview_snapshot` | 0 / 0 | 0 / 0 |
| `navmap_tile_overview` | 5.4 / 8.4 | 6.9 / 18.1 |

The second-half maximum update is frame 236 at 241.4 ms: core integration
144.9 ms (raycast 81.9, vote integration 59.7), NavSnapshot 61.2 ms and prepare
24.2 ms. Overall update p95/max worsened modestly, while core-integration max
was nearly flat. Control interval p95/max was 392.7/478.2 → 391.0/530.3 ms.
This run does not show a severe late-run latency regression, but some phase maxima
are higher in the second half.

#### Goal, movement and advancement decision

All 240 control navigation traces contain the full goal/path/lookahead/heading
field set. The 186 accepted actuation proofs are complete and within the existing
0.15 m/s linear, 0.524 rad/s yaw and 100 ms horizon limits. The measured translation
lower bound is 1.408 m, compared with 1.473 m in the earlier UI-on 60 s smoke.

Control returns include 7 `expired_or_zero` in the first half and 47 in the
second. Of those 47, 46 are safe zero commands from
`committed_goal_waiting_after_collision`; one additional second-half result is
`expired_before_step` and one is `navigation_source_pending`. This is a clear
second-half rise in collision-related waiting, not an RSS or actuator deadline
problem.

In the final 9.95 s, endpoint translation is only 0.046 m with 12 `turn_right`
and 4 `move_forward` actions; yaw changes by about -0.531 rad. The selected final
goal remains `frontier-7d49df6e562c-view--13--24`, its path has 15 points, and
heading error decreases from -0.588 to -0.119 rad. That is slow, one-direction
alignment rather than left/right oscillation, but still a near-stationary tail.

**Decision:** do not advance to 120 s. Artifact and command completion passed,
and overall safe translation is measurable, but the final near-stationary window
and second-half committed-goal wait burst fail the progress gate. The modest
NavMap/control tail increase adds caution. Diagnose the collision-wait and final
alignment sequence, then perform another bounded confirmation. `native_runtime_validated`
remains false.

Artifact:
`.runtime/hydra_ws/artifacts/hydra-forensic-telemetry-smoke-00805-20261105/ui-on-60s/`.

### Audit 11 expired_or_zero và resource sampling — 2026-11-05

Artifact được kiểm tra: `.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/ui-on-60s/`.

**Kết quả actuation proof:** cả 11 `expired_or_zero` đều có `linear_mps=0` và `yaw_radps=0`, nên worker không bước simulator và không thể sinh actuation proof. Sáu stop do `committed_goal_blocked:goal_not_traversable` (frame 3–8), hai do `frontier_viewpoint_reached` (frame 120, 181), ba do `depth_stale` (frame 127, 187, 196). Trong 228 lệnh `executed`, source-key join khớp đủ 228 proof và không có executed command nào mất proof. Vì vậy `missing_command_proofs=11` cũ là lỗi diễn giải counter: nó cộng cả no-op stop.

Đã sửa `RunMeasurements.control()` để chỉ tăng counter khi proof vắng mặt và worker trả `executed=true`. Unit test mới đỏ trước sửa, xanh sau sửa. Không sửa điều khiển, guard, hoặc actuator; artifact gốc vẫn chứa counter cũ và cần một lần chạy sau này mới kiểm tra được output runtime đã sửa.

**Resource sampler:** RSS có 609 mẫu được chấp nhận / 609 được hỗ trợ; không sample truncated, không lỗi đọc cuối cùng, identity ổn định, sample trace không drop. Sampled peak 1,934,004,224 byte. Một response sau khi stop được ghi rõ là `discarded_after_stop`. Trong 608 khoảng giữa các mẫu được chấp nhận: p50 119 ms, p95 nearest-rank 261 ms, max 832 ms. Provider call duration (610 calls): p50 17.7 ms, p95 nearest-rank 167 ms, max 540 ms. 21 `FileNotFoundError` ở census con tiến trình (19 initial, 2 final) đều retry thành công; không deadline/attempt-limit exhaustion.

GPU memory có 0 sample, `no_usable_provider`; chưa có provider Intel có process attribution khả dụng. GPU OpenVINO chạy inference không đồng nghĩa sampler có thể đọc memory theo process. `resources.complete=true` cho RSS/provider contract nhưng `boundedness_certified=false` vẫn chính xác vì peak chỉ được lấy mẫu và thiếu GPU provider.

**Verification:**

- Trước sửa: `./.venv/bin/python -m pytest tests/test_runtime_measurement_wiring.py::test_intentional_zero_command_does_not_count_as_missing_actuation_proof -q` — 1 failed, exit 1 (đỏ mong đợi).
- Sau sửa: `./.venv/bin/python -m pytest tests/test_runtime_measurement_wiring.py tests/test_runtime_measurements.py tests/test_actuation_measurements.py -q` — 86 passed, exit 0.
- Không chạy simulator trong lượt audit này.

Audit dữ liệu máy đọc được: `.runtime/hydra_ws/artifacts/hydra-bootstrap-command-sweep-00805-20261105/expired-zero-resource-audit.json`.

### UI-on telemetry counter smoke — 2026-11-05

Ran a bounded 20 s smoke from `Kiet_branch2` with the same UI-on profile, scene 00805, seed 0 and initial configuration used for the prior smoke. Profile SHA-256: `1aa2e14bb126cb66cce3982fcd98a9536e55c1b2bbe14a6f2571f6bfd815899d`. OpenVINO reported `GPU` available in host context, X11 `:0` connected, and profile preflight returned `ready=true`, `issues=[]`.

- Command: `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 20 .runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-20s` — exit 0.
- Runtime: `outcome=completed`, 163 frames, seed 0 acknowledged/applied, active detector `openvino_gpu` without fallback. Recording complete; Hydra export complete at graph revision 5; UI final publication 43 rendered; sensor/UI/resource shutdown clean.
- Counter proof: **`missing_command_proofs=0`**. The control trace contains 78 `executed` results; all 78 distinct source keys match actuation proof. Artifact holds 79 proof records total, including a proof on a source whose control outcome was not `executed`; do not use total proof count as the executed denominator.
- Control outcomes: 78 `executed`, 7 `expired_or_zero`, 1 `expired_before_step`, and 1 `navigation_source_pending`. Of the 7 `expired_or_zero`, six are zero-motion stops and one is a deadline-expired heading command. The corrected counter does not treat these non-executed results as missing actuation proof.
- `actuation.complete=false` remains expected by its contract: observed body travel is only a partial lower bound without full-run integration proof. RSS sampling was complete (342/342 supported samples, sampled peak 1,866,129,408 B); GPU memory remains unsampled (`no_usable_provider`) and boundedness remains uncertified.

Machine-readable verification: `.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-20s/telemetry-counter-verification.json`.

### Same-profile UI-on 60 s → 120 s verification — 2026-11-05

Both runs used `/tmp/neusymnav-telemetry-smoke-00805-ui-on.json` (SHA-256 `1aa2e14bb126cb66cce3982fcd98a9536e55c1b2bbe14a6f2571f6bfd815899d`), scene 00805, seed 0 applied, UI enabled, active `openvino_gpu` with no fallback. Host checks reported OpenVINO `['CPU','GPU']`, X11 `:0` connected; profile preflight was `ready=true`, `issues=[]` (exit 0).

The 60 s smoke met the gate to proceed to 120 s:

- Exit 0, `outcome=completed`, 457 frames; recording and Hydra export complete at graph revision 12; UI publication sequence 122 rendered; clean sensor/UI/resource/recorder shutdown.
- 224 executed controls, 224 source-matched proof records, zero executed sources missing proof, `missing_command_proofs=0`.
- Body translation lower bound 1.801 m: 0.775 m in the first half, 1.027 m in the second half. No `navigation_source_pending`; one command actually expired at its deadline. The other 11 `expired_or_zero` entries were zero-motion stop decisions.
- The initial 10.28 s had no translation, but the recorded heading error decreased monotonically while aligning; tracking and translation followed. Control interval p95 nearest-rank 415 ms, max 519 ms.

The 120 s smoke completed, but does **not** clear the gate for 300 s:

- Exit 0, `outcome=completed`, 892 frames; recording and Hydra export complete at graph revision 25; UI publication sequence 244 rendered; clean shutdown.
- 433 executed controls, 433 matching proof records, zero executed sources missing proof, `missing_command_proofs=0`.
- Translation lower bound 3.543 m: 1.544 m in the first half, 1.984 m in the second half. There were five goal changes. Sixteen `expired_or_zero` outcomes were no-op stops for blocked goal, stale depth or reached viewpoint; there was no `expired_before_step` and no actual movement command marked `deadline_expired`.
- There were 13 `navigation_source_pending` outcomes. Eleven were isolated; two were adjacent at 119.8 s and 120.02 s, at the run boundary. Control p95 increased to 462 ms (max 589 ms). Two sampled 10 s windows fell below 0.1 m translation: 0–10.27 s and 71.02–81.09 s. Both correspond to heading alignment after a goal selection, with heading error converging monotonically before tracking resumes; no oscillating turn loop was observed.
- RSS was complete at 1,043/1,043 supported samples, peak sampled RSS 1,998,946,304 B, max sample gap 638 ms. GPU memory had zero samples (`no_usable_provider`), so resource boundedness remains uncertified.

Decision: retain the 120 s result as a completed bounded smoke, but do not start 300 s yet. Inspect source/map cadence for the 13 pending events, particularly the final adjacent pair, then run a bounded confirmation if warranted. No 300 s run was started.

Commands:

- `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json bash tools/run_hydra_map_demo.sh 00805 --preflight` — exit 0.
- `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 60 .runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-60s` — exit 0.
- Same command with duration `120` and output `.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-120s` — exit 0; full CLI output saved to `/tmp/neusymnav-telemetry-counter-fix-ui-on-120s.log`.

Comparison: `.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-60s-120s-comparison.json`.

### Truy nguyên navigation_source_pending và smoke xác nhận cadence — 2026-11-05

Phân tích offline trên 120 s artifact đã đối chiếu `control.source` với `navmap_update` và `control_navigation_wait` cùng source frame. Quy tắc tại `coordinator.py::_navigation_map_compatible` cho phép control chỉ dùng map có cùng episode/clock và source còn trong freshness window 300 ms; nếu không tương thích, control fail closed bằng `navigation_source_pending`.

- Trong 13 pending returns của run 120 s, **12 có depth age 301–314 ms**, tức đã qua freshness limit. Map update của frame tương ứng còn đang chạy hoặc vừa kết thúc khi control trả về.
- Pending cuối cùng (frame 463, 120.025 s) có depth mới, age 72.7 ms, nhưng map update của chính frame đó hoàn tất **195.7 ms sau** khi control trả về; navigation wait chỉ kéo dài 52.3 ms. Frame 462 ngay trước đó đã stale (303.8 ms), map xong sau control 22.4 ms.
- Ở 120 s, `navmap_update` p50/p95/max = **81/200/414 ms**, `control_navigation_wait` = **82/192/288 ms**. Đây là đuôi gần freshness budget; stale source bị từ chối, không phát lệnh dựa trên map cũ.
- Smoke xác nhận UI-on 30 s cùng profile/hash, scene và seed: exit 0, 243 frames, 117 executed, 117 proofs, `missing_command_proofs=0`, body translation lower bound 0.765 m, recording/export/shutdown hoàn tất. Có **1 `navigation_source_pending` tại 30.054 s**, depth age 84.4 ms; wait 34.7 ms, nhưng map update cùng frame kết thúc 106.7 ms sau control. Đây là pending do map còn in-flight ngay ở run boundary, cùng kiểu với frame 463 cuối run 120 s.
- Run 30 s có 10 `expired_or_zero`, tất cả là zero-motion stop do goal chưa traversable hoặc đã tới viewpoint; không có command hết deadline. Không thay đổi freshness TTL hoặc hành vi safety.

Kết luận: cặp cuối run 120 s gắn với stop boundary và NavMap update chưa kịp hoàn tất; 12 pending còn lại là freshness misses lẻ tẻ trong run, do capture/control/map cadence vượt giới hạn 300 ms. Không thấy chuỗi pending dài; chỉ cặp cuối là liên tiếp trong control trace. 120 s vẫn chưa đủ gate cho 300 s vì còn 12 freshness misses trong run và p95 control interval tăng lên 462 ms. Hướng tiếp theo là cải thiện/đo lại cadence NavMap/control mà giữ nguyên freshness gate, rồi smoke giới hạn lại.

**Smoke command:** `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/ui-on-30s-cadence-confirmation` — exit 0.

Analysis artifact: `.runtime/hydra_ws/artifacts/hydra-telemetry-counter-fix-smoke-00805-20261105/navigation-source-pending-investigation.json`; CLI log: `/tmp/neusymnav-telemetry-counter-fix-ui-on-30s-confirmation.log`.


### Tách overview khỏi đường publish map/control và smoke giới hạn — 2026-11-05

**Thay đổi:** `NavMapper` tách cập nhật NavSnapshot an toàn khỏi refresh tile overview chỉ phục vụ UI. Pipeline publish snapshot ngay sau core map update, đánh thức control, rồi mới chạy overview; chỉ sinh room input khi có region worker. Freshness gate 300 ms, kiểm tra footprint/swept clearance và điều kiện dùng map giữ nguyên. Timing mới gồm `navmap_publish`, `navmap_overview_refresh`, `navmap_room_input`.

**Correctness:** test mới chứng minh snapshot đã được publish và control chạy được trong khi overview còn bị chặn; không gọi room tile khi không có region worker. Kiểm tra tập trung `tests/test_runtime_scheduling.py tests/test_navmap.py tests/test_runtime_measurement_wiring.py` — 67 passed, exit 0.

**Runtime validation:** host preflight `ready=true`, `issues=[]`; X11 `:0` kết nối; OpenVINO `['CPU','GPU']`. Chạy cùng profile `/tmp/neusymnav-telemetry-smoke-00805-ui-on.json` (SHA `1aa2e14bb126cb66cce3982fcd98a9536e55c1b2bbe14a6f2571f6bfd815899d`), scene 00805, seed 0, UI-on trong 30 s — exit 0, `outcome=completed`, 238 sensor frames.

So với smoke 30 s ngay trước thay đổi:

- `navmap_update` p95 **196.9 → 164.1 ms**, max 241.0 → 232.5 ms.
- `control_navigation_wait` p95 **198.0 → 164.9 ms**, max 242.7 → 233.6 ms.
- Tách riêng, `navmap_publish` p95 0.010 ms; overview refresh p95 40.6 ms chạy sau khi snapshot đã khả dụng cho control. Control interval p95 giảm **437.1 → 418.8 ms** (timestamp invocation; chịu ảnh hưởng sensor/map wait).
- Có 1 `navigation_source_pending`, ở frame cuối 127, depth age 48.1 ms. Control trả pending trước khi map worker bắt đầu; update xong khoảng 99 ms sau đó, snapshot publish khoảng 104 ms sau control. Đây là map đang in-flight ở ranh giới kết thúc run; việc dời overview không thể xoá pending này.
- Kết quả control: 117 executed, 7 `expired_or_zero`, 1 `expired_before_step`, 1 pending; không thiếu control result. Body translation lower bound 0.765 m, missing proof 0. Recording đủ 238/238 frame, Hydra export complete revision 7, UI publication/rendered sequence đều 67; recorder và resource shutdown sạch. RSS có 447 samples, nhưng GPU resource sampler 0 samples (`no_usable_provider`), vì vậy resource boundedness chưa được chứng nhận.

**Quyết định:** cadence p95 đã giảm khoảng 17%, trong khi freshness không đổi. Smoke xác nhận thay đổi hoạt động nhưng còn một pending ở stop boundary cùng các zero/expired control; chỉ thử nghiệm 30 s không chứng minh ổn định dài hơn. Chưa đủ bằng chứng để chạy 60/120/300/600 s tiếp theo. Artifact audit: `.runtime/hydra_ws/artifacts/hydra-cadence-overview-publication-00805-20261105/ui-on-30s/cadence-smoke-audit.json`; runtime log `/tmp/neusymnav-hydra-cadence-overview-ui-on-30s.log`.

**Command:** `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-cadence-overview-publication-00805-20261105/ui-on-30s` — exit 0.


### Truy nguyên pending ở ranh giới run và smoke xác nhận — 2026-11-05

**Nguyên nhân gốc:** vòng live chỉ bắt đầu tick khi còn trong duration, nhưng capture sensor có thể hoàn tất sau run deadline. `_wait_exact_navigation()` đặt hạn chờ thành `min(run_deadline, capture+300 ms)` nên khi deadline đã qua, wait trở về ngay. Trước sửa, launcher vẫn gọi `control_step()` dù map đúng source chưa được publish. Trace smoke trước ghi control trước `navmap_update` bắt đầu khoảng 1.7 ms; nguồn đó được publish sau khoảng 104 ms. Đây là control phát sinh sau khi run đã hết ngân sách, không phải map cũ được dùng.

**Sửa:** ngay sau exact-map wait, launcher kiểm tra run deadline lần nữa. Nếu duration đã hết, nó bỏ qua control và ghi riêng `run_deadline_skips` cùng source frame trong `control-invocations.json`; không tính đây là control invocation hay kết quả pending. Các control trước deadline vẫn dùng exact source và TTL 300 ms. Không thay map compatibility, freshness hoặc safety gate.

**Correctness:** regression test mới trước sửa đỏ do thiếu nhánh deadline; sau sửa, `tests/test_long_runtime.py` — 22 passed, exit 0. Focused set launcher/long-runtime/scheduling/measurement có 104 passed và 3 lỗi checksum UI cấu hình có sẵn (`baseline`, `geometry-only`, `appearance`; YAML SHA cũ không khớp file UI hiện tại). Lỗi đó ngoài thay đổi này.

**Runtime smoke:** cùng profile SHA `1aa2e14bb126cb66cce3982fcd98a9536e55c1b2bbe14a6f2571f6bfd815899d`, scene 00805, seed 0, UI-on, 30 s. Preflight `ready=true`, X11 `:0` kết nối và OpenVINO thấy `['CPU','GPU']`; smoke exit 0, outcome completed, 243 frame. Frame cuối (132) được ghi rõ là một `run_deadline_skip`, `navigation_pending=1`, thay vì gọi control. Wait stage chỉ kéo dài 0.018 ms; map worker bắt đầu 0.8 ms sau đó và publish snapshot khoảng 189.5 ms sau khi wait kết thúc. Điều này xác nhận capture đã tràn qua deadline nên không còn ngân sách chờ map; nhánh mới bỏ lệnh control cuối đúng theo budget run.

**Pending trong thời gian chạy vẫn còn:** 3 `navigation_source_pending` ở frame 27/92/131 có depth age 306.1/302.0/301.4 ms, vượt TTL 300 ms. Cả ba map update kết thúc sau khi control đã trả pending (khoảng 21–82 ms sau), nên bị fail-closed như thiết kế. `navmap_update` p95/max 187.1/339.4 ms; `control_navigation_wait` p95/max 151.8/259.1 ms; control interval p95/max 419.5/515.5 ms. Do đó chỉ pending terminal được loại đúng nghĩa; cadence trong-run chưa đủ ổn định.

Run có body translation lower bound 0.793 m, missing command proofs 0; recording 243/243, Hydra export revision 8 complete, UI sequence 71 rendered, clean shutdown. RSS sampler có 449 mẫu; GPU memory sampler vẫn 0 (`no_usable_provider`), boundedness tài nguyên chưa được chứng nhận. **Chưa chạy dài hơn:** ba freshness miss trong run và update max 339.4 ms còn vượt TTL.

Audit machine-readable: `.runtime/hydra_ws/artifacts/hydra-run-deadline-control-skip-00805-20261105/ui-on-30s/run-deadline-root-cause-audit.json`; log: `/tmp/neusymnav-hydra-run-deadline-control-skip-ui-on-30s.log`.

**Command:** `NEUSYMNAV_HYDRA_DEMO_CONFIG=/tmp/neusymnav-telemetry-smoke-00805-ui-on.json OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-run-deadline-control-skip-00805-20261105/ui-on-30s` — exit 0.
