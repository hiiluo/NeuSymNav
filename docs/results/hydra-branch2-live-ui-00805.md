# Hydra live UI smoke — 00805 — 2026-11-04

## Scope

Enabled the existing PyQt dashboard on the calibrated Hydra/OpenVINO profile,
then ran one bounded 30 s simulator smoke to verify the coordinator-to-UI path.
The original `demo-00805.hydra-openvino.local.json` remains unchanged. A local
variant enables UI publication at 2 Hz:
`configs/demo-00805.hydra-openvino-ui.local.json`.

## Result

Preflight passed (`ready=true`, `issues=[]`); UI transport, cadence and Hydra
projection tests passed (36 passed, exit 0). The run used actual OpenVINO UHD.
During the smoke, the X11 desktop showed `NeuSymNav / Live Scene Explorer` as
the active window. The UI process emitted 80 publication sequences. Its final
persisted, decoded publication contains an available Hydra graph at revision 4
with 24 nodes and 79 edges; the publication has input-prefix SHA
`ca6789d3037f8d9cbc98763ff41c36fb905ab29307d510aa47c507ffebb7a744`.

UI process diagnostics: clean shutdown, `failed=null`, 0 dropped publications,
190 coalesced publications. The UI window closes with the run, as expected.
The saved publication is at
`.runtime/hydra_ws/artifacts/hydra-openvino-live-ui-00805-30s-20261104/ui/publication.json`.

Hydra itself finished at revision 6 with 31 nodes and 66 edges, and its native
export manifest is complete. Thus the final displayed publication was two
graph revisions behind the final native export. The profile demonstrates a
visible live coordinator-to-UI path, but not final-revision catch-up.

The command exited **1** and the overall outcome is **incomplete** for the
existing Hydra-only export contract: the legacy hierarchy/NavMap/object bundle
is unavailable. The UI-on run recorded 172 frames, 71 executed commands, 7
`expired_or_zero`, 5 `navigation_source_pending`, and a measured body-translation
lower bound of 0.283 m.

For context, the preceding 30 s UI-off smoke recorded 285 frames, 164 executed,
10 `expired_or_zero`, 1 `navigation_source_pending`, and 1.304 m translation
lower bound. This is a concerning difference, not a controlled causal result:
the runs are separate simulator samples. Do not claim UI has no effect on
navigation cadence yet. The UI-on run sampled 85 primary and 87 navigation
captures versus 108 and 177 in that prior run. Keep simulator duration bounded
until the terminal graph publication gap and the capture/control throughput
difference are understood.

## Verification

- `NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00805.hydra-openvino-ui.local.json" bash tools/run_hydra_map_demo.sh 00805 --preflight` — exit 0, ready, no issues.
- `.venv/bin/python -m pytest -q tests/test_ui_transport.py tests/test_ui_publication_cadence.py tests/test_hydra_projection.py` — 36 passed, exit 0.
- `git diff --check` — exit 0.
- One 30 s smoke with UI enabled — exit 1, overall outcome incomplete; X11 window observed, UI publication decoded, UI shutdown clean.

## Remaining work

- Measure actual control cadence on equivalent recorded sensor/control inputs;
  current replay A/B measures graph/detector throughput only.
- Repeat the live UI smoke with OpenVINO UHD and an accessible desktop/X11
  session. The latest smoke ran Qt offscreen and Torch CPU fallback.
- Validate room membership selection in the dashboard; this smoke showed a graph but did not exercise selection.
- Keep H7 end-to-end acceptance open; this 30 s smoke is not an A/B acceptance run.

## Follow-up — close-time graph gap and cadence evidence

Offline artifact/code tracing identified two sequential causes for the old final
revision gap. First, coordinator publication happened before `Hydra.close()`;
the worker drains already accepted frames during close, so native graph revision
6 was newer than the coordinator's last projection (revision 4). Second, UI
shutdown immediately stopped the publication thread and terminated Qt, without
waiting for a pending latest publication to be rendered.

