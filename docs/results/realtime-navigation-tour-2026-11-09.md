# Real-time navigation fixes + privileged navmesh tour — 2026-11-09

Status: **implemented, CPU tests pass in a container; not yet run live.**
Guard 300 ms / horizon 100 ms, footprint, unknown≠free, local re-planning and
the 0.2 m/s limit are unchanged.

## Evidence that motivated the change (00807, 120 s, two runs)

Body translation 0.0 m in every 10 s window. Control trace:
`world_intent_unavailable` 259/496 and 330/440 steps; executed steps were mostly
`align_heading`. World planner reasons (09/11 run): **`nav_stale` 156/235**,
`committed_goal_blocked:goal_not_traversable` 45, path produced only 33.
World map age at decision ≈ 356 ms (navmap_update p50 184 ms / p95 362 ms);
the world layer used the 300 ms *motion* TTL for *goal selection*, so it rarely
published a route. `local_depth_map` p50 152–173 ms / p95 318–388 ms.

## Changes

1. `navigation.controller.world_goal_max_age_ms` (300–2000, requires
   `local_depth_control`): goal selection and its failure watch accept older
   world maps. If the map is older than 300 ms the Navigator returns the route
   with **zero velocity** and reason `world_goal_selected` (selection-only).
2. `navigation.controller.world_intent_ttl_ms` (2000–5000): reference-route
   validity. The local follower still re-plans/guards on ≤300 ms depth.
3. `navigation.mapper.local_sampling_stride` (1–4, opt-in): coarser ray lattice
   for the per-frame safety map only; unsampled cells stay UNKNOWN. Trade-off:
   thin obstacles narrower than ~2 strides of floor sampling may be missed.
4. `runtime.process_priority` {hydra, detector, ui} nice values. Hydra and the
   detector start under `nice`; the UI tree (and the room-label server, nice 15)
   is reniced after launch. Control and the Habitat sensor stay at nice 0.
5. Privileged navmesh tour (`navigation.tour`, `navigation/tour.py`,
   `tools/make_navmesh_tour.py`): greedy geodesic coverage of the start floor,
   densified polyline in canonical XY. At run time it replaces frontier goal
   selection with the farthest plannable polyline point within a 1.6 m
   look-ahead on the observed map; skips a segment after 10 s without progress;
   after the tour it falls back to frontier exploration. Status under
   `navigation.world_planner.tour`. **Not an ObjectNav result.**

Profiles: `demo-00807.hydra-realtime.experimental.local.json` (1+2+4) and
`...-realtime-stride2...` (+3). SLM server nice 10→15 (pin updated).

## Verification

Container: new tests 20 passed; navigation suites unchanged failure set
(30 pre-existing environment failures in `test_launcher.py`, identical before
and after); room tests 139 passed. Tour tool smoke-tested with a fake
`habitat_sim`. Not verified: live Habitat, real navmesh, real CPU timing.

## Live result 1 — `rt-00807-120s` (stopped at ~63 s, outcome incomplete)

Planning layer fixed: world `nav_stale` 156/235 → 0/125 (40 `world_goal_selected`),
control `world_intent_unavailable` 75 % → 27 %, 179 commands executed (87
`move_forward`). **Body still did not move: 0 of 87 forward actions changed the
Habitat body position** (also 0/36 and 0/75 in the two earlier 00807 runs). In
the planar adapter a step is reduced to a no-op when the simulator collision
filter's result is not on the forward segment or its height differs > 5 cm
from the start height. The 00807 start pose is therefore suspected, not the
planner. `tools/diagnose_start_pose.py` checks 16 headings with the same
`step_filter` call and prints the snapped navmesh position.

The run named `tour-00806-300s` used the 00807 tour profile (the MAP argument
of `run_hydra_map_demo.sh` is only a label; the config selects the scene) and
stopped after ~70 s with one accepted keyframe.

## Live result 2 — `tour-00807-300s` (start height fixed; stopped by hand at ~143 s)

The body now moves: 44 actions in the first 6.5 s, 0.47 m along the tour.
Then no further action for 135 s (pose_version stays 44); fast lane reports
`world_intent_unavailable`. Replaying `TourFollower.select` on the published
NavSnapshot (frame 876) at the stuck pose returns `tour_target_unobserved`
every time:

