# Realtime control profile

User-selected target: at least10Hz control, report p95/p99 and deadline misses.
This is an observed soft-realtime objective; neither CPython/Qt nor the host OS
provides a hard scheduling guarantee. A fast UI timer is not evidence of fresh
control or graph updates. Do not infer timing acceptance from unit tests.

## Implemented opt-in profile

- Navigation and controller share the unchanged footprint rule. Each planner
  and frontier extractor may retain one exact-content mask: radius, resolution,
  state shape/dtype and ALL state bytes are the key. No revision-only, source
  identity or stale timestamp shortcut. Borrowed masks are bytes-backed and
  cannot become writable. Paths still carry the current map revision/origin.
- Optional `navigation.mapper.raycast_workers` is an integer1–4, default1.
  Numba's existing ray kernel runs on disjoint input chunks using task-local
  arrays and identical GLOBAL raster bounds. Union the masks and then apply
  occupied-wins exactly as serial. Keep every input ray, floor/height bin,
  unknown rule, sampling_stride and precision predicate unchanged.
- Parallel execution requires the existing Numba backend, at least256rays and
  aggregate task-local vote buffers≤64MiB. Otherwise use the original serial
  path. This leaves headroom inside the existing128MiB vote working budget.
  No new dependency. A per-call executor joins every task before returning,
  including error paths; no background global executor survives mapper close.
- The opt-in demo profile is `configs/p10/demo-realtime-00861.json`, with
  four workers on the inspected12logical-CPU host. Source/config hashes and
  before/after artifacts must identify the actual run; default stays serial.

Freshness300ms, command horizon100ms, v/yaw limits, footprint, collision checks,
source one-use and host proofv1 (including SUM of nominal translation/yaw
pulse durations≤100ms) remain unchanged. Giving each sequential axis100ms
would violate that existing proof contract; this candidate does not do so.

## Measurement and acceptance limits

Native preparation uses one GPU job at a time, same existing scene/models,
full raw recording, same budgets and Qt offscreen UI. Explicitly label this
as instrumented preparation, not P10 frozen acceptance or a real-display FPS
benchmark. All failures/incomplete outcomes remain recorded.

Report active observed control invocation cadence and inter-invocation interval
p50/p95/p99; deadline miss is an interval>100ms. Also report accepted motion
proofs/reasons so fast zero/stale calls cannot masquerade as useful control.
Startup until first control and shutdown after last control are separate and
not silently added to the active-rate denominator. Missing proofs, map waits,
resource support and source freshness must remain explicit. A mean≥10Hz does
not imply every100ms deadline was met; report both populations.

## Archive quota scheduling

The native mapper binds one run-owned archive reservation scope before worker
threads start. The existing conservative archive budget and RunQuota disk scan
now surround every actual archive write transaction (both eviction paths),
before any staging file write or active-tile mutation. Frames that only update
RAM do not scan disk. Other/custom mapper implementations retain the original
per-update reservation fallback. The quota check is moved, never cached,
weakened or skipped for an archive write; rejection leaves existing active
tiles/map revision unchanged. All raw/graph/export reservations remain.

Intermediate four-worker30s diagnostic:9.703Hz, intervalp95140.24ms/p99158.46ms,
110/282intervals>100ms; completed/raw/resources/cleanup supported but DOES NOT
meet the user's10Hz target. Further quota scheduling correction is a separate
source checkpoint; do not replace this result with a better rerun.

## Mathematical wavefront reuse

The planner retains at most one search result keyed by the exact eroded
traversability bytes, shape, episode/geometry, origin/resolution, start cell,
goals, planner configuration and blocked edges. Cache at most65goals and
65536path cells, with a mask cap of1million cells. A cache hit reconstructs
PathResult with the CURRENT map revision; Navigator still validates the fresh
map clock/TTL, recomputes frontier/policy/controller intent, and MotionGuard
validates actual current footprint/path/depth. No old command or source frame
is replayed. Changed geometry, mask, start, goals or blocked edges recomputes
the original Dijkstra search. The single-goal A* remains an independent oracle.

Cache keys snapshot primitive planner configuration values and frozen blocked
edges; they do not keep references to mutable caller state. Adversarial tests
retained a RED case for in-place configuration/edge mutation before this was
fixed.80historical recorded frames produced identical full Navigator decisions
with wavefront reuse versus forced recomputation (25276vs42632heap pops).

