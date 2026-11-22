# B3-semsearch — policy tìm kiếm ngữ nghĩa (paper mode)

Chiến dịch 7 ngày, bắt đầu 21/11/2026 17:05 (trần 28/11). Tên B3 vì "B2" đã dùng cho nhánh `B2-sysnavref` (đã bỏ).
Cổng: DEV167 so cặp với B0-paper (`paper-b0-dev60` + `paper-b0-devx107`), wins − losses ≥ 3; TEST180 chỉ xác nhận;
cuối chiến dịch chạy đủ val 1000 (B0 + policy cuối) chỉ để báo cáo. Mốc: ngày 2 DEV167 đầu tiên, ngày 4 giữ/bỏ,
ngày 6 TEST180, ngày 7 val 1000. Người dùng cho phép: tải model mới, thử detector/verifier mạnh hơn, chạy 2–3 sim song song.

Thiết kế (dự kiến, chốt sau khi đo ngày 1): thay ba khâu của B0
1. chọn frontier theo bản đồ giá trị ngữ nghĩa (bộ mã hóa ảnh CLIP/SigLIP trên iGPU, kiểu VLFM) + ngữ cảnh từ detection (B1-ctx);
2. xác nhận vật bằng gộp bằng chứng theo vật (kiểu ApexNav, có phạt khi thấy mà không có nhãn);
3. xác minh ảnh cắt trước STOP bằng CLIP giữa các nhãn dễ nhầm.

Bố cục code: `src/neusymnav/objectnav/paper/b3/`, `configs/objectnav/paper-b3-*.json`, `tests/test_objectnav_b3_*.py`,
`tools/objectnav/b3/`, model ở `local-assets/models/b3/` (không commit), venv `.runtime/clip-ov` (không commit).

## 21/11/2026 17:05 — Ngày 1: chuẩn bị
- Hủy lượt bó v2 (`paper-b1cpv-v1-ps64`, VLM nặng CPU) để nhường tài nguyên; plant sẽ thử lại trong bó B3.
- Venv `.runtime/clip-ov` (torch CPU, transformers, OpenVINO 2026.4 — cùng bản với detector, thấy `GPU` = Intel UHD).
- Venv chính không có OpenVINO ⇒ bộ mã hóa ảnh chạy trong worker riêng (pipe), như detector.
- `tools/objectnav/b3/clip_bench.py`: xuất image encoder sang OpenVINO IR FP16, đo ms/frame CPU/GPU, phân loại 48 ảnh cắt
  tại lần dừng của B0 DEV60 giữa các nhãn dễ nhầm (bộ prompt viết trước khi xem điểm).

## 21/11/2026 ~18:30 — Chọn model: SigLIP2-B/16

`tools/objectnav/b3/clip_bench.py` (sửa cho transformers 5: `get_*_features` trả `pooler_output`). Đo khi 2–3 sim đang
chạy song song (iGPU đang chạy YOLOE), nên tốc độ thật còn tốt hơn. Phân loại 48 ảnh cắt tại lần dừng của B0 DEV60, top-1
giữa nhãn đích và các nhãn dễ nhầm (bộ prompt viết trước khi xem điểm):

| Model | ms/frame GPU (CPU) | sofa thật giữ / armchair loại | toilet thật | bed thật | chair thật | tv | plant |
|---|---|---|---|---|---|---|---|
| CLIP ViT-B/16 | 109 (371) | 9/10 / 3/6 | 5/10 | 8/8 | 3/8 | 2/3 | 2/2 |
| **SigLIP2-B/16** | **97 (350)** | 9/10 / **6/6** | **10/10** (+ loại "bed" 1/1) | 8/8 | 4/8 | 2/3 | 2/2 |

- Ca sofa "thật" SigLIP2 loại (`TEEsavR23oF/0#3`, stopped_too_far) là ca mơ hồ, trước đây VLM cũng xếp vào armchair.
- So với Qwen3-VL-2B (sofa thật 8/8, armchair 5/7, 2–19 s/câu CPU): SigLIP2 tốt hơn và nhanh hơn ~100 lần.
- Chọn SigLIP2-B/16 cho cả bản đồ giá trị và xác minh; **không xác minh chair** (4/8). Mẫu sai còn nhỏ (7) ⇒ đánh giá lại
  trên ảnh dừng của B0 dev-extra.
