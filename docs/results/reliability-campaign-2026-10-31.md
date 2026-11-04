# Kết quả chiến dịch runtime, điều hướng và chất lượng — 2026-10-31

Đã triển khai các sửa lỗi có bằng chứng, chạy ba map mỗi map300s và một lượt
kiểm chứng sửa điều hướng90s. **Chưa đạt nghiệm thu toàn hệ thống:** RSS vẫn có
mẫu không chứng minh được;00802 vẫn chưa khám phá được đáng kể; dữ liệu chưa đủ
điều kiện fine-tune. Không che lượt lỗi hoặc suy test CPU thành runtime thành công.

CG+Visual, thân bán kính0.125m/cao1m, margin0.05m, camera RGB-D1.2m/camera nhìn
xuống2m được giữ nguyên theo xác nhận người dùng. Đây là bộ camera mô phỏng,
không phải hiệu chuẩn phần cứng robot hút bụi thực tế. Không training, tải model,
đổi hai repo nguồn, commit hoặc push.

## 1. Thay đổi đã triển khai

| Phần | Hành vi mới | Giới hạn |
| --- | --- | --- |
|RSS|Chọn RSS shared-mm từ task có VmRSS hợp lệ; lưu chẩn đoán có giới hạn|Không giả RSS thiếu thành0; vẫn có mẫu không hợp lệ khi process/task biến mất|
|GPU mapping|Chỉ response đã nhận đủ và kiểm tra hợp lệ nhưng quá250ms được bỏ trước map commit và tái sử dụng worker|Không tăng deadline; lỗi thiếu/malformed/protocol vẫn terminal; chưa chứng minh loại bỏ nguyên nhân latency|
|SQLite|Đóng tường minh5 kết nối đọc UI/export, giữ transaction và timeout|Fixture chứng minh một cơ chế giữ WAL; không khẳng định là nguyên nhân mọi WAL cũ|
|Chẩn đoán control|Telemetry ghi reason/source/thời điểm của kết quả control riêng với kế hoạch|UI DTO/overlay vẫn là last-plan, chưa có panel control riêng|
|Phục hồi điều hướng|Bằng chứng partial forward không dịch chuyển trước yaw refusal có thể kích hoạt watchdog hiện hữu|Giữ8s/20map revisions/3cm và mọi gate; không tự cho robot xoay/tiến khi thiếu an toàn|

Nhánh phục hồi chỉ nhận proof đã qua validator, khớp command/source/capture/clock/
map/pose, action/result và pose ban đầu, forward+turn dương và dịch chuyển≤1e-7m.
Proof thiếu/sai, pureturn, có tiến triển hoặc nguồn bị ngắt không được tính. Không
suy no-progress thành kết luận va chạm vật lý. Mục tiêu tọa độ thế giới đã được
latch từ trước; chưa có trace chứng minh goal bị trôi nên không sửa giả lỗi này.

## 2. Runtime thật và mọi lượt lỗi

| Lượt | Thời lượng yêu cầu | Exit/outcome | RSS hợp lệ | Bằng chứng |
| --- | --- | --- | --- | --- |
|00861 diagnostic trước sửa|300s|1/incomplete|2250/2251|Giữ nguyên lượt lỗi|
|00861 baseline sau sửa|300s|0/completed|2184/2184|4669frames,313.80s wall|
|00770 baseline đầu tiên|300s|1/incomplete|2092/2093|4139frames,312.66s wall, shutdown sạch|
|00802 baseline đầu tiên|300s|0/completed|2518/2518|4943frames,318.76s wall|
|00802 kiểm chứng phục hồi|90s|1/incomplete|796/797|1790frames,100.37s wall,400pins giữ nguyên|

