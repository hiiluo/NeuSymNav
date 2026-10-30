# ConceptGraphs Association Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Add an opt-in point-cloud/visual association recipe inside the existing canonical owner and measure it on fixed inputs.
**Architecture:** A validated immutable recipe controls a bounded directional scorer in AssociationEngine. ObjectOwner pins the recipe durably; runtime passes it explicitly. Offline replay separates assignment from GT scoring.
**Tech Stack:** Python, NumPy, SciPy cKDTree/Hungarian, SQLite, existing offline evaluators.
**Spec:** docs/superpowers/specs/2026-10-30-conceptgraphs-association-design.md (user approved2026-10-30).

## Global Constraints

- Only NeuSymNav writable; source siblings read-only; preserve prior evaluator edits.
- No downloads, installs, training, publish, default promotion or safety-gate changes.
- Single canonical owner, bounded clouds, unchanged event digests/checkpoint shapes.
- Semantic GT only in evaluator; full source/frame denominators retained.
- Sol High for geometry/identity/review; no Astra. No worker child agents.

## Review Focus

- Mixed feature availability must select a consistent row policy, never reward missing features accidentally.
- Restart with a different recipe must reject before state publication; legacy ledgers remain readable.
- Cloud ordering/partial views/planar surfaces must not induce prefix sampling errors.
- Failed/rejected projections remain in input accounting; unavailable identity scores stay explicit.
- Fixed replay must retain source ordering, real timestamps and online endpoints; no GT-dependent association choices.

## Task1: Recipe and point-cloud engine

Files: new objects/association_recipe.py, objects/conceptgraphs.py; modify objects/association.py; new tests/test_conceptgraphs_association.py.
Interfaces: immutable AssociationRecipe(mode='legacy'|'conceptgraphs', nn_distance_m=.03, voxel_m=.03,max_points=4096,physical_bias=0,match_threshold=.55,ambiguity_margin=.08,min_spatial=.10), from_mapping(), to_dict(). Engine accepts association_recipe=None and returns AssociationResult.diagnostics (bounded JSON scalar mapping).

- [x] Write/run failing independent-distance and partial-view/ordering/feature-policy tests.
- [x] Implement validated recipe and bounded directional scoring; keep legacy path exact.
- [x] Implement row policy, recipe threshold, ambiguity and per-ingest diagnostic counts.
- [x] Verify geometry/floor/wall/cannot-link/fork/strict-distance tests and legacy parity.
- [x] Main reviews task before integration gate; independent final reviewer checks whole change.

## Task2: Owner/runtime integration

Files: objects/store.py, runtime/configuration.py, runtime/launcher.py; new tests/test_conceptgraphs_integration.py; opt-in config and docs.
Interfaces: top-level association mapping parsed by AssociationRecipe.from_mapping(); ObjectOwner(...,association_recipe=None). Immutable recipe pinned in metadata association_recipe; old metadata absence means legacy. Engine receives identical recipe. New-mode batch data records association diagnostics and original online IDs, not event digest changes.

- [x] RED tests: invalid config, legacy compatibility, recipe mismatch/restart, rollback, online endpoint preservation after merge.
- [x] Implement recipe pinning and config forwarding; persist bounded diagnostics atomically with batches.
- [x] GREEN tests with actual SQLite and existing projection fixtures.
- [x] Supply runnable opt-in geometry-fallback profile with current local assets; document CLIP asset status explicitly.

## Task3: Fixed replay, review and final verification

Files: new tools/replay_association_quality.py and tests/test_association_replay.py; docs/results/conceptgraphs-association-2026-10-30.md; status/ledger updates.
Interfaces: input retained quality capture ledger + original prediction frames, no GT input during replay; generate derived prediction sets preserving source binding/frames and explicit filtered-memory scope, unique online canonical IDs mapped deterministically. Separate evaluator produces metrics.

- [x] RED tests for input source mismatch/order and frame-local IDs; implement read-only replay with safe ledger reader and source assets.
- [x] Execute legacy and new geometry comparisons with same observations/times; visual comparison only with verified existing compatible features/assets.
- [x] Run independent SolHigh review on frozen engine/integration/replay source; resolve findings with regression evidence.
- [x] Run full CPU suite once frozen; diff check, hashes, commands/exits, report unchanged/increased/decreased metrics honestly.
- [x] Update completion states and usage; no commit/push.

## Execution rulings

User approved design and explicitly requested implementation; proceed without another plan approval loop. Preserve this existing shared workspace and local-only deliverable rather than changing checkout location or committing unrelated evaluator work. Main owns recipe contracts, owner/runtime integration, docs and final integration. Geometry worker owns only assigned engine/scorer/tests; replay worker owns only replay tool/tests. Independent review required before completion.

## Final outcome

Completed available-asset scope:2024CPU tests pass, independent ACCEPT, real spatial replay/evaluation complete with identical identity partitions and unchanged quality. Full visual comparison unavailable for the declared local worker; no native campaign/default promotion. See docs/results/conceptgraphs-association-2026-10-30.md. No commit/push.
