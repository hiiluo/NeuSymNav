# Full Rebuild room pipeline — R0–R7 partial implementation checkpoint (2026-11-02)

This checkpoint tracks the user-authorized implementation of
`rebuild-full-room-pipeline-plan.md`. The adjacent Rebuild and 3DSG workspaces
remain read-only; the one-frame native smoke is recorded under R3 below.

## R0: selected source path and pins

The intended path is `NativeRGBDMappingStage` in Rebuild's
`src/standalone_sg/mapping/native_pipeline.py`: M1 calls
`standalone_sg.geometry.backproject_depth`, then delegates to one persistent
`OctoMapWorker` for native M2 OctoMap and M3 C++ MapConverter. The mapping stage
returns the M3 `FreeSpaceGrid2D`. `SceneGraphBuilder.update(packet)` runs mapping
before the injected region stage; its transaction does not roll back native map
mutation. The existing `OccuSGSession` in the 3DSG handoff owns ordering and
poisons the session on callback failure. The M4/M5 adapter is
`DudeM5RegionStage` in Rebuild `pipeline/stages.py`; it invokes DuDe and the
original `RegionUpdateProcessor` guard/tracker.

| Component | Selected local artifact | SHA-256 |
| --- | --- | --- |
| M1–M3 source | `src/standalone_sg/mapping/native_pipeline.py` | `b7263e6bfcf6156a468bfe35b41c320bc5e3b97277e6188c488c183fe241411b` |
| M2 persistent worker source | `src/standalone_sg/mapping/native.py` | `e103a35b7a59731e6d306e0962434e29b4b91d722a7a5c56e5651fdec938dd3f` |
| M3 projection contract/source | `src/standalone_sg/mapping/projection.py` | `399f9b7443b89efae1a1e80409515e4863b73b8fc7395eb42a0364c37235abd6` |
| M4/M5 stage | `src/standalone_sg/pipeline/stages.py` | `522222ea4a4dc367f5f2f538fcabe4732966934b9b621c9f963e8f88df2f1c63` |
| Builder transaction/order | `src/standalone_sg/pipeline/builder.py` | `47accc1b059b41c6cfc931070fc7be5ecb239a4d351d55c341f97280130a5014` |
| M2/M3 executable | `build/native-m3/occupancy/standalone_sg_octomap_fixture_runner` | `617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6` |
| M4 executable | `build/native-m4-dude/occusg_dude_worker` | `6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693` |
| Rebuild Python closure | 50 `standalone_sg/**/*.py` files (existing source pin) | `60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0` |
| 3DSG session caller | `integration_v2/occusg_session.py` | `d152a7f5af4429bc750f0160a9a226355e0358ad9ce9456208b7a3870926ac15` |
| Habitat RGB-D adapter | `adapters/habitat/frames.py` | `60e5bc8727d903faab1e856162b355f46b091d83b9834891b0eb16237f37a8e2` |

The existing Rebuild reference profile declares axial metric depth, stride 1,
min/max depth 0.1/10 m, 0.05 m occupancy resolution, M2 probabilities
hit/miss 0.7/0.4, clamping 0.12/0.97, threshold 0.5, and M3 minimum free
height/occupancy 0.3 m/5. These are source profile values, not yet proven to be
the exact values of a live caller. The existing M4 local profile is
decomposition threshold 1.5 m, safety distance 0.5 m and 30 s timeout. The
M1–M3 stage constructor defaults to max range 5 m. The RGB-D profile now uses
that value explicitly in packet metadata to avoid an unsupported range change.
This still does not prove parity with an independently verified live caller. No
source alteration is made.

The existing 44-frame `artifacts/m11_two_room_rgbd_sequence` is explicitly
synthetic analytic depth, has no RGB image, uses a scripted pose route, and is
not a live Habitat sequence. It can serve only as a later adapter/replay fixture
after its inputs are verified. A prior 00805 live result in NeuSymNav exercised
M4/M5 on NeuSymNav's accumulated map and does not establish Rebuild M1–M3.

