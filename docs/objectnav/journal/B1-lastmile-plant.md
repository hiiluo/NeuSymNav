# Nhật ký: kiet/B1-lastmile-plant (bó sửa nhỏ so với B0-paper)

## 20/11/2026 — Mở nhánh

- Nhánh `kiet/B1-lastmile-plant` cắt từ `kiet/paper-protocol` @ `a8d7ba6` (B0-paper đã commit local, chưa push).
- Baseline: **B0-paper** DEV60 `paper-b0-dev60` (SR 36/60, SPL 0,231, OSR 44/60). Chỉ chế độ paper.
- Quy ước (người dùng chốt 20/11/2026): chỉ SR tính là cải thiện; được gộp nhiều sửa nhỏ, mỗi sửa một cờ config;
  cổng giữ nhánh: so cặp DEV60, thắng − thua ≥ 3; TEST chỉ chạy một lần để xác nhận ứng viên cuối.
- Sim chế độ paper **tất định** (v3b: 52/60 episode trùng hệt B0), nên so cặp không có nhiễu chạy lại; tập con là
  ước lượng chính xác cho các episode mà thay đổi có thể chạm tới.

## 20/11/2026 — Phân tích lỗi B0-paper (offline, GT chỉ để chấm)

- **stopped_too_far (5):** script `stopdiag.py`/`centdiag.py` (scratchpad) so vị trí dừng với view point của goal.
  - `TEEsavR23oF/0#3`: cụm cách goal sofa 3,5 m → thực chất là dừng nhầm vật (armchair lớn), không phải chặng cuối.
  - `bCPU9suPUw9/4#3` (bed): đúng vật, view point gần nhất 0,11 m (hụt 1 cm).
  - `qyAac8rV8Zk/3#4`, `LT9Jq6dN3Ea/1#4`, `LT9Jq6dN3Ea/2#5` (sofa): dừng cạnh đầu sofa dài, view point gần nhất
    0,37–0,43 m.
  - Khoảng cách tới footprint lúc dừng (0,16–0,38 m) **không** phân biệt ca thành công và ca hụt; giả thuyết "đi tới
    điểm navigable gần tâm vật" sai: điểm snap từ tâm vật trúng view point ở **0/48** lần dừng (B0 trúng 36). Không có
    tín hiệu runtime có nguyên tắc → **tạm gác** chặng cuối (trần ~4, khó lấy).
- **plant: 2/9 episode plant thành công** — loại vật yếu nhất. Ở 3 ca `k1cupFYWXJ6` (min-DTG ≈ 0, 500 bước) và
  `TEEsavR23oF/1#3`, `LT9Jq6dN3Ea/0#6` memory **không có cụm plant nào**: detector không bao giờ báo "plant".
  - Báo cáo detector phase 2 (`phase2-detector-results.md`): frame recall plant 0,02; trên các view plant bị bỏ lỡ,
    detector gọi là **"vase" 184 lần**; goal plant của HM3D gồm flower vase / flowerpot / flower. Đòn bẩy số 1 đã ghi
    ở đó (ước tính plant tốn ~15 điểm SR trên phân bố TEST).

## 20/11/2026 — P1: map `vase` → plant (chỉ config)

- **Giả thuyết:** gán nhãn detector "vase" vào goal plant tăng recall plant; giá là vase không có cây (dừng nhầm).
- **Thay đổi:** `configs/objectnav/goal-categories-v2.json` (v1 + `vase` trong plant), `configs/objectnav/paper-b1p-v1.json`
  (= `paper-b0-v1` + mapping v2). Không sửa code.
