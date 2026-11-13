# Bàn giao ObjectNav: mốc B0 và bộ chấm (13/11/2026)

Trang này dành cho người làm policy chuyển động. Nó cho biết cách chạy và chấm một
policy, mốc B0 chính thức cần vượt qua, và chỗ B0 đang mất điểm. Nhánh `objectnav`.

Đọc theo thứ tự: mục 1–2 (mốc và chỗ mất điểm), mục 3 (cắm policy), mục 4 (quy tắc của
bộ chấm), mục 6 (so với B0). Số liệu và dữ liệu từng episode đã khoá nằm ở
[`results/`](results/README.md). Code của bộ chấm: tag `objectnav-scorer-v3` (`85cb146`).
Code của B0: tag `objectnav-b0-v3h-dev60` (`2dcb0ea`).

## 1. Mốc chính thức

B0: quay tại chỗ → khám phá frontier → xác nhận vật thể bằng detector YOLOE-26m →
tiếp cận → quay mặt → xác minh → STOP. Không dùng 3DSG, tour hay nhãn phòng.
Cấu hình `configs/objectnav/lockstep-b0-v3h.json` + `configs/objectnav/b0-policy-v3.json`
([thiết kế](phase3-b0-design.md)). Bộ chấm schema 3, commit `85cb146`.

60 episode DEV (6 scene × 10, `configs/objectnav/splits/hm3d_v2-val-dev.json`), chạy một
lần 13/11 01:09–06:58:

| | SR [95 % CI] | SPL [95 % CI] | SoftSPL | OSR | DTG cuối |
|---|---|---|---|---|---|
| **B0 v3h (mốc)** | **0,283 [0,183, 0,400]** | **0,064 [0,036, 0,099]** | 0,114 | 0,417 | 3,48 m |
| B0 v1 (dev1, chấm lại bằng schema 3) | 0,167 [0,083, 0,267] | 0,065 [0,029, 0,109] | 0,129 | 0,217 | 3,80 m |

So cặp theo episode: v3h thành công mà v1 không ở 8 episode, ngược lại 1 episode
(McNemar chính xác p = 0,039). SPL không tăng: tổng quãng đường của các lần thành công
có trung vị 5,1 × geodesic.

Theo category: bed 0,50, chair 0,56, tv_monitor 0,33, toilet 0,25, sofa 0,13, plant 0,11.

**Lưu ý:** 9 episode dùng để tinh chỉnh v2/v3/v3h (step 4–8) nằm trong DEV, nên con số
DEV hơi lạc quan. Tập TEST (180 episode, 30 scene, không trùng DEV) chưa chạy lần nào.
Chỉ chạy TEST một lần cho mỗi policy đã chốt.

## 2. B0 mất điểm ở đâu (bằng chứng offline, 60 episode)

| Bước | Episode |
|---|---:|
| Mục tiêu từng vào tầm ≤ 3 m | 30 |
| Detector thấy mục tiêu (IoU ≥ 0,1) | 29 |
| Xác nhận một vật thể đích | 26 |
| STOP | 37 |
| STOP trên vật thể đích | 19 |
| Thành công | 17 |

Lỗi: `never_seen` 26, `budget_exhausted` 6, `wrong_object_stop` 5 (armchair thành sofa 5,
chair 1), `stopped_too_far` 3, `seen_not_detected` 2, `stopped_elsewhere` 1.

Thứ tự ưu tiên cho policy:

1. **Khám phá (26/60 chưa bao giờ thấy mục tiêu).** Đây là phần lớn nhất. 23 episode
   kết thúc vì `max_sim_time` (500 s), 7 vì `stuck`. Ở 26 episode này, đích trung vị
   chỉ cách start 5,7 m (geodesic). Robot đi 20,5 m trong 500 s, tốc độ trung bình
   0,053 m/s so với 0,15 m/s danh định. Trong các lệnh: 41 % `tracking`, 13 %
   `align_heading`, khoảng 33 % là guard chặn hoặc thoát kẹt
   (`robot_not_on_observed_free_cell` 11 %, `escape_bootstrap_blocked` 10 %,
   `bootstrap_blocked` 6 %, `escape_step`/`escape_rotate` 12 %). Hai nguyên nhân chồng
   lên nhau: chuyển động chậm vì guard, và frontier không có ưu tiên ngữ nghĩa.
2. **Dừng khi đã tới (8/60).** Robot vào dưới 0,1 m của view point nhưng không STOP.
   `wcojb4TFT35/3#4` và `LT9Jq6dN3Ea/1#6` (bed) có DTG cuối 0,04 m nhưng hết budget.
3. **Hiệu quả đường đi (SPL 0,064).** Có thành công nhưng đường đi rất dài.
4. Perception, không thuộc policy: nhầm armchair thành sofa; plant recall 0,02 ([phase 2](phase2-detector-results.md)).

## 3. Cắm và chấm một policy

Runner lockstep, đồng hồ mô phỏng, chạy lại cho cùng kết quả:
`src/neusymnav/objectnav/runner.py`. Mỗi cycle: capture → map → detector → policy →
guard → execute. Policy là object có `reset(episode)` và `act(ctx) -> PolicyAction`.

- `StepContext` gồm `episode` (**chỉ được đọc `object_category`**), `nav` (NavSnapshot),
  `navigation_obs` (depth), `robot_xy`, `yaw_rad`, `now_ns`, `cycle`, `navigator`.
