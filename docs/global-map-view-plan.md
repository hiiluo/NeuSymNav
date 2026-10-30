# Whole accumulated occupancy display

User correction: prior zoom/pan operated only on the moving local NavSnapshot.
Implement an authoritative accumulated display map covering all measured areas,
independent of local navigation/room windows; do not substitute sampled UI-window
stitching or silently enlarge the controller raster.

- [x] Mapping worker: every integration copies classified dirty-cell state into
  bounded immutable overview tiles, preserving across 3D-tile eviction/reset.
  Build a bounded full-extent overview off the navigation/control lane; unknown
  gaps stay unknown, integer coarsening when needed is visibly display-only.
- [x] Main: pipeline latest overview pointer + UI publication provider; typed
  MapOverview optional DTO with source/calibration/time and backward decoder.
  Robot/planner remain bound to exact local nav; global map is display-only.
- [x] Main: MapWidget uses global world geometry for raster/overlays; Full map
  fits total extent, Focus robot centers once; wheel/pan hold arbitrary world
  area while robot moves. Current timestamp is latest integration, not the age
  of every accumulated cell.
- [x] RED/GREEN moving-robot global coverage, sparse unknown/corrections/bounds,
  transport provenance, Qt world camera/events; focused regressions + render.
- [x] Independent scoped review, docs/status/commands/exits/evidence. No commit,
  push, dependency install, GT/runtime semantic use or sibling changes.