- Model: `local-assets/models/b3/siglip2-base-patch16-224/` (IR FP16 `image_encoder.xml`, `text.npy` + `texts.json`
  embedding prompt "a photo of <x>", `meta.json`); bản HF gốc ở `local-assets/models/b3/hf/`.
- Worker đo đầu-cuối qua pipe: 164 ms cho frame 640×480 (đang tải), +~18 % thời gian/bước.

## 21/11/2026 ~19:00 — B3 v1: code

| Phần | File |
|---|---|
| Worker / client SigLIP (OpenVINO GPU, pipe) | `paper/b3/clip_worker.py`, `paper/b3/clip_client.py` |
| Bản đồ giá trị (VLFM eq. 1–2, conf = cos² góc lệch trục) | `paper/b3/value_map.py` |
| Policy (subclass B0) + config `semantic`, `clip_verify` | `paper/b3/policy.py` |
| Hook trong B0 (không đổi hành vi): `_choose_frontier`, `_wants_crop`, `_make_crop`, `_best_crop`, `_stop_veto` | `paper/b0.py` |
| `ObstacleMap.last_frame` (mặt nạ ô thấy ở frame cuối, không đổi hành vi) | `paper/obstacle_map.py` |
| CLI `--policy b3` | `tools/objectnav/run_paper_episodes.py`, `tools/objectnav/paper/run_dev60.sh` |
| Test (4 passed); B0/B1 sau khi tách hook: 16 passed | `tests/test_objectnav_b3.py` |

Chọn frontier: cost = path − 4 m × rel(v) − context bonus (B1-ctx); rel = (v − min)/(max − min) trên các frontier đã có giá
trị, = 0 khi chênh lệch < 0,01 (không có tín hiệu ⇒ frontier gần nhất). Xác minh: ảnh cắt mới nhất của ứng viên, top-1 phải là
prompt đích, mỗi ứng viên hỏi một lần; target: sofa, toilet, bed. Config `configs/objectnav/paper-b3-v1.json` (tham số chốt
trước mọi lần chạy B3).

## 21/11/2026 18:10 — Smoke B3 v1 (`paper-b3-v1-smoke3`, 3 episode DEV60)

- Exit 0, 33 tests passed. SR 1/3 (như B0 trên 3 ca này: wins 0, losses 0). Không lỗi; worker SigLIP tự tắt.
- `wcojb4TFT35/2#3` toilet: SigLIP "a toilet" → nhận, thành công (94 bước). `k1cupFYWXJ6/5` sofa: loại "an armchair", rồi nhận
  ứng viên thứ hai là "a sofa" nhưng vẫn là vật sai (wrong_object_stop như B0). `LT9Jq6dN3Ea/1#2` tv: hết 500 bước như B0.
- Bản đồ giá trị cập nhật mọi bước (0,13–0,15 s/bước embed khi 3 sim song song); đổi 1–3 lựa chọn frontier/episode; "flat"
  (chênh < 0,01) 0–7 lần.

## 21/11/2026 18:15 — Lịch chạy qua đêm

- Tạm dừng `paper-b1c-v1-devx107` ở 19/107 (resumable) để nhường chỗ cho B3.
- `paper-b3-v1-dev60` (đang chạy) ‖ `paper-b3-v1-devx107` (sau khi `paper-b0-devx107` xong) → rồi chạy tiếp
  `paper-b1c-v1-devx107`. Cổng: `python3 tools/objectnav/paper/dev167_gate.py paper-b3-v1-dev60,paper-b3-v1-devx107`.

## 21/11/2026 18:30 — Tham chiếu B0-paper trên DEV167

- `paper-b0-devx107` exit 0 (33 tests passed; WARNING "tracked code changed" vì đã dừng ở 4/107 rồi chạy tiếp khi `b0.py`
  có thêm cờ tắt mặc định — đường B0 không đổi). SR **57/107 (0,533)**, SPL 0,197, OSR 79/107, wall 4,9 h.
- **B0 DEV167 = 93/167 (0,557).** Lỗi (74): wrong_object_stop 26, stopped_too_far 11, seen_not_detected 11, never_seen 10,
  budget_exhausted 8, stopped_elsewhere 8.
