# Offline P10 annotations

`semantic-a.json` and `semantic-b.json` are **synthetic** annotations for the
existing P09 package recording. They differ only in raw semantic label (`chair`
versus `couch`), and never enter launcher configuration or runtime data paths.

The observed planar points lie at canonical z=3 m: depth=2 m and camera z=1 m.
With fx=fy=12, principal point (5.5,5.5), and selected 12×12 pixels, the analytic
XY extrema are ±11/12 m. `aabb_xy_iou_v1` therefore measures only an XY footprint
diagnostic. It does not imply nonzero 3D volume, native scene quality, detector
accuracy, room correctness, identity support, or appearance gain.

`gt_isolation.audit_gt_isolation` creates two independent output directories with
identical explicitly cloned and validated replay-session files, then runs the
real public launcher replay twice. It compares all object/map bytes, canonical
IDs, aliases, source keys and evidence. The sole excluded field is the hierarchy
publication counter (`HierarchySnapshot.revision`), which can differ with thread
scheduling while its pinned object/map/region/latest revisions and full nodes,
edges, statuses and source age remain identical. Both raw and compared hashes
are retained in the audit report.