Ba baseline300s hoàn tất wrapper2/3. Lượt90s riêng cũng chưa đạt; không gộp khác
thời lượng thành thí nghiệm so sánh hiệu năng. Các lượt mới đều không có runtime
worker failure; thiếu RSS vẫn làm kết quả incomplete dù shutdown sạch.
00770 mất file children giữa census;90s gặp task CUDA còn sống nhưng không có
VmRSS. Không đủ bằng chứng để bỏ process đó khỏi tổng hoặc giả số0. P1 chỉ được
xử lý một phần, không bảo đảm chạy dài luôn thành công.

Lượt90s ghi nhận hai goal_failed_no_progress:yaw_preflight_no_progress và năm
watchdog release theo nhánh collision-wait cũ. Điều này xác nhận nhánh phục hồi
mới chạy thật. Object WAL=0byte sau shutdown ở lượt này; không suy mọi run đều vậy.

## 3. Đo trên ba map

| Map | Quãng đường quan sát tối thiểu | Diện tích free đo được | Diện tích known | Cửa sổ10s ít tiến triển |
| --- | --- | --- | --- | --- |
|00861|8.635m|12.538m²|15.390m²|4|
|00770(incomplete)|7.979m|22.028m²|25.998m²|1|
|00802|0.326m|3.468m²|6.215m²|28|

Diện tích từ raster occupancy tích lũy5cm, complete và không coarsen; không phải
phần trăm diện tích thật của scene. Quãng đường là tổng các đoạn endpoint quan
sát được, không phải tích phân đầy đủ: missing command proof lần lượt610/21/0;
ngay cả0 missing cũng chưa chứng minh mọi chuyển động giữa mẫu. Low-progress
window có thể có quay tại chỗ, không tự chứng minh collision.

Control kết quả bao phủ3392/2896/3665 lần gọi tương ứng. Planner reason có mẫu
riêng3388/2888/3664, không cộng hai loại thành tỷ lệ va chạm.00861 có585collision-
wait decisions và5goal releases;00770 có7path_segment_blocked/5depth_stale.
00802 có3416yaw_preflight_unavailable,248executed,1sourcepending dù3664planner
reason tracking;3413 partial forward proofs trong nhóm refusal có dịch chuyển
<1micrometre. Sau sửa90s, observed lowerbound0.325420m, chưa có cải thiện khám
phá thực tế; trạng thái cuối frontiers_temporarily_suppressed_after_collision.
Cần chẩn đoán khả năng đi tới mục tiêu khác, không nới clearance để ép đi.

## 4. Detection và association offline

Chỉ00861 có semantic mesh/TXT tương ứng.00770/00802 accuracy unavailable, không
thay bằng confidence/object count. Tất cả57frame đã commit00861 được giữ lại:
230GT observations,25GT IDs,10GT classes; đây là scene phát triển, không held-out.

Ledger gốc có WAL khác0. Đã khóa owner và copy DB/WAL/assets, ghi hash gốc không
đổi, dùng owner kiểm integrity/schema/config rồi checkpoint bản phân tích. Export0,
5semantic render chunks tuần tự0, merge0, evaluate0. Không mở immutable mà bỏ WAL.
Provenance: `eval-prep/quality/00861/recovery-provenance.json`.

| Chỉ số | Kết quả | Mẫu số/phạm vi |
| --- | --- | --- |
|Detection precision/recall/F1|37.50%/23.48%/28.88%|IoU.5/conf.25;54TP/90FP/176FN|
|BBox AP50/AP50:95|13.19%/9.80%|COCO-style subset,10classes có GT|
|Mask AP50/AP50:95|14.38%/10.41%|Cùng frames, GT và prediction scope|
|Online assigned-memory IDF1|23.60%|40IDTP/69IDFP/190IDFN|
|Pairwise precision/recall|68.68%/73.53%|125/182 và125/170 matched pairs|
|ID switches/fragments|4/3|30eligible transitions|
|Revisit recovery|0/5|5first reappearances theo annotation frame sequence|