* The tour was built on a navmesh with the bare robot radius (0.20 m), so the
  route hugs the wall corner at x ≈ 6.1 m at 0.20–0.25 m. The runtime planner
  needs radius + margin (0.25 m) of **known free** cells; route points 3–11
  are all non-traversable (5–15 wall cells, then up to 47 unknown cells in the
  footprint; the space past the corner is occluded by the wall).
* With no target the Navigator returned `stop`, the robot never moved again,
  so the occluded space was never observed. The 10 s skip only moves the
  index 1 m along the route, so it could not break the deadlock either.

Fixes (`navigation/tour.py`, `controller.py`, `tools/make_navmesh_tour.py`):

1. Relaxed targets (`navigation.tour.relax_m`, default 0.5 m): each route
   point is replaced by its nearest traversable observed cells; the farthest
   plannable one wins. A point whose nearest traversable cell is where the
   robot stands counts as reached; reaching a relaxed goal advances to its
   index.
2. Approach (`approach_m`, default 3 m): if nothing in the look-ahead is
   plannable, go to the reachable cell nearest the look-ahead end when it is
   ≥ 0.3 m closer to it than the robot.
3. Frontier fallback: if the tour still has no target, the Navigator runs
   frontier exploration for that step instead of stopping
   (`world_planner.tour.frontier_fallback_steps`).
4. The tour tool now builds the route on a navmesh of radius + margin +
   0.05 m (0.30 m), `--navmesh-radius-m` to override. Regenerate tours.

Regression test `test_live_00807_corner_route_is_relaxed_to_traversable_cells`
uses the real map of this run (`tests/fixtures/tour_00807_corner_map.json`):
old behaviour `tour_target_unobserved`, new behaviour a relaxed `tour-6` goal
0.7 m ahead past the corner.

## Live result 3 — `tour-00806-300s-v3` (00806 = benchmark scene from now on)

5.33 m in 300 s, all of it before 120 s; tour coverage 43/187 points (23 %).
Two defects (from `measurements.json` proof records):

1. **Progress jumped to a later pass of the same corridor.** At 119.5 s the
   goal changed `tour-37` → `tour-145`: the progress search window (120 points
   from the current index) contained the return leg through the same
   corridor, so ~28 m of route (west/south rooms) were dropped. Then the
   10 s stuck timer kept running while the robot turned, and the rest of the
   tour was skipped metre by metre ("complete" was reached by skipping).
2. **Pulses far shorter than the control period.** Every command moved at most
   100 ms × v (and the yaw pre-flight capped one pulse at 3°), but the
   local-control loop period was 261 ms mean (`local_depth_map` p50 125 /
   p95 395 ms): effective speed ≈ 0.05 m/s for 0.15 m/s commanded, a 180° turn
   took ≈ 20 s.

Fixes:

* `TourFollower`: progress is searched only within look-ahead + reach of
  route LENGTH ahead (`progress_window_m`); moving ≥ 0.2 m or turning ≥ 0.35 rad
  while following a target resets the stuck timer; a hard
  `stall_timeout_s` (60 s) without route progress still skips. Status adds
  `coverage`, `visited_points`, `complete_reason` (`reached`/`skipped`) and
  `counts.skipped_points`.
* Opt-in real-time pulses `navigation.controller.pulse_ms` (100–300) and
  `rotation_pulse_ms` (100–500, ≥ pulse_ms), require `local_depth_control`.
  Translation pulse = min(pulse, wall time since the previous motion command,
  depth TTL remaining) — never faster than commanded, never past capture +
  300 ms. Pure in-place rotation (cylinder footprint sweeps no new cells)
  must be issued on fresh depth with the current footprint observed clear,
  and may then last min(rotation_pulse, wall time since previous command).
  The worker honours the guard deadline up to 300 ms translation / 500 ms
  rotation (yaw pre-flight cap 3° → 15°); the host proof validator
  (`actuation_measurements.py`) uses the same bounds (≤ 6 cm, ≤ 15°).
  Without these keys nothing changes: 100 ms pulses, no wall-time pacing,
  rotation bounded by the depth TTL as before.
  `habitat_worker.py` sha changed: pins updated in 15 Kiet_branch2 profiles.