- **Run:** `paper-b1p-v1-plant9` (9 episode plant của DEV) trước; sau đó DEV60 nếu có lợi.
- **Kết quả `paper-b1p-v1-plant9`** (20/11/2026, 0,2 h, exit 0): SR plant **3/9** (B0 2/9); thắng 3, thua 2, net +1.
  - Thắng: `k1cupFYWXJ6/0#3`, `/4#3`, `/6#3` (B0 seen_not_detected) — cả ba xác nhận cây bằng nhãn **vase** (12, 9, 6
    frame ≥ 0,5; điểm cao nhất 0,77–0,85).
  - Thua: `k1cupFYWXJ6/3#3` dừng ở cụm vase yếu (2 frame, 0,39/0,37) thay vì cây thật (cụm vase 0,78, 5 frame ≥ 0,5,
    đúng vị trí cây mà `/6#3` thành công); `TEEsavR23oF/3#6` dừng ở flower vase thật nhưng DTG 0,11 m (hụt 1 cm).
  - Gần như mọi detection trên cây đều mang nhãn vase; nhãn "plant" hiếm và điểm thấp (0,25–0,34). Hai ca plant B0
    thành công dựa trên "plant" 0,25–0,32, nên **không** được nâng ngưỡng chung của plant.
  - Mapping v2 còn đưa vase vào memory ở **mọi** episode (có thể ghép vào cụm của vật khác). Bỏ v1; file
    `goal-categories-v2.json` và `paper-b1p-v1.json` lưu trong `runs/objectnav/paper-b1p-v1-plant9/provenance/`.

## 20/11/2026 — P1 v2: `target_labels` (vase chỉ tính trong episode plant, điểm ≥ 0,5)

- **Thay đổi:** `PaperB0Config.target_labels` (mặc định `None` = B0), `paper/b0.py::_perceive`: nhãn trong bảng chỉ
  được đưa vào memory khi goal của nó là target của episode và điểm ≥ `min_score`. Ngưỡng 0,5 = ngưỡng của bed / sofa /
  chair / tv, đặt trước, không dò theo ca. Mapping v1 giữ nguyên ⇒ episode không phải plant chạy **y hệt** B0 (cùng
  code path). Config `configs/objectnav/paper-b1p-v2.json`. Test mới `tests/test_objectnav_b1_plant.py` (5 passed).
- **Run:** `paper-b1p-v2-plant9`.
- **Kết quả `paper-b1p-v2-plant9`** (20/11/2026, 0,3 h, exit 0; paper tests 33 passed): SR plant **4/9** (B0 2/9);
  thắng 3 (`k1cupFYWXJ6/0#3`, `/4#3`, `/6#3`), thua 1 (`TEEsavR23oF/3#6`: dừng ở flower vase thật, DTG 0,11 m, hụt
  1 cm — không sửa có nguyên tắc), **net +2**. `k1cupFYWXJ6/3#3` thành công trở lại (cụm vase 0,39 bị lọc).
  - Episode không phải plant: code path y hệt B0 (`target_labels` chỉ đọc khi goal == target) ⇒ kết quả DEV60 của
    P1 v2 đúng bằng B0 + 9 episode này: **SR 38/60, thắng 3, thua 1** (suy ra từ tính tất định; sẽ xác nhận bằng DEV60
    của cả bó).

## 20/11/2026 — P2 thử: cầu thang (`nav.step_max_m`) — tạm gác

- Dựng lại bản đồ của `wcojb4TFT35/1#2` và `k1cupFYWXJ6/8#2` (never_seen, hết frontier sớm): vùng cầu thang / bậc
  cao hơn thân 0,2–0,88 m bị đánh dấu vật cản, nên không có frontier đi tiếp.
- Cài `ObstacleMap._step_surface` (cờ `step_max_m`, mặc định tắt): ô 5 cm có độ chênh trong ô < 0,22 m và nối với
  sàn qua các ô lân cận chênh ≤ 0,22 m thì không phải vật cản; ô bậc được nhớ (`level.step`). Test tổng hợp
  (`tests/test_objectnav_b1_stairs.py`, 2 passed): bậc thang → free, hộp 0,45 m và tường → vật cản.
- Chạy thử 3 episode (scratchpad): **không đổi** (59/96/125 bước, vẫn hết frontier). Render RGB tại điểm kẹt của
  `wcojb4TFT35`: chiếu nghỉ cầu thang hẹp có tay vịn, cầu thang đi xuống sát tường; hình học phức tạp hơn mô hình bậc.
- **Quyết định:** tạm gác (không chạy DEV60); code để sau cờ tắt, sẽ gỡ khỏi nhánh nếu không quay lại.

## 20/11/2026 — P3: hỏi VLM trước khi STOP (sofa, toilet)