The configured native dependency metadata identifies OctoMap 1.9.7, New BSD.
`locks/sources.json` records the FIST license as limited to non-commercial
internal/academic use, requires prior written consent for modification or
redistribution, and leaves cloud scope unresolved. This implementation remains
local-only; no redistribution permission is inferred. The Rebuild checkout has
its MIT OccuSG license file. No native executable was run during R0.

## R1: contract added

`RoomMapSnapshot` and `RoomPipelinePublication` are now separate public
schema-v1 contracts. The map carries domain/revision, source FrameKey, clock,
calibration, admitted-prefix hash, M2/M3 revisions, worker/source/config pins,
and the exact M3 state raster. Floor/ceiling use finite values only where their
explicit masks are true; unknown cells cannot carry height evidence. The
publication binds M5 regions to the exact accepted map revision while retaining
the newest map independently. It does not convert structural free cells to
robot-clearance proof or use `NavSnapshot` as an alias.

The progress audit found two invalid publication states (accepted M3 revision
ahead of latest, and failure/replay marked fresh). The contract now rejects both,
retains the actual accepted `RoomMapSnapshot` paired with M5, validates its
domain/provenance, and checks each worker response against the admitted frame
and prefix plus worker startup pins/config. R1 remains **implemented and
focused-correctness-verified, but not independently reviewed**. Work proceeded
serially in this main session under the explicit no-subagent instruction.

Focused checks are recorded below for the combined R1/R2 slice. The initial
contract run had a fixture-only failure because the test did not set
floor_valid for the deliberately injected height; the fixture was corrected.
Source-tree aggregate was rechecked at 50 files and the pinned SHA above.
Read-only ldd found the M2/M3 executable loads system C++ runtime libraries;
the M4 worker additionally resolves local OpenCV 4.6, GMP and system
GL/LAPACK/BLAS/TBB. This is dependency visibility, not proof that the workers
execute correctly.

## R2: source-bound RGB-D adapter

RebuildRGBDInputAdapter converts one canonical primary Observation into a
source-neutral M1 wire frame. It preserves full capture ns and clock identity
alongside simulator seconds, FrameKey-derived frame identity, calibration and
pose versions, source geometry hash, ordered prefix hash, canonical axes, K,
pose, RGB, metric axial depth, and a separate valid mask. The profile pins
stride 1, 0.1–10 m depth, 0.05 m M3 resolution and 5 m M2 max range from the
Rebuild reference profile. The frame wire format stores array dtype, shape and
SHA-256; exact serialized byte length is available for later queue accounting.
The adapter rejects duplicate/out-of-order frames, sensor/calibration/clock
changes and certified no-return/far-plane rays, since the selected source M1
path cannot preserve those rays. Invalid depth remains NaN with a false mask.
This is implemented and focused-correctness-verified; no external source import
or native worker is performed by the adapter.

Focused command: PYTHONPATH=src:tests .venv/bin/python -m pytest
tests/test_room_pipeline_contract.py tests/test_rebuild_rgbd_input.py -q →
11 passed, exit 0; git diff --check → exit 0. Initial runs found a malformed
Observation fixture (NaN marked valid) and a no-return fixture that overlapped
valid depth; both test fixtures were corrected to honor the Observation
contract, then the final focused run passed.

## R3: worker/session boundary

`RebuildRoomSession` owns one subprocess and one episode. It admits one
in-flight plus at most two pending frames (32 MiB wire budget), journals
accepted/rejected frames, persists exact wire payloads before native mutation,
and bounds the recording at 8192 frames/2 GiB. It enforces per-response M3
cells (1,000,000), M5 regions (4,096), IPC line size (32 MiB), per-stage
deadlines and a sampled 10 GiB process-tree RSS ceiling. The RSS guard samples
every 50 ms, so this is a sampled ceiling rather than a strict instantaneous
memory limit. A failed request after admission poisons the episode, retains the
last publication as stale, and requires replay in a fresh session. Replays
verify run manifest, source/binary pins, frame bytes and ordered prefix hashes.
Worker shutdown targets and reaps its process group and descendants.