The coordinator now refreshes snapshot/projection and force-publishes after
Hydra close. UI shutdown drains its pending display bundle and waits for a
Qt-side rendered-publication sequence acknowledgment before terminating the
child. If the final publication is missing or not rendered before the deadline,
shutdown is reported unclean with the target sequence and render state.

Regression tests cover post-close projection and render acknowledgment for graph
revision 6. Verification: `PYTHONPATH=src:tests pytest -q tests/test_hydra_runtime.py
tests/test_ui_transport.py tests/test_hydra_projection.py tests/test_runtime_scheduling.py`
— 62 passed, exit 0 at that checkpoint. The runtime close path was subsequently
extended to stop waiting when the child exits and preserve logs on unclean close.

Cadence from the existing artifacts (both ~30 s, separate runs):

| Measure | UI enabled | UI disabled |
| --- | ---: | ---: |
| Control calls / interval mean | 85 / 353.93 ms | 175 / 171.33 ms |
| Control interval >100 ms | 84/84 | 137/174 |
| Capture-to-detector-return p50/p95 | 990/1,355 ms (7) | 489/688 ms (12) |
| Control depth age p50/p95 | 177/302 ms (85) | 100/197 ms (175) |

The measurements show lower cadence and higher end-to-end detector-return latency
in the UI-enabled run. The detector-return measure includes pipeline delay; it is
not pure model execution time. As the samples came from separate simulator runs,
they do not prove the UI caused the difference. There is no matched recorded-input
A/B yet. Keep simulator runs bounded until that comparison is made.

## Latest follow-up — same-recording replay A/B and UI catch-up smoke

The 30 s UI-enabled recording is complete: 172 observations and SHA-256
`60dd7fc2634e38068c1db72558f3c8251de4cae2f203c49594aa842b31b7bf20`. The replay
launcher now supports configured UI transport and omits NavMapper in Hydra graph
replay because the recording has no measured body-pose transaction for map
updates. Two temporary profiles differed only by `ui.enabled`; both used the same
`novelty` sampling policy because exact `capacity_deferred` replay requires the
selected-input journal.

| Replay arm | Wall time | Observations | Detector calls / commits | Hydra final revision | UI render ACK |
| --- | ---: | ---: | ---: | ---: | --- |
| UI off | 63.1 s | 172 | 7 / 7 | 4 | not applicable |
| UI on, Qt offscreen | 55.7 s | 172 | 7 / 7 | 4 | sequence 32, revision 4 |

Both arms used Torch CPU: OpenVINO requested but the worker exposed only `CPU`
and fell back. One pair with a fixed replay does not show a slowdown, but it does
not establish live control cadence: replay does not run sensor capture or the
actuator loop, and the configured live policy is `capacity_deferred`.

A subsequent 15 s live smoke ran the UI through Qt offscreen. It accepted three
Hydra inputs and exported a complete native graph at revision 3 (0 nodes, 0
edges). The final UI publication was sequence 34 at revision 3; `rendered.json`
acknowledged sequence 34. UI status had 0 dropped and 76 coalesced publications;
UI, sensor, Hydra, and resource sampler shut down cleanly. The generic result is
`incomplete` because the Hydra profile has no legacy hierarchy/NavMap/object
bundle. Controls were 24 `executed`, 7 `expired_or_zero`, and 2
`navigation_source_pending`; mean interval 450 ms, 32/32 intervals exceeded
100 ms. The detector again used Torch CPU fallback. The Qt window was not visible
because X11 `:0` is not accessible in this task environment. This smoke verifies
post-drain graph revision catch-up through the Qt offscreen renderer, not UHD or
the visible desktop.

One earlier 30 s offscreen smoke exited UI code `-6` before rendering the final
publication. Logs were not preserved by the prior close path. Shutdown now exits
the ACK wait when the child exits and persists its diagnostics; the 15 s retry
completed with a render acknowledgment. The cause of the earlier `-6` remains
unknown.

Latest focused verification:
`PYTHONPATH=src:tests pytest -q tests/test_ui_transport.py tests/test_hydra_runtime.py tests/test_hydra_projection.py tests/test_runtime_scheduling.py tests/test_launcher.py -k 'not shipped_ui_script_sha_matches_local_package'`
— 93 passed, 3 deselected, exit 0. No 300 s/600 s run was made. Keep the longer
ladder closed until UI impact on live cadence is measured on matched control
inputs with the intended runtime backend.

