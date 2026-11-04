# Kết quả hoàn thiện và fine-tune — 01/11/2026

Đã huấn luyện thật trên GPU, lưu checkpoint, đánh giá trên validation/test và
cùng 57 frame HM3D. Đã sửa hiệu chuẩn điều hướng 00802 và chạy model tuned trong
pipeline CG+Visual trên hai map. **Model base vẫn là mặc định** vì model tuned
cải thiện ở scene HM3D đang phát triển nhưng giảm điểm trên test Hypersim.

## Lệnh sử dụng

```bash
# Model base; điều hướng 00802 đã được hiệu chuẩn lại:
bash tools/run_map_demo.sh 00802 300

# Model fine-tuned thử nghiệm, GPU + CG+Visual:
bash tools/run_finetuned_demo.sh 00861 300
bash tools/run_finetuned_demo.sh 00802 300
# Có thể thêm tham số thứ ba là thư mục output mới.
```

Checkpoint: `.runtime/finetune-20261101/training-detection/epoch-01.pt`.
SHA256: `13edea274868fc7fdb4c5284578ba8ee9dc671dcdd5aac96749745f929972221`.
[Model card](../models/yoloe11s-hypersim-head-2026-11-01.md) ghi recipe và giới hạn.

## Fine-tune và dữ liệu

Bộ dữ liệu local gồm 1.400 triplet RGB/semantic/instance thuộc 14 scene, tách
900 train / 300 validation / 200 test theo scene (9/3/2). Đã kiểm hash, shape,
partition của 4.200 bitmap và đối chiếu HDF5 nguồn theo từng scene. Mask giữ nguyên
instance; vùng void, unsupported hoặc xung đột là ignore. Chỉ wall/floor/ceiling
được dùng làm nền có chứng nhận. Không pseudo-label hoặc biến unknown thành nền.

Có 25 mapping vào taxonomy 59 lớp; **20 lớp có mẫu dương trong train**. Bed,
bookcase, curtain, dresser và nightstand không có mẫu dương. Loss bỏ qua những
channel chưa được hỗ trợ và các pixel ignore; model vẫn xuất đủ 59 lớp. Đã sửa
sai lệch sampling PIL/Torch và tách eligibility của box/mask sau review độc lập.

- Thử nghiệm A: 6 epoch, 2.700 optimizer steps, head adaptation. Pipeline hoàn tất
  exit 0 trong 457,04 giây, source pins giữ nguyên. Validation bbox tốt hơn nhưng
  mask giảm; checkpoint base thắng tiêu chí lựa chọn, nên không promote.
- Thử nghiệm B: 2 epoch, 900 steps, AdamW 1e-4, batch 2, seed 0, từ original base.
  Chỉ cập nhật cv2/cv3/cv4; backbone và proto/cv5, kể cả BN buffers, được khóa và
  kiểm hash không đổi. Exit 0 trong 208,73 giây. Validation mask AP chọn epoch 1
  (450 steps, 900 training examples) trong các ứng viên base/epoch1/epoch2.

QC dữ liệu đã đọc nhãn test để kiểm cấu trúc. Script A tính test sau selection
của A; main không sử dụng kết quả đó để thiết kế B, mà dựa trên validation.
Không gọi test là chưa từng được mở/tính trong cả chiến dịch. Không tune thêm
sau khi xem kết quả test của B. Exposure trong pretraining gốc chưa được chứng minh.

## Kết quả độ chính xác

AP50:95 theo subset protocol, so model trong từng dòng:

| Phạm vi | Bbox base → tuned | Mask base → tuned |
| --- | --- | --- |
| Validation: 300 frame, 14 GT classes | 20,91% → 23,74% | 25,87% → 26,03% |
| Test: 200 frame, 7 GT classes | 15,01% → 11,82% | 10,33% → 7,54% |
| HM3D 00861: cùng 57 frame, 10 GT classes | 12,20% → 20,59% | 12,56% → 14,68% |

Mức tăng validation mask chỉ 0,153 điểm phần trăm; chưa có chứng minh ý nghĩa
thống kê. Hypersim dùng full-resolution bitmap, spatial/class ignore, confidence
floor 0,05 và maxDet 100. Eligibility IoU 0,5 được giữ qua các ngưỡng AP 0,5–0,95;
đây không phải COCO ignore matching chính thức. Các split có class support khác nhau.

Replay HM3D giữ đủ 57 frame theo cùng thứ tự/source hashes, kể cả bốn frame có
old predictions rỗng, cùng encoder/taxonomy/evaluator và 230 GT observations.
Suy luận không nhận GT; recipe chỉ khác checkpoint. Tại confidence 0,3:

| Chỉ số | Base | Tuned |
| --- | --- | --- |
| TP / FP / FN | 54 / 90 / 176 | 92 / 159 / 138 |
| Precision | 37,50% | 36,65% |
| Recall | 23,48% | 40,00% |
| F1 | 28,88% | 38,25% |

Tuned giảm bỏ sót nhưng tăng false positives trên scene này. HM3D là development
scene và annotation có giới hạn, không phải held-out benchmark mới. Box protocol
Hypersim và HM3D khác nhau; không so điểm giữa các miền để suy chất lượng chung.
Test regression là lý do giữ base mặc định, cung cấp tuned như lựa chọn thử nghiệm.

## Điều hướng 00802

