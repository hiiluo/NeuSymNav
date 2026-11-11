# Hydra branch2 — NavMap outlier investigation, map 00805

Date: 2026-11-04. This is an offline analysis of the recorded 30 s stage-profile
smoke. No simulator or live sensor was started.

## Live outlier and control impact

The largest NavMap interval belongs to recorded source
`downward-depth/frame-1`: mapper start `14290659985655 ns`, end
`14292762159076 ns`, wall duration **2,102.2 ms**. The source capture was at
`14290642957093 ns`, so it entered the mapper about 17.0 ms after capture.

While the navigation worker was occupied, frames 2, 3 and 4 were captured. The
exact-map waits for those sources ended at their 300 ms freshness deadlines
without a matching map; control recorded `navigation_unavailable` for each.
Frame 4's wait ended at `14292701584188 ns`, about **60.8 ms before** its map
update began at `14292762419133 ns`. That later update took 92.3 ms. This ties
the missed controls to the preceding long map update plus the existing freshness
deadline; no safety or movement parameter was changed.

The adjacent sensor stages do not show a comparable request stall on frame 1:
navigation round trip was 24.2 ms, host decode 4.2 ms, worker draw 8.5 ms,
readback 3.1 ms, and normalize/encode 5.4 ms. This supports the conclusion that
the long interval occurred inside the NavMapper update rather than in that
frame's Habitat capture.

## Offline reproduction on the recorded source

Replayed the exact recorded `downward-depth/frame-1` observation through a new
NavMapper created from the pinned local profile, with no simulator. The first
map update in a fresh Python process took **1,793.3 ms wall / 2,877.2 ms process
CPU**. Repeating the same source against a fresh mapper in the same process took
**130.3 ms wall / 1,250.3 ms process CPU**. A separate cold-process run measured
1,737.8 ms wall, followed by warm updates of 122–153 ms for the sampled frames.
The live outlier (2,102.2 ms) is close to the reproduced cold cost; typical live
NavMap p50 was 73.5 ms.

The configured runtime uses `raycast_backend=cpu`, `raycast_workers=4`, and
sampling stride 1. Numba is available. The raycast dispatcher starts with no
compiled signatures and gains its `float64`/`bool` signature after the first
map update. The kernel is declared `njit(cache=False)` in
`src/neusymnav/mapping/_raycast_kernel.py`, so each fresh process incurs first
call compilation. This is the strongest supported explanation for the outlier:
**cold Numba JIT compilation during the first raycast**, with substantial
parallel CPU use. It is not evidence that every NavMap update costs 2.1 s.

This diagnosis is strong but not a direct live JIT timer: the live trace records
the wall boundary around the full `NavMapper.update`, not a separate compiler
span. The offline replay reproduced the same raw source and profile, but ran on
a later host state. The live resource artifact contains only aggregate RSS
(sampled peak 2.216 GB, maximum sample gap 580.6 ms); it does not retain a
timestamped RSS/CPU series. GPU sampling had no usable provider. Therefore live
CPU utilization or memory pressure at the outlier cannot be reconstructed from
this artifact.

## Evidence and verification

- Live artifact directory:
  `.runtime/hydra_ws/artifacts/hydra-stage-profile-00805-30s-20261104/`.
- Live measurements SHA-256:
  `8fcba7153f72f9a7315a7fc7c6528c7347e68cc5956edb0c6ad72c4eb59078d1`.
- Offline replay used `ReplayReader.source_frames()` from the recorded
  `keyframes/recording` directory and `_mapper()` with the existing pinned
  `configs/demo-00805.hydra.local.json`. Both profiling commands exited **0**.
- Numba availability/signature probe: dispatcher signatures were empty before
  the cold update and contained the expected compiled signature afterwards.
- No product code, motion configuration, sensor settings, or simulator state
  was changed during this investigation.

The next targeted change, if authorized, is to compile/warm the exact CPU
raycast signature during mapper worker startup, before accepting fresh control
captures, and report that startup cost separately. Keep the 300 ms evidence TTL,
map algorithm, raycast workers, and motion profile fixed while verifying it.