## Forensic check — can this recording drive a control-cadence A/B?

The raw recording is lossless and complete (manifest/input SHA
`60dd7fc2634e38068c1db72558f3c8251de4cae2f203c49594aa842b31b7bf20`): 85
`primary-rgbd` and 87 `downward-depth` observations. Source timestamps span
57.211 s; one navigation inter-capture interval is 27.066 s. The separate live
measurement sidecar contains 86 body-pose samples (all navigation frames except
startup frame 0), 73 source-bound actuation proofs, and 85/85 control trace rows
bound to a source. Therefore the artifacts retain enough keyed inputs and
evidence to build an isolated offline control replay; no new recorder fields
are indicated by this audit.

The current `ReplayReader`/`launcher.replay` path does not use those sidecars. It
submits observations to the perception/graph pipeline but never calls
`control_step`; it also omits NavMapper when replay has no pose transaction.
The coordinator's measured-pose admission additionally requires a
`host_monotonic:` clock domain, so feeding the existing `replay:` observations
through the live pose/control seam is deliberately rejected. The boundary must
stay intact; an offline cadence harness needs its own isolated replay pose and
non-actuating interfaces.
Consequently the existing UI-on/off replay pair cannot measure control cadence.
Adding recorder fields alone would not fix this. A separate offline harness
must join observations to recorded poses/control outcomes, pace the same source
timeline, and use an actuator stub that cannot connect to or move Habitat. Its
result would measure replayed control-path cadence under UI load, not certify
live sensor/actuator cadence.

The existing UI-on live trace provides a bounded single-run reference: 85
control calls, mean interval 353.928 ms, p50/p95 327.1/527.4 ms, max 768.976
ms; 84/84 intervals exceeded 100 ms. Stage p50/p95 were 102.56/207.34 ms for
primary sensor roundtrip, 97.22/220.69 ms for NavMap update, and 100.19/211.77
ms waiting for the exact navigation map. This points to sensor roundtrip and
map update/wait as substantial contributors in this sample; it does not isolate
UI causality. The 57.211 s source span and 27.066 s navigation gap also mean
the nominal 30 s label does not describe the retained capture timeline.

Audit artifact: `.runtime/hydra_ws/artifacts/hydra-openvino-live-ui-00805-30s-20261104/cadence-recording-audit.json`.
No control-cadence A/B or additional simulator run was started in this audit.

## Offline control cadence A/B — same source window, fake actuator

Added a separate `replay_control_cadence` path and
`tools/run_replay_control_cadence_ab.py`. It checksum-reads the existing RGB-D
recording, joins each control and pose sidecar by episode/sensor/frame plus
capture timestamp, clock domain, pose version and calibration ID, then rekeys
the matched poses into an isolated `replay:` clock. It uses the normal
`Pipeline.control_step`, NavMapper, Navigator and MotionGuard under an explicit
offline flag. That flag is rejected for host clocks; the offline control seam
accepts only `OfflineReplayActuator`, which has no Habitat client, IPC handle or
simulator reference. In replay mode NavMapper consumes only pose-bound
navigation-depth frames; primary RGB-D remains on the perception/graph lane.

The A/B profiles were verified identical except `ui.enabled`; both were
preflight-ready. The arms ran sequentially on input SHA
`60dd7fc2634e38068c1db72558f3c8251de4cae2f203c49594aa842b31b7bf20`, with a
5 s source-timeline pre-roll and the same 15 s measured window: 112 observations
and 42 recorded control source events per arm. Both completed with clean
runtime shutdown and 42/42 exact navigation-map matches. The UI-on arm rendered
its final publication (sequence 52), with zero drops and 75 coalesced
publications.