* `demo-00806.hydra-tour-slm.experimental.local.json`: pulse 300 / rotation 500.

Replay on the real 00806 tour: from index 31 at the stuck pose the old window
picked point 141 (0.26 m away on the return leg); the new window stays on 31.

## Live results 4–5 — `tour-00806-300s-v4` / `-v5`: GIL contention (confirmed)

Tour no longer jumps (coverage 26 %); rotation pulses 5.5°. But the control
rate decays every minute: commands/min 323 → 181 → 74 → 19 (v5),
`local_depth_map` 103 → 337 ms, `navmap_update` 124 → 357 ms,
`navmap_overview_refresh` 12 → 76 ms (grows with explored area); the Habitat
worker handler does not slow down. `top -H` during v5 (12 cores, 60–80 %
idle): the main process's world thread (TID 11472) rises to 62–69 % CPU
while the control (main) thread falls from ~50 % to 21–26 % although the
trace shows it "busy" ~45 s/min — it is waiting for the GIL.

Plan A (opt-in, profile `demo-00806.hydra-tour-slm` only):

* `runtime.gil_switch_interval_ms` (0.5–5; profile 1): `sys.setswitchinterval`
  while the pipeline runs (restored on close).
* `runtime.world_navigation_hz` 2 → 1 in the profile.
* `navigation.mapper.overview_refresh_s` (0.5–10; profile 2): the display /
  room-history overview is refreshed at most this often on the world thread.
  Counts under `navigation.world_planner.overview_refresh`.
* `build_overview` full-resolution fast path (tile slice copy instead of
  `np.add.at`; identical output, ≈3× faster on a synthetic 80-tile map).
* Robot trail in UI publications is already bounded (1024 samples); unchanged.

Acceptance for the next run: commands/min must not decay over the 5 minutes
and `local_depth_map` must stay ≈ 100 ms. Otherwise plan B (world mapping in a
separate process).

## Live result 6 — `tour-00806-300s-v6` (plan A on): partial; the real hog is the graph lane

7.66 m, tour coverage 56/187 (30 %), west room reached (x = −10.0). Commands
per minute 361 / 184 / 83 / 74 / 92 (v5: 323 / 181 / 74 / 19): the decay
stops after minute 2 but `local_depth_map` still rises 88 → ~210 ms.
Overview refresh ran 122× and was skipped 177×; world updates now 1 Hz.

Correction of the v5 attribution: the busiest main-process thread (v5 TID
11472, v6 TID 16410, 28 % → 63 % CPU) is the **graph lane**, not the world
thread. It is created first and spawns the Hydra child (next PID, nice 2);
recorder/navigation threads start only after it is ready. Its loop wakes up to
~100 Hz and, on every wake, calls `HydraGraphRuntime.snapshot()` and
`projection()`; each deep-copies the whole graph summary (≈ 0.6 MB as
projected; ~10 ms per deep copy) and re-projects every node, although the
graph changes only ~35 times in 300 s. Cost grows with the graph.

Fix: `HydraSession.state_token()` (revision, failure, replay, metadata/close
identity) — the graph lane re-reads snapshot/projection only when the token
changes (`Pipeline.hydra_poll_counts`); `HydraGraphRuntime.projection()` reuses
its immutable projection for an unchanged token. `snapshot()` still returns a
detached deep copy (contract unchanged).

## Live result 7 — `tour-00806-300s-v7` (graph-lane token polling): real-time restored

| | v6 | v7 |
|---|---|---|
| Distance | 7.66 m | **18.3 m** (5.1 / 3.4 / 3.0 / 3.5 / 3.3 m per minute) |
| Commands/min | 361 / 184 / 83 / 74 / 92 | **423 / 348 / 307 / 308 / 285** |
| `local_depth_map` p50 (ms, per minute) | 88 → 209 | **58 / 74 / 87 / 84 / 77** (p95 122 → 305) |
| Tour coverage (robot within 0.5 m) | 30 % | **71 % (133/187)**; 1 skip; 1 frontier-fallback step |
| Graph-lane thread CPU | 28 → 63 % | below the top-10 threads (< 10 %) |