- **Dữ liệu:** render lại RGB của 48 lần dừng trên một ứng viên ở `paper-b0-dev60` (pose của frame cuối có detection
  của ứng viên, camera paper); xem bằng mắt: cả 7 `wrong_object_stop` sofa là **armchair một chỗ**.
- **Qwen3-VL-2B Q4_K_M** (llama.cpp CPU, local, ~2–15 s/câu) trên ảnh cắt (bbox + 15 %):
  - câu có/không: trả lời "yes" gần như mọi ảnh (cả 7 armchair) → vô dụng;
  - câu A/B ("một người / hai người trở lên"): kết quả đổi theo thứ tự chữ cái → thiên vị vị trí, bỏ;
  - **câu mở** "What is the main piece of furniture in this image? Answer with one or two words.":
    sofa thật 8/8 "couch"; armchair dừng nhầm 5/7 "chair(s)/armchair" (`k1cupFYWXJ6/7`, `TEEsavR23oF/0#3` vẫn "couch");
    toilet thật 9/9 "toilet", toilet dừng nhầm `TEEsavR23oF/4#6` → "bed". Với tv / plant / chair câu mở trả lời sai
    nhiều ca đúng ("couch", "bed", "table", "bar stool") ⇒ **chỉ bật cho sofa và toilet**.
  - Ghi chú trung thực: đã thử 3 dạng câu hỏi trên chính các lần dừng DEV; câu chọn là dạng chung nhất, không có từ
    khoá của ca nào.
- **Cài:** `src/neusymnav/objectnav/paper/vlm_verify.py` (khởi động `llama-server` khi cần, dừng cùng policy),
  `PaperB0Config.vlm_verify` (mặc định `None` = B0); `_perceive` giữ ảnh cắt mới nhất / điểm cao nhất theo cid cho
  target có trong `targets`; `VERIFY` hỏi một lần mỗi ứng viên, câu trả lời không chứa từ đồng nghĩa của target ⇒
  `reject:vlm_rejected`. Config `configs/objectnav/paper-b1v-v1.json`. Test `tests/test_objectnav_b1_vlm.py` 3 passed.
- **Chạy thử sim 3 episode** (scratchpad `diag-v1`): `qyAac8rV8Zk/2#5` sofa thật → "couch", chấp nhận, thành công
  (70 bước, như B0); `k1cupFYWXJ6/5` hai armchair → "chair" / "armchairs", loại, rồi hết 500 bước không tìm thấy sofa
  thật; `TEEsavR23oF/4#6` toilet dừng nhầm → "bed", loại, hết 500 bước. Mỗi câu hỏi 7–19 s wall (CPU). Server tự tắt.

## 20/11/2026 — DEV60 bó P1 + P3 (`paper-b1pv-v1-dev60`)

- Config `configs/objectnav/paper-b1pv-v1.json` (sha256 `38429b6bb9c0dd76…`) = P1 v2 + P3; nav như B0 (không có luật
  cầu thang). Lệnh: `bash tools/objectnav/paper/run_dev60.sh paper-b1pv-v1-dev60 b0 configs/objectnav/paper-b1pv-v1.json paper-b0-dev60`.
- **Kết quả (xong 23:32, exit 0, 33 tests passed, wall 1.7 h, median 75 s/episode):**
  SR **39/60 (0.650)** [0.517, 0.767] · SPL **0.251** · SoftSPL 0.305 · OSR 48/60 · DTG 1.35 m · invalid 0.
  So với B0-paper (SR 36/60, SPL 0.231, OSR 44/60): **wins 4, losses 1, net +3, McNemar chính xác p = 0.375 → keep rule PASS**
  (vừa đúng ngưỡng; p không có ý nghĩa thống kê).
  - win `k1cupFYWXJ6/0#3`, `/4#3`, `/6#3` (plant, B0 `seen_not_detected` → OK nhờ `vase`→plant): khớp đúng dự báo P1 v2.
  - win `wcojb4TFT35/4#5` (sofa, B0 `wrong_object_stop` → OK): VLM loại 2 lần "chair", nhận "couch" ở ứng viên thứ ba.
  - loss `TEEsavR23oF/3#6` (plant, `stopped_too_far` tại bình hoa thật, DTG 0.11 m): khớp dự báo P1 v2.
  - Failure modes (evidence): stopped_too_far 6, never_seen 5, seen_not_detected 4, wrong_object_stop 3,
    budget_exhausted 2, stopped_elsewhere 1. End reasons: confirmed_target 47, max_steps 6, frontiers_exhausted 6, fallback 1.
