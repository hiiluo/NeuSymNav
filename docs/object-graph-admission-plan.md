# Kế hoạch chọn lọc object vào graph — 2026-11-01

> Dành cho agent triển khai. Trạng thái: planned; lượt này chỉ viết tài liệu.
> Chưa có implementation, test hay runtime chứng minh chất lượng của cơ chế mới.

## Mục tiêu và quyết định thiết kế

Tăng precision của object graph, giảm node giả/trùng, có số liệu về recall và độ trễ phải đánh đổi. Giữ CG + Visual, point cloud và một canonical owner. Chọn cơ chế admission đa quan sát + hình học; confidence-only là đối chứng. Chưa chọn một tổng điểm có trọng số vì chưa có dữ liệu hiệu chuẩn; từng điều kiện phải giải thích được.

Không fine-tune thêm, đổi detector mặc định, tải model/dataset, thay safety navigation, commit/push hay sửa hai repo nguồn trong task này. Body/camera giữ cấu hình đã chốt. Base detector vẫn mặc định vì checkpoint fine-tune bị giảm chất lượng trên held-out Hypersim.

### Những gì hiện đã có

- `src/neusymnav/objects/store.py`: owner commit nguyên tử, checkpoint, canonical ID/alias; `_build_snapshot` xuất track và point cloud. Không tạo owner thứ hai.
- `src/neusymnav/verification/ledger.py`: đã đếm detected/independent views, negative evidence và label support; hiện `verified` yêu cầu ít nhất 5 observations, 3 independent positives, label support .8. Không sao chép hay đổi nghĩa `verified` thành admission.
- `src/neusymnav/hierarchy/composer.py`: composition/membership hiện nhận ObjectSnapshot đầy đủ; cần chọn lọc tại publication boundary, không chỉ ẩn bằng renderer.
- `src/neusymnav/visualization/scene_graph.py`: public view phải giữ đúng Floor–Room–Object. Composer nội bộ còn building/region/place; không mở rộng task thành viết lại toàn bộ internal graph, nhưng không để các loại này lọt public scene graph/export.
- Các bằng chứng chất lượng gần nhất trong `docs/results/completion-finetune-2026-11-01.md` là baseline, không phải kết quả admission.

## Contract dự kiến — main khóa trước khi chia việc

1. Candidate vẫn có ID do owner cấp và được association lại. Admission là thuộc tính riêng, không thay lifecycle/verification. Không cấp ID mới khi được nhận vào graph.
2. Trạng thái `candidate | admitted | review_required`; dữ liệu lỗi/thiếu watermark biểu diễn thêm `availability=unavailable`, không giả thành bằng chứng âm.
3. Tạo `contracts/admission.py` với immutable `AdmissionDecision` (canonical ID, state, availability, reason_codes, evidence_refs, quality components) và `AdmissionSnapshot` (episode, object/evidence revision, policy version/hash, decisions). Main chốt signatures/serialization sau kiểm tra pattern contracts hiện hành.
4. Tạo `objects/admission.py`: `evaluate_admission(object_snapshot, verification_snapshot, evidence_summary, prior_snapshot, policy) -> AdmissionSnapshot`. Hàm deterministic, không IO, không detector/CLIP/GT và không đọc wall clock ẩn. Summary có source keys, capture time/domain, calibration/taxonomy/feature-space provenance; không truyền unbounded history.
5. Chỉ lấy summary từ evidence được owner chấp nhận, canonicalize alias trước khi đếm. Cùng FrameKey/detection/event không được tính hai lần, kể cả restart/merge. Tracked-only không tạo detector-positive vote.
6. Chỉ publication `admitted` được đưa vào graph chuẩn khi chế độ enforce bật. `candidate/review_required` ở bảng chẩn đoán riêng; mọi memory vẫn truy cập được để association/verification. Không lọc occupancy, point cloud môi trường hay obstacle safety map bằng admission.
7. Object thật nhưng room chưa rõ vẫn được publish với membership unknown/unassigned, không bịa room hay cạnh. Room thay đổi phải tính lại membership/edge với cùng canonical ID.
8. Snapshot admission/hierarchy phải khớp revision. Lệch revision: không publish một graph mới như thể đầy đủ; giữ bản coherent cũ và báo stale/unavailable. Không để lỗi admission chặn control lane.
9. Chế độ `off | shadow | enforce`; mặc định `off` trong triển khai. Shadow tính quyết định nhưng không thay graph baseline. Enforce chỉ bật profile thử nghiệm trước khi qua gate chất lượng.

