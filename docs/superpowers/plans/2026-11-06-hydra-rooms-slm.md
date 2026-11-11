# Room geometry và text-SLM labels — Implementation Plan B

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development hoặc superpowers:executing-plans; implement từng task, không tự commit.

**Goal:** Có bằng chứng room segmentation và room labels riêng; SLM suy từ object/quan hệ dạng text như người dùng đã chọn.
**Architecture:** Native Hydra giữ geometry/IDs; evaluator offline đo observed support; room-semantic overlay không sửa topology.
**Tech Stack:** Python/NumPy/SciPy, existing Hydra export, SLM adapter backend-agnostic.
**Spec:** [Thiết kế chung](../specs/2026-11-06-hydra-objectnav-design.md).

## Global Constraints

Kiet_branch2 only; constraints roadmap/spec áp dụng. GT chỉ evaluator. Không rename geometry ID theo label; SLM không split/merge room. No model download/training trong plan hoặc triển khai khi chưa có authorization/asset.

## Review Focus

1room trên map không là segmentation success; same-label rooms vẫn là2instances; open-plan ambiguity có annotation riêng; stale SLM reply không gắn roomrevisionmới; repeated objects không tăng count/confidence. Tests B1/B2/B3 phải cover.

### B1 — Room export và quality baseline

**Modify:** `src/neusymnav/backends/hydra/{worker,graph_adapter}.py` qua main schema; `src/neusymnav/evaluation/gt_isolation.py` nếu cần guard import.
**Create:** `src/neusymnav/evaluation/room_quality.py`, `tools/evaluate_hydra_rooms.py`, `tests/test_hydra_room_quality.py`, `tests/test_room_gt_isolation.py`.
**Interfaces:** `RoomSupportSnapshot(episode_id,run_id,graph_revision,frame_convention,observed_support,support_domain,room_assignments,unassigned,source_hashes)`; `evaluate_room_geometry(pred,annotation,protocol)->RoomQualityReport`.

- [ ] Audit existing data/roomannotations/available scenes, actual native places→rooms/support/mesh and transform. Freeze offline protocol/annotation manifest before tuning; report noGT/onlyoneobservedroom as unsupported separation evidence.
- [ ] RED:2rooms/narrowopenpassage; same semanticlabel; allmergedprediction; oversplit; partialobservedfloor; disconnected/unassigned places; labelpermutation/nativeIDchurn; graphloopcorrection. Runtime import ofsemanticGT must fail isolation test.
- [ ] Run `.venv/bin/python -m pytest tests/test_hydra_room_quality.py tests/test_room_gt_isolation.py -q`; record RED.
- [ ] Export actual native support/membership; never manufacture Voronoi partitions as nativegeometry. Compute observed-support room IoU with matching, merge/split, boundaryF1(.20m plus.10/.30 sensitivity), temporal geometry consistency and ID churn separately. Cả place_points và surface_points: báo ARI/pairwiseF1/purity trên annotated points (pointIoU có tên/domain rõ nếu dùng); areaIoU/boundary unavailable. Chỉ floor_cells với GT/support tương ứng mới chấm areaIoU/boundaryF1; không nội suy nearestcentroid thành boundary để chấm. Unsupported domain/GT means typed unavailable, not0/1accuracy.
- [ ] GREEN + existing gt isolation/geometry tests. Run evaluator on frozen recordings from at most2existing scenes; publish overlays/failurecases/coverage/supportcounts/annotationversion. Human room outlines remain evaluator-only, not fed to runtime.
- [ ] If baseline shows merged rooms, diagnose observed coverage, place clearance, roomfinder input and config(.5/1.2m dilation,PLATEAU,minsize10) BEFORE parameter changes. A follow-up tuning patch gets separate config hash, same frozen evaluation and held-out run; do not select from repeated live runs or claim SLM repairs geometry. No accuracy promotion until quality targets/support are reviewed from baseline.

### B2 — Room context và SLM contract (không cần model thật)

**Create:** `src/neusymnav/rooms/{__init__,context,labels}.py`, `src/neusymnav/contracts/room_semantics.py`, `tests/test_room_context.py`, `tests/test_room_label_contract.py`.
**Interfaces:** `build_room_context(query,evidence,room_support,room_id)->RoomContext`; `RoomLabelBackend.infer(context)->RoomLabelProposal`; `validate_room_label(proposal,context)->RoomLabelResult`. Spec định nghĩa output keys, vocabulary, provenance; contracts versioned do main.

- [ ] RED: count uniqueobjectIDs, duplicateframes, ambiguousmembership, sameclassmergednode flagged, absentgeometry, memberschangingwhilesameRoomID, invalid/unknownsupportingIDs, free-formbadJSON, prompt-like rawlabels, lowevidence, oldreplyafterroomsplit/merge.
- [ ] Run `.venv/bin/python -m pytest tests/test_room_context.py tests/test_room_label_contract.py -q`; record RED.
- [ ] Implement boundedcontext ≤64distinctobjects plus truncation/totalcount; canonical vocabulary only, rawtext treated data. Include membership/association/geometry status and hashes. Never inherit geometryconfirmed from inferred label. Stub backend emits deterministic JSON for tests, not measured SLM quality.
- [ ] GREEN; room-label mutation must leave native room/object IDs, membership and geometric assignments byte-identical. Newgeometry/contextinvalidatesoldresult; native lineage unavailable means no invented split/merge identity.

### B3 — SLM worker, room UI và label evaluation

**Create:** `src/neusymnav/rooms/{worker,service}.py`, `tools/evaluate_room_labels.py`, `tests/test_room_label_worker.py`.
**Modify:** `visualization/{desktop,publisher}.py` via main owner for overlay/status.
**Interfaces:** `RoomLabelService.offer(context)->bool`, `snapshot(room_key)->RoomLabelResult|None`, `close(timeout_s)->Report`; immutable publication `RoomLabelPublication` pinned source/context/model/geometryrevision.

- [ ] Inventory available small text models/license/runtime/quantization/memory. Pin model+prompt+schema hashes and inference settings before real test. If absent, stop model-specific execution as unavailable; continue stub/context/UI/offline protocol, no auto-download. Model selection is still open, not implicitly approved.
- [ ] RED boundedqueue32/1inflight, contextcache hit, debounce3s,5stimeout, crash, malformedJSON, stale reply, scene reset, room removal, duplicate vote. Request budget/preemption must not block capture/control.
- [ ] Implement separate low-priority worker (pilot1CPUthread, measured memory cap), provenance/cache by content+model+prompt; unknown/insufficient_evidence valid output. Stable labels require2consistent proposals from distinct context hashes; conflicts show tentative/disputed. Self-confidence is not calibrated.
- [ ] UI shows roomgeometry ID + inferredlabel/status + supportingobjects/source/geometryrevision/model. Clickroom highlights membership/support when available; missing geometry visibly unavailable. Keep manual roomGT annotations out of SLMinput.
- [ ] GREEN worker/context tests, native graph/control delay fixtures unchanged. Offline label evaluation with frozen annotatedrooms: macroF1/confusion, abstentioncoverage/selectiveaccuracy; geometry error rate and labelaccuracy separate. So sánh baseline luật và SLM trên cùng predictedcontext; stratify geometry-correct rooms và end-to-end để không giấu segmentationerror. Report pilot/unsupported for insufficientclasses/rooms; no benchmark claim from stub or onebathroom.

## Handoff

B1 không đợi SLM. B2 cần A query và versioned evidence status, có thể dùng fixtures. B3 model pilot chờ asset/budget; no model does not block A/C. Geometry tuning only after B1 evidence; no semantic model promotion to geometry owner.
