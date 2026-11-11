# NavMap critical path — 2026-11-06

Worktree `Kiet_branch2` only. User requests lower work before control, aiming
freshness refusals below5% per tested run, as low as feasible. This is not a
claim for arbitrary duration, every scene, or complete ObjectNav acceptance.

## Kết luận hiện hành

Đã triển khai nhánh điều khiển bằng local depth độc lập world-map, giữ nguyên
source/TTL300ms/horizon100ms và các chứng nhận hình học. **Chưa đạt mục tiêu dưới5%
ổn định cho run dài. Không promote profile/default mới.**

| Native candidate | Thời lượng | Freshness | Quãng đường LB | Kết luận |
|---|---:|---:|---:|---|
| Local1worker,world không giới hạn |120s|3.17%|4.782m|Ngắn đạt5%|
| Cùng cấu hình |300s|6.96%|9.869m|FAIL5%|
| Local1worker,world2.5Hz |300s|7.34%|7.830m|FAIL5%|
| Thêm pre-captureGC |120s|5.32%|2.385m|Không promote|
| Capture/control5Hz |120s|0.00%|.649m|FAIL khả năng di chuyển|
| Local4workers |300s|13.32%|5.977m|Rút tùy chọn khỏi production|

Các lần native trên hoàn tấtCLI0, giữ proof/recording/UI/export/shutdown; kết quả
hiệu năng thất bại vẫn được giữ. Test/code correctness không thay thế long runtime
acceptance. Phần bên dưới lưu đầy đủ diễn tiến và các checkpoint theo thời điểm.

## Implemented

- Rolling built-in CPU ray collector accepts bounded output. It skips samples
  outside a conservative spatial/height slab while preserving each original
  physical ray's sample count/fractions, endpoint evidence, pending-last-voxel
  exclusion and occupied-wins. No stride reduction. Custom/GPU collectors and
  nonrolling mode retain prior behavior. Public bounded outputs have1Mcell/
  128MiB limits before allocation; signatures prewarmed before capture.
- Optional Hydra-only `runtime.defer_capture_gc`: full cyclic collection before
  a fresh request, periodically1s; automatic cyclicGC deferred solely across
  capture→exact-mapwait→synchronouscontrol. Reference counting stays active.
  Restore original GC state on exceptions/continue. Diagnostics bounded1024
  events with exact total/drop counts; no capture timestamp is altered.
- Depth/map guard300ms,100ms command horizon, measured floor/height/swept
  footprint/bootstrap, collision-filtered execution, speed and frontier policy
  unchanged. Legacy mode retains world-map control; optional local measured-depth
  planner/controller is implemented (see continuation below).

## Correctness and evidence

`tests/test_bounded_raycast.py`: full traversal plus independent cell crop is the
oracle, including negative geometry, exact faces, no-return masks, lastvoxel,
Python/Numba and parallel outputs; allocation rejection before kernel. Initial
RED15, thenGREEN. Allocationcap RED2 thenGREEN78focused. Paired replay1211/1211
recorded navigation sources: every NavSnapshot state/floor/clearance, source,
capture/domain/revision/origin and current-frame measuredcoverage EXACT.
Private replay clock preserves original numeric timestamps, not live evidence.
Alternating serial replay update p50/p95: full59.646/83.042ms versus bounded
47.210/62.325ms (~25% p95 reduction); offline does not prove live freshness.

GC tests cover collection before capture, no collection within transaction,
periodic/event bounds, exceptions, disabled initial state and strict configbool.
GC checkpoint full suite: **2655passed,10skipped,187.54s,exit0**. Earlier full2642pass
before allocatorcap/GC extension retained separately. No new skips. Independent
Luna xhigh read-only review found no blocking source/GC-state/deadline defect;
review did not run tests. Main runs all evidence-producing workloads serially.

## Runtime campaign

Same scene00805, UI on, local2m/10s, stride1/4CPUworkers, nav10Hz ceiling, primary
0.5Hz/UI1Hz. Selected profile stays opt-in; no guard/scoring/denominator changes.
Freshness miss definition unchanged: pending/expired-before-step/deadline-expired
or stale-depth/map command diagnostics; each invocation counts once, including
stale zero commands. Pure geometric zero commands are not freshness misses.

