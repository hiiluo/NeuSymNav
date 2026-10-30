# Đánh giá demo ConceptGraphs 5 phút — 2026-10-30

Đã chạy demo300giây với YOLOE-26m640×480, taxonomy-v1 và association
ConceptGraphs spatial; appearance tắt. Đánh giá toàn bộ79keyframe đã commit,
không chọn frame dựa trên chất lượng prediction. **Chất lượng detection và
association còn thấp; matcher spatial mới kém legacy trên cùng đầu vào lần này.**

## Phạm vi và độ tin cậy

- Run: `runs/demo-conceptgraphs-300s-20261030/`.
- Config: `configs/p10/demo-yoloe26m-conceptgraphs-gpu-00861.json`, SHA256
  `d3fea704fe45f56e5e4f9ab9c6dc2cce85b47b2e85ddad3ea547c2ccb3581ea2`.
- Thời lượng yêu cầu300s; wrapper gồm startup/cleanup320.964s. Control starts
  trải299.879s. Cùng scene00861, một seed; không phải benchmark nhiều scene.
- Recording4571/4571frame, missing0; gồm primary RGB-D và depth navigation.
  Chỉ79primary keyframe detector đã commit được chấm; không phải mọi raw frame.
- Có154detector outputs;137project được point cloud;108được gán online ID.
  Giữ đủ79frames/223GT observations/19GT identities trong evaluator.
-17detections không project được;29projected observations chưa gán được ID.
  Memory coverage108/154=70.13%; unresolved29/137=21.17%.
  Detector report vẫn dùng đủ154outputs. Association report là **assigned-memory
  output scope**, không phải score trên riêng các spatial matches đúng hoặc137
  projected observations có ID được bịa ra.
- GT offline được render ở đúng source pose, SHA-bound RGB-D/K/pose. Chia7batch
  liên tiếp≤12frame rồi ghép đúng đủ79frame, không bỏ frame lỗi. Tất cả strict
  alignment/calibration gates giữ nguyên; runtime không nhận semantic GT.
- GT gồm taxonomy hỗ trợ và mask≥100pixel;1855ID-frame records bị loại theo
  background/unsupported/small và có đầy đủ lý do. Đây là HM3D scoped annotation,
  không phải kiểm chứng thủ công toàn scene hay mọi vật thể có trong ảnh.

Alignment qua79frames: maxRGB MAE0.00234049byte,
maxRGBp99=0.0; maxdepth MAE
0.000006310m, maxdepthp99
0.000030637m; min depth-within-tolerance
0.999989755428. Không nới gate.

## Detection — đủ154outputs,223GT observations

Class-aware bbox IoU≥.5, confidence≥.25:

| Metric | Kết quả |
|---|---:|
| TP / FP / FN |46 /108 /177|
| Precision |29.87%|
| Recall |20.63%|
| F1 |24.40%|
| Box AP50 / AP75 |17.53% / 16.71%|
| Box AP50:95 |13.71%|
| Mask AP50 / AP75 |20.76% / 15.08%|
| Mask AP50:95 |14.16%|

| Lớp có GT | Recall | TP / FP / FN |
|---|---:|---:|
| chair | 30.88% | 21 / 20 / 47 |
| door | 15.00% | 9 / 0 / 51 |
| kitchen island | 0.00% | 0 / 0 / 12 |
| lamp | 0.00% | 0 / 5 / 8 |
| oven | 0.00% | 0 / 0 / 6 |
| table | 0.00% | 0 / 0 / 21 |
| toilet | 93.33% | 14 / 1 / 1 |
| window | 6.06% | 2 / 0 / 31 |

AP dùng101point ordinary subset trên outputs đã lọc upstream(confidence.25,
cap30); exporter giữ score_floor/max_detections null vì không tự suy metadata.
Giá trị trên lấy từ frozen captureconfig và actual detector recipe. Đây không
phải full low-score COCO AP. Các lớp không có GT không vào macroAP nhưng FP của
chúng vẫn nằm trong operating precision. Table/diningtable và các khác biệt
ontology cần audit hình ảnh; không gọi mọi unmatched label là hallucination,
không sửa alias hay GT để nâng score này.

