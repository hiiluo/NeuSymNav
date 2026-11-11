# Rebuild RGB-D M1–M5 runner checkpoint — 2026-11-02

## Scope

R6 from `docs/rebuild-full-room-pipeline-plan.md` is implemented as an opt-in
local runner. It builds a map-specific config from the calibrated
`configs/demo-00805.local.json`, labels it `rebuild-rgbd-m1-m5-v1`, and adds the
separate `workers.room_pipeline` lane. It keeps the navigation, sensor, body,
safety and existing region configuration from the local profile. The older
`tools/run_rebuild_map_demo.sh` remains untouched.

The runner now accepts any safe map identifier rather than an `0080x` allowlist,
and accepts `--config PATH` for a calibrated profile stored elsewhere. This
allows the same pipeline entry point to be used for teammate maps such as
`00770`; it does not create missing per-map scene/calibration data. Map profiles
remain local because they contain machine-specific asset paths and calibration.
The Rebuild checkout can be selected with `NEUSYMNAV_REBUILD_ROOT`.

The runner checks executable status and fixed hashes before writing the
generated config. On this host, the verified pins are:

| Resource | SHA-256 |
| --- | --- |
| Rebuild M2/M3 executable | `617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6` |
| Rebuild M4 executable | `6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693` |
| Rebuild Python source closure | `60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0` |

Profile M2 max range is 5 m, matching the audited `NativeRGBDMappingStage`
default. The earlier 8 m choice was unsupported and has been removed.
The profile gives Habitat sensor startup up to 60 seconds. The first integrated
smoke timed out at the base profile's 10-second worker startup deadline before
receiving any sensor frame; this changes startup allowance only and leaves
sensor, cadence and safety settings unchanged.
Live testing then exposed pose-dependent calibration IDs caused by native
float noise while recovering a static sensor mount. The worker now quantizes
that mount identity at 1e-6; world poses remain per-frame and unchanged. The
updated sensor script is hash-pinned by the calibrated local profile.

## Verification

- `bash -n tools/run_rebuild_rgbd_map_demo.sh` → exit 0.
- `bash tools/run_rebuild_rgbd_map_demo.sh 00805 --preflight` → exit 0,
  `ready: true`, empty `issues`, `native_runtime_validated: false`.
- `bash -n tools/run_rebuild_rgbd_map_demo.sh` → exit 0 after generic-map and
  `--config` support; `00805 --preflight` remains ready with no issues.
- Preflight for maps `00800`–`00809` → each exit 0, `ready: true`, empty
  `issues`; this checks local config/assets/pins, not runtime behavior on each
  map.
- `QT_QPA_PLATFORM=offscreen bash tools/run_rebuild_rgbd_map_demo.sh 00803 30
  runs/rebuild-rgbd-prepush-00803-30s` → exit 0, completed, 128 recorded frames,
  clean UI/resource/sensor shutdown. Acceptance checker → exit 0,
  `accepted: true`, M3 latest/accepted revision 8, M5 revision 8, two valid
  non-stale M5 regions. Artifact:
  `runs/rebuild-rgbd-prepush-00803-30s/`.
- Generated config:
  `.runtime/rebuild-rgbd-m1-m5-v1/configs/map-00805.json` (ignored runtime
  state); profile config hash reported by preflight:
  `1b30db9cb8c6e1e7127b2aa1b6453ea985a049f3531005c6eab67c7787f97335`
  after the range, startup-timeout and sensor calibration corrections.

The first preflight attempt exposed that the config parser's profile allowlist
did not contain the new versioned name. The allowlist was extended for this
exact profile and the preflight then passed.

## Limits and plan cross-check

This establishes the R6 runner/config/preflight. Later integrated runtime and
recorded-source oracle results are in
`docs/results/rebuild-rgbd-live-smoke-2026-11-02.md`; they do not close all R8
acceptance gates. Related general-plan
cross-check: P07 separate scheduling/failure state, P08 distinct room display
source tags, P09 config/preflight/export wiring. Those features remain
correctness-verified per `docs/implementation-status.md`. The later integrated
30-second Habitat smoke and its limits are recorded in
`docs/results/rebuild-rgbd-live-smoke-2026-11-02.md`.
