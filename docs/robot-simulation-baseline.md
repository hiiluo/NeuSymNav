# Robot simulation baseline — user confirmed 2026-10-31

The user explicitly retains a1m body and the existing simulated camera rig.
CG+Visual remains active. No camera or body dimensions changed in this campaign.

| Parameter | Retained value | Binding |
| --- | --- | --- |
|Cylinder radius/diameter|0.125m/0.25m|cylinder-r125-h1000-v1|
|Body height|1m|same geometry ID, native agent and recomputed navmesh ACK|
|Planning/safety margin|0.05m|navigation profile and RobotGeometry; not native ACK field|
|Primary RGB-D height|1.2m|versioned launch config/calibration provenance|
|Primary resolution|640×480|native sensor resolution ACK|
|Downward navigation camera height|2m|versioned launch config/calibration provenance|
|Downward orientation|pitch−π/2|launch config transform|
|Navigation depth resolution|240×180|native sensor resolution ACK|
|Navigation camera HFOV|120°|launch config|

This is a simulated research sensor rig. The camera heights exceed body height;
it is not a physically calibrated consumer-vacuum assembly. Keeping it fixed
allows comparison without confounding camera changes. Clearance checks retain
1m body height: a physically narrow/lower passage may correctly be refused.

Per-scene start pose/floor are intentionally scene-specific. Seed0 is acknowledged
by the simulator. Calibration IDs bind actual sensor transform/intrinsics;
canonical geometry uses Z-up/metres and observations preserve source/time/pose
versions. Native ACK verifies body/navmesh size and resolution, not independent
physical measurement of camera location. Launch configuration SHA binds those
camera settings. No claim of real-hardware calibration is made.

The three300s baseline profiles and their original SHA remain under
`.runtime/reliability-campaign-20261031/eval-prep/configs/`. Source-pinned ACK audit:
`eval-prep/comparison.md` and `source-pins.json`. Baseline source/hash and current
shipped config UI pin updates are distinct; never rewrite old campaign profiles
to make them appear to have used later code.

Geometry CPU oracles include actual planner and MotionGuard with measured
synthetic free strips .20m and .60m at two grid phases, invalid-depth blocking,
and world-latched targets across rolling origins. Existing .45m strip test also
retains unknown/low-clearance vetoes. These are raster fixture checks, not proof
of native passage traversal at an exact physical width. Grid resolution5cm and
wall/robot phase affect near-threshold decisions; do not weaken unknown/depth or
height checks to claim a narrow-passage success.
