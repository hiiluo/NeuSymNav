# Protocol đánh giá Probabilistic Semantic Memory

Tách các câu hỏi về identity, belief, retrieval, navigation và tài nguyên. Cùng input chỉ có thể dùng để so sánh hiệu ứng offline hoặc shadow, còn live B2 có thể đổi quỹ đạo nên kiểm matched episode/seed/protocol, không giả định observations các bước sau giống nhau. Baseline runnable giữ Paper B0 v2 và native Hydra/ReasoningGraph pins. [Plan](implementation-plan.md) · [Kết quả hiện có](integration-results.md).

## A/B prerequisite và nguồn ground truth

- Freeze per-scene longitudinal annotation gồm physical-instance ID, labeled category, frame/detection keys, pose/calibration, mask evidence, visibility/occlusion, timestamp, native endpoints ở exact revision, và các case `unresolved`. Tách đối tượng và scene giữa tuning và hold-out. Ghi version, scene/asset hashes, provenance và blind review.
- Có thể tạo annotations từ Habitat semantic instance sensor trong process offline. Validate reprojection với exact RGB-D, pose và camera intrinsics đã ghi. Dùng independent adjudication cho mismatch, crop partial, category mapping và geometry ambiguous. Soát evaluator artifacts trước khi chuyển cho agent để không đọc GT trong runtime.
- Gate đối chứng M1 dùng fixed inputs đối với A0/A1/A2, cùng allowlisted labels và native pose/calibration. Báo cross-category link recall trên physical objects có flip thật, precision/false-link bounds trên proposed links, duplicates trên distinct physical track, IDF1/ID switches theo one-to-one assignment và same-frame cannot-link. Report số matches/eligible, scene counts, duplicate count, unresolved và CI. Với U unresolved trong P proposals và F known false links, bound là [F/P, (F+U)/P]. P=0 trả unavailable.
- Fixture native positive và negative controls đều phải đạt, và held-out phải có cases cross-category multi-view, nearby distinct instances, nontrivial occlusion và per-scene reported denominator. Chốt biên false-link, minimum coverage và số lượng độc lập trên dev trước khi test. Không promote nếu held-out còn thiếu dữ liệu hoặc có observed false merge ở case đã adjudicate. 00806/00770 pilot hiện không cung cấp longitudinal physical tracks.

## Unit, integration và replay

| Scope | Input và oracle | Điều kiện đạt |
| --- | --- | --- |
| Faithful votes | Empty, singleton, 2:1 và tie. Expected entropy cho 2:1 là khoảng 0,636514 nats. Unknown/out-of-vocab/canonical alias, duplicate conflicting payload | Sparse counts, sum p≈1, stable tie-break, empty status rõ, mismatch làm state unchanged |
| Lifecycle | Create, deactivate, reappear, merge với unique keys, same key conflict, split reassigned/ambiguous, delete, world epoch, reset/raw reuse | Không copy votes sai, không nhầm ID, gaps trả unavailable, rebuild deterministically |
| Revision và serialization | Accepted revisions, extra export/repeated query, replay, wrong SHA/scope, quota, tampered manifest, restart | Semantic state và evidence digest khớp độc lập với số lần query/export. Diff graph digest off/shadow bằng 0 trên fixed input |
| Read-only API | Valid/stale token, invalid layer, wrong cursor, dropped sidecar, room membership pending, topo edges, category valid zero và unavailable | Token/state consistent, pagination bounded, no query-induced commits |
| Policy behavior | Paired frozen observation tapes và smoke Habitat, inject stale/no-support, alias conflicts và quota | B0/B1 equality ở actions, pose, planner results, applied-action receipts và safety reasons. B2 chỉ khác candidate selection, STOP cần verification cũ |

Dùng hold-out thực sau khi unit và replay chạy pass. Historical replay có thể so sánh `p(c)` và candidate list ở cùng revision. Không dùng belief future cho frame hiện tại. Kiểm causal prefix và exact actor sensor source trước khi chấm.

## Ablation matrix

| Arm | Biến thay đổi | Đường đo |
| --- | --- | --- |
| B0 | Existing Hydra/ReasoningGraph và deterministic candidate retrieval | CPU/native replay và Paper B0 |
| B1 | B0 + hard votes shadow | Same-input graph, action parity. Quality/coverage offline |
| B2 | B1 + probabilistic candidate retrieval | Same-input recall @k, paired live HM3D ObjectNav v2 |
| B3 | B2 + room/subgraph retrieval | Chỉ khi có consumer compatible và gate riêng |
| B4 | Soft evidence backend | Chỉ khi full per-instance score contract hoặc extension hợp lệ có pin. Thí nghiệm sau faithful baseline |