- Theo (lỗi, loại): **sofa wrong_object_stop 17**, plant seen_not_detected 9, sofa stopped_too_far 6, chair wrong_object_stop 4,
  plant/toilet never_seen 3 mỗi loại. ⇒ sofa là nút thắt số 1 (23 thất bại chỉ ở hai nhóm), đúng mục tiêu của xác minh SigLIP.

## 21/11/2026 21:41 — B3 v1 DEV60 (`paper-b3-v1-dev60`)

- Exit 0. SR **37/60 (0,617)**, SPL 0,242, OSR 50/60, wall 3,3 h. So với B0 dev60: wins 5, losses 4, net +1 (riêng DEV60, chưa
  phải cổng). Lỗi: seen_not_detected 6, stopped_too_far 4, budget 4, stopped_elsewhere 4, never_seen 3, wrong_object_stop 2.
- Wins: `wcojb4TFT35/1#4`, `wcojb4TFT35/4#5` sofa (SigLIP loại armchair 2 lần rồi dừng đúng sofa — đúng cơ chế),
  `LT9Jq6dN3Ea/1#4`, `LT9Jq6dN3Ea/2#5` sofa (B0 stopped_too_far), `TEEsavR23oF/3#4` tv (B0 never_seen).
- Losses: `qyAac8rV8Zk/0` bed — giường thật bị loại vì "a chair" 0,0539 > "a bed" 0,0523 (**gap 0,0016**, hòa sát);
  `LT9Jq6dN3Ea/0#2` sofa — loại "an armchair" gap 0,033 rồi hết 500 bước (có thể sofa thật; gap ngang các armchair thật nên
  ngưỡng không cứu được); `TEEsavR23oF/2#4` tv và `wcojb4TFT35/3#2` toilet — đường khám phá khác (value map), không do bộ lọc.
- Gap của các lần loại (top âm − đích): 0,009–0,038; chỉ một lần < 0,005 (cái giường trên).

## 21/11/2026 22:10 — B3 v2: reject_margin + plant yếu (code xong, chạy tập con)

Phân tích plant (B0 DEV167, frame log): trong 16/20 tập plant thất bại (29 tập plant, B0 thành công 9), detector **không trả về một phát hiện plant nào**
(ngưỡng sàn của profile là 0,25; recall instance plant của B0 = 0,16). Không phải lỗi ngưỡng xác nhận mà là sàn detector.

| Thành phần v2 | File |
|---|---|
| `clip_verify.reject_margin` (tùy chọn; chỉ loại khi prompt nhầm thắng đích ≥ margin); target dạng `{pos, neg}` | `src/neusymnav/objectnav/paper/b3/policy.py` |
| `low_conf`: worker detector thứ hai sàn 0,10 chỉ trong tập plant; dưới 0,25 chỉ giữ nhãn của đích; ngưỡng xác nhận plant 0,10; bắt buộc có clip_verify | `src/neusymnav/objectnav/paper/b3/low_conf.py`, `policy.py` |
| Chẩn đoán `semantic.flat_unknown` (flat vì < 2 frontier có giá trị, hay vì chênh nhỏ) | `policy.py` |
| Thêm text embedding cho prompt mới, giữ nguyên bit các hàng v1 (bản sao `text.v1.npy`) | `tools/objectnav/b3/export_texts.py` |
| Test: 8 passed | `tests/test_objectnav_b3.py` |

Config `configs/objectnav/paper-b3-v2.json` = v1 + reject_margin 0,005 + vase→plant (≥ 0,5, B1 P1) + plant clip_verify
(pos: potted plant / houseplant / flowers in a vase; neg: vase, lamp, painting, curtain, chair, pillow, towel) + low_conf.
Chốt trước khi chạy.

Vì sim xác định, v2 chỉ khác v1 ở (a) các tập plant và (b) các tập có lần loại SigLIP với gap < 0,005. Tập con
`paper-b3-v2-sub` = 29 tập plant DEV167 + `qyAac8rV8Zk/0` (phần devx của (b) bổ sung khi v1 devx107 xong). Kết quả DEV167
của v2 = `dev167_gate.py paper-b3-v2-sub,paper-b3-v1-dev60,paper-b3-v1-devx107`. Chạy ngay khi có chỗ trống (tối đa 2 sim).