| Candidate | Run | Misses / actual invocations | Percent | Body translation LB |
|---|---:|---:|---:|---:|
| ROI only |30s|2/218|0.92%|1.534m|
| ROI only |120s|6/807|0.74%|6.200m|
| ROI only |300s|112/1583|7.08%|11.532m|
| ROI + timestamp-only GC probe |300s|47/2167|2.17%|7.102m|
| ROI + scheduled GC |30s|0/211|0.00%|1.606m|
| ROI + scheduled GC |60s|4/360|1.11%|2.962m|
| ROI + scheduled GC |120s|5/763|0.66%|5.998m|
| ROI + scheduled GC |300s|52/1551|3.35%|11.562m|
| ROI + scheduled GC repeat |300s|103/1303|7.90%|8.936m|

Repeat300 failed the5% objective: GC scheduling is experimental and is NOT promoted.
A local-depth control lane is implemented and validated through120s below;
long-run validation and final profile selection are still pending.
All table runs completedCLI0, no missing executed proof/timing violation. First
sandbox30 was retained as incompleteCLI1 because X11 could not connect; it is
excluded from the completed-UI table, not hidden. Outside sandbox X11 probe0,
UI-enabled runs successful. No installs/model/source-sibling edits/commit/push.

The GC probe changes only callback diagnostics/CLIentry wrapper, not collection
policy. The auxiliary callback trace reached its10,000-event cap (5,000collections).
Observed active gen2 max130.555ms; at least3of47 misses overlapgen2>=20ms.
The overlap count is a LOWER BOUND from an incomplete auxiliary trace, not a
whole-run causal share. Complete control traces still support47/2167 freshness. Its2.17% versus ROI7.08% also shows large run/trajectory/load
variance. Do not attribute all observed reduction to GC scheduling or compare
cross-run timings as a controlled causal experiment.

First scheduled300 last100s: **35/411=8.52%**, versus whole3.35%; other windows
1/636=.16%,16/504=3.17%. NavMap p95 rises140.4→187.1→246.3ms. Max2 consecutive
misses. Cyclic maintenance242calls/33.422s total, max271.8ms, all before fresh
capture. It consumes real run time; control interval p95 425.2ms versus ROI-only
364.1ms. Path progress is comparable, not proof of wider coverage. Memory/time
tradeoff remains; no claim of uniformly smooth cadence or removed long tail.

## Limits / next boundary

- Below5% whole-run observed does not prove below5% rolling windows, arbitrary
  duration, multiple maps, or every repeat. Historical1%/P10 gates not declared
  passed; native3DSG room/object accuracy remains separate.
- Current512MiB trace ceiling: scheduled300403,759,104B charged, no drops. At
  this eventrate a600s episode cannot retain a complete full-stage trace. No600s
  run attempted; do not compute whole600s freshness from truncated records or
  silently lower tracing/scoring. Complete bounded streaming telemetry is needed
  before a defensible600s acceptance run.
- A true architecture split must treat world-map goals as intent and validate
  a local replanned segment exclusively on current measured depth, with separate
  source/scope/revision and floor/height/footprint provenance. Merely removing
  `_wait_exact_navigation` would bypass no safe map-age requirement. The optional split is implemented and focused-tested below; native validation
  is pending, so no performance success is inferred from unit tests.

Artifacts `.runtime/navmap-critical-path-20261106/`: RED/GREEN/full logs, paired
replay, originalROI and GC source closures, native recordings/assessments, strict
measurement/control inspection, GC callback correlation. Prior rolling-only
campaign remains `.runtime/navmap-window-20261106/` (6.38%300s from another boot).

## Local measured-depth control lane — implementation checkpoint

Opt-in `navigation.controller.local_depth_control=true`; initial experiments
keep `runtime.defer_capture_gc=false`. World mapping/Navigator run asynchronously
and emit immutable original-source intent, valid at most2s from originalcapture.
Control builds an independent measured-only1m raster, replans a local path,
and applies existing300ms current-depth TTL/100ms command horizon, floor/height/
unknown/swept-footprint checks. All commands use episode-monotonic LOCAL revisions;
world intent revision stays separate in navigation diagnostic schema v2. Legacyv1
remains supported; missing/stale intent STOPs are reported separately.

Independent review found and fixed transient-local-blockage goal blacklisting and
an expired old intent clearing a newer publication. Fault/pause invalidation still
uses a generation gate. Worker159focused passed/exit0; telemetry15focused passed/
exit0. Real threaded test shows newdepth control proceeds while world worker blocks.
Full suite/native runs pending at this checkpoint. No claim of below5% yet.

### Native availability regression and repair

Initial local30s completedCLI0 with0/275 freshness misses but0m translation:
8rotation commands then267null-intentSTOPs. This is an availability FAIL.
Telemetryv2 strict inspection accepted all275controls/provenance, with complete
trace/proofs. Low freshness alone did not establish useful exploration.

