# Kế hoạch Native Hydra Attribute and Query API Enhancement

> **Dành cho phiên triển khai:** dùng `superpowers:executing-plans` hoặc `superpowers:subagent-driven-development` theo phương thức đã được giao. Các checkbox là việc dự kiến.

**Mục tiêu.** Mở rộng đường đọc Hydra native hiện có để object, room, place và topology có thể truy vấn theo đúng revision, với hình học, semantics và evidence tải theo nhu cầu.

**Kiến trúc.** Giữ summary nhỏ, mở rộng `HydraSceneGraphQuery` và nối nguồn chi tiết bị giới hạn. Dùng semantic sidecar trên native IDs cho dữ liệu ReasoningGraph. Chỉ cân nhắc hook native nếu cần tín hiệu do Hydra sở hữu mà binding chưa cung cấp.

**Nền tảng.** Hydra 2.0.0 tại `2e58a35baea629eee8838409771876acff015daf`, Spark-DSG 1.1.3 tại `3c40997e4ae739c56ed3cdd6ef5e882d403d8b64`, pybind11 và Python worker tách process.

**Spec.** [Ma trận thuộc tính và bằng chứng](../../reasoninggraph/native-hydra-attribute-audit.md), [shared graph contracts](../../reasoninggraph/shared-graph-and-semantic-contracts.md).

## Vị trí và phạm vi

Milestone **HNA** là gate bắt buộc giữa M0 và M1 trong [roadmap ReasoningGraph](../../reasoninggraph/implementation-plan.md). Audit đã hoàn thành ở mức source và persisted graph. Xem checkpoint ngay dưới đây để phân biệt code đã triển khai và phạm vi runtime đã xác minh. M0 có thể chốt baseline và chạy replay độc lập. HNA chỉ đọc native graph hiện tại. M1 tiếp tục chịu trách nhiệm observation→object linking, canonical continuity và lifecycle cần cho semantic fusion. HNA có quyền trả `not_recorded` và `unavailable` theo capability. Điều này cho phép giữ đúng contract khi native feature và classifier probability rỗng. Để mở M2–M5, vẫn cần qua gate evidence/lifecycle của M1.

Giữ native identity và topology authority. Không thêm owner cấp object ID. Không đổi Hydra/Spark ABI, room label default, association, planner hoặc policy trong milestone này. Graph key gồm run/episode/epoch, native graph revision/prefix và native node ID/layer. `HydraObjectKey` và `HydraSceneGraphQuery.get()` giữ compatibility. Geometry refs thêm mesh generation và digest gắn với đúng byte asset. Tất cả trạng thái kiểm thử được ghi riêng theo synthetic, persisted native graph hoặc live replay.

## Bàn giao triển khai HNA

