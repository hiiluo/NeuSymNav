# Occupancy map overlays

The map viewer draws a measured body marker and heading arrow, a thin sampled
trajectory, calibrated RGB camera azimuth edges, occupied cells and region
boundaries. These are read-only display layers. They do not alter occupancy,
control, safety guards, robot footprint, TTL, canonical IDs or graph membership.

## Source binding and transport

After normal paired capture admission, the launcher optionally passes the
already acquired RGB, navigation depth and exact measured body proof to the UI
observer. It performs no additional sensor/pose IPC. The observer appends bounded
scalar samples with a nonblocking lock; it never renders, writes files or waits
for the graph/UI process. Display errors remain local to UI status.

RobotSample records navigation FrameKey, capture timestamp, clock domain,
pose version, canonical XY and yaw. The latest robot sample in a published
RobotTrack must exactly match the pinned NavSnapshot source, timestamp and
clock; otherwise the overlay is unavailable. The buffer retains at most1024
samples, resets across episode/clock changes and rejects backward/duplicate
samples or sensor changes within an episode. Truncation is disclosed. The UI
breaks the polyline across missing source indices or timestamp gaps over1s;
lines between consecutive observed endpoints are sampled trajectory segments,
not an independently measured continuous path or a planned route.

DisplaySources has an optional robot field. RobotSample, CameraCone and
RobotTrack use bounded, closed typed DTOs in existing wire_version1. Current
readers accept historical DisplaySources packets lacking the optional robot
field, defaulting it to None; other missing/extra fields remain rejected. Older
readers are not expected to understand new overlay packets. Existing quotas,
publication byte cap, revision binding and command/ACK transport remain.

## Camera, stale state and geometry

CameraCone uses the actual primary RGB K matrix, image edge coordinates and
T_world_camera rotation/translation to project the two horizontal image-edge
rays into canonical XY. It retains source, timestamp, clock, pose version and
calibration ID. RGB must be from the same episode/clock/body pose version and
captured no later than the measured navigation sample. A vertical optical axis
has no azimuth sector, so it reports FOV unavailable. The cone uses the camera
origin, while the robot marker uses the independently measured body origin.

The cone's1m drawn length is a schematic display scale, not sensing range,
measured visibility, free space or safe clearance; it may cross obstacles.
The heading arrow has a fixed screen size and is not the physical footprint.
The pose/trail/cone turn grey with an explicit STALE label beyond300ms, on a
clock mismatch or future timestamp. No old source is refreshed or interpolated
into a current control measurement.

Raster, region outlines, trail and robot share one origin/resolution transform
with positive canonicalY upwards. Occupied cells are bright red; free and
unknown retain distinct colors and state values. No dilation, new obstacle
classification or unknown-to-free conversion is performed.
