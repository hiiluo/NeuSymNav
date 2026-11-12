# Superseded: Stable Room owner policy

**Removed from the runtime on 2026-11-03.** This document is retained as design
history only. `RoomOwner`, tentative/confirmed/disputed room state, stable-room
IDs and portal-candidate projection are no longer part of the codebase. Rebuild
M1–M5 accepted polygons are the room partition source; room labels may be added
later by an SLM/LLM consumer without adding a second geometry owner.

`RoomOwner` consumes source-matched navigation and region snapshots. Region IDs are
proposal identifiers, not Room identifiers. A bipartite overlap component groups
all proposals touching the same existing Room or Rooms. One-to-one refinement keeps
the Room ID; a one-to-many proposal is held under the parent, and multiple region
IDs can therefore refer to that Room. A many-to-one proposal is held under the old
Rooms. Geometry remains the accepted geometry on proposal-only changes. An absent
confirmed proposal becomes disputed only when local measured support changes; it
retains historical geometry.

The occupancy history uses episode-relative integer grid cells, stores each measured
class only once and rejects misaligned origin shifts. Revision changes, raw DuDe ID
changes, and repeated or toggled observations cannot produce fresh cell/class
support. Header binding includes resolution, geometry, floor datum, calibration,
sensor, clock domain and region floor. An update is staged transactionally: a
rejected budget, source or alignment update does not consume evidence or advance
watermarks. An invalid new episode publishes an empty stale result rather than the
previous episode's Rooms.

Confirmation requires distinct local measured supports and enclosure or a
wall-supported door observation. Missing depth/unknown is not free or occupied;
a door is optional corroboration and does not certify passage. Structural changes
require the same polygon partition and two updates with at least four new relevant
cells each. A split uses newly measured occupied cells near shared interior polygon
edges; a merge uses previously occupied cells corrected to free there. At least
0.6 m worth of distinct cells must remain in the corresponding current class, and
at least 80% of sampled shared-edge cells must currently have that class. Unknown
cells remain in the denominator. A narrow doorway therefore does not merge rooms.
Accepted children get new IDs, all parent IDs in `predecessors`, and split/merge
events. Equal-count repartitions are conservatively held. Candidate portals are
independent occupancy gap proposals and are not passage certificates.

This is a conservative heuristic, not proof of a complete wall, a doorway or true
room boundaries. Cell count is not connected length, polygons may be inaccurate,
and exact proposal geometry must recur; jitter can defer a transition. The policy
does not infer multi-view observations: NavSnapshot carries no camera pose. Counts
are distinct occupancy cell/class evidence, not independent viewpoints. Door
observations currently corroborate only the update on which supplied. Retained
geometry and candidate work have explicit caps; partition edge checks are bounded.
Rejection preserves prior accepted state and reports stale. Neither these synthetic
tests nor this design establishes native room accuracy or motion safety.

Thresholds are fixed provisional policy values, not calibrated accuracy results.
The 250,000-cell maximum, bounded proposal/vertex/event counts and two-million
edge-check budget may yield a stale result on larger or complex inputs; they are
not a latency guarantee. Portal detection scans axis-aligned occupancy lines and
can miss diagonal or irregular openings. Existing region/object footprint
membership remains raw-region based; this owner does not change navigation or
motion-guard decisions.
