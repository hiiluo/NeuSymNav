# Accumulated measured room map — 2026-10-31

User authorizes fixing local-window-only DuDe segmentation. Main owns shared
runtime/geometry integration; builder worker owns only its new module/tests;
independent Terra review follows frozen P06/P07 snapshot.

1. Build a full-resolution room NavSnapshot on the region lane from immutable
   measured occupancy tiles and the mapper's exact frozen robot geometry. FREE
   cells already passed planar/height/floor gates; reconstruct only their
   conservative historical clearance bound. Preserve unknown and corrections.
   No UI coarsening, sensor/semantic/navmesh oracle or control-map substitution.
2. Bound dense room input to one million cells and raw history to its existing
   4096-tile/16 MiB budget. Incomplete, old-source or over-budget data publishes
   stale geometry/unavailable membership, including empty stale startup.
3. Feed the existing native DuDe/guard/tracker pipeline. Reset native state when
   accumulated raster geometry changes, preserving Python canonical tracking
   against the complete accumulated input. Keep thresholds unchanged.
4. Preserve exact accepted source pairing, floor/region input scope and extents,
   and bounded per-request diagnostics in final telemetry. Places are admitted
   on fresh local maps; published historical structural paths may be revalidated
   on the accumulated classification, always without a motion certificate.
5. Verify negative origins/source/height/caps/failure/recovery and local control
   independence; actual native two-room input plus moving-window retention;
   archived-run replay of recorded measured data and a bounded live smoke when
   assets support it. Do not certify true semantic room accuracy from node count.

End with implementation status, commands/exits, artifacts, independent review,
and explicit runtime/quality limits. No downloads/training/sibling edits/publish.