Hydra at the end: 540 places, 21 objects, 5 rooms (R(3): 231 places over
≈ 9 × 4.6 m — still suspected merged). SLM: 37 inferences, 86 cache hits;
final labels 4 × `unknown`, 1 × `bedroom`. Remaining real-time tail: the
`local_depth_map` p95 still grows; the room-label UI process (nice 8, its own
process) grows to ~67 % CPU — not GIL-coupled to control.

## Live result 8 — `tour-00806-600s-v8` (600 s) and first room check against user GT

Real-time holds for 10 min: 33.5 m, 488 → ~300 commands/min (≈ 220 in
minutes 7–9), `local_depth_map` p50 57–117 ms; tour index 154/187, coverage
76 % (143/187), 1 skip. Trace cap reached near the end (8 632 records dropped).

Hydra (rev 103): 759 places, 31 objects, 5 rooms. Hydra received only 103
frames in 600 s (primary RGB-D 0.5 Hz → 288 seen, `idle-semantic-v1` offered
121, 18 replaced): median gap 4.4 s, max 15 s.

User GT (2026-11-09, polygons digitised from the annotated plot; partial —
bathroom and the south/west areas are not annotated):

| GT region | places | Hydra room |
|---|---|---|
| bedroom 1 (blue) | 102 | R(2) 101, R(3) 1 |
| bedroom 2 (green) | 125 | R(0) 125 |
| hallway (red) | 13 | R(0) 10, R(2) 3 |
| outside GT | 519 | R(3) 248, R(1) 99, R(0) 81, R(2) 53, R(4) 25, none 13 |

Both bedrooms are recovered; the hallway is merged into bedroom 2 (R(0));
68 % of the places lie outside the annotated area, so the south corridor
(R(3)), the west room (R(1)), R(4) and the bathroom cannot be scored yet.

Bathroom (east end of the south corridor, x ≈ −4.8…−2.8, y ≈ −5.6…−3.4): the
robot reached its door (x = −4.83 at 264–275 s) and turned back; Hydra got 3
frames looking into it. Its few places were assigned to R(3); no room node.
Causes: (1) sparse Hydra input during a short visit, (2) little free space
with clearance in a small furnished room → few GVD places, (3) a room needs a
≥ `min_component_size` (10) component after the 0.5–1.2 m dilation
threshold, which a ~2 × 2 m room behind a narrow door rarely forms.

## Changes after v8 (bathroom): denser Hydra input, goal gates, in-place scans

1. **Why the robot turned back at the bathroom door.** The route enters the
   bathroom to coverage goal 10 (−3.74, −4.29; polyline 84) and comes back
   through the same door (polyline 85–95). At the door (x = −4.86, 267.9 s)
   the 2.1 m progress window contained the return leg 0.2 m away, so the index
   jumped 81 → 88 and the target became `tour-96`: the robot turned around
   without entering. Coverage goals are now **gates**: the progress window,
   the relaxed-progress pass and target candidates stop at the next unvisited
   goal; a gate is passed when reached (≤ `reach_m`, or relaxed) or skipped by
   the stuck/stall timeout. Replay on the real tour: window end 85, index stays
   at 81, target stays inside the bathroom.
2. **In-place scans at goals** (`navigation.tour.scan_degrees`, step
   `scan_step_degrees`, `scan_min_separation_m`, `scan_step_timeout_s`; 0 =
   off): at a reached goal the Navigator publishes `scan-<goal>-<k>` intents
   (zero velocity, reference path robot → heading); the local follower only
   rotates (≤ 30°/s, never translates) until within 8°, then reports
   `world_goal_reached`; the tour advances to the next heading. Scanning counts
   as progress; a step that cannot finish in time is skipped. Status:
   `goals`, `goals_passed`, `scanning`, `scanned_xy`, `counts.scans`.
3. **Denser 3DSG input** (opt-in): `keyframe_novelty`
   {`min_translation_m`, `min_yaw_deg`} (default policy 0.25 m / 20°).

Profile `demo-00806.hydra-tour-slm`: `primary_hz` 0.5 → 1.0, keyframe novelty
0.15 m / 15°, scans 360° in 90° steps, ≥ 2.5 m apart, 8 s per step.
Tests: `tests/test_tour_goal_gates_and_scan.py`.

