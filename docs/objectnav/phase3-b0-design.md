# ObjectNav phase 3 — B0 baseline design (11/11/2026)

B0 is the non-privileged ObjectNav baseline that every later variant (B1a object–object, B1b with Hydra + SLM rooms) is compared against on the same episodes and seeds. It uses no 3DSG, no navmesh tour and no room labels. Decided by the user 11/11: B0 runs with the current detector (YOLOE-26m, taxonomy-v1); vocabulary fixes wait for phase 5.

## Inputs (non-privileged)

- The episode's object CATEGORY (runner `StepContext.episode`, only `object_category` is read).
- Robot RGB-D frames (640×480, hfov 90°, 1.2 m) and the simulator pose (AGENTS.md: runtime uses RGB-D + simulator pose).
- The downward depth camera through the unchanged `NavMapper` / `Navigator` / `MotionGuard` path of phase 1.

## Pipeline per episode

| State | What happens | Leaves when |
|---|---|---|
| SPIN | in-place turn at 29.5°/s (guard limit 30°/s), frames every pulse | ≈ 360° turned, or 40 cycles |
| EXPLORE | project frontier Navigator (gain-aware, 8 m snapshot) | a candidate of the target category is confirmed; frontiers exhausted for 30 cycles (then best unconfirmed candidate if `fallback_best_unconfirmed`, else STOP) |
| APPROACH | `Navigator.step_toward`: A* on the observed map to traversable cells within `stop_distance_m − aim_margin_m` of the candidate's observed points (fallback: nearest cells within +1.5 m, or toward the centroid when outside the snapshot) | centre within `stop_distance_m` of the object points; 60 s timeout or 30 cycles without a path → candidate rejected |
| FACE | rotate toward the candidate centroid | heading within 10° |
| VERIFY | hold until one frame captured after arrival is released by the detector | still confirmed → STOP; not confirmed → reject, EXPLORE; object points moved away → APPROACH |

## Detection

- Runtime worker `perception/detector_worker.py` through `DetectorClient`, recipe and interpreter pinned by the v11 profile (`configs/demo-00806.hydra-tour-slm.experimental.local.json`, sha256 checked at start). One worker per episode (the worker pins its episode id).
- Latency in simulated time (`b0/detection.py: LatencyGate`): a frame captured at t is released at t + 400 ms (measured 360 ms/frame on the iGPU in phase 2); one frame in flight; the robot keeps moving meanwhile. The control loop never waits for the detector (AGENTS.md invariant).
- Frames: every opportunity in SPIN / APPROACH / FACE / VERIFY; in EXPLORE when moved ≥ 0.3 m, turned ≥ 20° or 3 s since the last frame.
- Projection: runtime `Projector` (median-depth component, 3 cm voxels, depth 0.15–5 m).

## Candidate memory and confirmation (`b0/memory.py`)

- Only detections whose label maps to a goal category (`goal-categories-v1`) and whose score ≥ the lowest rule threshold (0.25) enter. Points kept 0.03 m above the measured floor up to robot height + 0.5 m, as 5 cm voxels.
- Association: dilated (10 cm) voxel contact ≥ 20 % of the smaller set, or — same goal category only — overlapping floor-plan boxes grown by 10 cm (the far side of a bed joins its near side; a TV next to a bed stays apart). Overlapping candidates are merged.
- Confirmation = `b0-detection-v1` as measured in phase 2 (per category threshold, min distinct frames, vote among goal categories at the same threshold).

## Stop distance

Success requires < 0.1 m to a view point. `tools/objectnav/b0/stop_calibration.py` (DEV, offline) renders every goal object from its view points, takes the visible surface points (same quantity B0 measures), and reports P(success) by distance and the success of "stop at the first point within D" coming from the start. `stop_distance_m` in `configs/objectnav/b0-policy-v1.json` is set from that table. It also reports the ceiling of the planar body: the motion adapter keeps the launch height, so goals on other floors are unreachable for B0.

## Budget

`max_sim_s` = 500 s of simulated time (B0 config; the phase-1 runner default stays 300 s). At 0.15 m/s this is ≈ 75 m of straight motion, in the range of the habitat-lab 500-action budget (≤ 125 m of 0.25 m steps, plus turns). Reported with every result.

## Records

- `trajectories.jsonl` diagnostics: policy events, state cycles, stop record (candidate, distance to its points), candidate summary, detector wall time, primary frames, wall time per runner stage (mapper, policy, guard, execute, captures, perception).
- `evidence/<uid>.jsonl.gz`: per detection frame the camera pose, intrinsics and every goal-category detection (label, score, box, RLE mask, candidate id). Used offline (step 3.4) to label failures: target never seen / seen but not detected / stopped at a wrong object.

## Files

| File | Role |
|---|---|
| `src/neusymnav/objectnav/b0/memory.py` | candidate memory + confirmation |
| `src/neusymnav/objectnav/b0/detection.py` | recipe from the profile, worker factory, latency gate |
| `src/neusymnav/objectnav/b0/approach.py` | approach goal cells, facing |
| `src/neusymnav/objectnav/b0/policy.py` | `B0Config`, `B0Policy` state machine |
| `src/neusymnav/navigation/controller.py` | `Navigator.step_toward`, `release_goal` (additive; `step` unchanged) |
| `src/neusymnav/objectnav/runner.py` | primary-frame hook, policy lifecycle, stage timers (phase-1 policies unaffected) |
| `tools/objectnav/run_episodes.py` | `--policy b0 --b0-config` |
| `tools/objectnav/b0/stop_calibration.py` | stop-distance calibration (offline) |
| `configs/objectnav/b0-policy-v1.json` | B0 parameters |
| `tests/test_objectnav_b0.py` | unit + runner-hook tests |

## Steps

1. Stop calibration on DEV → `stop_distance_m`.
2. Smoke: 3 DEV episodes of 00800; check states, stop distances, wall time per stage.
3. DEV run (60 episodes) → SR / SPL / SoftSPL with CIs, per category.
4. Offline failure evidence tool → failure table (feeds phase 5).
5. TEST split only once B0 is frozen (no tuning on test).