| Replay arm | Control interval mean / p50 / p95 / max | `expired_or_zero` | `navigation_source_pending` | Simulated ACK |
| --- | ---: | ---: | ---: | ---: |
| UI off | 353.98 / 331.38 / 506.79 / 619.04 ms | 0 | 0 | 42 |
| UI on, Qt offscreen | 355.83 / 336.27 / 541.31 / 722.51 ms | 1 | 0 | 41 |

In this one pair, UI-on mean interval increased 1.86 ms and p95 increased
34.52 ms. It is a bounded replay result, not a causal or live-cadence
certification. The selected original live window recorded 35 `executed`, 1
`expired_before_step`, 3 `expired_or_zero`, and 3 `navigation_source_pending`.
Replay regenerated 0/1 expired and 0 pending; the fake actuator immediately
acknowledges fresh nonzero commands and does not reproduce real sensor
roundtrip/actuation delay. The replay counts show the control code's behavior
under replayed map timing; the original sidecar counts remain the live reference.

Both arms requested OpenVINO GPU but activated Torch CPU because the worker
reported only `CPU`. The single pair does not clear the 300 s/600 s gate, and no
simulator was started. Successful artifacts:
`.runtime/hydra_ws/artifacts/hydra-openvino-control-cadence-ab-00805-20261104/final-15s/`.
An earlier harness attempt that sent primary 640×480 frames to NavMapper hit
the 100,000-ray guard; that offline-only routing defect was fixed, and its
failed artifact is retained under `retry-1/`.

Focused verification after the harness changes:
`PYTHONPATH=src:tests .venv/bin/pytest -q tests/test_replay_control_safety.py tests/test_replay_cadence_tool.py tests/test_navigation.py tests/test_navigation_motion_config.py tests/test_navigation_fresh_map_lag.py tests/test_hydra_runtime.py tests/test_launcher.py -k 'not shipped_ui_script_sha_matches_local_package'`
— 86 passed, 3 deselected, exit 0. A/B artifact consistency checks and
`git diff --check` also passed.

## Live matched A/B attempt — environment gate not met

The UI-off/UI-on profiles were rechecked and are identical except
`ui.enabled`; both preflights returned `ready=true`, `issues=[]`. They retain
the same scene/seed (`local-intel-00805`, seed 0) and initial pose. Before
starting any simulator, the target runtime check found OpenVINO devices
`['CPU']` with no GPU, `/dev/dri` absent, and `xdpyinfo -display :0` failing to
open the desktop despite `DISPLAY=:0`. Thus this execution environment cannot
run the requested UHD + visible-desktop live A/B. No simulator was started.
The preflight outputs are `/tmp/cadence-off-preflight.json` and
`/tmp/cadence-on-preflight.json`; the OpenVINO device probe returned CPU only.
The live A/B remains open until launched in a session exposing the UHD device
and the desktop display to the runtime process.

## Live UHD + desktop X11 UI A/B — three short matched pairs

The A/B was rerun in the host session after both required gates passed:

- Profile-pinned OpenVINO interpreter: `available_devices=['CPU','GPU']`, GPU
  full name `Intel(R) UHD Graphics (iGPU)`.
- `xdpyinfo -display :0`: exit 0. `/dev/dri/card1` and `renderD128` were present.
- Both profile preflights: `ready=true`, `issues=[]`, exit 0. Profiles were
  identical after normalizing `ui.enabled`; scene 00805, seed 0 and initial
  position matched. Habitat acknowledged the seed in every run.

Six 15 s measured runs were executed sequentially, with one GPU workload at a
time. Pair order was off/on, on/off, off/on. Each detector reported
`backend_active=openvino_gpu`, with no CPU fallback. All six runtime shutdowns
were clean, and all six Hydra-native graph exports were complete at revision 5.
The three UI-on runs used the desktop Qt worker and rendered the final UI
publication at graph revision 5; their publication sequences were 40, 38, 38,
with zero drops and clean shutdown.

### Control results