## Live result 9 — `tour-00806-600s-v9` stopped by the user: frozen at (−5.94, 0.47)

The robot stood still for > 125 s (trail pose_version constant), local lane
`world_intent_unavailable`. The published world NavSnapshot at that pose has
100 FREE cells and **1 UNKNOWN cell** in the robot's current footprint
(radius + margin 0.25 m), so its start cell is not traversable: every tour,
approach and frontier plan fails (`start_not_traversable`) and the guard
bootstrap (all capsule cells FREE on the current frame) blocks every command,
including in-place rotation. Skips advance the tour index but cannot move the
robot. Probable cause: occluded floor next to an overhang/the alcove wall as
seen by the nadir depth camera.

Opt-in `navigation.controller.start_unknown_tolerance` (≤ 0.3): UNKNOWN cells
inside the current footprint disc are treated as FREE for the start only, if
no disc cell is OCCUPIED and at most that fraction is UNKNOWN; the swept
corridor beyond the disc must still be measured FREE. Regression:
`tests/test_start_footprint_tolerance.py` with the real v9 map. It relaxes the
project invariant "unknown ≠ free / missing depth blocks motion" for the
robot's own current footprint only; **enabled (0.2) only in
`demo-00806.hydra-tour-slm` by explicit owner decision (2026-11-09)**, disabled
in every other profile. Counters: `navigation.world_planner.start_unknown`.

## Room GT v1 (user, 2026-11-09) and evaluation tool

`docs/results/gt/00806-rooms-gt-v1.json` (5 polygons, digitised ±0.15 m;
figure `docs/results/figures/00806-gt-v1-over-v8.png`) and
`tools/evaluate_rooms_vs_polygon_gt.py <run> <gt>`:

| | v7 (300 s) | v8 (600 s) |
|---|---|---|
| places inside GT | 464 / 540 | 633 / 759 |
| GT rooms matched one-to-one | 4/5 | 4/5 |
| matched place accuracy | 0.586 | 0.676 |
| west_room | R(1) 93 % | R(1) 93 %, purity 1.0 |
| bedroom_1 | split R(3) 49 % / R(2) 34 % / R(4) | split R(3) 53 % / R(2) 47 % |
| hallway | R(2) 96 % (merged with bedroom 1) | R(0) 74 % (merged with bedroom 2) |
| bedroom_2 | R(0) 100 % | R(0) 100 % |
| bathroom | inside R(3) 100 % (no own room) | inside R(3) 100 % (no own room) |

## Live result 10 — `tour-00806-600s-v10` (600 s, goal gates + 360° scans + tolerance 0.2)

Figure: `docs/results/figures/00806-v10-rooms-vs-gt.png`.

- Motion (runtime-validated on this run only): 26.3 m observed lower bound,
  2584 accepted commands; per minute 334/300/272/222/220/235/275/256/237/233
  commands and 2.4–3.4 m — no decay over 10 min. No freeze: start tolerance
  used 9× by the guard, 3× by the world planner, 100× by the local map.
- Tour: coverage 0.711, progress 0.634 (index 118/187), goals passed 11/16.
  4 scans completed (11 steps, 5 step timeouts). Skipped tour points include
  (−4.44, −4.17) and (−5.24, −4.14): the robot reached x = −4.82 at t ≈ 415 s
  and turned back without reaching bathroom goal 10 (−3.74, −4.29). No scan
  inside the bathroom: goal 9 (−5.45, −4.25) is 2.0 m from the goal-8 scan
  (< `scan_min_separation_m` 2.5). bedroom_2 visited only at the start; the
  west room never entered (route order, run ended at index 118).
- Hydra input: 212 frames (v8: 103), r104, 697 places, 4 rooms.
- GT v1: 3/5 matched, matched place accuracy 0.862 (inflated by a 3-room
  merge). west_room → R(1) 96 %; bedroom_1 → R(2) 99.6 % (no longer split);
  bedroom_2 → R(0) 99 %; **hallway (24/25) and bathroom (50/50) merged into
  R(2)**; R(2) purity 0.78. Bathroom places exist only in a ~1 m strip along
  the robot path (y −3.7…−4.9).