- Snapshot v1 giữ nguyên wire schema. `HydraReadToken` và `NativeNodeRef` cấp khóa đọc theo revision. Các method cũ vẫn dùng được và đánh dấu candidate stale khi live graph tiến.
- `SavedHydraDetailReader` đọc manifest và bytes đã xác minh, giữ một graph resident. Kênh live detail opt-in có hai anonymous pipes riêng. Mỗi session giữ một request đang xử lý, hai pending, tối đa 64 cached results và deadline 2 giây. Worker dùng lại graph clone của snapshot, giữ tối đa graph hiện tại và graph đang đọc khi hai việc trùng thời điểm. Mỗi mesh được giữ tối đa 64 MiB. Asset cache giới hạn 8 MiB hoặc 128 blobs, mỗi blob tối đa 1 MiB. Store binary chỉ giữ những trang đã yêu cầu.
- Bật thử nghiệm bằng `scene_graph.hydra.detail_queries=true`. Từ `Pipeline.scene_graph_query()`, gọi `node_ref(native_id)`, sau đó gọi `place_detail()`, `geometry()`, `features()` hoặc `edge_detail()`. Trong kênh live, `pending` nghĩa là có thể poll lại bằng cùng query và request. `stale` nghĩa là phải lấy query mới. `read_asset()` thực hiện I/O rõ ràng cho nhánh đọc chuyên dụng khi cần bytes. Rollback bằng tắt cờ opt-in.
- Topology trả kết cấu graph và dùng `edge_detail()` để lấy weight native theo yêu cầu. Weight chưa xác minh producer mang kind `native_untyped`. Subgraph trả một tập có giới hạn node/edge/hop và cờ truncation. Các list queries dùng cursor theo scope. Room label đi qua `RoomLabelDebugService.scene_graph_query()` trong tiến trình sở hữu nhãn. Planner core tiếp tục đọc snapshot độc lập với service UI.
- Native CPU replay và saved exports đã có [kết quả nghiệm thu](../../implementation-status.md#native-hydra-attribute-and-query-api-enhancement--triển-khai-2026-11-26). [Nghiệm thu Habitat live tại 00806](../../implementation-status.md#nghiệm-thu-hna-trên-habitat-live--2026-11-26) đã xác nhận chức năng và cách ly timeout. Ngưỡng p95 live và chứng nhận P10 còn mở. Feature producers ReasoningGraph và M1 identity/lineage có gate riêng.

## Quyết định tích hợp

| Phương án | Khi dùng | Quyết định |
| --- | --- | --- |
| Đọc native attributes qua binding và projection | Geometry, flags, measured native topology đã có producer. Giao diện đọc immutable và schema-versioned. | Dùng mặc định cho milestone. Dùng lại một graph clone của revision đã chọn. |
| Native attribute update hook | Cần writer bên trong pipeline, ví dụ xuất explicit mesh remap hoặc merge lineage. Muốn native graph làm owner của semantic write phải có API lock/transaction, schema và persistence tests. | Chỉ đánh giá ở HNA. Track riêng khi M1 xác định tín hiệu thiếu và có native hook đã chứng minh. Mutation trên `HydraPipeline.graph` chỉ sửa clone, không phải native update API. |
| Versioned semantic sidecar | Model provenance, object/room embeddings, relation tokens, retrieval/evidence và probability của future owner. | Dùng cho ReasoningGraph. Key theo native ID + generation + revision, chịu invalidation cùng graph. Semantic output chỉ ghi qua owner của sidecar. |

Các trạng thái cần phân biệt gồm `available`, `missing`, `not_recorded`, `ambiguous`, `stale`, `evicted`, `corrupt`, `unavailable`. Giá trị default zero/false và namespace chưa có producer được trả kèm validity/provenance. HNA không coi native feature rỗng là một vector hợp lệ. `registered` và `world_R_object` chỉ được thêm công khai khi có producer cùng consumer cụ thể. Metadata dùng allowlist, schema/byte cap và validator riêng khi có consumer, tránh chuyển toàn bộ metadata tùy ý.

## Ba cấp đọc và ngân sách

| Cấp | Nội dung | Chiến lược vận hành |
| --- | --- | --- |
| 1. Lightweight snapshot | Summary v1 giữ tương thích. Node IDs, layer, position, label, parent, envelope object và structural edges. Nếu thêm scalar fields sau đo, dùng capability/schema opt-in. | Giữ cadence và caps hiện tại. Chuyển schema theo negotiation. Client cũ đọc v1. Tái dùng `state_token()` để tránh deepcopy lặp lại. |
| 2. On-demand semantic / topology | Typed attribute details, feature descriptors/ref, room label publication và adjacency, bounded neighborhood/subgraph. | Tính topology từ immutable summary nếu đủ. Detail chỉ chạy theo query batch và budget ở graph lane. Model tensor tải lazy bằng ref, chỉ công bố khi spec/checksum hợp lệ. |
| 3. On-demand geometry / evidence | Native bounding box đầy đủ, object mesh support, room geometry support, evidence pages và asset refs. | Đọc graph asset cùng revision trong tiến trình reader. Lượt live có thể ghi asset chọn lọc từ clone đang dùng dưới budget. Geometry binary header chứa codec, dtype, shape, size, checksum và revision/mesh generation. Trả trạng thái rõ khi không còn revision. |

Các output lớn không đi qua frame JSON. Gợi ý pilot cần chốt ở M0/HNA-04 là 64 items/page, tối đa 1 request in flight và 2 pending cho detail, 2 retained revision handles và 128 MiB aggregate decoded cache. Giới hạn cả byte, age, node/edge count và request deadlines trước deserialize. Giữ caps frame snapshot 16 MiB và worker line 32 MiB. Cache key gồm run, episode, epoch, revision, prefix, build và asset hash. Cursor opaque hoặc signed digest bind với full key, filter, ordering và page size. Lease readers bounded và expire. Khi release, restart hoặc eviction, caller có thể nhận status và xin snapshot mới. Serving read history yêu cầu opt-in và gắn cờ historical, không trả lịch sử như dữ liệu live.

Worker hiện dùng một request/response loop cho frame. Bước đầu reuse saved graph để phục vụ tests và offline query. Lượt live chỉ enqueue việc chọn asset từ cùng clone ở safe boundary, chấp nhận skip khi backlog. Không đặt decode, mesh streaming hoặc I/O nặng vào `HydraSession._run` đường frame. Mọi extraction trên native clone phải hữu hạn, đo được và có cách bỏ qua khi budget không đủ. Planner chỉ đọc bản in-memory đã publish. `usable_for_targeting` giữ điều kiện hiện hành và không cấp chứng nhận traversability.

## So sánh revision và room identity

- Object address dùng native IDs theo snapshot. Không tái sử dụng `HydraObjectKey` mới thay cho key cũ dựa vào trùng tên hay hình học. M1 thêm persistent lineage proof như merge aliases. Nếu thiếu proof, node view scope chỉ là revision hiện hành.
- RoomFinder xây clusters và cấp lại IDs theo thứ tự của oldest place. `R(0)` vẫn có thể biểu diễn room khác sau split/merge. `RoomGenerationKey` dùng scope + native room ID + geometry/membership hash, bao gồm place IDs, coordinate/floor và source prefix phù hợp. Hash không tự chứng minh cùng physical room. Mọi reuse xuyên revision cần explicit continuity proof.
- Split, merge, reassignment, corrected poses và snapshot epoch change tạo room mapping mới. Invalidate previous feature/geometry request và stale label publication. Có proof lineage và retained per-view sources thì reassign, dedup và rebuild aggregate theo generation mới. Thiếu proof thì `stale`/pending recompute. Không chép centroid hoặc gộp probabilities chỉ từ trùng native ID.
- Giữ `RoomContext`, `RoomLabelResult`, `RoomLabelPublication`, request key của service SLM/VLM và room-stability diagnostics. Tạo context từ public read view, không truy cập `query._projection` sau khi có accessor tương đương. Chỉ lấy current publication nếu `matches_current()` với đúng key. Feature request và label request có namespaces và version riêng trên cùng room geometry. [Room context](../../../src/neusymnav/rooms/context.py), [room semantics](../../../src/neusymnav/contracts/room_semantics.py), [publication](../../../src/neusymnav/contracts/room_label_publication.py).

## API dự kiến

Một `HydraSceneGraphQuery` được pin đúng snapshot. API cũ `objects(category)`, `get(node_id, expected_revision=...)` và `evidence(HydraObjectKey, limit, cursor)` vẫn trả kết quả tương thích. Bổ sung các method hoặc một provider private phía sau cùng facade. Không tạo planner graph API song song. Kiểu dưới đây là tên dự kiến.

| Nhóm query | Signature đề xuất và giới hạn |
| --- | --- |
| Object | `object_detail(key: HydraObjectKey) -> Result[ObjectDetail]`. Native flags, timestamps, optional bbox/mesh refs. Object ID gốc được giữ nguyên. |
| Room | `rooms(page) -> Result[Page[RoomRef]]`, `room_detail(room_key) -> Result[RoomDetail]`. Place/object memberships, adjacency, optional current label và support refs. |
| Place | `places(room_key, page) -> Result[Page[PlaceDetail]]`. Optional clearance/basis/real-place/frontier fields với producer status. |
| Geometry | `geometry(node_key, kind, page) -> Result[GeometryRef | Page[GeometryRef]]`. Bbox, mesh subset hoặc room geometry support. Mọi mesh index đi với mesh generation. |
| Semantic feature | `features(node_key, spec_id=None, page) -> Result[Page[FeatureRef]]`. Trả tensor metadata, shape và provenance. Native có field nhưng rỗng thì `missing`. So sánh cosine chỉ khi feature space tương thích, để M2/M3 xử lý. |
| Observation evidence | Giữ `evidence()` và `EvidencePage`. Reuse `ObservationEvidence` và `HydraEvidenceIndex`. Nếu M1 chưa cấp index thực, trả `not_recorded`. Nếu link mơ hồ hoặc asset hết hạn, trả status tương ứng, không nâng geometric link thành native confirmed. |
| Topology | `neighbors(node_key, edge_kinds, page) -> Result[Page[StructuralEdge]]`. Endpoints pin cùng revision, weight nullable, weighted flag và weight kind. |
| Relationship | `relationships(subject_key, object_key, kind, page) -> Result[Page[RelationshipRef]]`. Discriminator structural/geometric/visual, trả `not_recorded` cho sidecar chưa kết nối. Evaluator VLM thuộc M6. |
| Task-relevant subgraph | `subgraph(seed_keys, filters, max_hops, max_nodes, max_edges, page) -> Result[Subgraph]`. Duyệt bounded, sort deterministic theo native ID, flags truncation và provenance. M6 chọn seeds theo semantic task. |

Mọi query validate token, scope, layer, ID, endpoint membership và freshness trước khi dùng data. Result error code phân biệt wrong episode/revision, unsupported field, unavailable feature, corrupted/evicted asset và incomplete graph. For query tốn I/O, runtime enqueue có deadline và facade read-only trả `pending` hoặc cache result. Reply chỉ adopt khi request ID, expected token, asset digest và clock window còn trùng. Giữ sidecar `FeatureSpec/FeatureRef` dùng chung với M1, tránh hai schema khác nhau cho cùng kiểu.

## HNA-01 — Snapshot typed và bảo toàn tương thích

**File dự kiến.** Sửa `src/neusymnav/contracts/hydra_graph.py`, `backends/hydra/{worker,graph_adapter}.py` dưới cùng namespace và `tests/test_hydra_projection.py`. Pin version bằng contract tests cho frame/summary cũ.

- [ ] Chốt `HydraReadToken`, `NativeNodeRef`, source/build/schema provenance và statuses theo audit. `HydraObjectKey` giữ constructor và behavior cũ. Object detail phân biệt native update time, graph last source/publish time và verified last seen evidence.
- [ ] Giữ v1 shape. Nếu scalar extension đủ nhỏ theo baseline, thêm qua versioned optional fields và default parser cho artifacts cũ. Sử dụng ID đã validate và read-only records. Native bounding box kiểu cụ thể nằm ở detail tier.
- [ ] Kiểm v1 fixtures, summary malformed, duplicate ID, wrong layer, invalid bbox/no feature, NaN, old graph headers và round-trip v1/v2. Bbox oracle gồm OBB/RAABB corners và kiểm world envelope tính từ cả tám góc.
- [ ] Chạy `OPENBLAS_NUM_THREADS=1 PYTHONPATH=src:.:tests .venv/bin/python -m pytest -q tests/test_hydra_projection.py tests/test_hydra_frame_wire.py tests/test_hydra_contracts.py`. Gate: parity v1, field provenance đầy đủ, synthetic validation tách native replay. Rollback dùng summary v1.

## HNA-02 — Detail provider và tài nguyên theo revision

**File dự kiến.** Tạo `src/neusymnav/backends/hydra/detail_reader.py` và `tests/test_hydra_detail_reader.py`. Sửa `backends/hydra/{runtime,session,wire,worker}.py` trong scope đọc hoặc export chi tiết. Reuse safe artifact reader của repo nếu đáp ứng budget.

- [ ] Thêm reader `read(request, expected_token)` cho saved graph đã pin. Serialize binary ref có codec/dtype/shape/bytes/hash và mesh generation. Manifest publish atomic sau xác minh assets. Dùng relative keys và giới hạn root. Native file load có thể deserialize toàn bộ mesh. Cap file và decoded cache trước khi giữ asset. Chỉ trích phần cần dùng sang Python, tránh xuất cả mảng vertices hay tensors.
- [ ] Một exact token ghim mesh canonical với indices của object geometry. Test bad/out-of-bounds index, different mesh at same graph key, same mesh digest ở khác episode, checksum mismatch, stale lease, concurrent eviction/reset và short/truncated payload. Place support refs giữ namespace khác với object vertex index.
- [ ] Thử native `.sparkdsg` fixtures và 2 saved exports trong audit. New API xử lý stored feature fake có spec hợp lệ, native empty 0×0 và semantic dtype mismatch. Unknown header/version fail safe.
- [ ] Live adapter chỉ bật sau khi đo export on-demand và queue/backpressure. Test ingress frame thắng detail requests, deadline, worker restart và missing/pending response. Không đổi frame IPC bằng tensor. Rollback đóng detail provider và dùng v1 summary.
- [ ] Chạy test mới cùng `tests/test_hydra_session.py tests/test_hydra_asset_reader.py tests/test_hydra_object_evidence.py`. Gate: exact-token checks, old artifacts load, bounded byte/memory và không có dangling refs hoặc helper giữ clone vô hạn.

## HNA-03 — Facade, topology và room context

**File dự kiến.** Sửa `src/neusymnav/backends/hydra/query.py`, `src/neusymnav/rooms/context.py` và `tests/test_hydra_scene_graph_query.py`, `tests/test_room_context.py`. Dùng `room_semantics.py`, `room_label_publication.py` và evidence contracts sẵn có.

- [ ] Expose query groups theo bảng. Tái dùng summary cho object/room/place membership và adjacency. Room adjacency structural và connectivity có source. Đưa selected scalar place attrs theo detail provider. Với `weighted=false`, trả `weight=None`. Nếu producer không rõ, dùng `weight_kind=native_untyped`. Không nối native edge weight vào A* hoặc PaperNav.
- [ ] `RoomContext` chuyển sang dùng public snapshot/accessors, giữ context hash cho dữ liệu v1. Test room split, merged/reused ID, reassignment giữa floors, geometry update cùng ID, missing parents và cycle. Feature refs/labeled publication cũ trả stale. Không tạo room identity theo nhãn VLM.
- [ ] Query subgraph test missing seeds, cross-episode/cross-revision, cap/hops/truncation, defaults rỗng, stable ordering, large cycle và cursor mismatch. Test relationship delegates trả structural/native versus visual feature from sidecar, missing sidecar trả `not_recorded`.
- [ ] Chạy test trên với `tests/test_hydra_query_wiring.py`. Integration hai exports kiểm object/room/place counts, memberships và edges khớp audit. Gate: public APIs read-only, label publications parity, endpoint/layer identity và stale handling được kiểm. Rollback giữ methods object/evidence cũ và room consumer v1.

## HNA-04 — Regression, IPC và gate trước ReasoningGraph

**File dự kiến.** Thêm targeted workload benchmark dưới `tools/` nếu chưa có harness tương đương. Dùng saved exports và Hydra selected-prefix replay hiện có. Ghi results vào `runs/hydra-attribute-query/<run-id>/`.

- [ ] Chốt budget trước benchmark theo baseline M0. Đo size frame summary cùng source/accepted prefix, worker step p50/p95/p99, parent decode/deepcopy, query service latency, RSS native/reader, disk bytes và eviction. Arm off byte-equivalent trên summary replay. Arm on-demand có riêng traces load, cold and warm cache, file size và queue drops. Số byte audit chỉ là size baseline hai snapshots, không thay latency measurement.
- [ ] Dùng fixtures lỗi rồi replay native nghiêm ngặt. Có simulator hợp lệ mới thêm smoke ngắn trong worktree/profile được phép. Kiểm vẫn có rooms/labels v1, thiếu latest depth không biến structural graph thành phép di chuyển, không thay Paper B0/C hoặc planner. Khi thiếu runtime, verdict tách phần persistent/native replay đạt với live mode chưa được mở.
- [ ] Gate HNA cho M1 gồm audit đủ 30 fields, version/load provenance, exact snapshot queries, geometry/evidence stale handling, both room label parity và budget pass ở mode consumer cần dùng. Readiness từng capability được ghi riêng. Native feature vẫn có thể `missing`, live per-object provenance và merge proof vẫn là điều kiện M1. Chuẩn bị độc lập fixture cho M1 nếu live scope còn blocked.
- [ ] Cập nhật [trạng thái](../../implementation-status.md) với commands, exit code, artifacts, pinned source/build, off/on verdict và blockers. Rollback tắt detail provider, giữ summary/parser v1 và assets trong scope archive. Không bật integration mặc định từ static audit.