Đã sửa việc extractor chọn lại viewpoint đang cooldown, kể cả khi ID cooldown
500 revision dài hơn spatial cooldown 100 revision. Giữ nguyên TTL, world-goal
latch và phân biệt failed với visited. Các kiểm tra liên quan 119 pass, review
độc lập 101 pass. Telemetry có candidate reason/provenance với giới hạn số lượng.

Sau sửa policy, robot vẫn chỉ đi 0,326 m trong 300 giây. CPU rebuild navmesh và
các endpoint dựng lại cho thấy cặp spawn Y=0,124 / cell height=0,20 không khớp
với dải chiều cao cố định ±5 cm. Chỉ giảm cell height cũng chưa đủ: phải hiệu
chuẩn vị trí khởi đầu cùng navmesh. Raw path queries chỉ dùng chẩn đoán, không
được coi là chứng nhận guard hay chuyển động thật.

Profile được kiểm chứng dùng cell height 0,01 m và fixed initial Y=0,0010702843,
cùng XZ, bán kính 0,125 m, thân cao 1 m, margin 0,05 m. Offset tới floor RGB-D đã
đo khoảng 5,64 mm. Giữ nguyên fixed-Y/slab, unknown, depth, clearance và yaw gates;
không đưa navmesh vào mapper. Request/ACK có version, kiểm actual precision/pose.
Camera mount vẫn 1,2 m/2 m; world height giảm 12,293 cm theo vị trí khởi đầu.
Đã thu RGB-D/map/guard/proof mới để kiểm chứng cấu hình đó.

Native qualification đi được **3,175 m trong 120 giây**, exit 0, RSS 963/963.
Sau đó profile 00802 thông thường được thay bằng file byte-identical với profile
qualified đã chạy; model base không đổi. Bản trước sửa được giữ trong artifact.

## Các lượt runtime mới

| Lượt | Yêu cầu / wall | Exit | RSS support | Translation lower bound | Commits / CLIP frames |
| --- | --- | --- | --- | --- | --- |
| 00802 sau policy fix, base | 300 / 318,06 s | 0 | 2395/2395 | 0,3255 m | 11/11 |
| Qualified profile lần đầu | startup 1,01 s | 1 | unavailable | unavailable | unavailable |
| 00802 paired qualification, base | 120 / 132,75 s | 0 | 963/963 | 3,1754 m | 14/14 |
| 00861 tuned | 60 / 71,64 s | 0 | 524/524 | 2,4390 m | 17/17 |
| 00802 tuned + paired | 60 / 70,72 s | 0 | 515/515 | 2,2385 m | 9/9 |

Lượt startup lỗi do validator launcher chưa nhận optional field; đã giữ stderr,
viết test RED, sửa validator closed-v1 và review lại. Không bỏ lượt lỗi. Bốn lượt
thực sự khởi chạy đều shutdown sạch, không worker failure, source pins giữ nguyên.
Ba lượt cuối dùng CLIP feature thật và không có geometry fallback.

Quãng đường là tổng endpoint quan sát được, chưa phải tích phân đầy đủ. Thời lượng
và quỹ đạo khác nhau nên không coi tỷ lệ khoảng đường là speed benchmark hay
causal model gain. Không suy detection/room/association accuracy từ số commit.

RSS vẫn là phép đo /proc có thể thiếu mẫu khi process thoát. CPU lifecycle probe
và 149 tests không chứng minh atomic census; giữ unknown=null, không tăng retry,
TTL hay hạ gate. Các incomplete của 31/10 vẫn được giữ. Không tuyên bố mọi run
dài đều có resource certificate hoặc toàn hệ thống đã qua nghiệm thu P10.

## Kiểm chứng cuối và artifacts

- Independent loss/data/trainer review; 5 gradient tests trong detector environment;
  actual-model 59-prompt forward/backward/checkpoint oracle; GPU train thực 8 epoch.
- Precision worker/client: 220 focused và independent checks; launcher config sau
  sửa: 53 pass. ACK thiếu/sai/muộn bị chặn. Sensor-worker pins được cập nhật trong
  75 profile; chỉ thay hash trước khi thêm qualification/profile mới.
- Full CPU cuối: **2290 passed, 3 skipped, 9 deselected, exit 0, 138,80 s**.
  Lệnh: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'`.
  Host không có Torch nên loss tests chạy riêng; hai skip còn lại là optional
  Numba và GPU worker cần slot riêng. Diff check cuối exit 0.
- Native chạy trước alias promotion 00802; alias có nội dung byte-identical với
  cấu hình đã chạy. Full CPU cuối chạy sau promotion. Không có source delta khác.

Artifacts ở `.runtime/finetune-20261101/`: `completion-manifest.json`,
`final-source-pins.json`, `dataset/README.md`, hai thư mục training, các
`*training-exit.json`, `hm3d-exits.json`, `review/`, `navigation-native-rootcause/`
và `native-*` request/result/exit/log. Recording/proofs/map nằm trong các `runs/`
được manifest chỉ rõ. Checkpoint là artifact local, chưa commit/push/publish.

CG+Visual, canonical ID owner, point cloud và hierarchy Floor–Room–Object được
bảo toàn. Profile tuned 00770 đã validate config nhưng chưa có native run mới.
Giới hạn còn lại là khả năng tổng quát của model, GT nhiều map và RSS atomicity;
không ghi chúng thành đã chứng minh chỉ vì training hoặc unit test thành công.