- Objects: toilet O(44) (−5.10, −4.64) and mirror O(39) were detected in the
  bathroom but belong to R(2); SLM labels R(2) "bedroom".
- **R(3) is a phantom room**: 28 places at x −9.3…−7.7, y −4.9…−6.5, i.e.
  behind the south wall of bedroom_1, and its only object is mirror O(28)
  (−8.34, −4.84). Most likely depth through the mirror reflection integrated
  as free space (not yet verified on the depth frames).
- Room finder config in use (`config-root/stable/datasets/neusymnav.yaml`):
  dilation 0.5–1.2 m PLATEAU (ratio 0.25), `min_component_size` 3,
  `min_room_size` 10, `clustering_mode` NEIGHBORS.

## Evening runs — freeze at (−5.94, 0.46) and the tolerance disc mismatch

Runs `tour-00806-600s-v8.1`, `tour-00806-600s-v9.1`, `demo-00806-600s-live`,
`demo-00806-600s-live1` (same code and config hash `6272d44f…` as v10) all froze
at tour point 14 (−5.94, 0.46), in front of the north alcove (goal 1, index 17),
for 52–122 s until the user stopped them. v10 passed this point only by luck.

- World planner and local follower still produce paths: replayed on the real
  snapshots they return `tracking`, 0.15 m/s, heading error ≈ −5°.
- The guard refused every forward pulse: v9.1 local reasons
  `path_segment_blocked` 335, `bootstrap_blocked` 52, only 30 commands issued at
  the stuck point (28 rotations, 2 tiny forward steps).
- Offending cell: local cell (44, 44), UNKNOWN, ≈ 0.27 m north-east of the
  robot centre.
- Cause: the follower/world planner tolerated the footprint disc padded by 0.75
  cell (r ≈ 0.29 m), `MotionGuard.bind_nav` and `NavMapper.bootstrap` the
  unpadded disc (r = 0.25 m). The follower's first path segment (robot →
  its cell centre) swept that cell, which the guard still saw UNKNOWN.
- Fix: one shared helper `tolerate_robot_footprint` for all four consumers;
  regression fixture from the three snapshots
  (`tests/fixtures/start_footprint_00806_guard_mismatch.json`). Not yet
  validated live.

## Live result 11 — `tour-00806-600s-v11` (600 s, shared tolerance disc)

Figure: `docs/results/figures/00806-v11-rooms-vs-gt.png`.

- Runtime-validated (this run): passed (−5.94, 0.46) in ≈ 2 s at t ≈ 52 s; the
  guard used the shared start disc 125×. No freeze in 600 s.
- 28.3 m (lower bound), 2820 accepted commands; per minute 376/377/279/267/240/
  239/225/320/256/241 commands and 2.2–3.9 m. Tour coverage 0.770 (best so far),
  progress 0.656, goals passed 11/16, 4 scans.
- Bathroom dead end again not reached: at t ≈ 416 s, robot at (−4.83, −4.15),
  the world planner switched from `tour-81` to frontier fallback, then resumed at
  `tour-95`; goal 10 (−3.74, −4.29) and point (−4.44, −4.17) were skipped.
  Cause not yet diagnosed.
- Hydra: 5 rooms, 679 places. GT v1: 3/5 matched, matched place accuracy 0.868;
  west_room → R(1) 95 % (purity 1.0), bedroom_2 → R(0) 100 % (purity 1.0),
  bedroom_1 → R(2) 98 %, hallway and bathroom merged into R(2) (purity 0.80).
- The bathroom **was** a separate room for several mid-run revisions (rooms
  R(4)/R(5)/R(7) with toilet O(40), towel, mirror O(31)) and was merged again at
  the end: room flip-flop, not only missing data.
- The SLM answered `unknown` for those {toilet, towel, mirror} rooms; R(2) is
  labelled `bedroom`, R(0) `bedroom`.
- Phantom room behind the bedroom_1 south wall again (R(4), 19 places, x −9.5…
  −8.2, y −5.3…−6.3); its only object O(28) is detected as `fireplace` here
  (`mirror` in v10) — consistent with a reflective/framed surface.