The new world worker did not feed its own no-path decision into the existing
watchdog; once intent vanished, local feedback vanished too. Fixed by observing
world no-path STOPs directly on fresh source-bound world maps/poses. A real
Navigator regression requires6fresh blocked maps before clearing the held target,
then a different target next update. Bounded worldplanner reason/age diagnostics
added;160focused passed/11.15s/exit0. Prior full2694passed was BEFORE this repair.

Repaired30s completedCLI0:1.4755m,0/200freshness, no missingproof/timing violations,
recording/UI/export/shutdown complete. Native diagnostics now confirm the original
held goal became `committed_goal_blocked:goal_not_traversable`, watchdog recovered
after1.040s/7distinct fresh world revisions, and exploration resumed.
Repaired60s completedCLI0:2.5480m,9/328=2.74%;120s:4.7824m,21/663=3.17%.
Both recording/UI/export/shutdown clean, no missingproof/timing violations.
GuardTTL300ms/horizon100ms unchanged.

### Separate world-map cadence experiment

Optional `runtime.world_navigation_hz` applies only with local-depth control.
It waits outside admission locks BEFORE dequeuing the newest capture/pose; first
update immediate, no timer catchup, shutdown wakes without a cadence delay.
Capture/control ceiling remains10Hz; original timestamps persist. Intermediate
world-map requests coalesce intentionally; local safety still processes the fresh
captured depth independently. Hydra primary RGB-D cadence is unchanged.

Focused cadence/local/telemetry/scheduling/launcher112passed/12.22s/exit0.
2.5Hz30s:1/248=.40%,0.6475m; p95source167.1ms vs repaired fullrate30s211.6ms.
But137bootstrap-blocked controls and different trajectory mean no causal speed
claim or promotion from this short run; measuring120s next.

### Cadence300s result and combined follow-up

World2.5Hz /localdepth /GCoff300s: CLI0/completed,122/1661=7.34%,7.8301m,
max6consecutive freshness misses. **FAIL5%**. Full strict inspection accepted all
6repaired/cadence runs and every v2 control; no trace drops/missingproof/timingfault.
Current-source hash closure matched before the following configuration-only change.
Full suite2705passed/10skipped,184.00s/exit0 for this cadence snapshot.

Last100s localmap p95 246.4ms, max492.8ms; worldwait p95.004ms. Thus removing the
world wait did not remove all synchronous depth-map tails. Trying the existing
capture-GC window in combination with the local lane; initial mutual exclusion was
an experimental staging restriction, now removed after current-depth/source-bound
synchronous actuation regression. Guard/source TTL/scoring unchanged. RED1config
rejection; focused80passed/9.79s/exit0 including GC restore/caps/exceptions, world
latest-only cadence, local no-world-wait movement and provenance/safety tests.
Combination remains experimental until native results; GC alone previously failed.

### Combined-GC result; admission-rate headroom experiment

Combined30s:0/194,1.1854m. Combined120s:29/545=5.32%,2.3850m,CLI0/cleanproofs;
**FAIL5% and worse movement**. Do not promote this combination or claim GC removed
the latency cause. The original GC staging ban is now lifted with tests, but GC
remains optional/experimental and is OFF for the next candidate.

Next candidate uses existing runtime.navigation_hz=5 (capture/control ceiling),
world_navigation_hz=2.5, local-depth proof and full rays unchanged. This provides
CPU headroom between measured-depth transactions; it does not delay a fresh depth
to wait for an older world map. Actual controller throughput/progress and all
refusals still count. No new control TTL/denominator/sensor downsampling changes.

### Admission5Hz result

World2.5Hz/localcapture-control5Hz/GCoff30s:2/142=1.41%,.8049m.
120s:0/589=0%,but only.6492m;450bootstrap-blocked controls/55missingintentSTOPs,
worldfrontiers also temporarily suppressed after repeated clearance failures.
**Availability FAIL despite excellent freshness.** Do not promote this candidate.
No clearance/unknown/floor gate was weakened to make it move.

Fullrate local-depth/world-unlimited candidate previously moved4.782m/120s at3.17%;
its300s comparison is now running. The rate-limited experiments do not establish
an overall movement improvement. Preserve every failed experiment and report both
freshness and progress, with no universal acceptance claim.

### Fullrate300s and local-kernel parallelism

Fullrate local300s:104/1495=6.96%,9.8689m,max4misses,CLI0/clean proofs. FAIL5%.
This candidate moves farther than the2.5Hz world300s experiment but does not solve
the long freshness tail; no promotion or repeat-pass claim.

