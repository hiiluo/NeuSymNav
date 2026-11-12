# Multi-map Kaggle runner design

## Goal and boundary

Package and run the RGB-D M1–M5 pipeline across a declared set of maps, with a
separate calibrated profile and asset manifest for every map. Keep Kaggle
orchestration, schemas and campaign outputs under `kaggle/rebuild_rgbd_multimap/`;
do not add Kaggle-specific execution logic to `src/neusymnav/`. Start evaluation
campaigns only after runner preflight and a strict-acceptance smoke pass.

The 00805 measurements show that CUDA can speed up the detector adapter and the
optional navigation raycast backend. Habitat currently renders on llvmpipe, and
Rebuild room mapping M1–M5 has not been shown to use CUDA. The runner must report
each stage's actual device; it must not infer acceleration from Kaggle's GPU
allocation.

## Bundle layout

```text
kaggle/rebuild_rgbd_multimap/
  README.md
  RUNNER_DESIGN.md
  schemas/map-profile.schema.json
  schemas/bundle-manifest.schema.json
  common/                         # source closure, workers, shared pinned assets
  profiles/<map_id>.json          # exactly one calibration/floor/scene profile
  tools/preflight.py
  tools/run_campaign.py
```

Each uploaded bundle may contain several map profiles and their scene/navmesh
assets, plus common assets stored once. A requested map must resolve to exactly
one profile. No profile lookup by prefix, implicit fallback, or borrowing
another map's calibration is allowed. Map outputs are isolated under
`/kaggle/working/<campaign_id>/<map_id>/`.

## Per-map profile contract

Each profile records, at minimum:

- `schema_version`, exact `map_id`, profile revision, source provenance and a
  profile SHA-256.
- Exact scene GLB path and SHA-256, scene-dataset config path and SHA-256, and
  an exact scene identifier. Scene selection must not rely on a wildcard that
  could select a different asset.
- Navmesh path and SHA-256 bound to that scene, plus a navmesh provenance
  record. Preflight must load it with Habitat and verify `pathfinder.is_loaded`;
  a bounded set of configured points must be on the navmesh and reachable where
  the profile says they should be. Missing navmesh is a hard preflight failure.
- Floor datum and coordinate convention: calibrated `floor_y_m` (or declared
  equivalent), evidence/source identifier, calibration revision and checksum.
  The floor cannot be guessed from a default or recomputed from semantic GT.
- Per-sensor calibration for primary RGB-D and navigation depth: dimensions,
  intrinsics, optical frame convention, depth convention/units, sensor IDs,
  calibration IDs, sensor extrinsics and expected pose frame. Include the
  calibrated starting pose and its source. A captured frame must match profile
  dimensions/intrinsics and produce finite positive metric depth samples.
- Explicit initial pose / admissible spawn region and any bounded capture
  settings required for that map. No silent pose substitution when a point is
  not navigable.

Shared bundle pins include NeuSymNav source commit/tree hash, Rebuild source
closure hash, M2/M3 and M4 binary hashes, region worker hash, Python and
dependency lock hashes, detector checkpoint/encoder/taxonomy hashes, Habitat
version, native library hashes, and the profile schema version. Hashes must be
computed from the actual packaged files at preflight time, not trusted only
because they appear in a manifest.

## Fail-closed preflight

`preflight --map <id>` runs before reserving a long session and reports one
structured result with evidence for each check. Any missing, ambiguous or
mismatched item yields nonzero exit and prevents capture.

1. Resolve exactly one profile and validate its schema, map ID and profile hash.
2. Verify all required files exist and match their SHA-256; verify common code,
   binaries, model assets, taxonomy, native libraries and runtime versions
   against pins.
3. Parse the scene-dataset config and prove that the configured exact scene is
   the profile's scene; load that scene in Habitat.
4. Load the paired navmesh in Habitat, check pathfinder readiness and validate
   configured spawn/waypoint probes. Record pass/failure and the measured
   positions; never mark a missing navmesh as a warning-only condition.
5. Capture a short RGB-D calibration frame from the real scene. Compare frame
   shape, K, calibration ID, depth units/range and sensor pose to the profile.
   Verify floor datum provenance and transform consistency. Do not feed
   semantic annotations or GT into runtime preflight.
6. Check writable disk space, per-run caps, output path isolation and runtime
   device availability. Record renderer string, CUDA device name/UUID, and
   model/raycast execution metadata separately; a GPU exists only if the stage
   itself confirms a CUDA device.
7. Emit `preflight.json` with profile/bundle hashes, checks, stage devices and
   explicit readiness. The runner does not start when `ready` is false.

The calibration capture is a provenance check, not a room-quality score. Map
specific calibration/floor profiles must be supplied and reviewed before a map
joins the runner's eligible set.

## Runner modes and gates

- `--list-maps` enumerates profile IDs that are present and schema-valid.
- `--map ID --preflight` only runs preflight.
- `--map ID --smoke` runs one bounded live diagnostic, exports evidence and
  invokes the existing acceptance checker with unchanged settings.
- `--maps ID1,ID2,... --campaign` runs maps serially, one GPU workload at a
  time, and writes one per-map result plus an aggregate index. It does not
  proceed to the campaign phase until every selected profile passes preflight
  and the designated runner smoke passes.

Smoke qualification requires a completed run, complete recording and clean
shutdown, accepted M3 paired with the latest M3 revision, non-stale M5 from that
M3, at least one geometrically valid region, and every condition required by the
existing acceptance checker. No thresholds, validators, timeouts or denominators
are lowered to turn a rejection into a pass. A rejected smoke remains in the
run report and blocks campaign start.

Campaign accounting includes every requested map in the denominator. Missing
profile/assets, preflight failure, runtime error, incomplete run, rejected M5,
and interrupted execution each produce an explicit failed row. Never omit a
failed map or silently replace it with another profile. Preserve per-map scene,
profile, source and binary hashes alongside reports and visual artifacts.

## Smoke plan before campaign implementation

1. Validate profile schema on the existing 00805 profile without changing its
   calibration or pins.
2. Run preflight for 00805 and verify the scene, navmesh, calibration/floor and
   common pin checks fail closed when each is individually corrupted in a
   temporary fixture.
3. Run a bounded 00805 smoke through this runner and require the current strict
   acceptance checker to pass. Until this gate passes, do not run a campaign.
4. Add a second map only after its own scene/navmesh, calibrated RGB-D profile
   and floor provenance are available; pass preflight and smoke for that map.
5. Run a campaign only over the explicit set of profiles that passed these
   gates. Retain the strict acceptance report for every map.

## Current readiness and unproven points

- 00805 has a pinned bundle and its Habitat RGB-D probe passed, but its latest
  full M1–M5 run is incomplete and rejected with zero accepted M5 regions.
- No multi-map Kaggle runner is implemented yet and no profiles for other maps
  are included in this design artifact. Preflight and campaign behavior are
  therefore not correctness-verified or runtime-validated.
- GPU detector and optional navigation raycast runtime configuration has been
  added to the 00805 Kaggle bundle in `kaggle/rebuild_rgbd_00805/`. The new GPU
  bundle still needs to be built, uploaded, and smoke-tested on Kaggle. The
  optional raycast backend is navigation mapping and does not speed Rebuild room
  M1–M5.
- Habitat GPU rendering and M1–M5 GPU acceleration have not been established.