## 22/11/2026 00:52 — **B3 v1 DEV167: cổng PASS** (mốc ngày 2 đạt sớm)

- `paper-b3-v1-devx107` exit 0, SR 62/107 (0,579) vs B0 57/107: wins 11, losses 6, net +5. Wall 6,1 h.
- **DEV167: SR 93 → 99 (0,557 → 0,593), SPL 0,209 → 0,231, wins 16, losses 10, net +6 ≥ 3 ⇒ PASS** (McNemar p = 0,327 —
  chưa có ý nghĩa thống kê; TEST180 sẽ là xác nhận).
- 16 wins: sofa 10 (wrong_object_stop → OK 4: SigLIP loại armchair; stopped_too_far → OK 4; stopped_elsewhere 1),
  toilet never_seen 2, tv 2, plant 2, bed 1. 10 losses: phần lớn do đường khám phá khác (budget 2, never_seen 1,
  stopped_elsewhere 2, plant seen_not_detected 2, stopped_too_far 2), một ca giường bị loại sát nút (v2 sửa), toilet
  `qyAac8rV8Zk/1#5` loại "a sink" gap 0,0098 (toilet thật?).
- Lỗi còn lại DEV167 (68): seen_not_detected 17, budget 13, wrong_object_stop 12, stopped_elsewhere 11, stopped_too_far 9,
  never_seen 6.
- Gap SigLIP devx: một lần loại có gap 0,0042 (`wcojb4TFT35/2#2`, là ca thắng của v1) — nằm dưới reject_margin 0,005 của v2,
  nên được thêm vào tập con v2 để đo (resume sau khi phần plant xong). Không sửa margin giữa chừng.

## 22/11/2026 01:40 — B3 v3: endgame (code xong, chạy tập con)

Chẩn đoán `tools/objectnav/b3/endgame_diag.py` (offline, dùng vị trí goal GT chỉ ở evaluator) trên B3 v1 DEV167: **47 tập kết
thúc không quyết định** (max_steps 31, frontiers_exhausted 16; chỉ 1 thành công). 19/47 có trong bộ nhớ một vật thấy là đích
nằm ≤ 1 m quanh goal thật: chưa xác nhận 10, bị SigLIP loại 6 (phần lớn sofa thật ở k1cupFYWXJ6 bị coi là armchair; một toilet
bị coi là sink), bị loại do chuyển động 3. Xếp hạng chọn vật: điểm detector cao nhất chọn đúng vật ≤ 1 m ở 14/24 tập (số view:
12/24); trên B0 chỉ 5/14 (B0 dừng sai sớm hơn). Thành công muộn của v1: 6 tập > 300 bước (muộn nhất 481) ⇒ không cắt sớm.

| Thành phần v3 | File |
|---|---|
| Hook `_exhausted_hook()` (B0: False, hành vi không đổi) | `src/neusymnav/objectnav/paper/b0.py` |
| `endgame`: hết frontier, hoặc từ bước 200 khi bước còn lại ≤ ceil(đường/0,25 × 1,3) + 25 tới vật tốt nhất ⇒ tiến tới vật có điểm cao nhất (kể cả đã bị loại; mỗi vật một lần), dừng không qua luật xác nhận và veto SigLIP | `src/neusymnav/objectnav/paper/b3/policy.py` |
| Chẩn đoán endgame | `tools/objectnav/b3/endgame_diag.py` |
| Test: 10 passed trong `test_objectnav_b3.py` | `tests/test_objectnav_b3.py` |

Config `configs/objectnav/paper-b3-v3.json` = v2 + endgame (chốt trước khi chạy). Tập con `paper-b3-v3-sub` (75 tập) = tập con v2
∪ mọi tập v1 dài > 200 bước hoặc kết thúc không quyết định — ngoài tập này v3 trùng v1 (endgame chỉ kích hoạt từ bước 200 hoặc
khi hết frontier). DEV167 v3 = `dev167_gate.py paper-b3-v3-sub,paper-b3-v1-dev60,paper-b3-v1-devx107`.

## 22/11/2026 02:46 — B3 v2 tập con (`paper-b3-v2-sub`, 30/31 tập; `wcojb4TFT35/2#2` đang chạy bổ sung)