Pre-JIT software gate:1377CPU tests pass, fault4, source-only packaging,
nativeDuDe3 and202selected source hashes all exit0. Source97Python files stayed
fixed during that gate. Fixed confirmation inputs:00861scene,seeds0and1,
30seconds each, one execution per seed, source/config/profiler pinned before
either starts. This is a realtime preparation batch, not the P10 two-scene
campaign; resource-incomplete results stay incomplete and all slots count.

## GIL-free stable wavefront

The optional existing Numba runtime now executes the SAME multi-goal Dijkstra
loop outside the GIL: identical neighbor order, distance/serial heap priority,
corner/blocked-edge tests, partial expansion budget, goal settlement order and
predecessor reconstruction. No fastmath. Compile its actual read-only input
signature during planner setup before fresh capture/control. The Python engine
remains available (`accelerate_many=False`) and is the fallback without Numba,
for rasters>16384cells,>65goals,>1024blocked edges or unsupported input types.
Noncanonical edge sets use Python rather than silently normalizing a previously
ignored edge. This corner was caught by retained differential RED case84.

Actual host tests:300randomized cases match EXACT paths, costs, output order
and budget outcomes against Python.80retained recorded frames produce identical
full Navigator decisions versus forced Python recomputation; Python heap pops
fall from42632to0. This is CPU correctness evidence, not native timing acceptance.
Fresh full gate1379CPU/3native-deselected, fault4/source-only/nativeDuDe3/source202
all exit0;98sourcePython hashes unchanged during verification. A new two-slot
30s/seed batch is separately frozen atjit-confirmed-batch/frozen.json. Earlier
batch outcomes remain historical and are not relabelled to certify this head.


## Latest measured outcome

Both final frozen slots completed with complete raw/resource support and clean
shutdown. Strict seed/config/execution binding passed. Same existing scene 00861,
seeds 0/1, 30 seconds each, one execution per slot; Qt enabled offscreen.

| Seed | Mean active control Hz | Interval p95 / p99 ms | Deadline >100 ms |
| --- | ---: | ---: | ---: |
| 0 | 11.181 | 124.653 / 135.205 | 80/327 (24.46%) |
| 1 | 10.503 | 131.239 / 146.490 | 114/306 (37.25%) |

Mean throughput meets 10 Hz in these two slots. Stable 10 Hz does not: the p95
and p99 remain above 100 ms. The JIT checkpoint did not consistently reduce
native jitter over the preceding frozen cache-only checkpoint; retain both
results without selecting a best run or attributing an unproven native speedup.
Measured tails remain in map waits, navigation, guard, capture and UI publication;
stage quantiles overlap and cannot be summed as a critical-path proof.

1,379 CPU tests / fault4 / nativeDuDe3 / packaging / 202 selected sibling source
hashes pass, all exit0. Source98-file checkpoint stable during gate and final
native batch. Independent Sol High review remains pending account usage limit;
no self-certified review. P10 final campaign and useful/membership acceptance
remain incomplete. Detector/graph updates are asynchronous, not certified 10 Hz.

Run `bash tools/run_realtime_demo.sh 60` from the project root for the UI demo.
`--preflight` returned ready true / exit0; desktop display timing still unmeasured.
Full commands, all outcomes, hashes and limits:
[retained report](../runs/realtime-fix-20261028/report.md).


## Later user-selected high-resolution model profile — 2026-10-29

The active demo wrapper now selects YOLOE-26m/MobileCLIP2 and actual640×480primary
RGB-D (imgsz640); navigation depth stays180×240 H×W. Its isolated runtime uses
Ultralytics8.4.24. This is a new profile and the earlier10Hz observations above
do not apply. New20s nativevalidation:7.388Hz mean control, intervalp95165.476ms,
p99173.716ms,142/142intervals>100ms; **target NOT met**. Profiler retains aggregate
invocation interval statistics rather than the raw start vector, so exact
quantiles cannot be independently rebuilt from actuation proofs.

30s attempt hit unchanged rawrecordquota and is incomplete;20s bounded demo
completed/rawresourcescomplete/cleanshutdown. Default demo20s, no quota/TTL/proof
relaxation, no continuous60s or semantic accuracy claim. Full denominator/evidence:
[high-resolution report](../runs/yoloe26-640x480-20261029/report.md).