## Association —108assigned observations, toàn bộ223GT

Online IDs lấy trực tiếp từ batch association.online_object_ids bất biến.
Finalaliases lấy từ final snapshot. Lần này online và final score bằng nhau.
Không dựng lại online history từ các cột IDs đã bị canonical merge ghi đè.

| Metric | Kết quả | Support |
|---|---:|---|
| IDF1 |25.98%|IDTP43 /IDFP65 /IDFN180;86/331|
| HOTA |22.28%|19alpha thresholds|
| AssA |29.45%|cùng HOTA protocol|
| DetA |17.16%|cùng108pred/223GT|
| LocA |85.99%|chỉ hỗ trợ localization của matched pairs|
| Conditional pair precision |80.99%|115/142matched-observation pairs|
| Conditional pair recall |52.51%|115/219matched-observation pairs|
| False-merge / split pairs |27 /104|cặp quan sát, không phải số object merge/split operations|
| ID switches / fragments |6 /8|33eligible transitions|
| Revisit recovery |30.00%|3/10eligible first reappearances|

Có43predicted identities cho108assigned observations,52spatially matched
observations và19GT identities. Không suy43-19là số object trùng: còn FP, thiếu
GT scope và fragmentation. HOTA adapted cho object-memory bbox, không phải
submission MOT chính thức. Revisit tính khoảng vắng mặt trong chuỗi annotated
keyframes, không phải giây hoặc mọi sensor frame.

## Đối chứng cùng137point clouds

Replay dùng đúng nguồn quan sát/timestamp và không đọc GT khi association.
Mỗi matcher được chấm đầu ra memory có ID của chính nó, giữ đủ79frames/223GT;
phần chưa gán ID luôn được báo riêng. CGreplay tái tạo chính xác phân hoạch ID
online thực tế trước khi so score. Không có appearance feature trong inputs.

| Metric | Legacy geometry | ConceptGraphs spatial |
|---|---:|---:|
| Assigned / unresolved |119 /18|108 /29|
| IDF1 |26.90%|25.98%|
| HOTA |25.81%|22.28%|
| AssA |34.34%|29.45%|
| DetA |19.72%|17.16%|

Đây là đối chứng offline cùng input cho một run; không phải hai live trajectories
hoặc bằng chứng tổng quát. Cấu hình CGspatial hiện tại chưa nên thay default.
Không tune threshold trên chính run này rồi gọi đó là held-out improvement.
So với pilot12frames cũ, đầu vào/đường đi/lớp/denominator đã đổi nên score chênh
lệch không tự chứng minh model hay toàn hệ thống tốt/xấu đi.

## Geometry — observed RGB-D surface proxy

GT cloud dựng từ semantic mask đã aligned cùng recorded valid depth/K/pose;
predicted cloud hợp các108assigned observations trong79frames theo final IDs.
Không dùng unobserved mesh hoặc final whole-episode geometry vượt scope này.
Voxel2cm/cap20000points mỗi object, bounds lấy trước sampling; cap không bị chạm.
Cùng depth/pose làm input nên đây là mask/projection/fusion consistency proxy,
không phải độ chính xác sensor/pose hoặc full-object reconstruction.

| Metric | Kết quả |
|---|---:|
| Predicted / GT observed objects |43 /19|
| TP /FP /FN tại3DAABBIoU≥.25 |9 /34 /10|
| Instance precision / recall /F1 |20.93% / 47.37% / 29.03%|
| Mean matched3DIoU |0.5908|
| AABB-center error median /p95 |0.1659m /0.4911m;9matches|
| Matched surface pointF1@5cm |86.79%|

PointF1 chỉ pooling9matched pairs(11119pred/23701GT sampledpoints); unmatched
objects vẫn làFP/FN trong instance metric, không được tính vào pointF1 này.
Có5geometric duplicate predictions theo protocol; không gọi đây là mọi duplicate
trong scene. Derived geometry inputs/report và sampling counts được lưu riêng.

