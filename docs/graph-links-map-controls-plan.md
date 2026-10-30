# Graph links and map camera

Goal: user-requested Room–Object membership lines, Room–Room connectivity lines,
and occupancy zoom/pan. Existing PyQt UI and measured RGB-D remain unchanged in
meaning; display-only changes, no canonical membership guesses or control changes.

Approach: render existing assigned in_region parents and accepted
region_adjacent_to topology through a shared display-edge projection in 3D/2D.
Room connectivity uses distinct dashed cyan lines/tooltips: structural topology,
not a current robot traversability certificate. Hide stale/conflicting/cross-floor
links; do not expose hidden Building/Place kinds. Bound visible edges to1200.

Map interaction: wheel zoom about cursor, drag left/middle/right to pan,
double-click Fit. Raster, outlines, route, robot and view cone share the same
world-to-screen transform and viewport clipping. Retain manual world view across
publications (including moving origin), resize; reset on episode/domain change.
Normal default auto-fit stays compatible. No new dependencies/GPU workloads.

Alternative: renderer-only nearest-room/distance guesses rejected as false
membership/topology. New nav planning/room persistence would change backend
semantics and is beyond this display/interaction request.

- [x] RED→GREEN shared relation projection + 2D/3D edge regression.
- [x] RED→GREEN map wheel/drag/Fit, overlay alignment, clipping and moving-origin persistence.
- [x] Integrate, focused regressions, inspect actual Qt render; document controls and limitations.
- [x] Update status/commands/exits/source evidence. No commit/push.
