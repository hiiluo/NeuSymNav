# Graph links and occupancy map controls — 2026-10-31

Implemented the user-requested display changes in the existing PyQt viewer.
The visible graph still contains only Floor, Room and Object nodes; measured
RGB-D point clouds, Object XYZ/bounds and canonical membership stay unchanged.

Solid lines connect assigned Room–Object and Floor–Room membership. The previous
UI already drew valid assigned membership, but omitted canonical Room–Room edges.
Both 3D Scene and Graph layout now share `hierarchy_links`, which adds current
assigned `region_adjacent_to` relations as cyan dashed lines. Duplicate reverse
edges are deduplicated. Stale, unavailable, conflicting-parent and cross-floor
room links are omitted. Only links between visible nodes survive; membership is
prioritized within the 1200-edge cap. Same-level 2D links curve above the room row.

These edges express accepted structural connectivity. They do not certify
current robot clearance. Object membership still requires the canonical geometry
resolver; an unknown/unassigned object is not connected by a nearest-room guess.
The previously observed local-window membership limitation remains; this task
changes presentation, not persistent room geometry or semantic-room accuracy.

Occupancy map interactions:

- Wheel: zoom about the cursor (bounded relative to fit scale).
- Drag left, middle or right: pan in world XY.
- Double-click: return to automatic fit of the current map.

Manual world center and pixels/metre survive moving origins and live publications,
as well as resize. New episode/clock contexts reset the view. Raster, polygons,
route, robot, trail and camera cone share the world-to-screen transform and clip
to the map viewport. Fixed source/status captions retain their own screen layout.
Zoom draws the clipped source image directly, avoiding oversized scaled buffers.
No capture, controller, room-worker or source freshness policy is changed.

## Verification

Evidence: `.runtime/graph-links-map-controls-20261031/`.

- Graph RED: 3 failed/4 passed, exit1, missing adjacency and typed/styles metadata.
  GREEN: 7 passed, exit0 (`graph-{red,green}.log`).
- Initial map RED: 2 failed/2 passed, exit1, no zoom/pan and origin persistence.
  Final map GREEN: 6 passed, exit0 (`map-green.log`). Qt event tests cover cursor
  anchoring, drag, moving origin, resize, fit, episode reset and clipping. A real
  pixel check verifies robot, goal and occupied cell share the transformed raster.
- Review found the ROBOT world label escaped the outer viewport margin. New
  `test_robot_world_label_stays_inside_map_viewport` first failed (exit1;
  `robot-label-red.log`); clipping fixed before disabling it for fixed captions.
- Final focused UI/map/publication/navigation/cloud suite: **123 passed**, exit0,
  4.79s (`regressions-final.log`). Commands include the two new files and existing
  room graph, display, spatial/cloud, scene graph, UI, robot and navigation suites.
- Independent delta review: scoped ACCEPT, 75 focused tests exit0, eight additional
  probes exit0 (zero/negative wheel, all drag buttons, domain reset and relation
  rejection cases). See `review/review.md` and its source hashes/probe logs.
- Actual Qt offscreen rendering of a typed synthetic fixture: exit0
  (`render-final.log`). Inspected `spatial-detail.png`, `dashboard-2d.png` and
  `map-zoom-pan.png`: retained colored cloud, grounded Objects, solid membership,
  cyan dashed Room links and transformed map. Fixture source explicitly synthetic;
  it does not establish room semantic quality or native runtime performance.
- `git diff --check`: exit0; `point_cloud.py` unchanged. Final nine source/test
  hashes recorded in `final-source-hashes.json`.

No new GPU workload, native simulator run, download, install, training, sibling
edit, commit or push. The prior native run is not relabeled as validation of these
new controls. Restart a demo to load this UI, for example:

```sh
bash tools/run_map_demo.sh 00861 300
```