`rebuild_room_worker.py` imports the pinned source closure in an isolated child,
then calls M1/M2/M3 and M4/M5 through the audited source stage classes. M3
values are converted as negative→unknown, zero→free and positive score→occupied
100. This policy is included in the config hash and run profile. It does not
establish robot clearance. Floor/ceiling evidence is retained only where finite
and known.

Focused command:
`PYTHONPATH=src:tests .venv/bin/python -m pytest tests/test_room_pipeline_contract.py tests/test_rebuild_rgbd_input.py tests/test_rebuild_room_session.py -q`
→ 16 passed, exit 0. Session tests use a fake protocol worker. They verify host
admission, persistence, publication, failure and replay behavior, not native
source-stage execution. `PYTHONPATH=src .venv/bin/python -m py_compile
src/neusymnav/regions/rebuild_room_worker.py
src/neusymnav/regions/rebuild_room_session.py
src/neusymnav/regions/rebuild_rgbd_input.py
src/neusymnav/contracts/room_pipeline.py` → exit 0;
`git diff --check` → exit 0.

R3 is **implemented and host-protocol correctness-verified**, but not
fully runtime-validated against native M1–M5. One local synthetic single-frame
smoke did exercise the pinned M1→M2→M3→M4→M5 stages end to end: admitted and
processed 1/1 frame, M2/M3/map revisions all 1, 40 M3 cells, one accepted M5
region bound to map revision 1, non-stale publication, clean shutdown and
`runtime_complete=true`. Sampled process-tree RSS peak was 57,782,272 bytes
against the sampled 10 GiB threshold. The smoke did not use Habitat RGB-D or a
multi-frame/live sequence and is not quality/parity evidence. Its profile,
exact payload, pins and completion manifest are retained in
`runs/rebuild-room-native-smoke-20261102-final/session/`.

There is no cumulative OctoMap
voxel/node-count cap: the inspected source API exposes per-update key counts
but not a bounded cheap aggregate count, and this checkpoint does not claim a
memory cap for internal OctoMap growth. The sampled process RSS guard, M3 cell
cap, recording budget and deadlines limit other resources but do not replace
that missing cap. Source/caller parameter parity, the native empty-episode
path, and source-vs-adapter output parity also remain unproven.

## R4: independent runtime ingress

An optional `workers.room_pipeline` configuration selects the full RGB-D M1–M5
path. It requires an explicit Rebuild source root and executable M2/M3 and M4
paths with SHA-256 values. Launcher preflight verifies the 50-file source
closure and both fixed native binary pins before constructing the runtime lane.
Mapping resolution, range and stride can be declared and are validated by
`RebuildRGBDConfig`; no existing profile enables this option by default.

`Pipeline.submit` offers the primary RGB-D `Observation` directly to an
independent room lane. The lane never accepts NavMapper `NavSnapshot` or room
input tiles. It has one in-flight plus two pending frame references, a 32 MiB
conservative byte budget, and a bounded admission journal in telemetry. A
background thread performs adapter serialization, persistence and worker IPC.
Queue rejections include a reason. `room_pipeline_snapshot()` exposes the
source publication. Room worker startup/frame failures mark only this lane
failed and retain its last map/region pair as stale; the shared control health
remains available. Final shutdown reports the room failure and is incomplete.

The recording directory receives a run-wide covered quota reservation of
2 GiB payload plus 128 MiB metadata before frame admission. The reservation is
released only after clean session shutdown. Cross-check: `docs/implementation-plan.md`
P07 keeps graph scheduling separate from control freshness and deadlines; this
room lane does not extend either.

R4 is **implemented and CPU correctness-verified**, not live-integrated
validated. Tests prove direct Observation admission, bounded drop behavior,
blocked room submission not blocking primary `Pipeline.submit`, depth/control
continuing, and room failure not failing global control health. Config tests
check explicit source/binary declarations and validation. They use a fake room
session; no live launcher run enables this branch. The R3 one-frame native
smoke exercised the underlying session, not this integrated lane or UI.