## Chính sách v1 đề xuất để bắt đầu đo

Các số dưới đây là giá trị thử nghiệm, không phải ngưỡng đã được chứng minh:

- Giữ detector confidence floor hiện tại .30. Không thể phục hồi các detection đã bị floor loại; mọi thay floor phải là thí nghiệm riêng.
- Admission cần ít nhất 3 detector observations hợp lệ, ít nhất 2 independent views theo logic đã có của verification. Không thêm định nghĩa độc lập mâu thuẫn; pin recipe hiện tại và kiểm tra pose/provenance.
- Mỗi positive dùng được cần tỷ lệ depth hợp lệ trong mask >= .50 và ít nhất 20 voxel hữu ích sau preprocessing hiện tại. Không có denominator gốc thì unavailable, không suy từ cloud đã truncate.
- Geometry support: ít nhất 2 independent positives có centroid cách robust median không quá `max(.10 m, .25 × bbox diagonal)`; ghi rõ world canonical axes và đơn vị. Chưa dùng kích thước tuyệt đối theo class làm hard rejection; tránh loại bàn rộng, vật mỏng hay vật bị che.
- Association phải qua gates CG + Visual đang có; ambiguity/cannot-link giữ nguyên. Lưu component overlap/visual và lý do, không xem score ghép đôi là xác suất object có thật.
- Label support < .70 chỉ đánh dấu label uncertain ở v1, không tự phủ nhận sự tồn tại. Nhãn và hình học có confidence riêng.
- Hysteresis: positive yếu hoặc không nhìn thấy không tự hạ admitted. Chuyển review_required sau 3 negative proofs độc lập còn hợp lệ theo visibility/depth contract hiện có; khôi phục cần 2 independent positives mới kể từ transition. Không dùng thời gian vắng mặt làm negative.
- Mọi tham số finite/range-checked, versioned và ghi vào artifact. Bounded counters/summary, giữ event IDs cần dedup bằng durable ledger; không thêm danh sách point cloud không giới hạn.

## Các task triển khai theo thứ tự

### A1 — Khóa evidence và contract (main; prerequisite tất cả)

Files: `contracts/admission.py` (mới), `contracts/serialization.py`, `contracts/__init__.py`, `runtime/configuration.py`; tests mới `tests/test_admission_contracts.py`.

- [ ] Inventory detector confidence, mask/depth denominator, voxel sampling, association diagnostics, independent-view rule trong đường commit thật. Ghi trường có/thiếu; bổ sung provenance tại producer, không dựng số từ snapshot cuối.
- [ ] Viết test reject NaN/inf, sai range/version/domain/episode/revision; round-trip; mode off đọc profile cũ; không tự coi state thiếu ở checkpoint cũ là admitted.
- [ ] Chốt types, signatures và cấu hình v1 nêu trên. Ghi migration/rebuild từ ledger; thiếu asset lịch sử thì unavailable.
- [ ] Chạy `.venv/bin/python -m pytest tests/test_admission_contracts.py -q`; lưu RED/GREEN và exit code thực tế.

### A2 — Evidence summary và decision engine (Terra; sau A1)

Files: `objects/admission.py` (mới), `objects/store.py`, `objects/ledger.py`, phần producer cần thiết được main giao độc quyền; test `tests/test_object_admission.py`.

