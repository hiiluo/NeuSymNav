# Detection fine-tuning readiness — 2026-10-30

**Chưa train-ready.** Đã kiểm kê và xuất bộ annotation candidate để review;
không training, tải/cài thêm, chạy GPU hoặc thay runtime/GT online. Không có
bằng chứng fine-tuning sẽ cải thiện detector. Thực thi dưới đây chỉ chuẩn bị dữ
liệu, không khởi động lại các chiến dịch training của repo nguồn.

## Tài sản thực có

Evidence: `.runtime/detection-improvement-20261030/training-readiness/`.
`inventory.json` ghi đường dẫn tuyệt đối, byte size, SHA256 của scene/model/recipe,
counts và blocker; `hypersim-source-hashes.json` hash toàn bộ file trong phạm vi
`../NewOH3DSG/data/m3-adaptation/` (4.315 file, 142.306.686 byte).

| Nguồn | Hiện trạng được kiểm chứng | Giới hạn |
| --- | --- | --- |
| HM3D 00861-GLAQ4DNUx5U | basis GLB + semantic GLB + semantic TXT có thật, đã hash | Một scene đã dùng phát triển |
| HM3D 00337-CFVBbU9Rsyb / 00770-NBg5UqG3di3 | basis GLB có thật, đã hash | Không có semantic GLB/TXT tương ứng trong thư mục scene local; không suy semantic từ geometry |
| Fixed79 / 00861 | 79 RGB 640×480, 223 GT masks, 19 instance IDs, 8 lớp | Frames tương quan, annotation chưa được audit thủ công đầy đủ |
| Hypersim local | 1.400 RGB + 1.400 semantic HDF5 + 1.400 semantic_instance HDF5, 14 scene; 1.400 triplet khớp đường dẫn | Chỉ xác nhận tồn tại/hash/path pairing; chưa đọc/validate HDF5 content, NYU mapping, rights hoặc split history |
| Local checkpoints | YOLOE-11s, 26s, 26m segmentation; FastSAM-s; YOLO-World; legacy `selected-59-checked.pt` và `trained59-diagnostic.pt` | Hash/existence không chứng minh architecture/class compatibility hoặc chất lượng |
| Text encoders | `mobileclip_blt.ts`, `mobileclip2_b.ts` | Local file có thật; trainer lifecycle chưa chạy |

Hypersim scene IDs và group ghi đầy đủ trong inventory. Legacy recipe đang chỉ
13 lớp, `diagnostic_only: true`, absolute paths từ checkout cũ và custom bitmap
loader; không thể gọi là dataset NeuSymNav hợp lệ hay dùng nguyên recipe để train.
Không kế thừa kết quả hay quyền thực thi từ các run cũ.

**Taxonomy hiện tại có 59 lớp, không phải 60.** Ordered names được xuất nguyên
vẹn vào `taxonomy-names.json`; SHA256 taxonomy
`04596183aa090cf6d0e561c6d4e469dafca11574f2d21f08202971c3436a2603`.
Không thêm background thành lớp thứ 60. COCO category IDs là 1..59; Ultralytics
labels phải chuyển sang 0..58 đúng thứ tự, không remap theo support.

GT support: chair 68, door 60, window 33, table 21, toilet 15, kitchen island 12,
lamp 8, oven 6; 51 lớp còn lại không có GT support trong fixed79.

## Candidate phục vụ review

`candidate-review/annotations.coco.json` gồm boxes XYWH, area và uncompressed
COCO RLE (Fortran order), 79 PNG source RGB và 223 annotations. Mỗi annotation
có `annotation_review_status: unreviewed`; `info.training_ready=false`.
`source-bindings.json` giữ source/geometry/timestamp/calibration/pose/vocabulary
provenance, source hashes và từng mask hash. RGB được lấy qua readonly committed
ledger `_inputs`, không dùng ảnh prediction overlay. Đã roundtrip 223 RLE, khớp
223 bbox với mask và kiểm tra 223 mask SHA256. Không tạo split/train YAML.

Đây là candidate review offline, không phải nhãn exhaustive đã xác nhận. GT gốc
bỏ unmapped/unsupported/background/small IDs theo policy evaluator; nếu dùng ngay
làm training, vật thể bị bỏ có thể bị học thành background sai. Review cần kiểm
tra door/window geometry và vocabulary (table/dining table, lamp/floor lamp),
missing instances, visibility/occlusion, boundaries, vùng ignore và completeness.
Giữ nguyên GT đánh giá gốc; annotation sửa phải có version/reviewer/change log
riêng. Ultralytics segment loader không nhận trực tiếp uncompressed COCO RLE:
cần converter instance-preserving có kiểm chứng holes/disconnected masks hoặc
bitmap loader được review trước. Chưa viết converter/train dataset.

## Bàn giao thu thập và nghiệm thu dữ liệu

1. Đóng băng taxonomy, annotation policy, source/license manifest và scene registry.
   Giữ 00861/fixed79 là development; tuyệt đối không gọi là held-out test.
2. Kiểm tra 1.400 local Hypersim triplets bằng HDF5 reader có sẵn/được phép trong
   bước sau: shape/alignment, valid IDs, instance-to-semantic consistency,
   provenance, NYU-to-59 mapping từng lớp, ambiguous/unsupported IDs và annotation
   completeness. Không tự ánh xạ many-to-one để làm metric đẹp. Xác minh split
   history của các checkpoint cũ trước khi cân nhắc chúng cho baseline.
