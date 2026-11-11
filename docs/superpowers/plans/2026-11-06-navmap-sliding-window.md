# NavMap Sliding Window Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or subagent-driven-development task by task. Preserve one writer per file.

**Goal:** Bounded spatial/temporal NavMap memory with measured choice of radius/retention.
**Architecture:** Optional per-component TTL and local-window vote integration/eviction; unmodified Hydra graph and existing fresh measured control guard.
**Tech Stack:** Existing Python/NumPy/Numba, replay and Habitat workers; no new dependencies.
**Spec:** ../specs/2026-11-06-navmap-sliding-window-design.md

## Global Constraints
- Kiet_branch2 only; keep source identity, TTL300ms/horizon100ms/stride1 and safety checks. No600s, commit or push.
- local_retention_s absent preserves legacy. Window uses existing snapshot_radius_m. Expired/outside evidence UNKNOWN, floor false, clearance uncertified.
- Each evidence component has its own last-observed timestamp. Negative age rejects. Timestamp bytes included in diagnostics/caps.
- One performance workload at a time; do not claim offline timing predicts native freshness.

## Review Focus
- Partial floor/height observation renewing stale free/obstacle data.
- Far exit/re-entry restoring archived FREE without new evidence.
- Invalid frame/timestamp mutating state; reset, negative coordinates and boundary alignment.
- Window edges becoming artificial frontiers/repeated goals, lost usable footprint.
- Historical overview or Hydra data accidentally becoming live motion evidence.

### Task1: rolling state implementation + tests (Luna)
- [x] Read mapping kernels and safety paths; record source hashes before editing.
- [x] RED tests: exact spatial boundary, far translation/re-entry, component expiry, timestamp rollback, reset, legacy parity, memory bound, immutable snapshots.
- [x] Add optional local_retention_s to NavMapper and bounded rolling helper/core integration. No archive resurrection in enabled mode.
- [x] GREEN focused mapping/guard tests; return files frozen with evidence.

### Task2: config + measurement harness (main)
- [x] Validate optional local_retention_s strict finite positive bound; wiring from mapper config existing kwargs.
- [x] Add replay CLI with radius/retention matrix, stage times, geometry/state/memory/provenance and source hashes. Use recorded300s, serial candidates.
- [x] Screen then full temporal replay shortlist, write measured selection rationale and opt-in profile.

### Task3: independent review and native validation
- [x] Frozen source review against safety/unknown/floor/expiry invariants; resolve findings with reproductions.
- [x] Run focused tests, full suite, native bounded30/120/300 measurement gates. Record failures honestly, no automatic600s.
- [x] Update implementation-status and results with command, exit, profile/source hashes, artifacts and unproven claims.


## Completion evidence / limits

Executed with Luna mapping/harness workers + independent Luna reviews; main owns
shared config/metrics and fused maintenance optimization. No commit/push.
See docs/results/navmap-sliding-window-2026-11-06.md and artifacts/progress.md.
Full suite2627passed/10skipped/exit0;7native UI-on runs completed, including300s.
Implementation/measurement tasks complete; long performance acceptance NOT met.
Ruling: allow equal capture stamps for distinct increasing FrameKeys; reject
rollback only, keeping original source expiry and frame dedup. Ruling: forensic
mapping uses private replay domain while preserving numeric original captures
and original domain/hash separately, after oldboot future-time probe failed.
No code change to live clock guard. No unresolved review blockers; no600s.