Isolated CPU cProfile50frames (after warmup):localmap36ms average,raycast20ms,
slab selection5ms,remaining projection/validation11ms. Alternating serial test on
51recorded sources validates exact states/floor/clearance across1/2/4workers.
Local total p95:39.97/33.08/28.15ms; max48.02/60.23/40.58ms. This is CPU-only
performance support, not a native guarantee. Added explicit local-only
navigation.controller.local_raycast_workers(1..4,default1); full ray lattice,
source/proof contract and legacy helper default remain unchanged. RED1closedconfig
failure,focused126passed/10.05s/exit0 including independent full-crop/bounded/parallel
ray tests and safety/launcher/GC/cadence tests. Native4worker30/120s next.

Parallel4 native30s:.847% (2/236),1.8021m;120s:3.299% (26/788),5.6916m,
max2consecutive misses. Both CLI0/clean recording/proofs/timing/shutdown.
120s sourceage p95269.9ms versus fullrate1worker282.0ms; different trajectories,
so this is native observation rather than causal isolation. 300s in progress.

### Final native finding / rejected parallel option

Parallel4 native300s:168/1261=13.32%,5.9770m,max3misses,CLI0/cleanproofs.
**FAIL5%, worse than1worker fullrate300s6.96%/9.869m.** Isolated ray throughput
improvement did not establish whole-pipeline native improvement under concurrent
world/render/perception work. Exact contention/GC/scheduling attribution is not
proven by this comparison; avoid claiming a single cause.

The extra parallel setting and its production wiring were removed. The exact
experimental source files are retained in `local-lane/parallel-source/`, with
snapshot hashes and the native records; do not load profile-parallel4.json with
the final code (its unsupported option is deliberately rejected). Final production
sources match the pre-parallel source closure; default local collector remains1.

No tested candidate satisfies below5% long-run freshness AND useful movement
consistently. Do not promote any long-ready default. Local-depth architecture is
implemented and correctness-verified; long performance objective remains FAIL.
Use `configs/demo-00805.hydra-local-depth.experimental.local.json` only as an
explicit experimental lane (fullrate,GCoff,world rate unlimited); existing default
and prior rolling profile remain unchanged. Final suite and strict all-run checks
follow this source freeze. No600s run, no guarantee across maps/durations/repeats.

## Hướng sửa tiếp theo — chưa triển khai

- Tách capture/current-depth mapping/control sang process riêng có một owner
  actuator; worldmap/UI/detector/telemetry không chung GIL/GC với đường điều khiển.
  Giữ nguồn/capture/clock/epoch/calibration gốc, intent chỉ là kế hoạch; localproof
  vẫn300ms/100ms, unknown/floor/height/capsule không đổi. Đây là thay đổi owner/IPC
  cần thiết kế và review safety, không phải chỉ bật thêm thread.
- Đo riêng projection/slab/raycast/raster và latency sensor/render/IPC để phân biệt
  chi phí tính toán với tranh CPU/GIL/GC. Bằng chứng hiện tại không xác nhận một
  nguyên nhân duy nhất cho đuôi trễ native. Không suy từ replay1process sang live.
- Chuyển telemetry sang lưu luồng có bộ đệm hữu hạn ngoài control, giữ đầy đủ
  capture/control/proof/invocation; reserve bytebudget cho300/600s và báo incomplete
  nếu thiếu. Không giảm denominator hoặc bỏ zero/stale commands để đạt tỷ lệ.
- Tách thiếu clearance khỏi freshness; lặp bootstrapblocked không được chữa bằng
  suy unknown=free. Cần chẩn đoán quan sát/geometry trước khi sửa recovery/movement.
- Kiểm chứng lại30/60/120/300s và lặp300s với nguồn/seed/profiles công bố rõ; báo
  cả quãng đường/extent, số STOP, rolling100s và graph/cloud provenance. Chưa600s,
  chưa chứng minh graph accuracy hay module ObjectNav hoàn chỉnh.

## Final verification

Final production source freeze matched; full2706passed/10skipped,255.46s,exit0
(`local-lane/full-release.log`). Strict all15native runs and9364actualcontrols
passed schema/source/clock/denominator/proof checks, all collectors complete,0trace
drops/rejections/contention, all final graph/cloud sources match, RSS fullysupported.
`local-lane/strict-final.log`,exit0; `git diff --check`,exit0; experimental config
loadvalidated, not promoted. Exact argv in `local-lane/commands.json`; machine-readable
state `local-lane/final-verification.json`. Performance objective remains FAIL.

Experimental120s command (not long-ready/default):
```bash
cd /home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2
NEUSYMNAV_HYDRA_DEMO_CONFIG=configs/demo-00805.hydra-local-depth.experimental.local.json \
  bash tools/run_hydra_map_demo.sh 00805 120
```
