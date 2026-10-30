# Robot body dimensions — 2026-10-30

User-requested main demo geometry: radius0.125m, diameter0.25m, height1.0m.
`configs/p10/demo-yoloe11s-conceptgraphs-visual-gpu-00861.json` now uses
`cylinder-r125-h1000-v1`. Margin remains0.05m per side; the ideal geometric
body-plus-margin diameter is0.35m. Map5cm, near-ground tolerance5cm, speed/yaw,
10cm bootstrap lookahead, freshness/safety, sensor mounts, CGvisual and selected
YOLOE11s640/.30 detector remain as configured. Height1m is the user's explicit
value, not a claim that this is typical vacuum-cleaner body height.

## One body geometry authority

Navigation.robot supplies planner/frontier/guard/height-clearance dimensions and
now also native agentgeometry through `_sensor_launch_configuration`. Worker
validates the closed positivefinite geometry before importing Habitat, sets
AgentConfiguration.radius/height and recomputes simulator-only collision navmesh.
Loaded NavMeshSettings are preserved except agentradius/height; defaults used
only when no previous settings exist. No source scene/navmesh file is written.
Navmesh is not fed to mapper/planner or observations. Runtime still needs measured
RGB-D floor/clearance evidence; unknown remains unknown.

A separate startup ACK reports actual native agent/navmesh radius and height,
geometryID and recomputation success. Host rejects missing/mismatched/unsolicited
ACK and closes the child. Legacy standalone sensorconfigs without explicit body
geometry retain the previous path. Other maintained runtimeprofiles retain their
own declared body sizes; they now bind those sizes to the simulator too. Eight
current profiles receive new sensor-worker checksum pins. Historical configs with
older source snapshots are not silently rewritten or declared runnable.

## Verification

Evidence root `.runtime/robot-geometry-20261030/`.

- Geometry regressions RED10failed/1passed exit1 → GREEN100focused exit0/2.54s.
- Preserve-loaded-navmesh-settings regression RED1failed/12passed exit1 → final
  GREEN208focused exit0/3.30s, including sensor/nativeprofile/actuation/planar tests.
- Final native smoke: `PYTHONPATH=src .runtime/host/bin/python .runtime/robot-geometry-20261030/native_smoke.py`, exit0. Real Habitat0.3.3 reports radius.125,height1 for both agent and navmesh, primary480×640RGB-D/navigation180×240depth, seed/config/worker checks and clean reaped shutdown. `native-smoke.json/log`, `native-request.json` pin this final source; initial smoke retained separately.
- IndependentSolHigh ACCEPT: fresh13geometry tests exit0; independent subprocess
  ACK/mismatch/childreaping and sweptguard probes exit0.73source/configsnapshot
  hashes/eightprofilepins/finalnative provenance checked. Review artifacts in
  `review/{report.md,final-evidence-check.json,final-hashes.json}`.
- Main selected-profile preflight readytrue exit0; final fullCPU evidence below.

Planner and MotionGuard CPU checks permit an observed0.45m strip for the new
body, reject a too-narrow strip, unknown, unsupportedfloor and clearance<1m.
These are geometry/evidence checks, not a native traversal demonstration.
Because closed raster cells touching the footprint count, an exactly0.35m
passage can remain blocked on the5cm grid. No passage-width guarantee, collision
rate/coverage improvement, fullpipeline runtime/P10 acceptance or fix for prior
IPC/RSS issues is established by this change. Objects lower than1m can still
prevent passage below them. Restart with a fresh output/episode for the new body.

Run from repository root:

```bash
bash tools/run_gpu_demo.sh --preflight
bash tools/run_gpu_demo.sh 60
```

Source siblings unchanged; no installs/downloads/training/commit/push.

Final fresh wholeCPU:2097passed/2skipped/3native-deselected, exit0/114.83s;
368source/config/test/toolpins unchanged. `full-cpu.log`, `verification.json`,
before/after-full-suite.json. gitdiffcheck exit0.