- Exit 0, 26 tests passed (B3 + B0 + B1). Trên 30 tập (29 plant + `qyAac8rV8Zk/0`): **B0 10, v1 9, v2 10**. So với v1:
  wins 5 (plant `LT9Jq6dN3Ea/3#2`, `bCPU9suPUw9/2#3`, `k1cupFYWXJ6/2#3`, `k1cupFYWXJ6/6#3`, `k1cupFYWXJ6/8#3`),
  losses 4 (plant `TEEsavR23oF/3#6` stopped_too_far, `bCPU9suPUw9/0#4` stopped_elsewhere, `k1cupFYWXJ6/3#3` budget,
  `k1cupFYWXJ6/7#3` wrong_object_stop). ⇒ v2 ≈ v1 + 1 trên DEV167 (ước tính 100/167, chờ tập cuối).
- `qyAac8rV8Zk/0`: margin cứu cái giường khỏi bị loại nhưng giường đó **không phải** goal (wrong_object_stop) — vẫn thua.
- Plant low_conf: 1–36 phát hiện plant dưới 0,25 mỗi tập. SigLIP loại nhiều ứng viên là "a vase" (k1cupFYWXJ6: 2–5 lần/tập);
  mỗi lần loại tốn một lượt tiếp cận ⇒ `k1cupFYWXJ6/3#3` hết bước sau 5 lần loại. Endgame (v3) nhắm đúng loại này.
- Kết luận tạm: plant low_conf có tác dụng (5 ca plant mới thành công) nhưng tốn bước; v3 sẽ cho biết endgame có gỡ được
  phần thua không.

## 22/11/2026 02:50 — Gán nhãn các lần SigLIP xác minh ⇒ B3 v4 (veto chỉ cho sofa/bed)

`tools/objectnav/b3/clip_gap_diag.py` (offline, GT chỉ ở evaluator): mỗi lần kiểm tra crop được gán "true" nếu ứng viên ≤ 1 m
từ goal, "wrong" nếu ≥ 2 m (v1 DEV167 + tập con v2; gap = điểm prompt nhầm tốt nhất − điểm đích tốt nhất):

| Đích | true giữ / tổng (gap ≤ 0) | wrong loại / tổng | Kết luận |
|---|---|---|---|
| sofa | 17/22 | 22/29 | có ích; margin 0,005 mất 1 lần loại đúng ⇒ margin 0 |
| bed | 21/21 | 1/1 (gap +0,002) | có ích ở margin 0 |
| toilet | 20/21 | 0/0 | chỉ có hại ⇒ bỏ |
| plant | **11/32** | 5/6 | **có hại**: cây thật bị coi là "a vase" ⇒ bỏ veto plant |

Lần kiểm tra đầu tiên trong mỗi tập plant (v2): 18/21 là cây thật; ở k1cupFYWXJ6, 5 tập hết bước vì cây thật bị loại.

Khoảng cách dừng (B0 + v1 DEV167, các lần dừng có vật): dừng < 0,2 m: 12 ok / 6 stopped_too_far (33 % hỏng); 0,3–0,4 m:
109 ok / 8 too_far. ⇒ ý tưởng sau: lùi ra ~0,3 m khi dừng quá sát (view point không nằm sát vật). Chưa làm.

Config `configs/objectnav/paper-b3-v4.json` = v3 với clip_verify chỉ sofa + bed, bỏ reject_margin; plant low_conf giữ (không
veto; validator không còn bắt buộc clip_verify cho low_conf). Tập con `paper-b3-v4-sub` = cùng 75 tập của v3 (thêm
`qyAac8rV8Zk/1#5` toilet bị loại "a sink" — đã có sẵn). Chú ý: v4 được chỉnh trên DEV ⇒ TEST180 là kiểm chứng thật.

## 22/11/2026 02:50 — B3 v2 DEV167 (tập con 31 tập + v1 cho phần còn lại)

- `wcojb4TFT35/2#2` (lần loại gap 0,0042 của v1): v2 chấp nhận armchair ⇒ **wrong_object_stop** (thua so với v1) — xác nhận
  bỏ reject_margin ở v4.
- **v2 DEV167: SR 93 → 99, wins 18, losses 12, net +6, PASS** — bằng v1 (so với v1 trên 31 tập: 10 → 10, wins 5 losses 5).
  ⇒ v2 không hơn v1: phần thắng plant bị trừ bởi veto plant và margin. v4 sửa cả hai.

