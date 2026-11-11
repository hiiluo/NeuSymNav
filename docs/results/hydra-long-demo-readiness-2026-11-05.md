# Hydra long-demo readiness checkpoint — 2026-11-05

Worktree: `Kiet_branch2`. This report records execution of the D0–D3 gates in
`docs/results/hydra-long-demo-readiness-plan-2026-11-05.md`. Existing dirty work
was retained; no commit or push was made.

## Current decision

The UI-on Hydra 3D demo runs on map 00805 for bounded 30- and 60-second trials.
The 120-second gate is **not passed**. Do not run 300 or 600 seconds yet. The
120-second trial had three in-run `navigation_source_pending` events and three
`expired_before_step` events (6/546 control events, about 1.10%), above the
plan's 1% target. Its RSS sampling issue is now fixed and passed a 30-second
runtime check; the remaining blocker is map/control freshness latency.

## D0 — durable profile and baseline

Implemented `configs/demo-00805.hydra-long-demo.local.json` with the original
00805 scene, seed 0, start pose, UI-on, OpenVINO GPU, NavMap stride 1, and the
existing 300 ms freshness gate. The current profile SHA-256 is
`3170649c387e3770265f2895137a4574b1968a59043a9d252bf65625ad6aafcd`; the UI
worker script pin is `e8350f60113b5a1b35e3f5e3eaf2063c383c7c4fa6c664c55994f49601c5db40`.
Preflight: `ready=true`, `issues=[]`, exit 0. `native_runtime_validated=false`.

The full suite baseline before this checkpoint was `2436 passed, 10 skipped,
32 failed` (exit 1); it has not been rerun after this work. The focused current
test groups are recorded below.

## D1 — Hydra 3D graph and RGB-D display

Implemented a Hydra-native 3D scene adapter that renders native XYZ node
positions and edges, displays Hydra layer counts/revisions, and uses the exact
recorded RGB-D source named by the graph. The bounded reader now indexes
recording payloads once, verifies the selected source again before projection,
and reports source, read latency, queue replacement, and shutdown state. UI
shutdown now asks the Qt event loop to stop, flushes the final graph source,
closes the reader, and writes the final rendered record.

The displayed cloud/frame match flag now compares `FrameKey` fields with the
graph source. An earlier version compared two different JSON representations
and reported false even when the source key and capture timestamp matched.

Visible UI screenshot:

` .runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-30s-final-verified/ui-screen.png `

The 30-second post-flush artifact is
`.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-30s-cloud-flush/`:
completed, 265/265 recorded frames, Hydra export revision 8, UI sequence 62,
clean shutdown, 19,951 displayed points. The final graph and cloud both refer
to `primary-rgbd` frame 90 with the same capture timestamp; display lag is 0 ns.
RSS was 377/377 supported samples (sampled peak 1.915 GB); process-attributed
GPU memory remains unavailable.

## D2 — latency and freshness

Offline, a one-entry cache for the sampled pixel lattice and inverse intrinsics
preserves exact map snapshot parity. On 58 verified recorded navigation frames,
preflight p50 changed from 13.588 ms to 12.738 ms; p95 changed from 14.356 ms to
14.734 ms. This is a small average improvement and does not resolve the latency
tail. Recorded-frame A/B of raycast workers 1/2/4 produced identical final
snapshot SHA `3903880342a29d2794b6e3fd8cef4e6a9be2c44a72b7b71129a36cf9e09c1a7b`;
4 workers was fastest (80 frames: p50/p95/max 126.3/137.7/143.2 ms versus
132.3/143.4/147.3 ms for 2 workers). The profile already uses 4 workers.

The 60-second smoke completed cleanly: 515/515 recorded frames, Hydra revision
16, UI sequence 127, 276/276 actuation proofs, 2.237 m translation lower bound.
There was one `navigation_source_pending` at frame 283 with depth age 303.0 ms
(1/291, 0.34%); no consecutive misses. Control interval p95 was 360.8 ms,
NavMap update p95/max 158.9/301.3 ms, and depth-age p95 212.2 ms. RSS was
615/615 supported samples; GPU memory provider unavailable.

The first 120-second validation ended CLI exit 1 with `outcome=incomplete`,
`error=null`. Recording was complete (986/986), Hydra export complete
(revision 29), UI final sequence 242 rendered, and runtime cleanup clean. The
artifact is
`.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-120s-first-gated/`.

