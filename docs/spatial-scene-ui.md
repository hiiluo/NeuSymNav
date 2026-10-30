# Spatial scene debug view

The demo now opens **3D Scene** by default in the lower panel. It places object
nodes at their measured canonical world centroids over an accumulated RGB-D
point cloud. This is a display of observed geometry, not a simulator mesh or
semantic ground truth. The existing **Graph layout** and **Hierarchy** tabs
remain available.

## Controls and colors

- Drag left to orbit; drag right/middle to pan; wheel to zoom. Hold **Shift**
  while dragging left up/down to zoom with a mouse drag. Orbit supports views
  above and below the scene.
- Double-click to fit the observed cloud. Camera orientation and zoom survive
  new publications. Choose `SCENE GRAPH` in **Focus view** for more screen space.
- Click a gold object to select its canonical ID, show its 3D bounding box and
  inspect its evidence. Alias selection uses the existing canonical resolver.
- The visible graph has exactly three kinds: **Floor → Room → Object**, in
  3D Scene, Graph layout and Hierarchy. Internal Building/Place records are not
  displayed. Gold Object nodes retain their exact measured XYZ centroid and
  measured bounds; the RGB-D cloud is unchanged.
- Blue Room nodes use the area centroid of the accepted room polygon. For a
  concave polygon whose centroid lies outside, an interior clearance center is
  used instead. The anchor updates with accepted room geometry. Teal Floor nodes
  use the area-weighted XY center of their rooms. Only Room/Floor display heights
  are raised: Floor above Room, Room above measured objects. These heights are
  graph layout, not measured structural elevations.
- Solid lines connect source-supported, assigned Floor→Room and Room→Object
  membership. Cyan dashed lines connect Rooms with current accepted structural
  adjacency, in both 3D Scene and Graph layout. This topology does not certify
  present robot clearance. Stale, cross-floor or unavailable adjacency is hidden.
  Missing, ambiguous, stale or unavailable object membership stays disconnected;
  proximity does not assign a room.

For example, the retained 00805 archive has 20 visible non-assigned objects,
so its spatial layout does not manufacture room-to-object lines. Investigate
membership through Hierarchy/evidence separately from renderer placement.

## Resize and detach the graph

- Drag the blue horizontal divider above the graph up/down to change its height.
  Drag fully up to collapse the camera/map row.
- Drag the blue vertical divider beside Object Evidence left/right to change
  graph width independently of the evidence column.
- **Expand** focuses the graph in the main window; click again to return.
- **Pop out** opens the same graph in a separate, resizable window. Drag its
  title bar to move it and its edges/corner to resize it. **Dock back** or closing
  that window restores the graph to the dashboard. Closing the main dashboard
  also closes the detached window. Data updates continue in either location.
- **+ / −** zoom; **Fit** fits the scene; **Top** switches to an overhead3Dview.
  Selection, orbit, pan and zoom survive resize, detach/restore and new data.
- In **Graph layout**, wheel zooms, Ctrl+wheel rotates2D, and left-drag pans.
  Double-click or **Fit** restores automatic fitting.3Dorbit is on **3DScene**.

## Data and limits

### Hide floor and ceiling cloud

The **Cloud** menu defaults to **Filter cloud height**, with **Keep floor**
selected and an upper limit of **2.20 m above the calibrated floor**. The lower
value of zero disables lower clipping, retaining the measured floor including
small reconstruction offsets. Set **Above floor** to a positive value to hide
low points, adjust **Below height** to change the upper limit, or uncheck the
action to restore the full cloud. This is a height filter,
not semantic surface classification: it also clips upper walls and any other
cloud points outside the selected range. All graph nodes, relations, object
bounds, stored RGB-D and navigation geometry remain unchanged.

The viewer uses the published navigation floor elevation, falling back to a
published floor node. If neither provides a floor datum, it leaves the cloud
complete and reports that the cutaway is unavailable. The footer shows visible
and total point counts. Its latest input timestamp describes the historical
RGB-D input; the points left after filtering may be older.