- **VLM:** 27 episode có hỏi (sofa + toilet), 35 câu, 13 lần loại; 4.2–16.3 s/câu. Không có sofa/toilet thật nào bị loại
  dẫn tới thua. Các lần loại armchair ở `k1cupFYWXJ6/4`, `/5`, `/6` và toilet "bed" ở `TEEsavR23oF/4#6` đổi lần dừng sai
  thành hết bước (thất bại ở cả hai), nên không thắng. `k1cupFYWXJ6/7` và `TEEsavR23oF/0#3` vẫn "couch" như offline.
- **Quyết định:** bó qua cổng, giữ nhánh. Phần đóng góp: P1 net +2, P3 net +1. Cầu thang P2 (`step_max_m`) không nằm
  trong bó và không có tác dụng → sẽ gỡ trước khi chốt code. Chưa commit (chờ bàn với teammate); TEST xác nhận chỉ chạy
  khi người dùng đồng ý vì cần ~thời gian GPU riêng.

## 21/11/2026 — Dọn code + TEST180 xác nhận

- Gỡ P2 cầu thang khỏi cây (không có tác dụng trên DEV): `nav.py`, `obstacle_map.py` về B0; bỏ trường `step_cells` trong
  `b0.py`; xoá `configs/objectnav/paper-b1s-v1.json`, `tests/test_objectnav_b1_stairs.py`. Bản patch + config + test lưu ở
  `runs/objectnav/_archive/B1-lastmile-P2-stairs-20261120/`. Test paper + plant + vlm: 41 passed.
- TEST180 (`configs/objectnav/splits/hm3d_v2-val-test.json`, 30 scene, chỉ xác nhận, không tinh chỉnh): chưa có tham
  chiếu B0-paper trên TEST nên chạy tuần tự `paper-b0-test180` (config `paper-b0-v1.json`) rồi `paper-b1pv-v1-test180`
  (config sha `38429b6bb9c0dd76…`, `--ref paper-b0-test180`). Ước tính ~9–10 h tổng.
- **Kết quả TEST180 (exit 0 cả hai, 33 tests passed, 6.3 h mỗi lượt):**
  - `paper-b0-test180`: SR **112/180 (0.622)** · SPL 0.210 · OSR 140/180 (2 invalid_episode).
  - `paper-b1pv-v1-test180`: SR **113/180 (0.628)** · SPL 0.220 · OSR 138/180.
  - So cặp: **wins 5, losses 4, net +1, McNemar p = 1.000 → keep rule FAIL trên TEST.**
  - Plant (vase→plant): thắng `5cdEh9F2hJL/1#3`, `mL8ThkuaVTM/0#3`, `mL8ThkuaVTM/5`, `yr17PDCnDDW/2`; thua
    `DYehNKdT76V/2`, `Dd4bFSTQ8gi/3#3` (wrong_object_stop: vase không có cây) và `a8BtkwhxdRV/1` (stopped_too_far) → net +1.
  - VLM: 44 episode, 48 câu, 6 lần loại. Thắng `CrMo8WxCyVb/0#3` (sofa: "chair" bị loại, rồi "couch"); thua
    `4ok3usBNeis/0` (toilet thật bị gọi là "cabinet", loại, rồi stopped_too_far) → net 0.
  - wrong_object_stop tăng 20 → 25, seen_not_detected giảm 9 → 4: vase→plant đổi lỗi "không nhận ra" thành "dừng nhầm".
- **Đánh giá:** mức tăng DEV (+3) không lặp lại trên TEST (+1, nhiễu). Theo quy tắc không tinh chỉnh trên TEST, nên coi bó
  này **chưa phải cải thiện SR**. Quyết định giữ/bỏ nhánh để bàn với teammate. Hết ngân sách 1 ngày; không chạy thêm vòng sửa.

## 21/11/2026 — Vòng tiếp theo (ngân sách +2 ngày): mở rộng DEV

