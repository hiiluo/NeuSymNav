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
- Blue nodes represent geometry-region polygon centroids, not inferred room
  categories or certified navigable points. Purple nodes are observed visited
  places. Gold nodes are objects; a dashed outline indicates non-assigned
  membership. Retired objects are hidden by default in 3D, but remain in
  Hierarchy and become visible when selected there.
- Only existing assigned hierarchy relations produce lines. Dotted structural
  connections do not certify traversability. An object with missing/ambiguous/
  unavailable membership stays disconnected; proximity does not assign a room.

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
remain unchanged. The UI transport DTO/schema and payload caps are unchanged;
point clouds are not serialized into the publication.

Cloud source/time is shown separately from graph object/map revisions and is
explicitly historical. A cloud accumulates committed detector-keyframe RGB-D,
so it can lag Live RGB and does not reconstruct every captured frame. New
clock/episode contexts clear old geometry. No new dependencies or downloads
are required. Restart an existing demo to load the changed UI:

```sh
bash tools/run_map_demo.sh 00805
```

## Verification artifacts

`runs/spatial-scene-ui-20261030/` retains projection/source/clock/empty-depth/
occlusion regressions, focused tests, independent review and desktop previews
from real previously recorded 00805 RGB-D. `dashboard.png` and
`spatial-focus.png` are marked archived previews. The four original review
findings and RED reproductions are preserved alongside their fixes and scoped
final ACCEPT. This UI work does not certify P10, semantic quality, navigation
performance, or a new long-duration native campaign.
