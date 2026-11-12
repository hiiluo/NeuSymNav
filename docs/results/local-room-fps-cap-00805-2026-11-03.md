# Local Rebuild room FPS-cap baseline — map 00805 — 2026-11-03

## Scope

Local only. The Rebuild source tree and M2/M3/M4 binaries were read-only and
matched the runner's pinned hashes. No Kaggle notebook or Dataset version was
changed, and the acceptance checker was not modified. The experiment compared
full replay and deterministic FPS selection from the same complete raw RGB-D
recording.

## Implementation

The room lane now supports an explicit `fps_cap_hz` and
`queue_policy=latest_wins`. FIFO remains the default. At most one selected room
frame waits behind the in-flight update; an older pending frame is journaled as
`room_queue_replaced_by_newer`. FPS-limited frames are journaled separately.
Bounded telemetry reports queue wait, service time and source age at start and
completion. Per-update M1/M2/M3/M4/M5 timings and point counts are also retained
in the room session journal.

The pinned Rebuild adapter had another integration issue: it used an empty
`records` list to select `full_refresh` versus `partial_update`, while
NeuSymNav popped each record after use. `_PersistentMappingRecords` now retains
only the one-bit “has integrated” state after the detailed record is popped.
The sequence is tested and present in both replay journals.

## Baseline and live runs

Profile: 00805, `fps_cap_hz=0.10`, `queue_policy=latest_wins`, 30-second bounded
local run. It completed with a complete raw recording and 3 room updates, but
the queue did not replace a pending frame because this cap was below the
measured processing rate. The default Qt platform could not connect to a
display; the strict checker rejected only `UI process failed`. An offscreen
retry started the UI but was marked incomplete because the sampled RSS
acquisition had a 1.264-second maximum sample gap. Neither run is an accepted
result.

Profile: 00805, `fps_cap_hz=0.25`, `queue_policy=latest_wins`, 30-second bounded
local run with `QT_QPA_PLATFORM=offscreen`. It completed with 132/132 sensor
frames recorded, clean worker shutdown, complete resource samples, and no UI
failure. Room lane counters:

| Metric | Result |
| --- | ---: |
| Primary RGB-D candidates | 65 |
| FPS-limited before queue | 57 |
| Room offers | 8 |
| Processed | 5 |
| Replaced pending frames | 3 |
| Queue rejections | 0 |
| Latest/accepted M3 | 5 / 5 |
| M5 | revision 3, 1 valid region, not stale |
| Strict acceptance | accepted, exit 0 |
| Room service p50 / max | 6.81 s / 9.33 s |
| Source age at completion p50 / max | 8.41 s / 13.67 s |

The 57 FPS-limited frames are deliberate sampling, not sensor-recording loss.
The 3 queue drops are old pending frames replaced by newer selected frames;
none of the 8 room offers were rejected.

## Same-recording full versus 0.25 Hz replay

Input recording certificate is complete. It contains 65 primary RGB-D frames.
The capped sequence selected 8 frames. Results from
`live-fps025-replay-comparison/comparison.json`:

| M3 metric | Result |
| --- | ---: |
| Known-cell recall | 0.9992 |
| Occupied-cell recall | 0.9660 |
| Occupied-cell precision | 0.9281 |
| Occupied IoU | 0.8987 |
| Free-cell recall | 0.9965 |
| M5 regions full / capped | 1 / 1, both fresh |
| Greedy polygon IoU | 0.9165 |
| Polygon area full / capped | 8.085 / 7.901 m² |

This is a positive but narrow result: the trajectory's path length was only
0.0478 m and displacement 0.0475 m. The reported 100% pose-neighborhood proxy
does not measure newly observed surfaces; this run barely moved and saw one
region. It does not establish room-boundary retention across hallways,
doorways, or multi-room trajectories.

## Timing evidence

Timing is measured over 65 full-replay updates (p50/p95):

| Stage | p50 | p95 |
| --- | ---: | ---: |
| M1 backprojection | 37 ms | 56 ms |
| M2 OctoMap integration | 2.825 s | 3.108 s |
| M3 projection | 78 ms | 131 ms |
| M4 backend | 7.0 ms | 15.8 ms |
| M5 guard/tracker | 0.124 ms | 0.200 ms |
| M1–M3 total | 5.016 s | 5.365 s |
| M1–M3 residual outside named M1/M2/M3 timers | 2.101 s | 2.309 s |

The residual is computed as M1–M3 total minus M1, M2 and M3 timers. It includes
pre-M2 Python work such as `ScanPoint` tuple construction and post-M3 bookkeeping
and count scans; it is not yet an isolated measurement of any one of those
costs. The Rebuild source's M2 timer starts before `OctoMapWorker.integrate`,
whose Python wrapper validates each point, formats each point as ASCII and
performs IPC before native integration returns. Therefore the measured M2
number is not pure OctoMap time. Do not attribute the full 2.101-second
residual or M2 timer to one hotspot until a profiler separates them.

The adapter journal now verifies `full_refresh` for the first M3 update and
`partial_update` on subsequent updates. The local replay used the same pinned
source, binary and mapping configuration for both sample rates.

## Verification and artifacts

- Focused tests: 50 passed, exit 0.
- Local preflight: `ready=true`, `issues=[]`, exit 0.
- 0.25 Hz acceptance: accepted=true, exit 0; threshold/checker unchanged.
- Shell syntax, Python compilation and `git diff --check`: exit 0.
- Run artifacts and generated profiles: `.runtime/local-room-fps-experiment-00805-20261103/`.
- Key live result: `live-30s-fps025/summary.json`.
- Same-recording comparison: `live-fps025-replay-comparison/comparison.json`.

## Status and next gate

**Implemented:** opt-in FPS cap/latest-pending policy, journal reasons, bounded
queue/age/service telemetry, per-update stage/work diagnostics, and M3
projection-mode persistence.

**Correctness-verified:** configuration/default behavior, replacement and
metrics tests, M3 full/partial sequence test, and local preflight.

**Runtime-validated:** one accepted local 30-second 0.25 Hz run and same-source
full/capped replay comparison on 00805.

**Not established:** run-long stability, meaningful scene coverage, performance
on other map profiles, or quality on trajectories with substantial motion.
No Kaggle campaign should be inferred from this single near-static trajectory.

The follow-up M2 profiling and full-sequence stride 1/2/4 comparison have now
run locally. Results are in
`docs/results/local-room-m2-stride-00805-2026-11-03.md`. Stride 2 is a candidate
for a further local trial; stride 1 remains the production default because the
recorded trajectory only moved 0.0478 m. The next quality gate is the same
comparison on a trajectory that crosses new space and room boundaries. Keep
acceptance unchanged and leave Rebuild's pinned source untouched unless the
user explicitly reopens that boundary.
