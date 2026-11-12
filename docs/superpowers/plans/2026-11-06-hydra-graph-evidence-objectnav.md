# Hydra Graph, Evidence và ObjectNav độc lập — Implementation Plan A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development hoặc superpowers:executing-plans; thực hiện từng task, không tự commit.

**Goal:** UI bớt place clutter, object gallery có lineage và các module ObjectNav kiểm thử không cần motor.
**Architecture:** Reuse query/picking hiện có; evidence index read-only theo native IDs; ObjectNav tách truy vấn/approach/verification khỏi actuation.
**Tech Stack:** Python/PyQt5/NumPy/SciPy, native Hydra bindings hiện có.
**Spec:** [Thiết kế chung](../specs/2026-11-06-hydra-objectnav-design.md).

## Global Constraints

Áp dụng toàn bộ constraints của roadmap/spec: Kiet_branch2 only, không owner ID thứ hai/GT runtime/automatic merge, source và revision pinned; guard300ms/horizon100ms; không model/download/commit tự động. UI/evidence không đọc ảnh trong control hoặc paint callback.

## Review Focus

Ẩn places không làm mất object do display cap; stale click không hiện ảnh node khác; ảnh latest graph không được giả thành evidence object; repeated frame không tăng vote; graph centroid không là goal navigable. Tasks A1–A4 bên dưới có tests tương ứng.

### A1 — Layer visibility chung và selection đúng

**Modify:** `src/neusymnav/visualization/{spatial_scene,scene_graph,desktop}.py`.
**Create:** `src/neusymnav/visualization/graph_visibility.py`, `tests/test_hydra_layer_visibility.py`.
**Reuse tests:** `test_hydra_spatial_scene.py`, `test_scene_graph_ui.py`, `test_spatial_scene_regressions.py`.
**Interfaces:** immutable `GraphVisibility(preset,visible_layers,place_budget,show_place_labels,show_derived_membership)`; `select_visible_nodes(graph,policy,selected_id)->VisibleGraph`; `set_graph_visibility(policy)` cho cả2view. `VisibleGraph` giữ visible IDs/edges và counts raw/filtered/budget-hidden; không canonical mutation.

