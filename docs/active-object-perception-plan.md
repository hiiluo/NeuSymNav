# Kế hoạch bộ nhớ góc nhìn và chủ động xác minh vật thể

Trạng thái: **prototype opt-in đã triển khai, CPU đã kiểm chứng và đã chạy native smoke; chưa đạt gate chất lượng**. Người dùng đã giao thực
thi. Kết quả, phần còn thiếu và giới hạn được ghi trong
[report triển khai](results/active-object-perception-2026-11-03.md) và
[kết quả native smoke](results/active-object-perception-native-2026-11-03.md). Không đổi
default, training, tải model/data, commit hoặc push.

## 1. Mục tiêu và cơ sở

Tăng số identity đúng được thu hồi trong một episode với ngân sách thời gian cố định,
giữ precision và khả năng khám phá. Tách ba vấn đề: vật thể chưa từng được đề xuất,
candidate thiếu bằng chứng, và association/admission làm mất quan sát đúng.

Bằng chứng hiện có (không gộp các cohort):
- Replay admission 57 frames: baseline thu hồi90/230 observations và8/25 identities;
  multiview55/230 và5/25; precision chưa chứng nhận vì annotation không đầy đủ.
- Replay79frames: CGvisual AssA tốt hơn CGspatial nhưng36/137 observations unresolved.
- Fine-tune: held-out bbox AP .150121→.118223 dù development HM3D cải thiện.

Nguồn: results/object-graph-admission-2026-11-01.md,
results/conceptgraphs-visual-completion-2026-10-30.md,
results/completion-finetune-2026-11-01.md. Đây là giả thuyết điểm nghẽn, chưa phải
chứng minh active perception sẽ thắng. Không tiếp tục tuning trên test đã xem.

## 2. Phạm vi và invariants

- Giữ base detector, CG+Visual, point cloud, một canonical object owner và alias.
- Tái sử dụng verification ledger/best_views và admission hiện hữu; không tạo ID
  authority hay định nghĩa verified thứ hai. Admission mặc định vẫn off.
- Body/camera, calibration, unknown/free, TTL, clearance, control deadlines và
  resource certificate giữ nguyên. Semantic GT chỉ ở evaluator offline.
- Chính sách quan sát lại là extension opt-in của frontier-only trong architecture.md.
  Khi được giao thực thi kế hoạch này, cập nhật contract extension rõ ràng; core
  frontier-only vẫn là baseline. Đây không phải ObjectNav theo lệnh người dùng.
- Đầu tiên chỉ xử lý candidate đã có. Không thể cứu vật thể chưa được detector
  đề xuất; nếu đây là bottleneck chính, chuyển tới nhánh Q7 offline trước.
- Mỗi episode reset view/request state. Không dùng historical frame làm control mới.
- Chỉ NeuSymNav được sửa; hai repo nguồn read-only. Không tự training/download.

## 3. Luồng đề xuất

RGB-D → detections/projection/CG+Visual → canonical owner + committed evidence
→ bounded view memory → yêu cầu quan sát lại → sinh viewpoint an toàn
→ arbiter frontier/reobserve → planner + motion guard hiện hữu
→ frame mới có nguồn thật → commit evidence → admission hiện hữu.

Memory lưu những góc nhìn có ích; scheduler chỉ tạo yêu cầu, không điều khiển robot.
Viewpoint visibility từ geometry hiện có chỉ là dự đoán, không phải chứng nhận nhìn
thấy. Chỉ quan sát thực đã commit mới làm tăng evidence. Dữ liệu thiếu/occluded không
được tự chuyển thành negative evidence.

## 4. Work packages và gates

### Q0 — Khóa baseline và khả năng đánh giá (Luna xhigh; main duyệt)

- [ ] Đọc status mới nhất, kiểm tra workload đang chạy và snapshot source/config.
- [ ] Kiểm kê retained RGB-D/pose/mask/commit/alias/appearance, hash và continuity.
  Run cũ đã bị xóa phải ghi missing; không dùng tên file trong report làm bằng chứng.
- [ ] Khóa một cohort development khả dụng và một protocol test độc lập theo scene.
  Nếu chưa có GT phù hợp, báo thiếu; không gọi frame gần nhau là test độc lập.
- [ ] Lập bảng attrition theo frame và identity: eligible GT → matched detection →
  valid projection → assigned ID → admitted; kèm lý do loại và mẫu số cố định.