- [ ] Test một detection confidence cao vẫn candidate; 3 observations/2 independent đủ geometry được admit; repeated frame, stale data, tracked-only không đủ bằng chứng.
- [ ] Test depth-invalid, sparse cloud, centroid outlier, thin object; label uncertain không xóa object tồn tại; finite input bắt buộc.
- [ ] Test negative đủ visibility mới hạ state, vắng mặt không hạ; hysteresis phục hồi chỉ tính evidence mới.
- [ ] Implement summary và pure evaluator, checkpoint atomic với owner commit hoặc rebuild deterministic từ committed ledger. Crash giữa commit/consumer không được đếm lại.
- [ ] Test merge/alias chồng evidence, replay/restart/new episode, cap overflow và thiếu provenance. Không cộng mù hai bộ đếm sau merge.
- [ ] Chạy focused tests; chứng minh quyết định giống nhau giữa live commit, restart và replay cùng event stream.

### A3 — Nối publication và giao diện (main integration; Luna UI sau contract A1)

Files: `runtime/coordinator.py`, `hierarchy/composer.py`, `visualization/scene_graph.py` và DTO/export consumers thực tế do inventory xác định; tests `tests/test_admission_publication.py` và UI tests hiện có.

- [ ] Main khóa một publication seam dùng chung cho UI/export/semantic consumers; full owner memory vẫn phục vụ association. Audit cả object-goal consumers để không vô tình chọn candidate qua đường khác.
- [ ] Test shadow graph byte-equivalent baseline (trừ diagnostics riêng); enforce loại candidate khỏi nodes và mọi edge endpoint; admitted giữ ID, point cloud, room membership và cập nhật vị trí.
- [ ] Test unavailable/revision mismatch giữ stale coherent publication; không chặn control. Không biến unknown room thành room giả.
- [ ] UI hiển thị lý do admission, depth support, số independent views, label uncertainty; bảng debug ứng viên riêng. Public graph chỉ Floor–Room–Object, giữ room adjacency và cạnh Object–Room hợp lệ.
- [ ] Test alias không dangling edge, ẩn node kèm cạnh, camera/world coordinates không đổi; chạy Qt offscreen fixtures và export parity.

### A4 — Replay đánh giá và ablation (Terra evaluator; sau A1, tích hợp sau A2/A3)

Files mới: `evaluation/graph_admission.py`, `tools/evaluate_graph_admission.py`, `tests/test_graph_admission_quality.py`.

- [ ] Cố định source frames/poses, detector output, CG+Visual recipe, GT scope và hash; chạy 3 nhánh: baseline, confidence-only, multiview+geometry. Chạy thêm ablation bỏ geometry nếu dữ liệu đủ.
- [ ] Match predicted graph objects với GT identity theo one-to-one spatial/mask protocol đã version; không lấy association ID tự sinh làm GT. Test duplicate/split/merge và IoU boundary bằng oracle tổng hợp.
- [ ] Báo precision/recall/F1 node, duplicate và false-merge rates, confirmation latency (median/p95 và objects chưa bao giờ admitted), node flicker, room-assignment accuracy, association IDF1/AssA khi đủ GT identity, memory/time cost.
- [ ] Mẫu số recall giữ nguyên toàn bộ GT thuộc phạm vi annotation và đủ điều kiện quan sát được định nghĩa trước; không chỉ lấy admitted làm mẫu số. FP ngoài vùng annotation là unknown/unsupported, không mặc định FP hoặc TP.
- [ ] Tách metric presence/label/geometry. Báo support theo scene/class/visibility; unavailable/failed runs và chưa xác nhận phải nằm báo cáo.
- [ ] 57 frames HM3D hiện có chỉ là development pilot. Hypersim ảnh rời không có camera/identity phù hợp không được dùng giả làm temporal replay. Nếu thiếu multi-scene GT, hoàn thành pipeline/oracles nhưng ghi quality gate chưa chứng minh.
- [ ] Khóa policy trên development trước khi mở held-out; không sửa threshold theo test. Không hứa tăng chất lượng trước khi có số đo.