### 22/11 07:10 — B1-ctx DEV167 (tham chiếu)
- `paper-b1c-v1-dev60` + `paper-b1c-v1-devx107` vs B0: SR 93 → 91, wins 3, losses 5, net −2 → **FAIL**. Context prior đứng riêng không có lợi; B3 không dùng lại nó.
- Waiter cũ `b4upv5oxc` đã dừng (chờ `paper-b1cpv-v1-ps64` không bao giờ có REPORT).

### 22/11 08:00 — v3 (v2 + endgame) DEV167
- **So với B0:** SR 93 → 99, SPL 0.209 → 0.230, wins 18, losses 12, net +6, **PASS**.
- **So với v1:** 99 → 99, wins 5, losses 5, net 0. Kết quả này giống hệt v2.
  - 5 ca thắng đều là plant, nhờ `low_conf`.
  - 5 ca thua cũng có ở v2-sub, nên do `low_conf`/veto plant/margin chứ không do endgame.
- **Endgame không cứu được ca nào:**
  - Có 30 tập kích hoạt, trong đó 25 'budget' và 5 'exhausted'. Không tập nào thành công.
  - Kết cục:
    - 10 wrong_object_stop;
    - 4 stopped_too_far;
    - 6 stopped_elsewhere;
    - 10 vẫn max_steps hoặc never_seen. Ở các tập này ước lượng đường đi thấp hơn thực tế, hoặc vật ở quá xa (reach 6–13 m ở bước 405–445).
  - Kết luận: ứng viên tốt nhất theo điểm detector ở cuối tập gần như luôn là vật sai. Endgame trung tính, vì chỉ đụng tới các tập đằng nào cũng thất bại, nhưng vô ích.
  - v5 sẽ bỏ endgame. Với v4 (vẫn còn endgame), mọi thay đổi so với v3 đến từ việc bỏ veto plant.

### 22/11 08:40 — v4 DEV167: bản tốt nhất hiện tại
v4 = v3, nhưng `clip_verify` chỉ còn sofa và bed, và không có `reject_margin`.

- **So với B0:** SR 93 → **104** (0.557 → 0.623), SPL 0.209 → 0.242, wins 21, losses 10, **net +11**, p = 0.071, **PASS**.
- **So với v1:** 99 → 104, wins 8, losses 3, net +5.
  - Ca thắng: 7 plant (low_conf, không còn veto), 1 toilet (`qyAac8rV8Zk/1#5`).
  - Ca thua: 3 plant (`LT9Jq6dN3Ea/1#3`, `TEEsavR23oF/3#6`, `bCPU9suPUw9/0#4`).
- **Độ phủ của tập con:**
  - 16 tập toilet nằm ngoài v4-sub có kiểm tra SigLIP trong v1, nhưng cả 16 đều `accepted`.
  - Vì vậy bỏ veto toilet không làm đổi quỹ đạo các tập đó, và con số 104/167 là chính xác.
  - Mọi tập plant đều nằm trong tập con.
- **Hướng v5:** v4 bỏ endgame (đã thấy vô ích ở v3), thêm stand-off cho stopped_too_far. stopped_too_far hiện là 17 tập, nhóm lỗi lớn thứ hai sau wrong_object_stop (24 tập).

### 22/11 08:50 — v5: early_stop (dừng sớm một bước), chạy full DEV167
**Phát hiện (offline, evaluator-side):**
- Xét lại 17 ca stopped_too_far, dùng `dtg_end` và khoảng cách Euclid từng bước tới view point GT.
- 9/17 ca đã đứng cách view point ≤ 0,1 m **ngay trước bước tiến cuối** của APPROACH. Bước đó được đi vì footprint vẫn còn > 0,4 m, và nó đẩy robot ra khỏi tập view point. Kết quả `dtg_end` nằm trong khoảng 0,11–0,24 m.
- Phản thực tế "bỏ bước tiến cuối" trên 155 tập có dừng: sửa 9, hỏng 0. Bỏ hai bước thì sửa 9, hỏng 4.
- Ý tưởng stand-off cũ (lùi về khi < 0,2 m) không đúng với dữ liệu, nên bỏ.