Association dùng immutable online_object_ids trong batch commit thực, không
phải replay matcher phản thực. Scope109assigned observations;34unresolved và
1unprojected loại khỏi memory scope nhưng không bỏ frame. Pairwise conditional
không thay end-to-end IDF1/detection. Detector đã lọc confidence≥.30 trước export,
nên AP bị giới hạn đầu vào. Semantic renderer loại unsupported/small/unmapped IDs;
GT chưa được audit exhaustive thủ công nên không kết luận mọi apparent FP đều
là lỗi detector. Không so khác trajectory với fixed79 để tuyên bố cải thiện.

## 5. Robot và dữ liệu fine-tune

Cấu hình/launch SHA và ACK cả3map khớp seed, scene/start/floor, body/navmesh và
sensor resolution. Margin0.05m thuộc config/planner/guard, không được echo trong
native ACK; camera transform được bind bằng launch SHA, không đo vật lý độc lập.
Chi tiết: `../robot-simulation-baseline.md`.

CPU oracles dùng planner/MotionGuard/NavMapper với strip free .20/.60m ở hai grid
phases, invalid-depth blocking và world goal qua rolling origins. Existing .45m
strip vẫn chặn unknown/thiếu clearance. Đây là synthetic geometry, chưa chứng
minh robot đi qua hành lang native có bề rộng được đo độc lập.

Đọc nội dung1400Hypersim semantic/instance HDF5 bằng C/HDF5 có sẵn, exit0; không
cài h5py.0structural errors,19instance→semantic conflicts. Mapping59class chưa
được xác nhận; quyền dùng và lịch sử split/checkpoint còn thiếu;7scene trùng pool
training cũ13class. Không biến pixel instance−1 thành background training. Chưa
fine-tune hoặc chỉnh association theo một scene. Báo cáo và review queue trong
`eval-prep/dataset-audit/`; cần nhãn/mapping/split hợp lệ trước training.

## 6. Kiểm chứng và phần chưa chứng minh

- FullCPU trước normalization cuối: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'`:2254pass/2optional skips/9deselected,exit0,131.73s.
- Review phát hiện non-dict actuator result gây diagnostic exception; RED rồi normalized control_rejected,75affected tests pass0/1.60s. Fullsuite và finaldelta là hai snapshot, không gọi fullsuite postdelta.
- Independent SQLite/config113pass0; finalnavigation163pass0 gồm19adversarial probes, scopedACCEPT. Giữ log lỗi cũ; all18shipped UI pins chỉ đổi hash script.
- Source399pins cuối +1config trong corrective native; diffcheck0. Không có actuation/yaw fallback hoặc đổi safety threshold.

Implemented và CPU correctness verified trong phạm vi trên. Runtime chỉ xác
nhận hai baseline hoàn tất, một nhánh recovery chạy thật và cleanWAL của một
lượt; chưa chứng nhận reliability, native passage, exploration gain hoặc model
gain. Blocker còn lại là RSS completeness,00802reachable motion và dữ liệu
fine-tune/GT nhiều scene. Không claim toàn bộ kế hoạch hoàn tất.

Artifacts: `.runtime/reliability-campaign-20261031/` với campaign-manifest,
final-source-pins, runtime-review/{review,followup,navigation}.md, eval-prep,
navigation-validation và named `runs/reliability-*`. Lệnh/exit nằm trong wrappers,
prepare-exits/render-exits và từng log; trạng thái trong implementation-status.

Chẩn đoán cuối00802: UI live_nav khớp chính xác pose/source cuối (khác map
hierarchy cũ được pin có chủ ý). Footprint và sweep0.1m có đủ free/floor/clearance;
sweep0.3m chứa13occupied cells. Planner với bộ nhớ policy rỗng tìm được đường
trên map tới4/4frontier. Không suy đường hình học thành robot đi được; thiếu
cooldown/visited history và lý do loại từng candidate để tái hiện policy thật.
Bước tiếp theo cần trace có giới hạn các lý do đó cùng guard/source-bound motion,
không tăng quyền đi xuyên unknown hoặc ép yaw. Chi tiết navigation-prep/report.md.