### A5 — Review, bounded runtime và quyết định rollout (main + reviewer độc lập)

- [ ] Reviewer kiểm canonical ownership, duplicate evidence, atomic persistence, GT boundary, public projection, caps và control independence trên snapshot đã pin. Model theo `docs/agent-orchestration.md`, không Astra.
- [ ] Chạy full CPU: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'`.
- [ ] Cố định campaign trước chạy: các map có sẵn 00861/00802/00770, mỗi map một seed đã ghi, shadow và enforce mỗi chế độ 120s; 6 runs tuần tự, một GPU workload. Điều kiện đầu/nav/recipe giống nhau; trajectories có thể khác, không dùng native trajectories khác nhau thay paired offline accuracy.
- [ ] Preflight/pins/profile mới trước native; giữ mọi failure, không retry để lấy run đẹp. Ghi RSS coverage, queue/drop, control latency, shutdown, admitted/candidate counts và lifecycle transitions. Không nới deadline/RSS gate.
- [ ] Gate đề xuất: paired held-out graph precision tăng >=5 điểm phần trăm, recall giảm <=5 điểm; duplicate/false-merge không tăng; p95 confirmation <=5 giây capture-time (báo riêng unconfirmed); p95 control latency tăng <=10% và không vi phạm deadline hiện hữu; memory trong cap cấu hình. Các mức này là tiêu chí thử nghiệm đề xuất, không phải kết quả.
- [ ] Không đủ evidence/support hoặc bất kỳ gate nào fail: giữ default off, giao profile shadow/enforce opt-in cùng báo cáo trade-off. Không tuyên bố toàn P10 pass từ campaign này.
- [ ] Cập nhật `docs/implementation-status.md`, `docs/running.md`, report `docs/results/object-graph-admission-<date>.md` với command, exit code, source pins/artifacts và ba trạng thái implemented / correctness-verified / runtime-validated.

## Điều phối và review focus

A1 tuần tự do main quản lý. Sau A1, A2 engine và A4 evaluator có thể song song với interface đã khóa; Luna chuẩn bị UI fixtures, không viết file main đang sửa. A3 tích hợp sau A2, A5 sau tất cả. Mỗi file một writer, không tạo agent cho từng thao tác nhỏ; không chạy GPU trong lượt lập kế hoạch.

Năm lỗi ưu tiên reviewer tìm: merge double-count; score độc lập giả từ frame lặp; checkpoint/revision lệch vẫn publish; unknown/occluded biến thành negative; filter UI nhưng export/consumer còn dùng node bị loại. Các test tương ứng thuộc A2/A3/A4.

## Prompt giao cho agent

> Triển khai `docs/object-graph-admission-plan.md` theo A1→A5. Đọc AGENTS.md, docs/agent-orchestration.md, docs/implementation-status.md và architecture trước. Giữ CG+Visual, point cloud, canonical owner, body/camera và detector base. Main khóa contracts, phân công theo dependency và một file một writer; không Astra. Chỉ sửa NeuSymNav, không training/download/push. Dùng tài sản hiện có, một GPU job mỗi lúc. Chạy shadow trước enforce, giữ mọi failure và không nới gate. Hoàn thành code, kiểm chứng và báo cáo; thiếu GT thì ghi rõ giới hạn, không tự suy quality pass. Không promote default nếu chưa đạt gate.

## Execution checkpoint — 2026-11-01

Implementation, focused/full CPU, independent review, real-source pilot and six
native attempts executed. See `docs/results/object-graph-admission-2026-11-01.md`.
A1–A4 functional paths implemented; A5 campaign/review executed, promotion gate NOT
passed. Default off. Precision/held-out/room/falsemerge gates lack suitable GT,
recall pilot regresses; 2/6 native attempts retain RSS errors. Do not interpret
this checkpoint as every validation checkbox passing or whole P10 completion.