Only the UI child reads committed source assets through the existing object
ledger in read-only SQLite mode. The reader checks the source file's SHA256,
episode, primary sensor, original clock/timestamp, frame key, calibration,
geometry hash and pose version. It uses the source's full inverse K and measured
canonical `T_world_camera`, filtering invalid/no-return/far-plane depth. No
historical frame is emitted into control or relabeled as a fresh sensor sample.
A frame with no measured points cannot refresh the older cloud's displayed age.

One background thread performs file reads and projection. Its pending envelope
queue has capacity one; the GUI only polls the latest result. Cloud work is not
on capture, control or graph-publication threads. Missing/corrupt assets leave
an explicit unavailable/historical view and do not run another sensor/model.

The display retains at most 80,000 measured voxel samples (4 cm display
quantization), 12,000 sampled pixels per frame, and 128 contributing source
records. This bounded visual decimation does not alter canonical object/map
geometry. Nodes are capped at 300 and labels are culled to avoid overlap;
selection/evidence still exposes exact IDs. Raw recordings and object history
remain unchanged. The UI transport retains its payload caps and versioned backward decoder;
point clouds are not serialized into the publication.

Cloud source/time is shown separately from graph object/map revisions and is
explicitly historical. A cloud accumulates committed detector-keyframe RGB-D,
so it can lag Live RGB and does not reconstruct every captured frame. New
clock/episode contexts clear old geometry. No new dependencies or downloads
are required. Restart an existing demo to load the changed UI:

```sh
bash tools/run_map_demo.sh 00861 60
```

## Verification artifacts

`runs/spatial-scene-ui-20261030/` retains projection/source/clock/empty-depth/
occlusion regressions, focused tests, independent review and desktop previews
from real previously recorded 00805 RGB-D. `dashboard.png` and
`spatial-focus.png` are marked archived previews. The four original review
findings and RED reproductions are preserved alongside their fixes and scoped
final ACCEPT. This UI work does not certify P10, semantic quality, navigation
performance, or a new long-duration native campaign.

## Current map and graph freshness

The map displays an accumulated measured occupancy overview through a separate
bounded UI publication worker (up to 5 Hz). The latest local navigation snapshot
still supplies source-bound robot/planner context, independently of graph work. It can advance before the first canonical graph
and while detector/region work is pending. Room outlines remain tied to their
hierarchy map; a differing source/revision is explicitly marked STALE. Robot
pose is bound to the displayed map's exact source/time/domain. RGB, detector,
map and historical cloud retain their own capture times. They need not represent
the same instant; no stale sensor is republished into control as fresh data.

The 2026-10-31 corrections and validation are documented in
[room-graph-sync-2026-10-31.md](results/room-graph-sync-2026-10-31.md).

## Occupancy map controls

- Wheel over the map to zoom about the cursor.
- Drag with left, middle or right button to pan.
- Double-click or **Toàn bộ map** to fit the entire accumulated map.
- **Về robot** centers once at the local navigation scale; it does not force follow.

Manual zoom and world center survive live map updates, moving map origins and
window resizing; a new episode/clock resets the view. Occupancy, room outlines,
robot, camera cone, trail and route use one transform and clip to the viewport.
These controls change the display only. Source timestamps and STALE indicators
remain visible. Restart the running demo to load the controls.

Evidence for the new lines/controls: `.runtime/graph-links-map-controls-20261031/`;
see [validation report](results/graph-links-map-controls-2026-10-31.md).

### Whole map data (2026-10-31 correction)

Zoom/pan now operates on measured 2D history from every mapper integration, not
only the small moving NavSnapshot. Known areas remain available after the robot
leaves them and after active 3D tile eviction. Full map fits this accumulated
extent; manual focus stays at the chosen world coordinates. Unknown gaps remain
unknown. The display may coarsen its resolution to keep a bounded raster and
shows the actual metres/cell. An INCOMPLETE flag exposes a history cap or lost
update. Latest-update age describes the overview source integration; individual
cells include historical evidence. This display map is not used for motion
clearance or room membership. See [validation](results/global-map-view-2026-10-31.md).