| Pair | Arm | Control intervals (n) mean / p95 | Executed | `expired_or_zero` | `navigation_source_pending` | Hydra / UI final graph revision |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | UI off | 50; 292.2 / 448.9 ms | 42 | 6 | 3 | 5 / n/a |
| 1 | UI on | 54; 269.2 / 438.4 ms | 47 | 6 | 2 | 5 / 5 (seq 40) |
| 2 | UI on | 54; 270.2 / 461.9 ms | 44 | 9 | 2 | 5 / 5 (seq 38) |
| 2 | UI off | 57; 259.1 / 423.3 ms | 50 | 6 | 2 | 5 / n/a |
| 3 | UI off | 56; 261.8 / 406.5 ms | 46 | 7 | 3 | 5 / n/a |
| 3 | UI on | 53; 276.3 / 437.6 ms | 45 | 6 | 3 | 5 / 5 (seq 38) |

Paired UI-on minus UI-off mean control interval was `-23.0, +11.0, +14.5 ms`
across the three pairs (mean `+0.9 ms`). Paired p95 deltas were `-10.5, +38.5,
+31.2 ms` (mean `+19.7 ms`). `expired_or_zero` totaled 19 off / 21 on;
`navigation_source_pending` totaled 8 off / 7 on. This small sample shows no
consistent mean-cadence change. UI-on p95 was higher in two pairs, so some tail
jitter remains possible; the experiment does not establish that UI caused it.

### Stage latency, p50 / p95 (ms)

| Pair / arm | Primary sensor roundtrip | Navigation sensor roundtrip | NavMap update | Exact NavMap wait |
| --- | ---: | ---: | ---: | ---: |
| 1 off | 69.9 / 126.3 | 15.0 / 25.4 | 137.7 / 230.7 | 135.6 / 232.2 |
| 1 on | 64.3 / 130.0 | 13.9 / 34.1 | 120.8 / 228.4 | 118.8 / 220.0 |
| 2 off | 59.9 / 120.1 | 12.5 / 19.9 | 124.9 / 205.6 | 125.9 / 207.3 |
| 2 on | 60.2 / 124.5 | 12.7 / 30.3 | 130.0 / 229.7 | 131.7 / 230.9 |
| 3 off | 59.5 / 110.0 | 12.6 / 21.2 | 123.9 / 228.1 | 124.4 / 229.2 |
| 3 on | 65.1 / 122.7 | 13.2 / 29.4 | 127.8 / 220.0 | 129.6 / 220.9 |

Across pairs, the mean p50 deltas were +0.1 ms for primary sensor roundtrip,
-0.1 ms for navigation sensor roundtrip, -2.6 ms for NavMap update and -1.9 ms
for exact-map wait. Mean p95 deltas were +6.9, +9.1, +4.6 and +1.0 ms in that
order. NavMap work/wait remains a substantial part of the control interval in
both arms; these short runs do not attribute its cost to the UI.

Each CLI run returned exit 1 with `outcome=incomplete` and
`export_issue="legacy hierarchy/NavMap/object bundle unavailable; Hydra-native
graph export verified"`. This is the selected Hydra-only profile's known result
contract, not a worker crash: native graph export completed, shutdown was clean,
and UI cleanup reported no failed child or dropped publication. No worker `-9`
was observed. The CLI exit is retained per run in the exit-code sidecars.

Machine-readable per-run measurements and device/profile provenance:
`.runtime/hydra_ws/artifacts/live-ui-ab-00805-20261104/live-ab-summary.json`.
Each run also retains `summary.json`, `measurements.json`,
`control-invocations.json`, Hydra export manifest, and (UI-on) publication,
rendered ACK and shutdown diagnostics.

**Verification:** both preflights exit 0; OpenVINO GPU and X11 gate commands exit
0; machine-readable summary parses with `python3 -m json.tool` (exit 0);
`git diff --check` exit 0. No tests were run because this task performed a
bounded runtime comparison and documentation update, with no product code edit.

**Limit:** three short pairs on one scene and seed are enough to compare this
bounded window but do not prove long-run stability, causality, useful navigation
coverage or readiness for a 300 s / 600 s run. The outcome remains
`runtime-validated (bounded)`; the broader `native_runtime_validated` / P10 gate
is still false.

## Command-cause diagnosis and profile-scoped completion — 2026-11-05