**Rule (policy, không dùng GT):** trong APPROACH, nếu action kế tiếp là `move_forward` và vị trí dự đoán sau bước đó lọt vào `stop_distance_m` của footprint, thì chuyển sang FACE ngay. VERIFY chấp nhận tới `stop_distance_m + step_m` cho lần đến này.

| Thành phần | File |
|---|---|
| Rule và lý do | `src/neusymnav/objectnav/paper/b3/early_stop.py` |
| Gắn vào B3 (`_act_approach`, `_stop_limit_m`, ghi `rec['early_stop']`) | `src/neusymnav/objectnav/paper/b3/policy.py` |
| Hook `_stop_limit_m()` (B0 không đổi hành vi) | `src/neusymnav/objectnav/paper/b0.py` |
| Config v5 = v4 − endgame + `early_stop {step_m 0.25}` | `configs/objectnav/paper-b3-v5.json` |
| Test | `tests/test_objectnav_b3.py` (`test_early_stop_*`) |

**Chạy:**
- Rule chạm vào mọi lần approach, nên phải chạy full DEV167: `paper-b3-v5-dev60` và `paper-b3-v5-devx107` chạy song song.
- Cổng tính so với B0 và so với v4 (tham chiếu v4 = v4-sub + v1).

### 22/11 08:58 — 63 ca thất bại còn lại của v4 (offline, để chọn hướng tiếp)
- **Theo loại lỗi:** wrong_object_stop 24, stopped_too_far 17 (v5 nhắm vào nhóm này), stopped_elsewhere 7, budget_exhausted 7, never_seen 5, seen_not_detected 3. Như vậy lỗi khám phá chỉ có 15 ca.
- **Các ca dừng nhầm đã confirmed:**
  - 5 ca sofa đều được SigLIP chấm "a sofa", và điểm detector 0.6–0.85, ngang mức các ca thành công. Nhiều khả năng đây là vật giống sofa nhưng không được gán nhãn goal, nên rất khó sửa bằng verifier.
  - 3 ca tv_monitor không có veto.
  - 3 ca chair ở `bCPU9suPUw9` cùng một chiếc ghế, cách GT khoảng 1,5 m.
- **Kinh nghiệm cũ:** VLM Qwen3VL-2B ở B1 cho net +1 trên DEV60 và net 0 trên TEST180, nên không ưu tiên lại hướng này.

### 22/11 09:15 — v6: SigLIP veto cho tv_monitor (xếp hàng)
- **Trạng thái v5:** bộ test đầy đủ qua (25 passed, 6 phút), sau đó v5 bắt đầu chạy DEV167.
- **Config `configs/objectnav/paper-b3-v6.json`** = v5 + veto tv_monitor:
  - `pos`: "a television", "a computer monitor" (vì goal tv_monitor gồm cả màn hình máy tính);
  - `neg`: "a painting", "a picture frame", "a mirror", "a window", "a cabinet", "a fireplace".
- Đã thêm 2 text embedding mới (26 → 28) bằng `export_texts.py`; các dòng cũ giữ nguyên.
- **Lý do:** tv_monitor trên DEV167 có 18 tập, thành công 9, wrong_object_stop 4. Có 3 ca dừng nhầm đã confirmed mà không có veto.
- **Tập con `runs/objectnav/paper-b3-v6-sub`:** 18 tập tv_monitor, vì v6 chỉ đổi lần dừng của tv_monitor. Chạy khi v5-dev60 xong và có chỗ trống.
  - Kết quả DEV167 của v6 = v6-sub ghép với v5.
  - Sau đó chạy `clip_gap_diag.py` để xem veto giữ được bao nhiêu TV thật.

### 22/11 13:00 — v5 nửa đầu: `paper-b3-v5-dev60` xong (exit 0, 12:15)
- **Tổng quát:** SR **42/60 (0.700)**, SPL 0.293, OSR 49/60. early_stop kích hoạt ở 50/60 tập.
- **So với B0 (DEV60):** 36 → 42, wins 9, losses 3, net +6.
- **So với v1 (DEV60):** 37 → 42, wins 5, losses 0.
- **So với v4 (DEV60):** 39 → 42, wins 3, losses 0, SPL 0.258 → 0.293.
  - Cả 3 ca thắng đều là stopped_too_far → OK: `TEEsavR23oF/3#6` (plant), `bCPU9suPUw9/4#3` (bed), `wcojb4TFT35/3#2` (toilet). Đúng như phân tích phản thực tế dự đoán.
