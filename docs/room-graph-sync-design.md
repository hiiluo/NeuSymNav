# Three-level room graph and current occupancy display

User explicitly authorizes implementation: visible scene graph onlyFloor→Room→Object;
roomXY follows current accepted roomgeometry center, higherlevels above lowerlevels,
centered floor, membershipedges; audit roomsegmentation and fix occupancy displaylag.

Presentation maps canonical geometryregion nodes to Room without inventing roomtypes;
no Building/Place nodes in3D/2D/tree. Canonical IDs/region lineage/internalplaces
remain for consumers; onlypresentationprojection isrestricted. Unknown/ambiguous/
staleroommembership remainsdisconnected andexplicit; floor→room androom→object
edges onlysource-supported. Layoutuses roompolygoncenter (interiorcenter when
concave), floorcenter derived from samefloorroomgeometry, Object node XYZ remains exactly measured in the point cloud; only Room/Floor
displayZ is elevated above all Object bounds, strictly Floor>Room>Object.
Point-cloud points and measured object bounds are unchanged.

Currentmapdisplay is independent of hierarchy's pinnedmap: optional latest_nav DTO
with exactsource/time/domain/episode and boundrobottrail. It isdisplayonly, never
relabels olddepth or replaces hierarchy.source_nav for roommembership. UItransport
updates via a dedicatedboundedcoalesceddisplayworker independent ofgraph/model
work, uses latestnavigation snapshot provider, keeps one graph/sourcebundle and
monotonic provenance. UI labels map/RGB/detector origins and lag. No control waits
forUI. Roomoutline stale label when sourced from old region-map revision.

Roomaccuracy audit: inspect nativeDuDe thresholds/polygons/support/tracker, concave
centers and sourcejoins. Fix demonstrated defects withRED→GREEN; no imagined
semanticroomaccuracy or GT online. No broadparameterweakening toinvent rooms.

Ownership: roomUIagent visualhierarchy/spatial_scene/scene_graph/desktop+tests;
mapagent publisher/ui_transport/coordinator/launcher+tests; mainregion/hierarchy
center/source contracts/docs/configpins/reviewintegration. Eachfileonewriter.
OneGPUjob at a time, CPUwindow coordinated. No install/download/siblingwrite.
Runtime75s or boundedrecordedQtfixture where appropriate afterCPUchecks; showrender.
No commit/push unless requested for this newwork.

Confirmed user correction: the scene remains the measured RGB-D point cloud.
Object nodes MUST stay at exact measured XYZ; no object-layer lifting. Only
Room/Floor nodes use elevated graph-layout Z while retaining geometry-centeredXY.