- [ ] Chọn annotation scope exhaustive để đo precision; ngoài scope là unknown.
  Chuẩn bị quy trình annotation độc lập với predictions, không chỉ sửa FP thấy được.

Đầu ra: `.runtime/active-object-perception/q0/{manifest.json,baseline.json,gaps.md}`.
Gate: tái lập baseline cùng input/protocol hoặc công khai lý do không tái lập được.
Thiếu GT không chặn unit engineering nhưng chặn quyết định chất lượng/default.

### Q1 — Oracle ablation và quyết định đầu tư (Terra high)

- [ ] Baseline B0 giữ nguyên pipeline.
- [ ] O-label: chỉ thay nhãn ở các detection↔GT match hợp lệ đã định nghĩa; giữ mask.
- [ ] O-mask: thay bằng GT masks, projection/association vẫn thực; ghi rõ đã thay
  cả proposal recall. Không cấp appearance GT: trích lại từ RGB/mask cùng recipe.
- [ ] O-ID: gán GT identity chỉ cho observations match hợp lệ; unmatched còn nguyên,
  không lén bỏ FP/FN. Các metric không còn ý nghĩa dưới oracle phải ghi riêng.
- [ ] Đối chiếu admission off và policy hiện hành với cùng projected observations.
- [ ] Audit synthetic cases: miss, confusion, split, merge, partial GT, occlusion.

Đầu ra: báo cáo sensitivity từng stage; oracle không phải performance deployable,
không cộng các mức tăng như các nguyên nhân độc lập.
Gate quyết định: nếu ít candidate đúng tồn tại, ưu tiên Q7; nếu candidates có nhưng
thiếu views/admission loại nhiều, tiếp Q2–Q6. Nếu lỗi source/geometry lớn, sửa và
đóng gate correctness đó trước; không dùng policy mới để che lỗi.

### Q2 — Bộ nhớ góc nhìn có giới hạn (Terra high; main giữ shared contracts)

Phạm vi dự kiến: verification/best_views.py, verification/ledger.py,
objects/store.py integration, contracts mới khi cần; không sao chép admission engine.

- [ ] Chốt ViewEvidence: episode, canonical ID, event/source key, capture time,
  camera pose/K, geometry/feature-space provenance, mask fraction, depth support,
  crop asset ref, view direction, quality components và revision.
- [ ] ViewMemorySummary lưu refs của tối đa6 views/object, không nhân bản pointcloud.
  Global cap đề xuất256 objects/64MiB metadata+features; assets tính vào cap recorder.
  Eviction deterministic, có reason; không xóa ledger hay tăng confidence khi thiếu.
- [ ] Đánh giá diversity bằng hướng camera tương đối object và baseline vị trí;
  dịch camera nhỏ/frame lặp không được tính thành evidence độc lập.
- [ ] Giữ raw scores; nhãn/uncertainty hợp nhất phải có version, chưa gọi là probability
  đã calibrated. Không tự nhân likelihood các frame tương quan.
- [ ] Alias merge deduplicate event IDs, restart/replay idempotent, episode reset.
  Unknown/gap không trở thành bằng chứng phủ định; tổng cap có test stress hữu hạn.
- [ ] Ban đầu chạy shadow; dùng cùng admission policy để cô lập hiệu quả view selection.

Gate: fixtures chứng minh không double-count, không mất provenance, bounded memory;
replay báo diversity/evidence retention và trade-off. Chưa tuyên bố tăng recall.

### Q3 — Yêu cầu quan sát lại và viewpoint planner (Terra high)

Phạm vi mới dự kiến: verification/reobserve.py, navigation/viewpoints.py.

- [ ] Request có ID, object/evidence revision, reason, creation/expiry, attempts,
  budget, state và cancel reason. States queued→active→satisfied/expired/blocked/cancelled.
- [ ] Chỉ yêu cầu khi candidate có depth/hình học đủ hợp lệ và thiếu góc nhìn hoặc
  label evidence; loại request từ geometry invalid/stale hoặc đã hết ngân sách.
- [ ] Sinh tối đa12 poses/request từ observed-free reachable space trên NavMap hiện
  hành; camera mount cố định, không giả robot có pitch/gimbal. Lọc FOV, khoảng cách,
  đường đi, footprint/clearance. Không có pose hợp lệ thì blocked, không ép di chuyển.
- [ ] Rank minh bạch: feasible → dự đoán visibility/diversity → path cost; chưa dùng
  weighted information gain giả calibrated. Không truy vấn semantic mesh/navmesh GT.
