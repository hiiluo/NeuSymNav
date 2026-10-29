# NewOH3DSG-style UI refresh — 2026-10-29

User request: make the demo about 50% larger, show bounding boxes and object
segmentation on robot observations, and follow NewOH3DSG's UI design throughout.
This is an explicitly requested implementation within the existing PyQt viewer.

## Design and source references

Read-only references: `../NewOH3DSG/visualization/render.py`, `live_ui.py`,
`layout.py`, `hierarchy_graph.py`. Retain the reference navy palette, RGB FRAME /
OCCUPANCY MAP / SCENE GRAPH vocabulary, occupancy legend and evidence inspection.
Preferred window size is 2160×1350 (previous 1440×900 ×1.5 per dimension), bounded
to the current display's available geometry and maximized on smaller screens.
Larger text, splitters and a focus selector make each view easier to inspect.

The chosen layout gives the RGB/map views a large top workspace, with a wide
graph and evidence drawer below. This adapts the reference's three parallel
panels to the user's explicit readability request. A direct copy of the entire
legacy runtime would duplicate identity/render owners and is outside scope.
Merely enlarging the old window would still leave the detector data absent.

The detector observation and live RGB have separate tabs. Box/label and mask
controls affect presentation only. Robot position, measured trail, camera FOV,
map regions, graph selection, canonical aliases and Pause/Stop ACKs remain.

## Exact source binding

A read-only reader selects the latest committed detector batch and its original
RGB-D observation from the existing object ledger/assets. It verifies the two
asset SHA256 digests, the detector batch's geometry/source binding, exact
processed FrameKey and host clock. Overlay uses that observation's RGB, never
the latest camera image. The caption names its source/frame, age, completion,
cap flag and displayed/total instance count and explicitly marks it historical.
The UI does not infer canonical object IDs from detector instance IDs.

The reader runs on the existing graph publication lane and caches one immutable
observation. No detector, simulator or control request is added. An unavailable
or invalid overlay is omitted with a bounded local diagnostic; the rest of the
UI publication can continue. There is no new control wait for detections.

DTO limits: 64 displayed instances, 8 MiB aggregate bool masks, existing 8 MiB
per RGB image, all counted inside the existing 32 MiB envelope payload budget
and 64 MiB wire cap. Excess display instances are omitted with explicit counts;
full committed detector evidence remains intact. Old UI packets without optional
robot/observation fields still decode. Active UI worker SHA pins are refreshed;
historical run snapshots and manifests retain their original hashes.

## Validation and limits

Tests exercise immutable source/masks, shape/count/confidence limits, episode and
clock rejection, different detector/live frame indices, mask/box toggles, real
committed asset reads, checksum corruption, old IPC packets, screen bounds,
focus controls and existing map/alias/ACK regressions. Offscreen previews use
historical real detector evidence, with a frozen historical presentation clock;
no image is represented as current sensor data.

Fresh commands/exits, source pins, preview images and independent review live in
`runs/ui-new-reference-20261029/`. Main status records the final results after
verification. This UI change does not certify new realtime measurements, live
desktop timing, semantic quality or P10 acceptance. Source sensor pixels retain
their measured resolution; enlarging the viewer does not create more detail.


Final verification: **1,388 CPU passed, 3 native deselected, exit0**; source-only
packaging/preflight/202 selected sibling hashes all exit0. Independent scoped
review ACCEPT (51 tests) and graph-label follow-up ACCEPT (10 tests). Exact
commands, frozen source hashes, preserved RED cases and limitations:
[checkpoint report](../runs/ui-new-reference-20261029/report.md).
