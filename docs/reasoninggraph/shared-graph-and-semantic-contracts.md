# Hợp đồng Shared Graph và Semantic Evidence

Đây là contract đề xuất M1. Các kiểu đã có được dẫn đúng tên để tái sử dụng. Type mới thuộc `src/neusymnav/contracts/reasoninggraph.py` khi bắt đầu triển khai. [Audit](current-system-audit.md), [thiết kế](integration-design.md), [roadmap](implementation-plan.md).

## Khóa, owner và publication

| Record | Trường tối thiểu | Owner và quy tắc |
| --- | --- | --- |
| `GraphReadToken` | schema version, run/episode, graph epoch, native revision/prefix SHA, sidecar revision, calibration/coordinate/vocabulary/build pins | Publisher cấp snapshot immutable. Pinned reader nhìn thấy đúng graph và sidecar của token, kể cả khi bản mới đang được cập nhật. |
| `CanonicalObjectId` | episode + graph epoch + native ID + generation | Authority lifecycle Hydra phát qua một adapter duy nhất. `HydraObjectKey` hiện có vẫn là snapshot address chứa revision. Generation ngăn reuse của raw native ID. |
| `RoomRef` | scope, geometry region ID/generation, membership/pose revision | Hydra topology owner cấp. Nhãn room VLM hoặc room embedding gắn như attribute. |
| `GraphLifecycleDelta` | previous/next token, create/update/merge/delete, aliases/tombstones, changed pose/membership/region, proof/reason | Native lifecycle adapter ghi ordered batch và consume idempotently. Revision thiếu hoặc reset namespace khiến view invalidated cho đến khi rebase. |
| `NativeLink` | evidence ID, revision-scoped Hydra key, resolved canonical ID nullable, method/policy version, status, support, competing endpoints, lineage hash optional | Linker giữ bằng chứng. Tái dùng `HydraEvidenceIndex` làm read-page cho debug. Scale/score của matcher ghi kèm version, giữ riêng calibration xác suất. |
| `PaperCandidateLink` | paper CID và generation/alias state của `CandidateMemory`, shared graph token, evidence intersection, link status | Bridge read-only theo episode. CID là handle điều khiển cục bộ. Consumer yêu cầu duy nhất cả hai phía, cùng frame/detection và đối chiếu geometry. Không phát alias graph từ CID. |

Từ code hiện tại, `HydraGraphRuntime.scene_graph_query()` tạo query theo một projection mỗi lần, `HydraEvidenceIndex` tra theo revision và frame được Hydra xử lý chưa chứng minh liên kết per-instance. Trước khi pin ID qua nhiều revision, M1 phải kiểm native ID lifetime, reuse và merge lineage tại build được chọn. Khi thiếu proof, xem view theo từng revision, hạ status `unavailable` cho incremental consumer và chỉ đánh giá retrieval một snapshot. Stable continuity chỉ được giữ khi có contract native đã kiểm, merge chỉ theo explicit old→new lineage. Các tuple ambiguous, disappearance và cùng class/IoU không đủ để suy merge. Nếu native merge event cần thêm dữ liệu, bổ sung export có phiên bản vào adapter/binding sau khi xác minh upstream hooks, giữ schema native hiện có. [Query](../../src/neusymnav/backends/hydra/query.py), [index](../../src/neusymnav/contracts/hydra_evidence.py), [paper CID](../../src/neusymnav/objectnav/b0/memory.py).

## Shared observation evidence

`EvidenceId = (FrameKey, detector_profile_hash, detection_id)`, với `FrameKey = (episode_id, sensor_id, frame_index)`. `ObservationRef` ghi camera pose `T_world_camera`, pose_version, K/calibration ID+hash, capture monotonic timestamp và clock domain, sim time nếu có, coordinate/camera/depth conventions, geometry hash. `DetectionEvidence` ghi bbox XYXY exclusive, mask và crop refs content-addressed, raw label, raw detector confidence, category score vector kèm ordered vocabulary và score type nếu detector cung cấp, valid-depth support (số pixel, observed 3D bounds và visibility status), optional feature refs. Gắn association/link confidence, method và status vào `NativeLink` để observation vẫn immutable khi graph đổi. Scope encoder, detector, prompt recipe và provenance được pin bằng phiên bản/hashes. Tái dùng `Observation`, `DetectionBatch`, `ObservationEvidence` và validators. [Observation contracts](../../src/neusymnav/contracts/observations.py), [Hydra evidence](../../src/neusymnav/contracts/hydra_evidence.py).