- [ ] Goal lưu world coordinate, revalidate theo nav revision; không lệch theo origin
  local map. Object merge/move, episode đổi hoặc request stale phải cancel/replan.

Gate: tests unreachable/unknown corridor/camera FOV/origin shift/stale aliases;
shadow ghi viewpoints và lý do, không phát command. Shadow không chứng minh lợi ích
của những góc nhìn chưa thực sự được quan sát.

### Q4 — Arbiter với frontier và capture thật (Terra high; independent review)

Phạm vi: navigation/controller.py, runtime/coordinator.py và launcher/config.
Main là writer duy nhất phần integration; safety.py không nới bất kỳ gate nào.

- [ ] Modes off / shadow / active; off tương đương baseline; shadow chỉ log.
- [ ] Một goal owner/arbiter: frontier hoặc reobserve; không có hai controller cùng
  phát lệnh. Frontier goal có quy tắc suspend/resume/revalidate rõ ràng.
- [ ] Ngân sách đề xuất:1 active request, tối đa3 attempts/object/episode,
  tối đa10s/attempt tính từ activation, tối đa20% episode wall time cho reobserve.
  Queue tối đa32, TTL30s; expire không xóa object. Các số là khởi điểm development.
- [ ] Timeout/no-progress/unreachable trả về frontier; safety STOP không bị override.
  Request complete chỉ khi evidence mới đúng nguồn được commit, không khi tới goal.
- [ ] Yêu cầu primary capture qua scheduler hiện hữu, không gọi simulator song song,
  không chờ detector/CLIP/room worker trong control lane. Drop/defer có reason.
- [ ] UI tối thiểu: target, reason, budget/state; label historical/fresh riêng.
  UI/export cùng revision; không tạo node room hay object giả để hiển thị request.

Gate: injected slow/crash worker, cancel/merge/reset, exhausted budgets, replay
historical và stale nav đều giữ safety; không starvation frontier. Review độc lập
trước lần active native đầu tiên, model theo độ khó, tuyệt đối không Astra subagent.

### Q5 — Ablation offline và native pilot (main + evaluator Terra)

Bốn nhánh frozen: B=baseline; M=view memory mới/passive; R=memory+reobserve;
C=memory+đổi góc nhìn an toàn theo lịch đơn giản với cùng budget (đối chứng xem
lợi ích có đến từ chọn candidate/viewpoint hay chỉ từ việc di chuyển thêm).

- [ ] Offline B/M trên cùng frames/outputs, cùng admission policy và evaluator.
  Không mô phỏng kết quả R bằng cách chọn frame tương lai chưa nhìn thấy.
- [ ] Preflight Q0–Q4; một GPU workload, không test CPU nặng trong timing run.
- [ ] Pilot development:1 scene có GT,2 start/seed đã khóa,4 modes×120s =8 attempts.
  Thứ tự modes được hoán đổi theo block; cùng body/cameras/models/time/inference caps.
- [ ] Giữ mọi failure; lỗi resource monitor vẫn incomplete dù graph có kết quả tốt.
  Dừng cohort khi phát hiện lỗi safety/provenance; fix rồi tạo cohort version mới.
- [ ] Chỉ pilot đủ triển vọng mới mở Q6; không chạy lại vô hạn để chọn run đẹp.

## 5. Đánh giá công bằng và điều kiện promotion (Q6)

Hai câu hỏi phải tách:
1. Perception trên cùng input: B/M replay với tất cả GT và exclusions cố định.
2. Embodied utility: R/C có trajectories khác; so ở cùng episode time/inference budget.

Primary embodied metric: số unique correct identities được xác nhận trong phạm vi
annotation exhaustive trước deadline. Báo precision/duplicates/false merge cùng nó.
Nếu có exhaustive whole-scene GT thì thêm scene recall; nếu không, chỉ gọi count
trong vùng đánh giá đã khóa. Không so recall với denominator visibility khác nhau
mà không báo support/coverage; conditional recall theo trajectory là metric phụ.

Secondary: thời gian đến xác nhận (gồm right-censored/unconfirmed), correct IDs/min,
known/free area (không gọi coverage% khi thiếu total GT), view novelty, request yield,
IDF1/AssA đúng scope, FP taxonomy, p95/p99 control latency, deadline misses,
RSS/VRAM/queue/drop và failed run rate. Phân tách class, scene và difficulty.