- **Đang chạy:** `paper-b3-v5-devx107` (59/107), song song với `paper-b3-v6-sub` (11/18).

### 22/11 13:20 — Kế hoạch kiểm chứng (người dùng duyệt): chốt config, ablation, held-out
- **Vấn đề:** mọi lựa chọn từ v1 tới v6 đều tinh chỉnh trên DEV167, và tập này chỉ có 6 scene. Value map cũng chưa được đo riêng.
- **3DSG:** không nằm trong B3. Nhánh B1-apexref-3DSG đã bỏ. Lớp "tìm" của B3 gồm value map SigLIP2 và context prior.
- **Bước 1 — chốt:** sau v6-sub chọn v5 hoặc v6, rồi không thêm luật theo từng loại vật.
- **Bước 2 — ablation value map:** bản chốt với `semantic.value_weight_m = 0`. Value map vẫn được tính nhưng không ảnh hưởng việc chọn frontier; SigLIP veto giữ nguyên. Đo trên DEV167 và trên held-out.
- **Bước 3 — held-out mới `configs/objectnav/splits/hm3d_v2-val-holdout.json`:**
  - 180 tập, 6 tập mỗi scene ở 30 scene của TEST, chọn ngẫu nhiên với seed 20261122.
  - Không trùng DEV167 hay TEST180, và chưa từng được nhìn khi tinh chỉnh.
  - Phân bố: chair 48, tv 31, sofa 29, toilet 28, bed 23, plant 21.
  - Chạy 3 bản: B0, bản chốt, bản chốt không value map. Kết luận về value map lấy từ tập này.
- **Bước 4:** TEST180 xác nhận, gồm bản chốt và ablation (B0 đã có sẵn). Sau đó mới tới val1000.
- **Lưu ý:** val 1000 tập trùng DEV167 và TEST180, nên đó là số báo cáo chứ không phải kiểm chứng độc lập.

### 22/11 13:55 — v6 (veto tv_monitor): BỎ
- `paper-b3-v6-sub` xong (18 tập tv, exit 0, 1,5 h).
  - So với v4 trên 18 tập tv: SR 9 → 6, wins 0, losses 3, net −3.
  - So với v5 trên 6 tập tv thuộc DEV60: 3 → 2, net −1.
- `clip_gap_diag`: veto loại được 9/11 vật sai, nhưng cả 3 ca thua đều là ca bị loại liên tục với gap rất nhỏ (0,004–0,06): TV thật bị gọi là "a window", "a cabinet", "a picture frame". Robot sau đó hết bước (`TEEsavR23oF/4#2`, `wcojb4TFT35/1#3`) hoặc dừng sai chỗ (`TEEsavR23oF/1#5`).
- Loại được vật sai chỉ biến lỗi "dừng nhầm" thành "hết bước", nên không thắng thêm ca nào.
- **Quyết định:** bỏ v6. Bản chốt là **v5**, chờ cổng DEV167 khi `paper-b3-v5-devx107` xong. Không thử veto theo từng loại vật nữa (nguyên tắc chốt ngày 22/11).

### 22/11 15:20 — v5 DEV167: **CHỐT v5** (`configs/objectnav/paper-b3-v5.json`)
- `paper-b3-v5-dev60` + `paper-b3-v5-devx107`, cả hai exit 0.
- **So với B0:** SR 93 → **113/167 (0.677)**, SPL 0.209 → 0.273, wins 27, losses 7, **net +20**, p = 0.001, **PASS**.
- **So với v4:** 104 → 113, wins 9, losses 0, p = 0.004. Có 7 ca stopped_too_far → OK (early_stop) và 2 ca sofa wrong_object_stop → OK.
- **Thất bại còn lại (v5):** budget_exhausted 12, wrong_object_stop 12, stopped_too_far 9, seen_not_detected 8, stopped_elsewhere 7, never_seen 6.
- **Kiểm chứng (bước 2–3 của kế hoạch):** đã xếp hàng `paper-b3-v5-holdout180` và `paper-b3-v5novmap-holdout180` (ablation value map); `paper-b0-holdout180` đang chạy. Kết luận về value map sẽ lấy từ held-out.