Control and movement evidence: 522 executed events, 525/525 command proof
records with zero missing proofs, 4.539 m translation lower bound, 16
`expired_or_zero` zero-motion stops, 3 `expired_before_step`, and 3
`navigation_source_pending`. The pending sources were frames 240/302/451 at
depth ages 301.6/304.8/331.4 ms. They were rejected by the 300 ms freshness
gate. No stale source was executed. The six freshness misses are 6/546 control
events (about 1.10%), above the plan's ≤1% gate.

Latency by run third (p95/max, ms):

| Run third | Control interval | NavMap update | Core integrate | Raycast | Vote integration |
| --- | ---: | ---: | ---: | ---: | ---: |
| First | 369.5 / 491.9 | 144.2 / 241.6 | 99.6 / 155.2 | 65.4 / 136.6 | 28.7 / 102.8 |
| Middle | 404.5 / 498.3 | 150.3 / 281.4 | 124.0 / 246.5 | 81.2 / 184.4 | 53.9 / 179.2 |
| Final | 388.5 / 546.2 | 155.4 / 295.9 | 117.4 / 280.7 | 84.1 / 169.1 | 36.3 / 176.9 |

The tail increases mildly over the run, especially in raycast/vote integration.
At frames 240/302/451, map update took 281.4/275.2/295.9 ms; core integration
took 246.5/231.5/280.7 ms. Sensor roundtrip was 55.4/23.1/40.1 ms. The misses
therefore coincide with map-core tail work plus sensor time, while freshness
rejection remains correct.

### RSS incomplete cause and fix

One of 1,031 RSS samples was unsupported (`FileNotFoundError`,
`initial_census:children_read`, process 65752) after all three bounded trials
encountered a thread task disappearing between `/proc` enumeration and reading
its `children` file. This made RSS support 1,030/1,031 and resource measurement
incomplete; it was not a Hydra/export/shutdown failure.

Implemented a narrow race handling fix in `runtime/proc_scope.py`: ignore a
missing per-thread `children` file only when that exact task directory has
disappeared and the process identity is still unchanged. The whole process
closure is still checked in the second census. Focused resource tests pass.
The bounded post-fix artifact
`.runtime/hydra_ws/artifacts/hydra-readiness-D1-00805-20261105/ui-on-30s-rss-fix/`
completed 268/268 frames, graph revision 9, clean shutdown, and 427/427
supported RSS samples with zero missing processes or read errors. Sampled RSS
peak was 1.911 GB. This runtime-validates the fix for 30 seconds; the old
120-second artifact remains incomplete and a 120-second post-fix confirmation
has not passed.

The smoke recorded 141/141 command proof records and a 1.065 m translation
lower bound. UI cloud source matched the final graph source; one in-run pending
at frame 29 (depth age 301.2 ms) was rejected by the existing 300 ms gate.

## D3–D6 status

D3 is not passed: only one 120-second run exists and it has freshness misses
above the proposed 1% limit. Its recording, graph/cloud final sources, UI final
render and shutdown succeeded; that artifact's RSS sample was unsupported and
resource `complete=false`. The later 30-second artifact validates the RSS fix,
but does not repair or replace the 120-second result. GPU memory support is 0.
D4/D5/D6 (300 seconds, 600 seconds, second map) were not run.

## Verification commands

- `./.venv/bin/python -m pytest tests/test_hydra_projection.py tests/test_hydra_asset_reader.py tests/test_hydra_spatial_scene.py tests/test_spatial_scene.py tests/test_spatial_scene_regressions.py tests/test_ui_transport.py tests/test_projection_reuse.py tests/test_navmap.py -q --tb=short` — 85 passed, exit 0.
- `./.venv/bin/python -m pytest tests/test_resource_sampling.py tests/test_rss_retry_wait.py tests/test_gpu_provider.py -q --tb=short` — 88 passed, exit 0.
- `./.venv/bin/python -m neusymnav.cli preflight --config configs/demo-00805.hydra-long-demo.local.json` — ready, no issues, exit 0.
- `xdpyinfo -display :0` — connected, exit 0; OpenVINO reported `['CPU', 'GPU']`, exit 0.
- Post-fix UI-on smoke30s — completed, CLI exit 0; resource samples427/427.
- `git diff --check` — exit 0 after report/status updates.

## Next gate

Keep the 300 ms freshness gate, stride 1, and 4 raycast workers. RSS fix
runtime-validation passed at 30 seconds. The remaining D2 work is map-core
latency: pending frames 240/302/451 align with high core/raycast/vote durations;
no tested lossless change has yet reduced the tail enough. Keep the verified
30/60-second UI-on demo path available. Repeat 120 seconds only after an offline
candidate shows exact occupancy parity and meaningfully reduces core tail, then
verify it first with 30/60 seconds. Two clean 120-second runs are still required
before 300 seconds; no 300/600-second demo is currently certified.
