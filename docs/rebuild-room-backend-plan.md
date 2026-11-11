# Rebuild M4/M5 room backend — 2026-11-02

User authorizes using the existing readonly Rebuild_3DScene_OccuSG project as a
room segmentation backend, temporarily hiding portal candidates, and completing
a runnable comparison within the existing assets/environment. No source-sibling
edits, installation, training, model download, commit or push.

One Luna6.0High owns the actual Rebuild stage adapter, explicit pinned config,
launcher selection, runnable wrapper and adapter tests. Main owns portal display
switch, verification/review and result/status. No duplicate implementation workers.
Baseline is the current uncommitted Room/accumulated-map implementation; preserve
user orchestration edits and all prior work.

Selected seam: same immutable measured accumulated occupancy enters either the
existing NeuSymNav backend or Rebuild's native M4 + original M5 guard/tracker. The
Rebuild mode uses one canonical region owner, preserves unknown/source revisions,
and pins external Python source closure plus binary. This is not a replacement
of sensor/occupancy mapping with OctoMap; holding the input map fixed isolates the
segmentation backend effect. Control/safety continue their unchanged local map.
Backend/preprocessing/input provenance must be explicit in diagnostics.

Validation: bridge and source rejection tests; actual saved input through both
backends with raw polygons compared before RoomOwner; preflight and a bounded
native live smoke if current assets support it. Compare geometry/counts, do not
infer quality improvement without room annotation. Portal candidates remain in
debug data but are hidden by default in map/3D/list, with an explicit debug toggle.
No threshold/TTL/GT-normalization changes to turn failures into passes.
