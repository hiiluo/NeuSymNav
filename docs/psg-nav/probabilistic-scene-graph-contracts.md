# Contracts cho Probabilistic Scene Graph

Đây là contracts đề xuất. Tên mới được chỉ rõ để phân biệt với interfaces đã tồn tại. Source of truth hình học là native graph. Native lineage là authority duy nhất về ID, alias và epoch. Read view không có quyền sửa các owner này. [Audit interfaces đang có](current-system-audit.md).

## Scope và observation receipt

- Scope của store gồm `episode_id`, `run_id`, native lineage epoch, world epoch, coordinate convention, detector profile/checkpoint, vocabulary ID, labelspace hash, config/build/source pins và schema. Scope changes đóng store. Không nối category counts giữa hai labelspaces hoặc map epochs.
- `HydraReadToken` là freshness guard, gồm graph revision, input prefix và scope native. `GraphReadToken` nối đúng source FrameKey, timestamp, clock domain, calibration, pose version, vocabulary và detector. `CanonicalObjectId` do `ObjectLineageView` cung cấp. `HydraObjectKey` thuộc exact revision và dùng cho existing evidence APIs.
- `VoteKey` đề xuất là tuple `(run_id, FrameKey, detection_id)` trong scope cố định. `FrameKey` đã chứa episode/sensor/frame. Revision, asset path và mutable object alias không nằm trong khóa. Detector output khác trên cùng source trong cùng scope là conflict, không phải vote bổ sung.
- `CategoryVoteReceipt` đề xuất giữ VoteKey, canonical object, canonical category và raw label, raw score, original GraphReadToken hoặc hash + ref có thể xác thực, source timestamp, acceptance revision, status/method association, instance-support reference, lineage hash và existing ObservationEvidence reference. Không lưu crop, mesh, pose array hay embedding trùng.
- Category được canonicalize bằng taxonomy pinned. Unknown, invalid, empty hoặc ngoài vocabulary trả lý do và không vote. Merge canonical category alias (như `couch → sofa`) ở input normalization. Giữ raw label để audit. Không collapse category gần nghĩa bằng embedding.
- Association receipt nêu exact endpoint, token và method/version. Trạng thái đề xuất gồm `confirmed`, `pending`, `ambiguous`, `unassigned`, `invalidated`. Chỉ `confirmed` đủ chứng cứ đi vào ledger. `geometric_candidate` ở interface cũ là pending. Nếu future `native_confirmed` chỉ có topology lineage mà thiếu evidence đồng nhất physical object, vẫn pending.
- Profile M1 nghiệm thu dùng `reconcile` trong batch journal v2 để nối một frontend tombstone tối đa 24 accepted revision tới live ID mới hơn. Graph và geometry không đổi. Khi đọc revision hiện tại, native lineage resolve tham chiếu cũ qua alias do owner đã ghi.
- `CategoryVoteReceipt` của M1 dùng exact source token và hai RGB-D anchors từ các accepted revision khác nhau, cùng resolve vào một owner endpoint. Receipt chứa source crop hashes, lineage SHA và witness SHA. Producer chỉ thêm mục `confirmed_receipts` khi có opt-in provider và exact lineage reader. [Nghiệm thu M1](integration-results.md#m1--nghiệm-thu-a4-và-confirmed-receipt)
- Một VoteKey với cùng immutable receipt sau replay là no-op. Payload, source prefix hoặc owner khác với receipt cũ là conflict trước mutation. Correction là event riêng có provenance và authority, yêu cầu supplied prior receipt digest. Graph revision chỉ xuất hiện trong provenance và transaction pins. Một unique frame/detection pair không có vote mới do query, feature refresh hay export.

## Belief value và query status

| Trường đề xuất `ObjectSemanticBelief` | Contract |
| --- | --- |
| `object_key`, `native_ref` | Canonical ID và endpoint trong exact read token |
| `category_counts`, `category_distribution` | Immutable sparse pairs, positive integer counts và p=count/N. Full discrete domain là vocabulary pinned. Absent valid category có p=0 khi distribution available |
| `observation_count` | N unique confirmed observations được giữ. Pending không count. Aggregate lưu riêng raw detector score |
| `semantic_entropy_nats` | `-sum(p * log(p))` trên support. 0 cho singleton, null nếu N=0 hoặc status không available |
| `most_likely_category`, `top_k_categories` | Sắp count giảm dần rồi category ID tăng dần, top-k không renormalize. Mode null khi unavailable |
| `first_observed_ns`, `last_observed_ns` | Min/max capture ns của confirmed receipts trong một clock domain. Null khi không evidence |
| `source_revision`, `read_token` | Receipt revision mới nhất có đóng góp và token dùng để đọc state hiện tại, có thể khác nhau |
| `association_status`, `belief_status`, `reason` | Association provenance riêng. `available`, `unavailable`, `stale`, `not_found`, `invalidated` là read status. Reason cụ thể như disabled, no_confirmed_evidence, revision_mismatch, gap, quota, epoch, conflict, lineage_unavailable |
| `model_provenance`, `evidence_references`, `schema_version` | Detector/labelspace/calibration refs, paginated VoteKey/receipt refs, integer schema 1 |

Không có distribution khi unavailable. Numeric p=0 dành cho category hợp lệ không xuất hiện trong distribution available. Query category ngoài vocabulary trả input error. Top-k nhận `1 ≤ k ≤ 64`, threshold probability hữu hạn trong [0,1], entropy threshold hữu hạn và không âm. Query theo category có min_probability=0 vẫn chỉ enumerate objects có support category. Point query trả 0 nếu valid nhưng absent. Thống kê vote không thể override native semantic label, raw confidence, embedding, verification hoặc validity của navigation commands.

## Revision-safe interface đề xuất

Mở rộng `HydraSceneGraphQuery` qua optional `belief_reader`. Mọi response đính read token. `NativeNodeRef` phải đúng OBJECTS layer và exact token. Canonical ref phải resolve qua `ObjectLineageView`. Alias resolve cùng scope, deleted node trả `not_found`. Stale token được kiểm trước và sau khi lấy immutable view. Nếu publication thay đổi trong query, trả stale thay vì trộn dữ liệu. Historical query chỉ đọc sealed export được caller chọn rõ, không dùng cho targeting.

```python
object_belief(ref: NativeNodeRef, *, expected_token: HydraReadToken, top_k: int = 5)
category_probability(ref: NativeNodeRef, category: str, *, expected_token: HydraReadToken)
objects_by_probability(category: str, *, min_probability: float, expected_token: HydraReadToken,
                       limit: int = 64, cursor: str | None = None)
uncertain_objects(*, min_entropy_nats: float, expected_token: HydraReadToken,
                  limit: int = 64, cursor: str | None = None)
probabilistic_room_context(room: NativeNodeRef, *, expected_token: HydraReadToken,
                           limit: int = 64, cursor: str | None = None)
probabilistic_subgraph(seeds: tuple[NativeNodeRef, ...], *, expected_token: HydraReadToken,
                       max_nodes: int = 64, max_edges: int = 128)
belief_evidence(ref: NativeNodeRef, *, expected_token: HydraReadToken,
                limit: int = 64, cursor: str | None = None)
```

Distribution, entropy, top hypotheses và status đọc từ `object_belief`. Tránh thêm getters dư thừa. Ranking sắp p hoặc entropy giảm dần, canonical stable key tăng dần. Cursor pin token/scope/filter/limit, giới hạn 64. Room/subgraph reuse hierarchy và native relation edges, đánh dấu missing member beliefs riêng. Query không tăng bộ đếm, không decode ảnh/tensor và không chạy inference. `objects()`, `get()`, `evidence()` deterministic giữ signature và behavior hiện có.

## Lifecycle, transaction và serialization

Single writer nhận ordered accepted revisions. Mỗi publication verify đúng previous scope, monotonic sequence, native token, batch completeness marker và proof. Replay cùng revision/digest là no-op. Một revision không có detection hợp lệ vẫn cần explicit marker để phân biệt không-vote với gap. Missing packet, lag, lineage revoke hoặc source mismatch trả unavailable và bắt đầu rebuild từ prefix đã chứng nhận. Publication cũ không được dùng làm current. Reader không cần lock qua I/O.

Create tạo empty entry theo owner view hoặc tính lazy unavailable. Update không thay receipt cũ. Trong visibility disappearance, chỉ giữ current nếu authority vẫn có object endpoint. Eviction/quarantine không cấp alias. Merge đã chứng nhận cùng physical object chuyển union receipt keys atomically rồi tính counts từ receipt. Conflict rollback cả merge vote transaction. Split không tách bằng aggregate. Repoint receipt có proof chính xác, remainder invalidated. Delete rút khỏi index/current view và giữ tombstone/receipts trong retention scope. Reset/epoch mới mở scope rỗng. Không load history scope cũ vào active store.

Wire v1 ưu tiên canonical JSON manifest với receipt order theo revision rồi VoteKey, key order ổn định, finite scalars, schema/scope/prefix/receipt digest. Size/count check trước parse lớn. Atomic temp + rename và durability như store hiện có, không overwrite mutable state đang phục vụ query. Restore validate expected SHA, schema, caps, pins, ordered revisions, event structure và lineage. Rebuild counts từ source receipts, verify parity rồi publish. Restore conflict giữ state trước đó. Tiếp tục nhận duplicate đã có sau restart mà không tăng counts. Quota thì reject whole stage, mark saturation và chỉ cho export lịch sử đã commit. Không cắt seen keys để giữ aggregate online mồ côi.

## Consumer và feature flag

`off` mặc định, không allocate store hay thay graph/controller. `shadow` chạy admission, publish và trace, planner vẫn deterministic. `probabilistic` là opt-in run-scoped sau gate M5, chỉ biến đổi candidate retrieval/ranking. Phải khai báo fallback `deterministic` hoặc `abstain` trong protocol và ghi reason. Candidate record mang canonical ref, native token, category, p, N, source receipt IDs, join identity và verification status riêng. Policy chỉ nhận candidate trong scope, fresh, reachable theo planner hiện có và không suy confirmation từ probability hoặc entropy. Existing STOP path không nhận trực tiếp belief fields.
