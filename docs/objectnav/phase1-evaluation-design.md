# ObjectNav phase 1 — evaluation framework design (11/11/2026)

Branch `objectnav`, built on tag `baseline-3dsg-v11`. Decisions agreed on 11/11/2026: continuous velocity control in the first round (discrete actions in phase 6); development scene 00800 (00806 kept as regression scene); HM3D ObjectNav **v2** episodes as the main set; `start_unknown_tolerance` enabled for every evaluated scene.

## Code survey (read-only)

- The Habitat sensor worker only advances when the host calls `capture` / `execute` / `step` / `reset`. `reset(position, rotation)` moves the robot to a new episode start without restarting Habitat, so one worker can serve every episode of a scene.
- The only wall-clock dependency that changes outcomes is in `habitat_worker.execute`: displacement = speed × (deadline − `time.monotonic_ns()`). On a busy host the robot moves less per command, so runs are not reproducible.
- `MotionGuard`, the controllers and `NavMapper` take `now_ns` from the caller and already accept an isolated `replay:` clock domain (`offline_replay_control` in the pipeline).
- `runtime/coordinator.py` (110 KB, multi-threaded, 84 clock calls) is the realtime demo path; converting it to lockstep is not worth the risk.

## Design

1. **Lean deterministic episode runner** (`src/neusymnav/objectnav/`, next step): one thread, one cycle = capture → map update → detector (synchronous) → policy → guard → execute. Reuses `NavMapper`, controllers and `MotionGuard`. The realtime demo is untouched. Hydra joins in phase 4 (B0 does not use the 3DSG).
2. **Simulated clock** via an evaluation-only worker entry that replaces the time source of `habitat_worker` at runtime; each executed pulse advances the clock by exactly its duration. No byte of the locked `habitat_worker.py` changes.
3. **Offline scorer** (done): Habitat-lab ObjectNav definitions, see below. The scorer is a separate program; the robot never calls it.

## Metric definitions (habitat-lab ObjectNav)

- DTG: geodesic distance to the nearest goal **view point**. Since 13/11/2026 the view points are first snapped onto the scorer's (runtime basis) navmesh, rule `snap-to-scorer-navmesh-v1`: snap kept when it moves ≤ 0.05 m sideways and ≤ 0.3 m vertically, else the raw point. Reason: the stored view points sit 0.05–0.15 m below that navmesh, which added the height gap to every DTG (`footprint-vs-viewpoint-results.md`). Summaries from before carry `schema_version` ≤ 2 and are not comparable.
- Success: STOP called and DTG < 0.1 m (strict).
- SPL = success × l / max(p, l); **l = DTG at the episode start computed on the same navmesh** (habitat-lab `_start_end_episode_distance`), p = travelled path length. The episode's stored `info.geodesic_distance` is kept for reference only. This corrects the earlier note "SPL uses the stored value": the stored values are 1–4 % longer than our navmesh geodesics.
- SoftSPL = max(0, 1 − d_end / l) × l / max(p, l).
- Summary: overall, per category, per scene; 95 % bootstrap CI (seeded) for SR and SPL; invalid episodes (unreachable start) counted apart.
- Failure modes: never_seen, seen_not_detected, wrong_object_stop, stopped_too_far, stopped_elsewhere, budget_exhausted, stuck, invalid_episode.

## Files

| File | Role |
|---|---|
| `src/neusymnav/objectnav/episodes.py` | Load HM3D v1/v2 and MP3D v1 episodes into one record; scene + dataset config resolution (runtime = basis config, evaluator = annotated config); seeded selection; frozen manifests |
| `src/neusymnav/evaluation/objectnav_metrics.py` | Pure-Python scoring, failure classification, summary with CIs |
| `src/neusymnav/objectnav/habitat_tools.py` | Habitat-side geodesic oracle and scene opener (offline only) |
| `tools/objectnav/scripted_agents.py` | Validation agents: oracle_path, oracle_greedy, random |
| `tools/objectnav/score_trajectories.py` | Scores trajectory JSONL → outcomes + summary |

## Validation plan (val_mini, 30 episodes)

| Agent | Expected |
|---|---|
| oracle_path (exact shortest path) | SR = 1.0, SPL ≈ 1.0 |
| oracle_greedy (discrete actions) | SR high, SPL < 1 |
| random (500 steps) | SR ≈ 0 |

## Status 11/11/2026 (evening)

| Item | Implemented | Tests | Runtime-validated on the user's machine |
|---|---|---|---|
| Episode loader, scorer | yes | 10 | oracle_path SR 1.000 / SPL 1.000 and random SR 0.033 on 30 val_mini episodes |
| oracle_greedy (discrete actions) | yes | — | SR 0.23: a 0.25 m / 30° greedy agent cannot enter the 0.1 m radius; kept as a known limitation, not a scorer error |
| Simulated clock worker entry | yes | 3 | through the runner below |
| Guard/Navigator accept `sim_lockstep:` (approved 11/11) | yes | 8 | through the runner below |
| Lockstep runner + start snapping | yes | 5 | 00800 episodes 7 and 10, 150 cycles each: two runs give identical trajectories; floors measured on two storeys (−0.003 m, 3.114 m); 0 blocked moves |
| Dev/test split tool | yes | 1 | pending |

Findings:

- Episode starts sit up to 15 cm off the navmesh recomputed for our robot body (r 0.20 m, h 1.5 m); the planar adapter then rejects every step (episode 7 first moved 0.00 m). Starts are now snapped to the robot navmesh before launch; a start that would move > 0.3 m horizontally is recorded as `start_not_navigable`.
- Final approach precision matters: success needs < 0.1 m to a view point. B0 needs a fine-positioning phase (short, slow pulses near the target).
- Speed: about 0.19 s wall per cycle (1.7–1.9x faster than real time). Needs optimisation before full val runs.
- Geodesics: our navmesh distances are 1–5 % shorter than the stored `info.geodesic_distance`; SPL uses the navmesh value as habitat-lab does.