Nếu M1 đổi association, freeze phiên bản đã nghiệm thu giống nhau giữa B0/B1/B2. Báo A0/A1/A2 riêng. Pin scene list, ordered UID, seeds, detector class mapping, digest of checkpoints, calibration, sim version and scene asset hashes, agent geometry, action parameters, step/time budget, planner settings, scoring version và issue/abort policy. Dùng DEV60 chọn thresholds, TEST180 held-out chỉ một protocol cố định sau đó. HM3D-OVON thuộc phase tùy chọn khi vocabulary/mapping và coverage đủ. Khác cách đo distance-to-goal, success threshold, STOP hoặc benchmark split khiến số paper không còn so sánh trực tiếp.

## Semantic belief và retrieval metrics

- Evaluable unit là physical instance tại một revision đã pin, hoặc một cutoff/instance được chọn trước để tránh overweight long trajectories. One-to-one matching do evaluator dùng geometry/mask/GT ID độc lập với predicted category. Báo eligible GT, matched/unmatched, unavailable distribution, sensor-visible, abstention và false candidates.
- Top-1/top-k, macro per-class, object-level recall và retrieval recall@k có cả all-visible và linked subset. Dùng same cutoffs cho B0/B1/B2, score B0 category baseline theo deterministic output. Nếu label annotated là nhiều alias, canonicalize bằng frozen taxonomy. Unresolved/out-of-domain báo riêng.
- Chấm NLL `-log p(gt)` và multiclass Brier trên full vocabulary, p=0 cho valid category absent trong available distribution. Raw NLL có +∞ cho zero truth mass. Nếu báo clip diagnostic, pin epsilon 1e-12, báo số zero cases và giữ raw behavior. ECE top-label dùng 10 equal-width bins đã pin, giữ reliability table và bin counts. Thêm entropy versus error, coverage/selective accuracy và stratify N. Report separate available-only denominator và missing/out-of-domain, không suy calibration từ normalized probabilities.
- Candidate gồm type, vote count, supporting receipts, p, entropy, association/verification status và match result ngoại tuyến. Báo target-detection recall, probability retrieval recall, wrong-object proposal, confirmed/correct verification, fallback rate và target-visible coverage.

## Navigation metrics và integrity

Dùng existing offline scorer HM3D ObjectNav v2 cho SR, SPL, SoftSPL, Distance to Goal, steps và collisions. Wrong-object STOP yêu cầu independent evaluator match giữa observed/stopped instance và GT. Báo theo số STOP lẫn tổng episodes, kèm unknown attribution. Include target-detection recall, retrieval recall, verification accuracy/coverage, episode time, peak memory và crashed/incomplete. Không loại failed run khỏi denominator nếu protocol coi là episode failure. Report paired per-episode deltas, cluster bootstrap theo scene và confidence intervals cùng counts.

Dùng trace detector, association, selection, planner và execution cùng offline visibility để xác định failure stage theo các nhãn target never observed, visible but missed, wrong association, wrong belief, wrong selected object, approach failure, false-positive STOP, exploration budget exhausted. Giữ multiple flags và báo earliest causal stage khi timeline xác định, không gán sai từ SPL đơn lẻ.

Runtime chỉ dùng current/past RGB-D, calibrated pose, observed geometry và detector outputs. Không cấp ground-truth labels/locations, full unexplored scene, future frames hoặc episode success feedback. GT chỉ dùng dựng episode hoặc chấm offline. Strict zero-shot reset mỗi episode. Lifelong feedback/EEC hoặc oracle là experiment và report riêng nếu được giao sau này.

## Tài nguyên và latency

Đo CPU/profile ngày chạy, OS/Python, YOLOE/Habitat/native build và device availability. Tách service latency (enqueue, native step, accepted→semantic publication, vote commit, object/category/room query, serialize/reload và IPC payload bytes) với end-to-end control percentiles p50/p95/p99/max. Giữ N observations, O active canonical IDs, K per object, quota/reject/drop counts và persisted bytes. Peak RSS lấy cả host và process tree. Report sampling interval và thiếu provider. VRAM đo per-process nếu runtime có device, nếu không trả unavailable, không ghi 0. Test memory monotonic đến cap, duplicate replay không tăng ledger, saturation hiển thị và read-only query latency không block control.

So sánh fixed prefix với cùng cadence/thread settings, CPU/GPU workload duy nhất tại một thời điểm. Proposed run gate chọn trước từ baseline measured variance, kiểm budget theo repo và trên RTX 3060 Laptop 6 GiB thật nếu có. Faithful baseline không cấp phát model mới. Không promote default chỉ vì synthetic speedup.
