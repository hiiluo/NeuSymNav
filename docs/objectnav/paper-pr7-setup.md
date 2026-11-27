# Baseline B0 cho ObjectNav

**B0 là baseline duy nhất cho ablation ObjectNav.** B0 dùng frontier hình học,
YOLOE và giao thức paper với hành động Habitat rời rạc. Kết quả lockstep cũ được
lưu trong [bàn giao lịch sử](b0-baseline-handoff.md).

Cấu hình này dùng cho thí nghiệm mô phỏng trên nhánh `hiiluo-policy`. Diff được
đọc từ GitHub `main` `4a3aa0e` đến đầu [PR #7](https://github.com/hiiluo/NeuSymNav/pull/7)
`d1592f7`. PR thêm một đường chạy riêng. [Paper protocol](https://github.com/hiiluo/NeuSymNav/blob/d1592f77908b8c278ac579c9149a75b6b0a2063b/docs/objectnav/paper-protocol-plan.md)
mô tả môi trường của teammate.

| Thông số | Cấu hình trên nhánh hiện tại |
|---|---|
| Dữ liệu | HM3D v2 `val`, 1.000 episode trên 36 scene, trong `local-assets/datasets/hm3d-val` |
| Agent khai báo | Cao 0,88 m, bán kính 0,18 m |
| Quan sát | Một RGB-D 640 × 480, HFOV 79°, cao 0,88 m, depth 0,5–5 m |
| Hành động | Tiến 0,25 m, quay trái/phải 30°, nhìn lên/xuống 30°, STOP |
| Va chạm | `allow_sliding: false`, mô phỏng dùng navmesh đi kèm scene |
| Giới hạn | 500 hành động, tính cả STOP |
| Bộ chấm | Schema 3, STOP với geodesic DTG < 0,1 m tới viewpoint đã snap theo quy tắc hiện hành, SR/SPL/SoftSPL/DTG và OSR chẩn đoán |

[Config protocol](../../configs/objectnav/paper-hm3d-v1.json) và [config B0 v1](../../configs/objectnav/paper-b0-v1.json)
khớp byte với PR. ApexNav dùng cùng số bước và kích thước bước tiến/quay, với depth
0–5 m và success 0,2 m. Habitat Challenge 2023 chính thức dùng robot Stretch và điều
khiển liên tục. Khi trình bày kết quả hãy gọi đây là **paper protocol của PR #7**.
[ApexNav §V-A](https://arxiv.org/html/2504.14478v3#S5.SS1), [config ApexNav HM3D v2](https://github.com/Robotics-STAR-Lab/ApexNav/blob/main/config/habitat_eval_hm3dv2.yaml), [Habitat Challenge](https://github.com/facebookresearch/habitat-challenge).

Cả 36 navmesh BASIS sẵn có được bake với cao 1,50 m, bán kính 0,10 m, max climb 0,20 m
và max slope 45°. Kích thước agent 0,88/0,18 m được đặt ở cấu hình và dùng cho bản đồ
quan sát. Độ rộng lối đi thật trong mô phỏng vẫn phụ thuộc navmesh có sẵn. Paper mode
giữ nguyên mesh này và pose xuất phát của dataset như PR. Probe native ghi nhận cú
tiến bị cản vẫn đi thêm 0,076 m tới biên trong một trường hợp. `allow_sliding: false`
không bảo đảm toàn bộ bước bị hủy.

## Chạy trên máy này

Chạy ở thư mục gốc NeuSymNav. Runner mặc định dùng [Paper B0 v2](../../configs/objectnav/paper-b0-v2.json).
Để tái lập lượt cũ bằng v1, truyền `--policy-config configs/objectnav/paper-b0-v1.json`.
Preflight chỉ nạp và kiểm cấu hình, dữ liệu, interpreter Habitat và model pins.

```bash
.venv/bin/python tools/objectnav/run_paper_episodes.py --preflight
```

Khi chủ động chạy B0 trên DEV60, dùng manifest cố định, rồi chấm offline
sau khi runner hoàn tất.

```bash
run_dir=runs/objectnav/b0-dev60
.venv/bin/python tools/objectnav/run_paper_episodes.py \
  --policy b0 --manifest configs/objectnav/splits/hm3d_v2-val-dev.json \
  --run-id b0-dev60 --out-dir "$run_dir"
PYTHONPATH=src .runtime/sensor/bin/python tools/objectnav/score_trajectories.py \
  "$run_dir/trajectories.jsonl" --set hm3d_v2 --split val \
  --habitat-data local-assets/datasets/hm3d-val
```

`--policy explore` dùng cùng tầng di chuyển và bỏ nhận diện mục tiêu. B0 thêm
YOLOE, xác nhận qua các ảnh quan sát, tiếp cận và STOP. Profile tại máy này dùng
backend Torch, ngưỡng 0,25, tối đa 30 detection, trong khi handoff của teammate dùng
OpenVINO. Để ghim recipe tương ứng khi đã cài, truyền `--detector-profile` tới profile
local đã xác minh. Bản chuyển này lấy B0 từ commit hạ tầng `a8d7ba6`. B3/SigLIP2 và
Hydra/Qwen là các policy khác. Các số điểm teammate công bố thuộc run của teammate.
[Handoff B3 v5](https://github.com/hiiluo/NeuSymNav/blob/d1592f77908b8c278ac579c9149a75b6b0a2063b/docs/objectnav/b3-v5-handoff.md).

Launcher dùng khóa native chung, ghi manifest và pin code, protocol, model, runtime
và dữ liệu vào output. Chạy lại đúng lệnh để tiếp tục các UID còn thiếu. Khi đổi
recipe hoặc code, dùng `--out-dir` khác. Cùng giao thức, manifest và recipe cần được
giữ cố định cho mỗi phép ablation. Nếu chạy cả `val` bằng cách bỏ `--manifest`,
kết quả gồm cả episode từng xuất hiện trong tập phát triển.

## Đánh giá tầng di chuyển

- **PaperSim và vòng lặp theo bước.** Pose và góc quay đo trực tiếp từ Habitat.
  Camera hướng trước thay cho cặp camera trước/nhìn xuống của lockstep. Detector
  của B0 xử lý đồng bộ mỗi ảnh mới. Giao thức xác định số action rõ ràng và
  thuận tiện đối chiếu các policy, với chi phí chờ detector được phản ánh bằng
  thời gian thực. Cơ chế xử lý va chạm này dành cho mô phỏng.
- **Bản đồ và frontier.** Lưới 5 cm, 60 × 60 m, khởi đầu rỗng, có lớp theo độ cao
  và không khóa robot vào độ cao xuất phát. Chiếu ray depth tạo ô đã thấy và
  gom biên free/unknown. Frontier được lọc qua khả năng tới trên lưới. Lớp theo
  độ cao hữu ích ở cầu thang, nhưng cách ghép lớp và blacklist bằng XY vẫn có
  thể ảnh hưởng giữa hai tầng.
- **Dijkstra và bộ chọn hành động.** Planner 8 hướng chặn cắt góc. Chi phí tăng
  gần tường trong 0,5 m. Controller thử một bước tiến ở 12 hướng khả dĩ, chấm
  chi phí còn lại cộng chi phí quay, rồi chọn quay hoặc tiến. Khi không có
  hướng giảm chi phí, controller quay lại bám waypoint. Đây là thay đổi đáng
  giữ nhất với action 0,25 m/30°. Nhật ký teammate ghi OSR explore DEV60 từ
  32/60 lên 50/60, trung vị số va chạm 15 xuống 2, thời gian tăng từ khoảng
  35 lên 99 giây/episode. Phép đo này gộp thay đổi điều hướng, chưa tách phạt
  sát tường khỏi chấm hành động. [Nhật ký paper protocol](https://github.com/hiiluo/NeuSymNav/blob/d1592f77908b8c278ac579c9149a75b6b0a2063b/docs/objectnav/journal/paper-protocol.md).
- **Thoát kẹt.** Dùng va chạm để đánh dấu vật cản, quay về phía nhiều ô đi được
  và bỏ frontier bị kẹt. Khi hết frontier có đường, planner thử giảm inflation
  0,18 xuống 0,08 m, vẫn giữ vết chắn do va chạm lặp. Cách này giúp khám phá
  cửa hẹp nhưng có thể tốn hành động hoặc bỏ nhầm lối, nhất là nếu bản đồ nhiễu.
- **B3 v5 và bước tiếp cận cuối.** PR có heuristic `early_stop` ở tầng policy,
  bỏ bước tiến kế khi footprint dự đoán sẽ vào vùng dừng. V5 thắng 9, thua 0
  so với v4 trên DEV167 theo báo cáo của teammate. Đây là ý tưởng nên ablate
  riêng vì có thể dừng sớm quá, và DEV167 đã dùng để tinh chỉnh. Trên các lượt chạy
  của teammate, B0 đạt 93/167 và v5 đạt 113/167, SPL lần lượt 0,209 và 0,273.
  Chênh lệch này gộp cả các module ngữ nghĩa.
  [Nhật ký B3](https://github.com/hiiluo/NeuSymNav/blob/d1592f77908b8c278ac579c9149a75b6b0a2063b/docs/objectnav/journal/B3-semsearch.md).

Trong bản local, depth thiếu giữ trạng thái unknown, khác với pixel thực đo
bị cắt ở 5 m. Runner chỉ cấp UID và category cho policy, từ chối bật sliding,
khóa provenance khi resume và trả không có đường khi robot vượt biên bản đồ.
Những thay đổi này cùng backend detector local khiến kết quả không được coi là
tái lập từng quỹ đạo của PR. Bộ chấm schema 3 có bước snap viewpoint nên cần
giữ cùng bộ chấm khi đối chiếu các run.