Ngưỡng đề xuất để khóa TRƯỚC evaluation, không phải kết quả hứa hẹn:
- R tăng >=20% correct identities so B và ít nhất1 identity/episode trung bình;
  precision giảm không quá2 điểm phần trăm; false merge không tăng.
- Free area đạt >=90% baseline trong cùng thời gian; reobserve time <=20% budget.
- p95 control latency tăng <=10%, deadline hiện hữu không bị nới; không vi phạm
  safety invariant, không tăng tài nguyên ngoài cap đã khai báo.
- R phải cho lợi ích so C hoặc không được kết luận cơ chế chọn view tốt hơn lịch đơn giản.

Held-out confirmatory campaign dự kiến: ít nhất3 scenes có annotation phù hợp ×
3 start/seed ×4 modes ×300s =36 attempts,180 phút simulated horizon (wall overhead
báo riêng). Dùng scene phát triển riêng, không tune trên các scenes test. Đây là
ngân sách kế hoạch khi được giao thực thi, không chạy trong lượt lập kế hoạch.
Nếu không đủ scene/GT, chỉ giao prototype và report development, không promote.
Báo paired differences theo scene/start và uncertainty, không bootstrap từng frame
như độc lập;9pairs không tự chứng minh tổng quát rộng. Kết quả chưa chắc chắn thì
thu thập thêm theo protocol mới, không tự hạ gate. Không claim toàn P10 pass.

## 6. Nhánh Q7 tùy kết quả: proposals không phụ thuộc lớp

Chỉ làm khi Q1 cho thấy detector proposal recall là giới hạn chính. Đầu tiên offline:
prototype proposals từ RGB-D/mask assets đã có, temporal linking và fusion 3D;
canonical owner vẫn quyết định identity, nhãn tách khỏi existence. So proposal recall
ở cùng candidate count/compute, oversegmentation, false merge và semantic quality.
Không đưa mask GT vào runtime hoặc gọi depth clusters là hoàn chỉnh về vật thể.
Nếu cần SAM/3D checkpoint mới phải lập yêu cầu tài sản riêng; kế hoạch này không
cho tải model hay thay detector mặc định. Chỉ viết kế hoạch online sau offline gate.
Tham khảo: https://arxiv.org/abs/2306.13631 và Any3DIS CVPR2025; không sao chép
benchmark của paper thành dự đoán kết quả NeuSymNav.

## 7. Điều phối, kiểm chứng và bàn giao

Dependency: Q0→Q1→quyết định Q2–Q6 hoặc Q7. Sau shared contracts, evaluator và
view memory có thể song song, mỗi file một writer. Luna xhigh làm inventory,
fixtures/report theo contract; Terra effort phù hợp làm core/planner/evaluation;
Sol chỉ cho vấn đề thật sự khó hoặc review cần thiết. Không dùng Astra cho bất kỳ
subagent/reviewer/fallback. Người dùng đã làm rõ Astra được phép cho main do họ chọn;
điều đó không cho worker kế thừa Astra. Đọc clarification này cùng orchestration doc.

Mỗi Q có focused tests theo cases ở trên, commands/exit codes/source hashes và
artifact paths. Tên module mới là đề xuất, kiểm tra seam thực trước khi tạo.
Full CPU trước native gate:
`PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'`.
Không cộng test cũ thành chứng nhận cho thay đổi mới.

Bàn giao: experiment profile opt-in, reproducible evaluator, bounded request traces,
source manifest, báo cáo ablation/failures và limitations. Update implementation-status
với implemented / correctness-verified / runtime-validated riêng. Default chỉ promote
khi Q6 đạt; giữ rollback bằng mode off. Không commit/push nếu chưa được giao.

## 8. Prompt thực thi sau khi người dùng giao triển khai

> Triển khai docs/active-object-perception-plan.md theo Q0→Q1 và evidence gates.
> Giữ baseline/CG+Visual/canonical owner/body/cameras và safety contracts. Tái sử dụng
> admission/verification hiện hữu, chạy shadow trước active. Main giữ shared contracts,
> một file một writer, một GPU workload. Không Astra subagent. Không training/download,
> không sửa source siblings, không tự promote/commit/push. Nếu thiếu exhaustive GT,
> hoàn thành engineering và report giới hạn, không tuyên bố quality gate đạt. Không
> chạy Q7 hoặc confirmatory campaign mù quáng khi gate trước không hỗ trợ.