Focused regression command:
`PYTHONPATH=src:tests .venv/bin/python -m pytest tests/test_runtime_scheduling.py tests/test_rebuild_room_session.py tests/test_rebuild_backend.py tests/test_launcher.py tests/test_runtime_measurement_wiring.py -q`
→ 84 passed, exit 0.

## R5: display and export projection

`DisplaySources.room_pipeline` carries the typed immutable
`RoomPipelinePublication` in the same envelope as its own source age. Publisher
validation checks the room episode, clock/freshness and accepted M3 revision;
it does not equate this map's revision with the control NavSnapshot revision.
The dashboard has separate Control map and Rebuild M3/M5 tabs. M3 colors keep
unknown/free/occupied distinct. Raw M5 source regions draw only when their
accepted map revision matches the displayed latest M3 raster; an older accepted
pair is named in the caption and omitted from that raster. Stale same-generation
outlines use a dashed style. The Latest/Accepted M3 selector can display the
retained raster that exactly pairs with an older accepted M5 output. The profile
selects the Rebuild tab when its actual-profile tag is active. The tab labels M3
domain/revision/source and M5 revision/binding/staleness separately from the
existing Stable Room/region UI.

Final export writes the typed publication to `room-pipeline.json` and includes
its checksum in the normal export manifest, separately from `nav.json` and
`hierarchy.json`. Summary metadata carries latest M3, accepted M3 and M5
revisions. Raw accepted M5 geometry now also enters `HierarchySnapshot` as
separately named `source_region` nodes, with independent M3-domain/revision
provenance and footprint-based membership fields/edges on the existing canonical
object IDs. Stale/replay or floor mismatch makes membership unavailable. This
does not feed M3 into the control-map composer or replace the existing stable
Room/region source. Publisher validates that these hierarchy rows match the
attached `RoomPipelinePublication`. This follows `docs/implementation-plan.md`
P08 atomic source tags and P09 export model.

R5 is **implemented and offscreen/correctness-verified**, not runtime-validated
with the new live room lane. Tests cover typed publication validation, older
M5 generation not being drawn over a newer M3 raster, separate dashboard tabs,
and final contract export/checksum. The focused UI/runtime command
This turn's focused regression set covers contract/session/frame binding, map
retention, UI selector, source hierarchy/object membership and runtime
scheduling; see the updated audit-response report for final combined counts.
No live launcher profile has run with this source.

## Environment and current limits

Host project interpreter: `.venv/bin/python`, Python 3.12.3, NumPy 1.26.4.
The shell `python` command is absent, so commands use `.venv/bin/python`.
This does not establish full native ABI closure, historical caller parity, or
general live sensor readiness. The later bounded smoke establishes one
integrated run on the local host, not R8 acceptance.
R6 runner/profile is implemented: `tools/run_rebuild_rgbd_map_demo.sh` generates
the opt-in `rebuild-rgbd-m1-m5-v1` config, verifies M2/M3, M4 and Python-source
pins, then uses the existing preflight or bounded demo launcher. Shell syntax
and the local 00805 preflight pass; one bounded live M1–M5 episode has run
through this integrated profile. R7 has a bounded three-frame synthetic native parity
harness `tools/compare_rebuild_rgbd_source_oracle.py`; direct source M1–M5 and
the NeuSymNav adapter/session produced equal M3 states, origin, resolution,
revision, height masks/values (atol 1e-7), and M5 persistent IDs/polygons. Report:
`runs/rebuild-rgbd-source-oracle-20261102-final/parity-report.json`.
This is not historical live-caller parity or room-quality evidence. A later
five-frame prefix from a 30-second Habitat recording passed the same direct
source oracle; the integrated smoke and its queue/drop limits are reported in
`docs/results/rebuild-rgbd-live-smoke-2026-11-02.md`. Broader recorded parity,
independent review and R8 acceptance remain open. The runner profile's M2 range
was corrected from 8 m to the source stage default 5 m. Findings from the progress
audit and their dispositions are recorded in
`docs/results/rebuild-rgbd-progress-audit-response-2026-11-02.md`. No model/data download, package installation,
training, source-sibling write, commit or publish occurred in this checkpoint.
