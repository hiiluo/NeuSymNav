# Đo chất lượng object detection và association

Bộ đánh giá offline, không đưa semantic GT vào runtime. Kết quả phân biệt
synthetic (kiểm tra công thức) và recorded (quan sát thật có annotation độc lập).
Không dùng test-pass, confidence hoặc số node làm accuracy.

## Chạy ví dụ có đáp án biết trước

```bash
PYTHONPATH=src .venv/bin/python -m neusymnav.cli evaluate-quality \
  --gt configs/evaluation/quality-example/gt.json \
  --predictions configs/evaluation/quality-example/predictions.json \
  --out .runtime/quality-example-new
```

Output gồm `report.json` và `report.md`. Output directory phải mới/rỗng để không
ghi đè evidence cũ. Ví dụ này là analytic synthetic, không phải accuracy model.

## Chuẩn bị dữ liệu từ ledger thật

```bash
PYTHONPATH=src .venv/bin/python -m neusymnav.cli export-quality \
  --ledger runs/demo-yoloe26m-640x480-gpu-20261030-104928-497271978/objects \
  --scene-id 00861-GLAQ4DNUx5U \
  --recording-manifest runs/demo-yoloe26m-640x480-gpu-20261030-104928-497271978/keyframes/recording/manifest.json \
  --taxonomy configs/taxonomy-v1.json \
  --max-frames 100 \
  --out .runtime/object-quality-annotation-new
```

Xuất theo thứ tự nguồn, giữ cả batch rỗng và detection không project được.
`predictions.json` chứa ảnh nguồn/mask binding, confidence và identity nếu có;
`previews/` hỗ trợ kiểm tra annotation. `ground-truth-template.json` khởi đầu
**annotated=false**. Không lấy predicted mask/ID làm GT. Cần annotation độc lập
hoặc semantic render offline đã chứng minh alignment với đúng camera/scene.

GT objects cần `id` bền theo object thật, `label` theo taxonomy đóng băng,
`bbox=[x1,y1,x2,y2]` half-open pixel và mask boolean cùng kích thước ảnh. Mask
có thể là danh sách 2D hoặc `{path,sha256}` của NPY bool không pickle. Đánh dấu
`annotated=true` chỉ khi frame đã được gán nhãn đầy đủ trong scope đã công bố.
Frame annotated=true/objects=[] là thật sự không có object thuộc scope.

Hai file phải có cùng binding và toàn bộ chuỗi frame/source hashes, geometry,
timestamp, kích thước. Prediction thiếu phải có status=missing và objects=[];
không xóa frame để tăng recall. Partial/failed/missing được đếm trong báo cáo.

## Các chỉ số

| Nhóm | Chỉ số | Cách dùng |
|---|---|---|
| Detection | TP/FP/FN, precision/recall/F1 tại threshold | Phân biệt báo nhầm và bỏ sót |
| Box/mask | AP50/AP75/AP50:95 và per-class | Phân biệt nhãn/lọc confidence và localization/segmentation |
| Geometry | Volume và XY IoU độc lập, observed recall, duplicates | Đo object map; không coi footprint là thể tích |
| Geometry | AABB-center error median/p95, cloud P/R/F1 tại epsilon | Kiểm projection/fusion và lẫn nền |
| Identity | IDF1, online/final riêng | Giữ identity qua chuỗi quan sát; tính cả FP/FN |
| Association | Pairwise P/R, false-merge/split pairs | Gộp nhầm hay tách trùng; chỉ trên observations đã geometric-match |
| Temporal | Switches, visible fragments, revisit recovery | Lỗi continuity và nhận lại object sau mất quan sát |

AP là subset 101-point ở IoU .50:.05:.95, không có crowd/ignore/area bins của
COCO đầy đủ. Chỉ dùng prediction được cung cấp: upstream threshold/cap làm mất
kết quả không thể khôi phục. Ledger không ghi threshold/cap đáng tin thì giữ
null, không lấy minimum observed confidence làm score floor. Muốn so AP model
đầy đủ cần replay detector cùng input với score floor/cap đã chốt từ trước.

Identity matching dùng geometry độc lập nhãn để không che association tốt bằng
lỗi nhãn. Standard IDF1 tích lũy mọi cặp trajectory đủ IoU trước global identity
assignment; các diagnostics pairwise/switch dùng local matching đã khai báo.
HOTA/AssA nằm ở `association.tracking`: global soft alignment, Hungarian trước
lọc alpha, trung bình 19 mức IoU .05:.05:.95 theo protocol TrackEval được pin.
Đây là adaptation bbox class-agnostic cho object memory, không phải chứng nhận
benchmark dataset chính thức. Alias làm hai observations cùng frame trùng final
ID thì final HOTA unavailable, không tự deduplicate. Không dùng GT chưa từng
visible làm FN của detector từng frame.

Ledger rewrite ID sau merge nên bản xuất có identity_semantics=
`final_canonical_only`: **không có online IDF1 lịch sử**. Input độc lập có IDs tại
thời điểm phát hành có thể dùng `online`; final_aliases chỉ áp vào phần final.
Prediction không có identity không được tự cấp ID từ GT; identity metrics sẽ
unavailable. Gaps của revisit đếm annotated frames vắng object, không phải giây.

Geometry cần `geometry_objects` và cùng `geometry_scope` ở hai file: bounds
canonical Z-up mét, optional observed-surface points. GT chỉ gồm objects từng
quan sát trong scope này. `scope_gt_ids` riêng để đo object-count scene coverage.
Không lấy partial predicted cloud so toàn bộ mặt sau chưa quan sát rồi gọi đó
là lỗi reconstruction. Thiếu cloud của match nào thì aggregate cloud unavailable.

## So sánh cải thiện

1. Khóa recording, frame scope, GT, taxonomy, model/config hashes và thresholds.
2. Chạy detector-only trên cùng ảnh; không so hai trajectory khác nhau.
3. Chạy association với GT observations offline để tách lỗi detector khỏi matcher.
4. Chạy end-to-end, xuất hai report cùng input và xem per-class/per-scene/error cases.
5. Chọn threshold trên development scenes, không tune trên bộ test cuối.

Báo số samples/objects/frames, scene/seed và các scope exclusions cùng metric.
Nếu cần confidence interval cho AP/IDF1, bootstrap theo scene/sequence, không coi
hàng nghìn adjacent frames là independent samples. Chưa áp một ngưỡng pass quality
chung: lấy baseline có GT trước, chọn tradeoff từ mục tiêu ứng dụng.