- `PolicyAction(stop, decision, note)`: `decision` đi qua `MotionGuard`, guard có quyền chặn.
- Mẫu đơn giản: `ExplorePolicy`. Mẫu đầy đủ: `src/neusymnav/objectnav/b0/policy.py`.
- Guard: `lockstep-b0-v3h.json` bật escape (`escape`), column fallback (`column_fallback_cells` 6)
  và planar height tolerance 0,15 m (`src/neusymnav/navigation/safety.py`). Policy mới nên dùng
  cùng runner config để chỉ có policy khác nhau khi so với B0. Nếu đổi guard thì ghi rõ đã đổi,
  vì kết quả khi đó gộp cả hiệu ứng của guard.
  Đăng ký một lựa chọn `--policy` mới trong `tools/objectnav/run_episodes.py` (chỗ `a.policy == 'b0'`).
- Quy tắc (`AGENTS.md`): input chỉ gồm RGB-D và pose simulator. Không dùng semantic GT,
  navmesh, view point hay tour. Control không được chờ detector.

Chạy (resume được) rồi chấm, từ gốc worktree:

```bash
PYTHONPATH=src .venv/bin/python tools/objectnav/run_episodes.py --set hm3d_v2 --split val \
    --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --policy <tên> --run-id <id> \
    --out-dir runs/objectnav/<id> --config configs/objectnav/lockstep-b0-v3h.json
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/score_trajectories.py \
    runs/objectnav/<id>/trajectories.jsonl --set hm3d_v2 --split val
```

Mẫu đầy đủ (bản chụp nguồn gốc, test, chạy, chấm, bằng chứng lỗi, chẩn đoán, báo cáo):
`tools/objectnav/b0/run_dev60.sh`. Không tham số thì chạy lại đúng mốc B0. Cho policy
khác: `OUT=runs/objectnav/<id> RUN_ID=<id> POLICY=<tên> bash tools/objectnav/b0/run_dev60.sh`.
Các bước bằng chứng lỗi, chẩn đoán và báo cáo đọc file `evidence/` mà B0 ghi ra. Policy
khác cần ghi cùng định dạng, hoặc chỉ dùng bước chấm.
Thời gian của B0: khoảng 320 s wall mỗi episode (60 episode ≈ 5 h 20 phút, CPU + iGPU).
Mapper chiếm 45 %.

## 4. Bộ chấm (đã đóng băng ở schema 3)

`src/neusymnav/evaluation/objectnav_metrics.py`, `tools/objectnav/score_trajectories.py`.
Dùng định nghĩa habitat-lab: success = STOP và DTG < 0,1 m tới view point; SPL dùng
geodesic lúc start trên cùng navmesh. Có thêm hai chỉ số chẩn đoán:

- **OSR / min-DTG** ([kết quả](oracle-metrics-results.md)).
- **Snap view point** `snap-to-scorer-navmesh-v1`: view point của episode nằm thấp hơn
  navmesh 0,05–0,15 m nên phải snap lên navmesh ([lý do](footprint-vs-viewpoint-results.md)).

Validation val_mini: oracle_path SR 1,0 / SPL 1,0; oracle_greedy SR 1,0 / SPL 0,944;
random SR 0,067.

Chỉ sửa bộ chấm khi có bằng chứng nó đo sai (validation agent trượt, hoặc cùng
trajectory cho hai kết quả khác nhau). Khi sửa phải tăng `schema_version` và chấm lại
mọi run đang được so sánh. SR thấp không phải lý do để sửa bộ chấm. SR chấm trước
13/11 (schema ≤ 2) không so sánh được với kết quả hiện tại.

## 5. Artifact và nguồn gốc

- Run (chỉ có trên máy chạy, `runs/` bị git ignore): `runs/objectnav/b0/dev60-v3h/`
  (`trajectories.jsonl`, `trajectories+evidence-*`, `report.md`,
  `step9_dev60_official.log`, `evidence/`).
- Code của mốc: `2dcb0ea` (tag `objectnav-b0-v3h-dev60`), trùng từng byte với bản chụp.
- Nhánh `objectnav` đã rebase lên `main`. Khác biệt duy nhất so với tag nằm ở `occupancy.py`
  (tham số `preserve_known_overview`, mặc định tắt, B0 không dùng). Chi tiết ở
  [`results/README.md`](results/README.md).
- Bản sao đã commit của summary, outcomes, report và SHA config: `docs/objectnav/results/b0-dev60-v3h/`.
  Bộ chấm: tag `objectnav-scorer-v3` (`85cb146`).
- Nguồn gốc lúc chạy: `runs/objectnav/b0/dev60-v3h/provenance/` (HEAD `85cb146`, diff của file
  đã track, tgz và SHA-256 của 20 file chưa track, SHA config). Sau khi chạy đã kiểm
  tra: code đã track và chưa track đều trùng bản chụp.
- Mốc tham chiếu v1: `runs/objectnav/b0/dev1/score-snap-v1-*`.

## 6. So sánh một policy mới với B0

1. Chạy trên cùng 60 episode DEV bằng `tools/objectnav/b0/run_dev60.sh` với `OUT` riêng.
2. So SR/SPL kèm khoảng tin cậy, và **so cặp theo episode** (thắng/thua, McNemar), vì
   CI của 60 episode rộng (SR ± 0,1).
3. Xem funnel và các lỗi (`report.md`) để biết policy cải thiện ở bước nào.
4. Khi đã chốt một phiên bản, chạy TEST (180 episode) một lần cho policy đó và cho B0.