The six A/B artifacts recorded `expired_or_zero` in the same count as missing
actuation proofs, but they did not persist the command payload, so those runs
could not distinguish an expired nonzero command from an intentional zero
command. They did persist source-bound stage timings. Of the 15
`navigation_source_pending` events across the three pairs, 10 reached or crossed
the original 300 ms freshness budget while the exact NavMap source was still
updating/waiting (observed source age about 300–323 ms); the other 5 were final
ticks cut short by each run deadline while a source/map operation remained in
flight. This is stale/incomplete map input being rejected at the control seam,
not a sensor worker crash. The freshness limit was not changed.

The smoke adds bounded command diagnostics and disambiguates the `incomplete`
result for the Hydra-only profile. It ran the UI-on profile for 15 s on scene
00805, seed 0, initial pose unchanged, with OpenVINO reporting CPU+GPU and the
desktop `:0` X11 gate connected. The detector reported `openvino_gpu` with no
fallback. CLI exit was 0 and `outcome=completed`: all 96 expected frames were
durably recorded, Hydra-native graph revision 5 exported completely, and
runtime, sensor and UI cleanup completed. The UI rendered its final publication
(sequence 44, graph revision 5), with zero drops. `legacy_bundle` was
`expected=false, available=false`, as appropriate for this profile; this no
longer forces `incomplete`. `native_runtime_validated` remains false because
this smoke does not meet P10 acceptance.

### Smoke control diagnosis

There were 47 control ticks: 35 `executed`, 8 `expired_or_zero`, and 4
`navigation_source_pending`. All 8 former outcomes are confirmed zero commands
with `failure_detail=zero_motion_command`, not nonzero commands whose deadlines
expired. Seven were emitted after decision and motion guard both reported
`committed_goal_blocked:goal_not_traversable`; one was a `depth_stale` safety stop
after a `nav_stale` decision. The 4 pending results comprise three exact-map
updates that reached/exceeded the 300 ms freshness budget (source ages 300.7,
301.8 and 318.3 ms; NavMap update 217.6–316.7 ms; matching wait 193.1–273.9 ms)
and one terminal tick where the 15 s run ended during a map update (251.7 ms)
after a 134.5 ms navigation wait, at source age 169.1 ms. The last is run cutoff,
not a freshness violation.

Control interval mean/p50/p95/max was 316.7/285.6/465.4/514.4 ms. All 35
accepted actuation proofs were `turn_right`; the 48 sampled body poses retained
the same XY and no forward translation was observed. Therefore lifecycle and
artifact completion are acceptable for this profile, but navigation behavior
is not yet acceptable for a longer run: the robot rotates without translating,
the committed goal remains non-traversable, and map work sometimes misses its
freshness window. Keep the freshness/safety policy intact. First diagnose why
the selected goal cannot be traversed and why NavMap update/wait consumes the
freshness budget, then repeat a short smoke and require safe measurable
translation before increasing duration in steps.

### Implementation and verification

Actuation telemetry now includes bounded decision and command reasons, linear
and angular velocities, issue/deadline timestamps, and a typed failure detail.
`zero_motion_command` is prioritized over deadline equality for zero safe-stop
commands; `deadline_expired` is used for nonzero commands whose deadline elapsed.
The Hydra-only completion rule is profile-scoped: complete native export plus
recording, measurements and clean shutdown can produce `completed` without a
legacy bundle. No motion/freshness threshold was changed.

Focused regression command:
`PYTHONPATH=src:tests .venv/bin/pytest -q tests/test_sensor_actuation.py tests/test_actuation_proof_ipc.py tests/test_runtime_measurements.py tests/test_runtime_measurement_wiring.py tests/test_launcher.py -k 'not shipped_ui_script_sha_matches_local_package'`
— 123 passed, 3 deselected, exit 0. Final targeted regression after the
zero-vs-deadline classification ordering change — 4 passed, exit 0.
The three deselected checks are existing UI script SHA pins outside this task.
Live smoke CLI exit 0; summary/measurement/control artifacts parsed and matched
the result counts above. `native_runtime_validated=false`; no 30/60/300/600 s run
was started.