| Value | Kiểu và ý nghĩa | Quy tắc |
| --- | --- | --- |
| Detector confidence / category scores | Raw scalar / vector có taxonomy+dạng logits, similarity hoặc score gốc | Giữ nguyên output detector, missing optional. |
| Object, text, room embedding | Vector theo `FeatureSpec` | Dùng cosine giữa image/text đã pin cùng feature space. Room giữ nhiều centroid. |
| Relationship embedding | Structured visual-token payload với `RelFeatureSpec` | Chỉ decoder tương thích mới decode. Kèm endpoint order, marker scheme và layout. |
| Geometric predicate | Kết quả phép kiểm hình học theo geometry revision | Đọc song song với visual evidence, ghi rõ tolerance/source. |
| Explicit relationship label | Verdict theo câu hỏi và đối tượng, có polarity/status và provenance | Kết quả query theo snapshot/prompt, có thể `insufficient_evidence`. |
| Category distribution | Categorical probability theo vocabulary, calibrated provenance | Reserved extension của PSG-Nav, chưa cần field vật lý. |
| Fused semantic confidence | Score/uncertainty của future consumer, model/calibrator provenance | Owner riêng, giá trị không đi ngược vào raw evidence hay CLIP mean. |
| Verification status | `match / mismatch / inconclusive / unavailable`, target, pose, evidence IDs, verifier revision | Verifier owner. HIT của retrieval không tự cấp verdict hoặc STOP. |

`FeatureSpec` ghi checkpoint/code/preprocess/tokenizer hashes, dimensions, dtype, normalization, modality, feature-space ID, fusion recipe/weights version, metric. Định danh `RelFeatureSpec` bổ sung encoder checkpoint, layer/cut point, tile layout/spatial crop, token count/dimension, dtype/endianness, decoder checkpoint, tokenizer và template. Dùng `FeatureRef` cho codec, byte count, checksum và relative key. Feature pipeline từ chối version/shape/finite/checksum lệch, tránh average tensors khác token layout hoặc khác order. `RelationKey = (subject, object, rel_feature_spec, marker_scheme)`. Co-visibility là điều kiện tạo evidence, còn verdict về `left_of`, `blocking` hoặc `on` là output riêng.

## Dedup, retention và phục hồi

- Per object, count và accumulator cập nhật theo event ID duy nhất có recipe hash. Per room, observation là một full-frame event. Per edge, observation là cặp endpoint/detection đã sắp thứ tự trong cùng frame và cùng spec. Watermark chỉ đóng prefix có cutoff explicit. Retry trong cửa sổ sử dụng key/event set. Event đã rơi dưới watermark bị từ chối cho cùng epoch dù asset đã xóa. Replays ngoài cửa sổ ghi phiên build mới. Merge dedup theo evidence set hoặc exact source disjointness, tránh cộng mù sufficient statistics có overlap.
- Giữ pending jobs theo item/byte/age cap, các asset cần debug theo TTL và quota episode, representative views theo quota từng object/room/edge. Vectors dùng sum/count có dtype tích lũy được pin. Room split/reassignment và selective edge replay có thể cần feature samples. Khi thiếu sample do eviction, đánh dấu incomplete và rebuild từ journal/offline hoặc tạo generation mới theo native delta. Evidence links cũng cần quota cho tombstones và `HydraEvidenceIndex._evicted`. Historical provenance đủ để biết mất phần nào, dù visual blob đã bị dọn.
- Writer transaction gồm feature manifest + aliases + endpoint validity + watermark. Bao phủ số lượng, shape, checksums và native graph hash/prefix trước khi rename manifest atomically. Reader sau restart chỉ mở manifest đã publish, kiểm scope/schema/hash/links và bỏ pending dở. Alias cycle, self edge, orphan, duplicate revision hoặc path vượt root khiến semantic snapshot unavailable. Schema version chưa hiểu trả unavailable và vẫn đọc được native graph độc lập.
- Dùng open/close theo episode và graph epoch. Khi pose đổi, giữ evidence nguồn bất biến, dựng lại derived room assignment và predicates bằng corrected poses có proof. Nếu loop closure không báo pose mapping, invalidate affected projections và assignment trước khi phục vụ query. Native relation visual tokens giữ camera provenance, còn graph endpoint mapping luôn theo revision hiện hành.
- Dedup future writes theo producer + evidence ID + update recipe + destination. Verification feedback, belief, retrieval score và source detector giữ các lineage IDs khác loại. Belief/LLM output không tái nhập evidence YOLOE. Semantic GT, evaluator verdict và điểm episode chỉ xuất hiện trong đánh giá offline.

## Query và feedback

```text
open_view(expected_scope, min_revision=None) -> view | unavailable
query_objects(view, text, scope, top_k) -> ranked canonical targets + provenance
query_rooms(view, text, top_k) -> ranked room references + coverage
query_relationships(view, subject, object, max_refs) -> evidence page + support
retrieve_subgraph(view, seeds, edge_kinds, limits) -> bounded IDs + evidence refs
evaluate_relation(view, pair, question, deadline) -> request_id | unavailable
poll(request_id, expected_token) -> verdict + evidence_ids + reasons | pending
```

Result statuses `available, empty, ambiguous, insufficient_evidence, stale, evicted, unavailable`. Score đi kèm metric/feature space. Request/poll dùng snapshot pin, reply late bị revalidate scope, deadline, request ID, endpoint generation và allowed IDs. Navigation chỉ đọc cached result không chặn vòng control. `GoalHint` ở M7 chỉ chứa canonical ID, linked CID, revision, priority và evidence refs. Điểm tiếp cận, path cost, guarded action và STOP thuộc existing policy/planner/verifier. L3–L7 extension dùng view và message version riêng sau khi có consumer thực tế. [Trách nhiệm tương lai](future-module-integration-roadmap.md).