- Bài học từ TEST180: DEV60 (6 scene) quá nhỏ và lệch phân bố lỗi. B0 TEST có wrong_object_stop 20/180 (11 %), còn DEV60
  chỉ 3–8/60. Mức +3 trên DEV đã biến thành +1 trên TEST.
- Thêm `configs/objectnav/splits/hm3d_v2-val-dev-extra.json`: toàn bộ 107 episode val còn lại của 6 scene DEV (không chạm
  scene TEST). DEV60 + 107 = **DEV167**. Chạy B0-paper trên phần thêm: `paper-b0-devx107` (config `paper-b0-v1.json`).
- Đề xuất (chờ người dùng duyệt): dùng DEV167 làm cổng giữ nhánh thay cho DEV60.
- **Người dùng duyệt (21/11/2026): cổng giữ nhánh dùng DEV167** (= `hm3d_v2-val-dev` + `hm3d_v2-val-dev-extra`), so cặp
  với B0-paper (`paper-b0-dev60` + `paper-b0-devx107`), luật wins − losses ≥ 3 giữ nguyên. TEST180 chỉ để xác nhận.

## 21/11/2026 — Ý tưởng bị loại bằng số liệu: bắt buộc phát hiện lại ở gần trước STOP

- Đo trên 47 lần dừng "confirmed" của `paper-b0-dev60` (evidence theo frame, cid của ứng viên): dừng nhầm sofa (armchair)
  vẫn được phát hiện là sofa ở 6 bước cuối với score 0,63–0,77 (11/12 ca sai có phát hiện lại); 12/34 ca đúng có score
  phát hiện từ lúc FACE = 0 (vật quá sát camera). ⇒ luật này mất ca đúng mà không cứu ca sai; **không cài, không chạy sim**.
  Script: scratchpad `redetect.py`.

## 21/11/2026 — B1-ctx v1: ưu tiên frontier theo vật ngữ cảnh (ESC / L3MVN)

- **Lý do:** trên TEST B0, lỗi khám phá (budget_exhausted 12 + never_seen 9 = 21/180) ngang dừng nhầm (20/180); nhánh
  value-map trước đây chỉ thử ở lockstep. Không cần model mới: YOLOE taxonomy-v1 có sẵn sink, bathtub, nightstand, wardrobe,
  coffee table, dining table…
- **Cài:** `src/neusymnav/objectnav/paper/context_prior.py` + `PaperB0Config.context_prior` (mặc định `None` = B0).
  Mỗi detection có nhãn thô nằm trong bảng của target và score ≥ 0,4 → điểm ngữ cảnh (median xy, độ cao sàn robot).
  Frontier = argmin(path cost − 4 m × max wᵢ·exp(−dᵢ/1,5 m)), chỉ điểm cùng tầng (±0,5 m) trong bán kính 4 m. Không có điểm
  ngữ cảnh ⇒ đúng frontier gần nhất của B0. Log `context_prior` {points, labels, choices, changed} mỗi episode.
- **Config** `configs/objectnav/paper-b1c-v1.json` = B0-paper + context_prior (không gộp P1/P3 để đo riêng). Bảng trọng số
  viết tay theo common sense ngày 21/11 trước mọi lần chạy, không tinh chỉnh trên DEV/TEST.
- Test `tests/test_objectnav_b1_ctx.py` 4 passed; paper_b0 + plant + vlm + ctx 16 passed (B0 không đổi khi tắt cờ).
- **Chạy (xếp hàng sau `paper-b0-devx107`):** `paper-b1c-v1-dev60` (ref `paper-b0-dev60`) rồi `paper-b1c-v1-devx107`
  (ref `paper-b0-devx107`). Cổng: net cộng hai phần (DEV167) ≥ 3.
- Đổi thứ tự (13:35): dừng `paper-b0-devx107` sau 4/107 episode (resumable) để chạy `paper-b1c-v1-dev60` trước (phản hồi
  nhanh), rồi chạy tiếp B0 dev-extra, rồi `paper-b1c-v1-devx107`. Khi chạy tiếp, B0 dùng `b0.py` đã có cờ `context_prior`
  (mặc định tắt, đường B0 không đổi; REPORT sẽ có WARNING "tracked code changed").
