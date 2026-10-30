# Occupancy navigation overlay — 2026-10-30

User requests continuous camera FOV plus actual frontier points/current goal.
Keep display-only; no inference/control/safety policy changes, extra sensor work,
GPU workload, dependency install or upstream edits.

1. Reproduce alternating paired/depth-only missing cone. Cache a bounded rigid
   planar camera mount calibrated from a source-matched RGB/body pair, then
   project it using each measured navigation pose. Separate derived CameraProjection
   DTO records current pose source and original calibration source/policy. Never
   relabel an old RGB capture, project across episode/clock, or invent occlusion.
2. Capture actual frontier extractor output and selected NavigationDecision in
   the existing control pass as one immutable pointer. Build a bounded display
   DTO on the graph/UI lane after its existing coalescing gate; do not rerun
   planner/extractor, serialize lists or do I/O on control. Include own source,
   map revision/time and guard reason; clear active goal on pause/stop/rejection.
3. Render frontier boundary points yellow, candidate viewpoints separately,
   selected goal clearly with route, using world coordinates and the occupancy
   raster transform. Planner map may differ from region-pinned display map;
   retain its own provenance/age and label stale instead of claiming same source.
4. Extend optional display schema with backwards-compatible decode defaults,
   bounded typed validation, strict episode/clock checks and pin updated UIworker
   scripts in active configs. Keep existing canonical hierarchy/map binding.
5. Regression/transport/source/Qt tests, CPU render preview, independent review
   of projection/provenance/wiring, update status/commands/limits. No fresh native
   GPU throughput claim from UI tests; previous benchmark remains historical.
