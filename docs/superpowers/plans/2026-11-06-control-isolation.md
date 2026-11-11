# Control isolation song song graph — Implementation Plan C

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans hoặc superpowers:subagent-driven-development; safety/IPC được review riêng trước live actuation.

**Goal:** Giảm tail latency trên capture→localmap→guard→actuation mà không khóa graph work hoặc nới safety.
**Architecture:** Đo contribution trước, rồi prototype process sở hữu duy nhất driver/control; worldgraph/UI/SLM ở ngoài. Existing pipeline giữ làm baseline opt-in so sánh.
**Tech Stack:** Python multiprocessing spawn, current SensorClient/Habitat subprocess, immutable contracts/bounded IPC, NumPy/Numba kernels hiện có.
**Spec:** [Thiết kế chung](../specs/2026-11-06-hydra-objectnav-design.md).

## Global Constraints

Kiet_branch2; source clock/capture/geometry/epoch giữ nguyên,300msTTL/100mshorizon,oneactuatorowner,unknown≠free. No default promotion by unit test. One native/GPU/performance workload; SLM/UI newwork không chạy đồng thời benchmark trừ khi thuộc frozen combined profile. Không thay denominator hoặc che đứng yên.

## Review Focus

Doubledriver ownership, sharedbuffer overwritten while reading, parentdeath with lastcommand active, oldepoch/sourceaccepted as fresh, low freshness due allSTOP. C2 tests/safetyreview và C3 scoring cover cả5.

### C1 — Đo contribution và bounded telemetry

**Modify:** `runtime/{measurements,observability}.py`, `evaluation/measurements.py` qua main; `navigation/local_control.py`, `mapping/local_coverage.py` chỉ instrumentation không đổi math.
**Create:** `tools/profile_control_stages.py`, `tests/test_control_stage_provenance.py`.
**Interfaces:** versioned stage records for projection/slab/raycast/raster/guard/sensor/render/IPC, same source+clock; `analyze_control_stages(artifact)->ControlStageReport`.

- [ ] RED missing/crosssource/futurestage/reorderedtime/overflow tests; run focused stage/measurement tests.
- [ ] Add low-overhead bounded stages, count diagnostic overhead and incomplete records. Record CPU/GPU utilization/frequency/thermal support when available; mark unsupported, not guessing cause.
- [ ] Offline A/B same recorded inputs: Hydra worker enabled/disabled, then UI/perception contribution separately; preserve otherworkloads. Native confirm after hypotheses supported. No claim replay predicts live latency.
- [ ] GREEN; publish attribution report and source hashes. Decide processprototype scope from evidence, not allworkloadtoGPU by default.

### C2 — Process/driver ownership prototype

**Create:** `runtime/{control_process,control_worker,control_transport}.py`, `contracts/control_process.py`, `tests/test_control_process.py`, `tests/test_control_transport.py`.
**Modify:** `runtime/{coordinator,launcher,configuration,resources}.py`, `sensors/client.py` only main integration owner.
**Interfaces:** `ControlProcess.start(config)->StartupReport`, `offer_intent(WorldIntent)->bool`, `poll()->ControlPublication|None`, `close(timeout_s)->CloseReport`. `ControlPublication` contains original captured sources/pose, local revision, accepted commands/proofs, health and bounded raw-frame refs for world/recording. Main freezes DTO/driver routing before dispatch.

- [ ] Write owner/IPC design against actual SensorClient request/response ordering. Critical child owns sole SensorClient for nav/primarycapture/actuation; main cannot retain a second competing RPCclient. Primary jobs never renew navsource timestamps. Use spawn, no inherited Qt/GPU/locks; process tree teardown/resource census includes child and nativeworker.
- [ ] RED fixtures: producer overwritesleasedslot, out-of-orderintent/proof, wrongcalibration/epoch, stale>300ms, sourcefuture, invalidfloor, processkillbefore/aftercapture/issue, parentloss, busyprimaryjob, queuefull, restartoldcommand, shutdownbackpressure. No realactuation in transport/replay tests.
- [ ] Implement bounded single-owner transport; epoch+slotgeneration/lease and hashes verify immutable buffers. No unboundedqueue, no blocking on detector/room/SLM/telemetry. Fail-closed no automatic fallback to another driverowner. Intent2s remainsplanningonly; localdepthproof and actuator deadline checked again atissue/execution.
- [ ] GREEN process+existing guard/replay/deadline tests. Independent Terra/Sol safetyreview required before native, including proof continuity and orphanworker/stop behavior. Keep profile OFF until review; correctness failure blocks this path only, not A/B.

### C3 — Native pilot và quality/performance reporting

**Create:** `tools/compare_control_profiles.py`, `tests/test_control_profile_accounting.py`; main owns new experimental config.
**Interfaces:** `ControlProfileReport` exposes allactualinvocations, refusalsbyreason, p50/p95/p99/sourceage, longestrefusalburst, usefulmovement/coverage/no-progress, proof/timingfaults, recording/export/RSS/tracecompletion, actualworkloadflags.

- [ ] GREEN accounting tests ensure stalezero and failedruns included; nofreshnesscredit for stationary run. Preflight protocol/asset/budget/seed freeze before GPU.
- [ ] Run30→60→120→300s only after safety/smoke gates. <5% is optimization target, not permission to bypass guard or block graph tasks. Report100swindows and workdone; safe run above5% can remain diagnostic.
- [ ] Combined acceptance bounded by roadmap: selectedprofile at most2existing scenes×2seeds×300s,1job; allfailedcases retained. No arbitrary reruns for a prettier number. 600s requires complete bounded recording/tracebudget first, not silent truncation.
- [ ] Promote only reviewed profile with complete proof and useful movement/coverage plus declared performance results. E2E ObjectNav adapter is a later integration gate: revalidate approaches/liveevidence/targetsuccess; no frontendqueryshortcut into motor.

## Handoff

C1 can run fixture/replay independently of A/B; native runs serialized globally. C2 touches shared runtime files only under main ownership. If process isolation does not help, keep previous default and publish attribution rather than lowering TTL/scoring rules.