- **Song song (người dùng cho phép 21/11, khi máy đủ tài nguyên):** máy 12 nhân / 15 GB, một run ~1 GB RSS, tải ~2,6 ⇒
  chạy 2 run cùng lúc. `run_dev60.sh` thêm `NSNAV_PARALLEL=1` để bỏ khoá một-run (worker dùng pipe, không cổng). Không bao
  giờ chạy hai config có VLM cùng lúc (cổng 8712). Kết quả paper mode tất định theo bước, nên chạy song song chỉ đổi wall time.
- **Tài liệu (web, 21/11):** ApexNav ablation HM3Dv2: fusion theo thể tích + phạt khi thấy cụm mà không có nhãn
  (c_det = 0) đóng góp lớn (76,2 vs 70,2 không phạt; 67,9 max-confidence), ngưỡng LLM theo lớp (sofa 0,6, bed 0,65,
  plant 0,4); VLFM: một detection là đủ, đích = điểm contour gần nhất, dừng trong 1 m. Ghi chú: nhánh ApexNavRef đã thử
  belief log-odds và mất recall; các ca armchair→sofa ở DEV được YOLOE gán sofa nhất quán nên fusion khó cứu.

## 21/11/2026 — B1-ctx v1 trên DEV60 (`paper-b1c-v1-dev60`)

- Exit 0, 33 tests passed, wall 2,4 h (chạy song song với `paper-b0-devx107`), median 91 s/episode.
  SR **38/60 (0,633)** · SPL 0,236 · OSR 47/60. So với B0-paper: **wins 2, losses 0, net +2, p = 0,5** (cổng DEV60 FAIL;
  cổng chính thức là DEV167, chờ `paper-b1c-v1-devx107`).
  - win `LT9Jq6dN3Ea/1#4` (sofa, stopped_too_far → OK, 164 → 373 bước); win `qyAac8rV8Zk/3` (tv, stopped_elsewhere → OK,
    208 → 139 bước).
- 43/60 episode trùng hệt B0, 17 rẽ hướng (context đổi 1–5 lần chọn frontier); trong 17 ca: nhanh hơn 7, chậm hơn 8; thay
  đổi xấu: `k1cupFYWXJ6/6` sofa wrong_object_stop → seen_not_detected (vẫn thất bại), `TEEsavR23oF/4#6` toilet
  wrong_object_stop → stopped_too_far (vẫn thất bại). Lỗi còn lại: stopped_too_far 5, never_seen 5, wrong_object_stop 5,
  seen_not_detected 4, budget_exhausted 3.
- **Bó v2 `configs/objectnav/paper-b1cpv-v1.json`** = B1-ctx v1 + P1 (vase→plant) + VLM **chỉ sofa** (toilet bỏ: trên DEV60
  VLM toilet loại 1 lần, không thắng ca nào; ghi chú trung thực: kết quả TEST180 của b1pv đã được xem trước quyết định này,
  nên TEST không còn "sạch" cho riêng phần toilet). Vì P1/P3 chỉ đổi episode plant/sofa (tất định), chạy bó chỉ trên 64 episode
  plant + sofa của DEV167 (`paper-b1cpv-v1-ps64`), phần còn lại lấy từ B1-ctx. Script cổng: scratchpad `dev167.py`.

## 21/11/2026 — Chẩn đoán "bỏ cuộc sớm" và sửa F1: thử frontier lần cuối không inflation

- **Quan sát (B1-ctx DEV60):** trong 8 ca never_seen / budget_exhausted, 5 ca kết thúc `frontiers_exhausted` sớm (58–126
  bước, trừ 1 ca 453) với vật đích chỉ cách 2,6–6,9 m.