## Vận hành và trạng thái incomplete

- Control invocation rate=11.11Hz, gồmSTOP/pending;
  intervalp95=164.99ms,3333intervals.
-3044results ghi executed,281expired_or_zero,9yaw_preflight_unavailable.
- Quãng đường body quan sát được **ít nhất9.38m**;
 9goal-arrival events,2confirmed no-progress recoveries; không phải kiểm chứng
  độ chính xác khoảng cách đến từng goal hay exploration completion.
- Capture→detector return median494.45ms/p95656.25ms;
  capture→object commit median670.80ms/p95916.72ms,79results.
 37semantic_stale events cho thấy độ trễ semantic cần cải thiện; không đổi TTL.
- RSS sampledpeak3.28GiB/GPU sampledpeak670MiB; không thấy capbreach. Có
 **1RSS readerror** nên resource complete/boundedness_certified=false,
 overall outcome=incomplete và native command exit1. Runtime/recording vẫn clean
 shutdown, không có runtime worker failure, raw missing0.
-117source/config pins giữ nguyên. Không rerun để giấu lỗi đo resource; không
  claim P10/20Hz/full runtime acceptance từ lần chạy này.

## Các bước cải thiện có căn cứ

1. Tập trung detection recall: door/window còn82FN, chair47FN; tổng129/177FN.
   Audit ảnh/ontology rồi đo PR và so checkpoint trên cùng ảnh, trước khi chọn
   threshold production. Hạ confidence có thể làm tăngFP vốn đang cao.
2. Khôi phục appearance có provenance và checkpoint tương thích, rồi so spatial
   và spatial+visual trên fixedinput/hardrevisit; fullvisual hiện chưa đo được.
3. Audit các29unresolved cases và lỗi split/merge. Thử giữ centroid/AABB làm tín
   hiệu phân biệt, hoặc kiểm chứng sampling/tolerance trên validation split;
   chưa có bằng chứng3cmtolerance là nguyên nhân duy nhất, không nới mù quáng.
4. Audit17projection losses, depth-edge contamination và cloud duplication;
   pointF1 cao trên matched objects không bù được34unmatched predictions.
5. Giảm capture→commit latency và làm resource sampler ổn định, giữ safety/TTL;
   mở rộng nhiều scene/seed với fixed split trước khi chọn default.

## Artifacts, commands và verification

Local evidence: `.runtime/quality-five-minute-20261030/` gồm request/config/source
pins, native result/exit, full exporter, memory-support/exclusions,7requests/
renderedGT và mergedmanifest, detector/memory/geometry reports, fixed79comparison,
helper scripts và independent audit. Dataset/model/source siblings giữ chỉ đọc;
không training/install/download/publish, không sửa production source.

Native300s exit1 như giải thích ở trên; export, memoryprep, semanticprepare,
7native renders, merge, detection/memory/geometry evaluators và fixedinput replay/
comparison đều exit0. Existing evaluator implementation đã có kiểm chứng trước;
lần này không tái gán fulltests cũ thành một fullsuite mới. Helper batch CPUfixture
13frames12+1 kiểm rejection/sourcebinding và merge trước khi dùng79frames thật.
Independent actual-artifact audit được lưu cùng báo cáo với scope/giới hạn riêng.

Independent actual-artifact audit PASS(exit0):79source frames/order và117source
pins;154detector/108memory/223GTmasks cùng bbox/shape/hash;137typedprojection
events, immutableonlineIDs và exact17+29exclusions được kiểm tra. Independent
globalIDF1 tái tạo43/65/180=86/331 cho online/final. Kiểm tra denominator và
arithmetic19HOTAalpha, không claim viết lại toàn bộ HOTA độc lập trong audit này.
Xem `.runtime/quality-five-minute-20261030/audit/result.json` và `audit/report.md`.
