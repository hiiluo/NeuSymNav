# Bàn giao B3-semsearch v5 (paper mode, Habitat ObjectNav challenge 2023)

Ngày 22/11/2026. Đây là bản tốt nhất hiện tại để phát triển tiếp.
- Nhật ký chi tiết từng phiên bản, kể cả các hướng đã bỏ: [journal/B3-semsearch.md](journal/B3-semsearch.md).
- Phần "vase → plant" và VLM của v5 bắt nguồn từ [journal/B1-lastmile-plant.md](journal/B1-lastmile-plant.md).
- Protocol paper mode: [paper-protocol-plan.md](paper-protocol-plan.md) và [journal/paper-protocol.md](journal/paper-protocol.md).

## 1. Kết quả

Tất cả kết quả là paper mode, protocol `configs/objectnav/paper-hm3d-v1.json`: HM3D v2 val, 500 bước, forward 0,25 m,
turn 30°, `allow_sliding` false, thành công khi cách view point ≤ 0,1 m. Mọi so sánh là so cặp trên cùng episode; simulator
tất định.

DEV167 = `hm3d_v2-val-dev` (60) + `hm3d_v2-val-dev-extra` (107), 6 scene.

| Bản | SR DEV167 | SPL | So với B0 (thắng/thua, net) | Ghi chú |
|---|---|---|---|---|
| B0-paper | 93/167 (0,557) | 0,209 | — | `paper-b0-v1.json` |
| B3 v1 | 99/167 | 0,231 | 16/10, +6 | value map SigLIP2 + veto SigLIP + context prior |
| B3 v4 | 104/167 | 0,242 | 21/10, +11 | plant hạ ngưỡng detector; veto chỉ cho sofa/bed |
| **B3 v5** | **113/167 (0,677)** | **0,273** | **27/7, +20 (p = 0,001)** | + early_stop (dừng sớm một bước) |

- So với v4: v5 thắng 9, thua 0 (p = 0,004).
- Thất bại còn lại của v5: budget_exhausted 12, wrong_object_stop 12, stopped_too_far 9, seen_not_detected 8,
  stopped_elsewhere 7, never_seen 6.
- **Chưa được kiểm chứng độc lập:**
  - Mọi lựa chọn từ v1 tới v5 đều được tinh chỉnh trên DEV167.
  - Tập held-out mới `configs/objectnav/splits/hm3d_v2-val-holdout.json` đang được chạy: 180 tập, lấy từ 30 scene của
    TEST, không trùng DEV167 hay TEST180.
  - Đang chạy B0, v5 và `paper-b3-v5-novmap` (ablation: tắt value map khi chọn frontier). Kết quả sẽ được thêm vào journal.
  - TEST180 (`hm3d_v2-val-test`) chỉ dùng để xác nhận cuối, chưa chạy cho v5.
  - Tiền lệ: bản B1 trước đây được +3 trên DEV nhưng chỉ +1 trên TEST.

## 2. v5 gồm những gì

Mỗi thành phần là một khối trong config. Khi bỏ khối đó, hành vi trở về B0.

| Thành phần | Khối config | File |
|---|---|---|
| Value map SigLIP2-B/16 (giống VLFM): độ giống ảnh với "a <mục tiêu>", hợp nhất theo độ tin cậy góc nhìn, dùng khi chọn frontier | `semantic` | `paper/b3/value_map.py`, `paper/b3/policy.py` |
| Worker SigLIP (OpenVINO, iGPU), giao tiếp qua pipe | — | `paper/b3/clip_worker.py`, `paper/b3/clip_client.py` |
| Context prior: thấy vật hay đi cùng mục tiêu (bồn rửa với toilet…) thì frontier gần đó được cộng điểm | `context_prior` | `paper/context_prior.py` |
| Veto SigLIP trước STOP cho sofa/bed (loại armchair, ghế…) | `clip_verify` | `paper/b3/policy.py` |
| Plant: detector worker với ngưỡng 0,10 (chỉ giữ thêm nhãn plant), ngưỡng xác nhận plant 0,10 | `low_conf` | `paper/b3/low_conf.py` |
| "vase" được tính là plant khi điểm ≥ 0,5 (HM3D có plant trong bình hoa) | `target_labels` | `paper/b0.py` |
| Dừng sớm một bước: nếu bước tiến kế tiếp sẽ lọt vào `stop_distance_m` của vật thì chuyển sang FACE ngay | `early_stop` | `paper/b3/early_stop.py` |
| Hook trong B0 (`_choose_frontier`, `_stop_veto`, `_stop_limit_m`, `_exhausted_hook`); B0 không đổi hành vi | — | `paper/b0.py` |

