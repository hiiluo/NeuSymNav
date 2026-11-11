# Rebuild M5-Only Hierarchy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove RoomOwner and make accepted Rebuild M5 regions the only room segmentation shown and associated in the Rebuild RGB-D M1–M5 runtime.

**Architecture:** Keep the bounded M1–M5 room worker and its source pins. In that profile, stop starting the legacy region worker and compose room geometry and object membership from accepted M5 regions only. Remove RoomOwner, stable-room fields, portal-candidate projection and their UI; retain the legacy region backend only for non-M5 profiles.

**Tech Stack:** Python, pytest, PyQt5, existing Rebuild M1–M5 native workers and shell runner.

**Spec:** User request on 2026-11-03; preserve M5, remove RoomOwner completely, regression-test cleanup, keep map-selectable runner behavior.

## Global Constraints

- Keep M5 polygon validation, freshness and accepted-M3 pairing strict.
- Keep Rebuild source and native binary SHA pins unchanged.
- Keep runner map-agnostic; each map still requires its own calibrated profile and scene assets.
- Keep legacy region processing available only to profiles that do not enable the Rebuild M1–M5 room pipeline.
- Preserve the pre-existing dirty working tree; do not delete unrelated untracked reports or experiments.

## Review Focus

- A stale or rejected M5 publication must not create an assigned object-to-region link.
- A Rebuild M1–M5 hierarchy must not expose legacy `region` nodes or stable-room metadata.
- A non-M5 profile must retain its existing generic region and membership behavior.
- Map-specific preflight still validates scene/calibration and the same M1–M5 pins.
- UI graph and hierarchy still show M5 region/object links and stale state without S1/RoomOwner overlays.

## File Map

- `src/neusymnav/hierarchy/composer.py`: remove RoomOwner and branch Rebuild hierarchy composition to M5-only regions/membership.
- `src/neusymnav/runtime/launcher.py`, `src/neusymnav/runtime/configuration.py`, `tools/run_rebuild_rgbd_map_demo.sh`: make M1–M5 profile independent of the legacy region worker while preserving map-profile validation.
- `src/neusymnav/visualization/hierarchy_view.py`, `desktop.py`, `spatial_scene.py`: remove stable-room/portal consumers and retain M5 hierarchy display.
- `src/neusymnav/rooms/`, `tools/replay_room_policy.py`, RoomOwner-only tests: delete code made unreachable by the decision.
- `tests/test_room_hierarchy.py`, `tests/test_room_debug_ui.py`, focused runtime/config tests: replace RoomOwner assertions with M5-only and legacy-profile regression coverage.
- `docs/architecture.md`, `docs/implementation-status.md`: record the new source-of-truth and validation limits.

## Tasks

- [x] Add and run failing tests for M5-only hierarchy/object membership and M5 UI projection.
- [x] Remove RoomOwner from hierarchy composition and route Rebuild-profile room nodes/membership exclusively through accepted M5 publication.
- [x] Stop creating the legacy region worker for Rebuild M1–M5 profiles; keep generic region mode for other profiles.
- [x] Remove RoomOwner-only UI, package, replay tool and tests without removing M5 validation or source-oracle tooling.
- [x] Update architecture/status and runner behavior documentation.
- [x] Run focused regression tests, full pytest suite, shell/config checks, and map-profile preflight for each locally available calibrated profile; report gaps where a map profile/assets are unavailable.