3. Đối với HM3D 00337/00770, thu trajectory RGB-D/pose/calibration/source hashes
   bằng runtime hiện hữu, ở những viewpoint khác nhau, rồi annotation thủ công
   nếu không có semantic mesh được cấp phép. Không giả lập semantic annotation
   từ GLB RGB. Collection/runtime mới vẫn là công việc tiếp theo chưa thực hiện.
4. Đăng ký train/validation/test theo **scene/building**, trước khi tune. Tất cả
   frame/camera/trajectory/near-duplicate của cùng scene ở cùng split. Cross-scene
   RGB dedup dùng hash + near-duplicate review; scene aliases cùng building cũng
   không được lọt qua split. Validation chọn hyperparameters/confidence; test chỉ
   mở sau khi recipe/checkpoint/thresholds đóng băng. Existing14 Hypersim scenes
   từng được dùng ở sibling nên không tự coi là test độc lập của legacy weights.
5. **Đề xuất khởi đầu, không phải measured requirement hay bảo đảm:** khoảng
   1.000–3.000 keyframes sau dedup từ ít nhất 10–20 scene, nhiều instances và
   viewpoint cho door/window/chair/table; nhắm 100–300 reviewed instances cho mỗi
   lớp ưu tiên trên nhiều scene. Có thể bắt đầu thí điểm nhỏ hơn để ước lượng
   learning curve. Lớp hiếm/zero-support phải báo riêng; không claim đủ cả59 lớp.
6. Publish dataset manifest nội bộ với input/output SHA, reviewed status, converter
   version, exact class IDs, scene-disjoint assertions và per-class/size/occlusion
   counts. So sánh base và tuned trên cùng held-out sources bằng AP50:95 mask/box,
   PR/support; giữ fixed79 diagnostic riêng. Chỉ promote sau bounded runtime
   latency/memory proof, không từ training loss.

## Command template sau khi dataset hợp lệ và training được giao

Môi trường hiện có `.runtime/detector26/bin/python`, Ultralytics **8.4.24**.
Installed source có `YOLOEPESegTrainer` cho linear-probe segmentation. Đây là
**template chưa chạy**, không chứng nhận trainer/checkpoint hay GPU memory đã pass.
Hyperparameters dưới đây là proposal. `approved-dataset/data.yaml` phải có
`path/train/val/test/names` hợp lệ, exact59 names, reviewed polygons/bitmap adapter
và split assertions. Không trỏ template vào candidate79.

```bash
# Từ root NeuSymNav; chỉ chạy sau khi dataset/training được giao.
mkdir -p .runtime/detection-finetune-approved/work
ln -s /home/hiiluo08/Works/NeuSym-Nav/NewOH3DSG/data/models/yoloe/mobileclip2_b.ts \
  .runtime/detection-finetune-approved/work/mobileclip2_b.ts
cd .runtime/detection-finetune-approved/work
YOLO_AUTOINSTALL=false /home/hiiluo08/Works/NeuSym-Nav/NeuSymNav/.runtime/detector26/bin/python - <<'PY'
from pathlib import Path
import json
import yaml
from ultralytics import YOLOE
from ultralytics.models.yolo.yoloe.train_seg import YOLOEPESegTrainer
root = Path('/home/hiiluo08/Works/NeuSym-Nav/NeuSymNav')
data = root / '.runtime/approved-dataset/data.yaml'
assert data.is_file(), 'reviewed dataset missing'
# Validate data.yaml names against taxonomy first, using the dataset gate.
names = json.loads((root / 'configs/taxonomy-v1.json').read_text())['categories']
assert len(names) == 59
cfg = yaml.safe_load(data.read_text())
actual = cfg['names']
if isinstance(actual, dict):
    actual = [actual[i] for i in range(len(actual))]
assert actual == names, 'dataset taxonomy/order mismatch'
model = YOLOE('/home/hiiluo08/Works/NeuSym-Nav/NewOH3DSG/data/models/yoloe/yoloe-26m-seg.pt')
model.train(data=str(data), trainer=YOLOEPESegTrainer,
            epochs=20, batch=1, imgsz=640, workers=0, device=0,
            optimizer='AdamW', lr0=1e-4, seed=0, deterministic=True,
            amp=False, cache=False, plots=False,
            project=str(root / '.runtime/detection-finetune-approved'),
            name='linear-probe-seed0', exist_ok=False)
PY
```

Chạy trong network-denied environment; `YOLO_AUTOINSTALL=false` chỉ chặn
requirements auto-install, không đảm bảo chặn mọi download. Text encoder symlink
cần khớp checkpoint `text_model`; fail nếu thiếu asset/dependency, không fallback
đến download. Có thể cần sửa recipe sau CPU initialization smoke được giao.
Một GPU owner tại một thời điểm; chưa có workload training nào trong lượt này.

## Trạng thái và lệnh kiểm chứng

Implemented: inventory + isolated candidate review export + reproducible helper.
Correctness-verified: source binding/mask hashes/RLE/bbox checks; **không** chứng
nhận annotation quality, HDF5 contents, valid independent split hay training.
Runtime-validated: chỉ offline CPU export, không detector/GPU/training runtime.

```bash
.runtime/detector26/bin/python \
  .runtime/detection-improvement-20261030/training-readiness/prepare_review.py
# exit 0: 79 frames, 223 annotations, 19 IDs, 59 categories,
# 1,400 Hypersim matched triplets / 14 scenes.
```

`verification.json` lưu assertions. `commands-exits.json` ghi cả lỗi thăm dò
`python` không tồn tại (exit127), sau đó dùng interpreter local thành công.
Mọi file nguồn và sibling chỉ đọc. Blockers cụ thể có trong `inventory.json`.