- **Chẩn đoán** (scratchpad `fxdiag.py`, dump map lúc kết thúc, 5 ca): map **vẫn còn 1–8 frontier** nhưng không cái nào
  tới được kể cả với inflation nới 0,08 m; blacklist = 0. Robot nằm trong túi 300–4.900 ô; bỏ inflation thì túi nối với
  vùng đã khám phá lớn ở 3/5 ca (TEEsavR23oF/3#4 10.415 ô, k1cupFYWXJ6/8#2 34.114, wcojb4TFT35/1#2 8.674); 2 ca còn lại
  (wcojb4TFT35/3, qyAac8rV8Zk/3#5) bị bao kín thật (cầu thang / mép tầng).
- **Sửa:** `NavConfig.last_resort_inflate_m` (mặc định `None` = B0). Khi cả inflation thường và nới đều không có frontier,
  lập kế hoạch thêm một lần với inflation này (config dùng 0,0): simulator (`allow_sliding: false`) tự từ chối khe không đi
  được, va chạm lặp lại thành bump (vẫn chặn với bán kính đầy đủ) nên không lặp vô hạn. Fallback ứng viên chưa xác nhận
  vẫn được thử trước như B0. Log `map.last_resort_steps`. Test thêm 1 (túi sau khe 0,15 m): `test_objectnav_b1_ctx.py` 5 passed.
- Config `configs/objectnav/paper-b1cx-v1.json` = B1-ctx v1 + `nav.last_resort_inflate_m: 0.0`. Chỉ đổi episode mà
  B1-ctx dừng vì frontiers_exhausted ⇒ chạy tập con: `paper-b1cx-v1-fx6` (6 ca DEV60, ref `paper-b1c-v1-dev60`).

## Bảng file theo thành phần (cập nhật 21/11/2026 17:20)

Mỗi thành phần bật bằng cờ config riêng; mặc định tắt = B0-paper.

| Thành phần | Cờ config | Code | Test | Config |
|---|---|---|---|---|
| P1 vase→plant | `target_labels` | `paper/b0.py` (`_perceive`) | `tests/test_objectnav_b1_plant.py` | `paper-b1p-v2.json` |
| P3 VLM trước STOP | `vlm_verify` | `paper/vlm_verify.py`, `paper/b0.py` (`_vlm_ok`) | `tests/test_objectnav_b1_vlm.py` | `paper-b1v-v1.json`, `paper-b1pv-v1.json` |
| B1-ctx context prior | `context_prior` | `paper/context_prior.py`, `paper/b0.py` (`_act_explore`) | `tests/test_objectnav_b1_ctx.py` | `paper-b1c-v1.json` |
| ~~F1 frontier lần cuối~~ (gỡ 21/11, không có tác dụng) | — | lưu `runs/objectnav/_archive/B1-F1-last-resort-20261121/` | — | — |
| Bó v2 | — | — | — | `paper-b1cpv-v1.json` (hủy chạy 21/11 17:05) |

Công cụ: `tools/objectnav/paper/run_dev60.sh` (thêm `NSNAV_PARALLEL`), `tools/objectnav/paper/dev167_gate.py` (cổng DEV167),
`tools/objectnav/b1/frontier_exhaustion_diag.py`, `tools/objectnav/b1/redetect_at_stop.py`. Split:
`configs/objectnav/splits/hm3d_v2-val-dev-extra.json`. Không thuộc nhánh này (B1-revisit lockstep, giữ nguyên theo người dùng):
`mapping/occupancy.py`, `objectnav/runner.py`, `sim_worker_entry.py`, `tools/objectnav/run_episodes.py`, `b1_revisit/`, `diag/`, `oracle/`.

## 21/11/2026 17:10 — F1 trên 6 ca frontiers_exhausted (`paper-b1cx-v1-fx6`): 0 thắng ⇒ gỡ

- Exit 0, wall 0,5 h. SR 0/6 (ref B1-ctx 0/6), wins 0, losses 0. Cả 6 ca vẫn kết thúc `frontiers_exhausted`, gần cùng bước
  (TEEsavR23oF/3#4 125 → 131, wcojb4TFT35/1#2 57 → 68, các ca khác như cũ); thử lần cuối 1–16 bước, va chạm 1–21.
- **Kết luận:** các khe nối túi với vùng lớn là khe thật quá hẹp cho thân robot (simulator từ chối); không phải lỗi inflation.
  Muốn cứu nhóm này phải đi được cầu thang / tầng khác — ngoài phạm vi chiến dịch. **Gỡ F1** (code `nav.py`, log trong
  `b0.py`, test, config) — patch và config lưu ở `runs/objectnav/_archive/B1-F1-last-resort-20261121/`. Test ctx còn 4 passed.