- [ ] RED tests: Rooms+Objects ẩnL3, Topology/All toggle; rooms/objects vẫn hiện khi200+places đứng trước trong array; filter không đổi query/graph; hidden node không pick; selection và orbit giữ qua repaint; floor cloud không bị tắt bởi place filter.
- [ ] Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_hydra_layer_visibility.py -q`; xác nhận thất bại đúng chức năng thiếu.
- [ ] Implement spec defaults: room/object ưu tiên, place nhỏ/labelsOFF, budget200 khi bật; native edges chỉ khi endpoints visible. Derived membership nếu bật có kind/style riêng và parent-chain tooltip; unassigned không tự nối.
- [ ] GREEN cùng command + existing UI regressions ở trên. Native smoke30s có screenshot/preset counters/picking proof trong `runs/hydra-objectnav/A1/`; không cần5%performance để thông qua UI.

### A2 — Native support probe và evidence contracts/index

**Modify:** `src/neusymnav/backends/hydra/{worker,runtime,session,query}.py`; shared contract changes do main.
**Create:** `src/neusymnav/contracts/hydra_evidence.py`, `src/neusymnav/backends/hydra/evidence.py`, `src/neusymnav/verification/hydra_best_views.py`, `tools/probe_hydra_object_support.py`, `tests/test_hydra_object_evidence.py`.
**Interfaces:** `HydraObjectKey(episode_id,run_id,native_id,graph_revision)`; immutable `ObservationEvidence` theo spec; `HydraEvidenceIndex.resolve(key,limit=64,cursor=None)->EvidencePage`, `EvidencePage(status,refs,next_cursor,reasons)`; runtime query có `evidence(key)` đọc một frozen generation. Observation asset key độc lập revision; AssociationLink key bao gồm current object revision+observation key+method/transform hashes. Assets có thể reuse, links phải revalidate theo current native support/pose. Old links chỉ historical đúngrevision, không transfer IDs khi chưa có actual native lineage. v1 per-object None/verifiedNone giữ nguyên; v2 evidence page cho candidate-debug, không được claim native-confirmed từ frame ACK.

- [ ] Probe graph artifact hiện có: binding `mesh_connections`, bbox/support và pose-correction/mesh-index stability. Lưu capability/source/build/hash/units trong `runs/hydra-objectnav/A2/capabilities.json`. Không rebuild binding hoặc tải dependency ngầm; thiếu support ghi giới hạn và candidate-only route.
- [ ] RED fixtures:2sinks cạnh nhau;2detection cùngframe vào1node;1detection vào2node; identical category nhưng khác3D; occluded points; wrong calibration/clock/episode; graph optimization thay pose; queued/rejected input; duplicate/replay; quotaeviction; node removed/reparented; revisioncarry-forward phải revalidate và unchanged asset không tự thành unchanged association; old run thiếu batch phải not_recorded. Không cùngclass/nearestcentroid-only links.
- [ ] Run `.venv/bin/python -m pytest tests/test_hydra_object_evidence.py -q`; record RED.
- [ ] Persist bounded detection/mask/source sidecar at offer; commit integrated refs sau native processed ACK/prefix. Sidecar geometry support có hash/size, không nhét full mesh vào UI transport. Chọn geometry/depth/mask consistency, preserve ambiguous links; native-confirmed chỉ khi có actual native lineage, không dựa vào matching heuristic. Mọi geometric link phải xuất score components và method, không confidence xác suất.
- [ ] Gallery index top3 đa góc, baseline.3m, paginated other refs; cache32MiB decoded/64MiB index, durable256MiB trong quota. Không reread toànjournal mỗipaint. Missing/evicted/corrupt refs có trạng thái riêng, path/hash validation chống đọc ngoài run root.
- [ ] GREEN command + `tests/test_hydra_scene_graph_query.py tests/test_hydra_query_wiring.py tests/test_hydra_session.py`; replay/export/reopen giữ exact key/evidence provenance. Native pilot ít nhất1object có crop/fullframe/mask/source thật và candidate-linkmethod hiện rõ; gate này chứng minh candidate-debug gallery, chưa chứng minh native identity association. Native-confirmed gate chỉ mở khi có explicit native lineage. Same-class pair nếu available. Thiếu cặp annotated thì ghi unsupported association accuracy, không suy từ fixture.

### A3 — Click gallery và association audit

**Modify:** `src/neusymnav/visualization/{desktop,spatial_scene,hydra_assets,publisher}.py` (main giữ publisher schema).
**Create:** `src/neusymnav/visualization/object_evidence.py`, `tests/test_hydra_evidence_gallery.py`, `tools/audit_hydra_association.py`.
**Interfaces:** `AsyncObjectEvidenceReader.offer(key,refs)->None`, `snapshot()->EvidenceGallery|None`, `close(timeout_s)->Report`; gallery carries exact object key/request generation and asset hashes; desktop renders only matching current selection.

- [ ] RED: clickA rồiB khiAloadchậm; selectionoutlivesgraphrevision/removal; missing/corrupt image; mask/bbox alignment; no evidence; candidate/ambiguous tooltip; hidden place cannot steal object click. Run offscreen `tests/test_hydra_evidence_gallery.py`.
- [ ] Implement asyncgallery: crop+mask, fullframe, top3 thumbnails + other observations, source/detection/node/revision/status. Highlight selected3D support; no latest-camera substitution. Selection tới native missing node phải show removed/stale, không nearest-ID fallback.
- [ ] Add review export schema `AssociationReview(object_key,evidence_ref,verdict,annotator,annotation_version)`; no native graph mutation. Import annotated observations only offline into existing association/tracking metrics; manual inspection notes không tự là benchmark GT.
- [ ] GREEN gallery/query tests; nativeUI smoke selecting nhiềuobject và resize/orbit/filters. Save evidence screenshots + at least correct pair and suspected merge/split cases if present; absent case logged, no fabricated native example.

### A4 — ObjectNav pure modules và query semantics

**Create:** `src/neusymnav/objectnav/{__init__,candidates,approach,verification,policy}.py`, `src/neusymnav/contracts/objectnav.py`, `tests/test_objectnav_candidates.py`, `tests/test_objectnav_approach.py`, `tests/test_objectnav_verification.py`.
**Modify:** `src/neusymnav/backends/hydra/query.py` chỉ additive/versioned API qua main; không đổi Navigator trong task này.
**Interfaces:** `query_candidates(query,category)->CandidateSet`; `propose_approaches(candidate,context: ObjectNavContext,robot,config,now_ns)->ApproachSet`; `verify_target(request,observation,batch,evidence)->VerificationResult`; `ObjectNavPolicy.step(goal,inputs)->ObjectNavIntent`. Contracts main khóa trước khi workers bắt đầu.
`ObjectNavIntent` là `SEARCH|APPROACH_PROPOSED|VERIFY_PENDING|VERIFIED|REJECTED|UNAVAILABLE`, chứa source/revision/reason; chưa là MotionCommand. `VERIFIED` là visual confirmation, không episode-success. Bản đầu category goal; native task success distance/visibility protocol chỉ chốt tại live integration gate. Proposed candidate position/membership không đồng nghĩa navigable/verified.
`ObjectNavContext` giữ run/episode/clock, NavSnapshot và SpatialFrameBinding(extrinsic/calibration registry/graph→nav world correction/floor datum). Primary/nav calibration hashes không cần bằng nhau; binding phải hợp lệ. Historical candidate chỉ SEARCH_PRIOR, graph.last_source không là per-object last_seen. Approach yêu cầu graphavailable/notreplay, fresh unique geometric target observation≤2s, nav≤300ms, observation.capture≤nav.capture≤now; transform known, cùng run/episode/clock, targetXYZ từ observation đã transform. Unknownage/ambiguity/missingbinding không commit target. Pure clocks explicit và không nới motor300ms/100ms.

- [ ] RED: unknowncategory, taxonomy aliases, sameclassmultipleobjects, ambiguous evidence, removednode/revisionmismatch; goalcentroidoccupied nhưng có free approach; no free/support means unavailable; stale nav; sameepisode butforeignrun; mismatchedclock; validcrosssensorcalibration versus missingframebinding; graphfresh nhưng objectold; oldgraphSEARCH_PRIOR; loopclosurecorrectionmissing; futuretargetobservation; roomedge không là passage. Verification requires fresh observed RGB-D and pinned candidate, stale/gallery-only evidence cannot succeed. Partial/failed/topK-saturated/occluded/invaliddepth batches không tạo negative vote; completeempty cũng cần visibility support trước khi reject.
- [ ] Run `.venv/bin/python -m pytest tests/test_objectnav_candidates.py tests/test_objectnav_approach.py tests/test_objectnav_verification.py -q`; record RED.
- [ ] Implement deterministic candidates, configurable approach ring initially.5–1.5m with footprint checks and yaw toward target; respect available geometry/unknown. Reuse existing verification policy where contracts match, declare uncalibrated scores. SLM room label optional prior OFF; no SLM in control. Replay outputs intents only, never real actuator calls.
- [ ] GREEN + fixtures of target removal/ambiguity/false confirmation; frozen recorded-query replay report. Live adapter remains separate gate after C safety review, fresh guard recheck and target success protocol; query/replay pass không hoàn thành ObjectNavE2E.

## Handoff

A1 có thể hoàn tất trướcA2; A3 phụ thuộc evidence contract/lineage củaA2. A4 candidate/approach fixtures có thể làm song songA3 sau khi contract khóa, verification integration chờA2. Mỗi task ghi commands/exit/artifacts/remaining; không tự commit. Freshness5% không gate các pure/UI tasks.
