# Exploration and movement implementation plan

**Goal:** sustained, measured exploration on 00805, with accepted Rebuild M5
remaining the only room partition source.

**Architecture:** retain the current sensor owner, measured navigation map,
planner, controller and guarded simulator actuator. First remove measured
latency and progress defects, then enable gain/heading-aware frontier ordering.
Adding ROS 2/Nav2 now would replace multiple unvalidated seams; an exploration
backend alone would leave the demonstrated navigation-source starvation intact.
The user delegated implementation choices and authorized bounded runtime tests.

**Constraints:** no sibling edits, new models, or installs. Keep unknown distinct
from free, exact capture/pose provenance, 300 ms depth TTL, 100 ms action horizon,
0.2 m/s hard cap and actual collision-filtered actions. Do not change M5 source,
guards or acceptance checker. Preserve pre-existing dirty work.

## Tasks

- [x] Diagnose capture, NavMapper, navigator, guard and actuator separately on
  an existing recording and one bounded native baseline. Save timings and
  source ages, distinguishing source-pending from geometric vetoes.
- [x] Add regression tests for demonstrated movement defects before fixing.
  Optimize exact computations and ordering, not evidence lifetimes. Check
  snapshot/coverage parity, stale-source rejection and shutdown.
- [x] Add optional information-gain and heading-aware frontier ranking with
  path-cost/commitment preserved. Enable through Navigator after focused tests.
- [ ] Verify bounded native movement after integration. Measure full retained
  capture pose trajectory (path, net displacement, yaw, extent), executed
  commands, wait reasons and observed map growth. Rotation or command counts
  alone do not establish exploration. Compare against the baseline, then run
  a longer case only when evidence warrants it.
- [ ] Independent review, relevant regression suite and full CPU suite; record
  commands, exits, artifacts, runtime acceptance and remaining limitations in
  implementation-status. No commits/publish requested.

Ownership: main owns runtime/mapping/controller/config/docs/integration. Luna
owns `_policy_core.py` and its new focused policy tests. A read-only Luna audits
motion seams; no overlapping writers or concurrent native workloads.

2026-11-04 checkpoint: source-wait profiling, frontier/continuity/deadline fixes,
expired-source recovery and a recorded corner regression are implemented.
Pre-hybrid full suite2362 passed/10 skipped. Native evidence and all rejected
experiments are in `docs/results/exploration-movement-2026-11-04.md`.
Luna's opt-in hybrid controller passed33 integrated regressions and independent
Terra static safety review;90s translated1.826m versus discrete1.527m. A300s
run is required before selecting the final runner mode and closing validation.
No native P10 acceptance or sustained-coverage success has been claimed.
