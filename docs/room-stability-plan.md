# Superseded: Stable Room policy and debug implementation — 2026-11-02

This historical implementation plan was retired on 2026-11-03. RoomOwner,
tentative/confirmed/disputed states, and portal debug UI were removed; current
Rebuild RGB-D room geometry comes directly from accepted M5 polygons. See the
current checkpoint in [implementation status](implementation-status.md).

Authorized scope: temporal Room identity and geometry, portal evidence and debug UI.
No room-driven exploration, motion-map replacement, training, model downloads, or
functional room-type inference. Existing accumulated room input changes are retained.

## Ownership and sequencing

- Luna 6.0 High `stable_rooms`: new `rooms/` policy, policy tests, design.
- Luna 6.0 High `room_runtime`: hierarchy integration and integration tests.
- Luna 6.0 High `room_ui`: presentation and offscreen tests/artifacts.
- Main: contracts/coordination, integration verification, result/status documents.
- Independent reviewer after a stable snapshot, initially Luna High; escalate only
  on concrete unresolved invariant or algorithmic findings. No Astra, no child agents.

Baseline HEAD: 9b90d3170f1a5fca7839df1d0468c567842381d9, with pre-existing
uncommitted accumulated-map work and user-owned orchestration edits preserved.
Prior 2026-11-01 dispatches stopped on model usage limits before writing sources;
2026-11-02 retries use the same explicit ownership. No prior test result certifies
this feature.

## Required behavior

Room identity is distinct from instantaneous DuDe regions. Tentative, confirmed,
and disputed states carry reasons and source provenance. Confirmation does not
require a physical door; geometry/topology and genuinely additional measured
support can suffice. A door detection alone cannot prove a room or passage.
Repeated maps/revisions and DuDe-only oscillations cannot create independent
support. Unknown is neither wall nor free. Confirmed geometry can be revised;
structural split/merge requires persistent additional evidence and records lineage.
Door absence is not negative evidence. No fixed bounding box can certify room
separation. Published historical geometry must be visibly distinguished from the
latest DuDe proposal and stale input.

Compatibility: keep existing region/object footprint membership semantics and
source-pinned hierarchy revisions. Carry additive bounded room debug metadata;
UI labels must not silently present raw DuDe region IDs as stable Room identities.
No room metadata is consumed by Navigator or MotionGuard.

## Verification gates

Targeted policy tests cover repeated input, changed revision without new measured
support, alternating DuDe partitions, expanding extents, open portals without
physical doors, unknown/furniture ambiguity, correction/split/merge lineage,
stale input and deterministic replay. Hierarchy tests cover source binding and
repeated composition. UI tests cover state/reason/lineage presentation, malformed
or missing debug metadata, and render an inspectable offscreen artifact.
Independent source review plus fresh focused tests precede final whole CPU suite.
Real archived measured input can demonstrate wiring and repeat invariance only;
without multi-room labels it cannot certify semantic room accuracy. Native/live
runs, if executed, are reported separately from synthetic correctness tests.