Code của endgame (v3) và VLM verifier (B1) vẫn còn trong cây nhưng v5 không bật. Kết quả của chúng xem trong journal.

## 3. Cài đặt (ngoài git)

1. **Habitat và cảnh HM3D v2:** như B0-paper, xem `docs/objectnav/policy-dev-cheatsheet.md` mục 6.
2. **Profile detector** `configs/demo-00806.hydra-tour-slm.experimental.local.json`:
   - YOLOE-26m-seg OpenVINO, `confidence_threshold` 0,25, `max_detections` 30.
   - File local, do `handoff/3dsg-v11/install.py` sinh ra.
3. **Venv SigLIP** `.runtime/clip-ov`: Python 3.12 với `openvino==2026.4.1`, `torch==2.15.0+cpu`, `transformers==5.23.0`,
   `numpy==2.5.5`, `pillow==13.0.0`.
4. **Xuất model** vào `local-assets/models/b3/siglip2-base-patch16-224/`. Lần đầu cần mạng để tải
   `google/siglip2-base-patch16-224`.
   ```bash
   HF_HOME=local-assets/models/b3/hf .runtime/clip-ov/bin/python tools/objectnav/b3/clip_bench.py google/siglip2-base-patch16-224 local-assets/models/b3/siglip2-base-patch16-224
   HF_HOME=local-assets/models/b3/hf HF_HUB_OFFLINE=1 .runtime/clip-ov/bin/python tools/objectnav/b3/export_texts.py configs/objectnav/paper-b3-v5.json
   ```
   - Bước 1 tạo `image_encoder.xml/.bin` (FP16), `meta.json`, `text.npy` và `texts.json`.
   - Bước 2 thêm embedding cho mọi prompt mà config cần. Thiếu prompt thì `ClipClient` báo lỗi.

## 4. Chạy

```bash
bash tools/objectnav/paper/run_dev60.sh paper-b3-v5-dev60 b3 configs/objectnav/paper-b3-v5.json paper-b0-dev60
```

- Script chạy test, rồi sim, chấm điểm, evidence offline và `REPORT.txt`. Nếu bị dừng, chạy lại đúng lệnh này để tiếp tục.
- **Tập khác DEV60:** tạo trước `runs/objectnav/<tên>/manifest.json` bằng cách copy split, ví dụ
  `hm3d_v2-val-dev-extra.json` hoặc `hm3d_v2-val-holdout.json`.
- **Cổng DEV167:**
  ```bash
  python3 tools/objectnav/paper/dev167_gate.py <dev60-run>,<devx107-run> --ref paper-b0-dev60,paper-b0-devx107
  ```
  Luật giữ: wins − losses ≥ 3.
- **Chạy song song:** đặt `NSNAV_PARALLEL=1` để cho phép tối đa 2 lượt cùng lúc (worker giao tiếp qua pipe). Không chạy
  hai config có VLM cùng lúc (cổng 8712).
- **Công cụ phân tích offline** (chỉ ở phía evaluator):
  - `tools/objectnav/b3/clip_gap_diag.py`: chấm từng lần veto SigLIP là đúng hay sai;
  - `tools/objectnav/b3/endgame_diag.py`;
  - `tools/objectnav/b1/*`.
- **Test:**
  ```bash
  PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/test_objectnav_paper.py tests/test_objectnav_paper_b0.py tests/test_objectnav_b3.py tests/test_objectnav_b1_ctx.py tests/test_objectnav_b1_plant.py tests/test_objectnav_b1_vlm.py
  ```

## 5. Các hướng đã thử và bỏ (chi tiết trong journal)

- **Endgame** (v3): dừng ở ứng viên tốt nhất khi gần hết bước. Kích hoạt ở 30 tập, không cứu được tập nào.
- **Veto SigLIP cho plant/toilet** (v1–v3): loại oan 21/32 plant thật (bị gọi là "a vase").
- **`reject_margin` 0,005** (v2): để armchair lọt qua.
- **Veto cho tv_monitor** (v6): TV thật bị gọi là "a window"/"a cabinet". Net −1 so với v5 trên các tập tv.
- **Context prior đứng riêng** (B1-ctx): DEV167 net −2.

## 6. Đang làm tiếp (chưa có trong PR này)

- Kiểm chứng trên held-out: B0, v5, và v5 tắt value map.
- Lớp tìm kiếm neuro-symbolic (3DSG nhẹ: phòng, loại phòng, KB, luật suy diễn) đặt trên v5. Sẽ gửi PR riêng khi có kết quả.
