# ObjectNav — kế hoạch chế độ "paper protocol" (theo VLFM / ApexNav)

Ngày lập: 19/11/2026. Trạng thái: **P0–P5 đã triển khai, chờ các run DEV60 của P6** (người dùng duyệt kế hoạch và D1–D7 ngày 19/11/2026).
Tiến độ, kiểm chứng và lỗi đã sửa: [journal paper-protocol](journal/paper-protocol.md).

Chạy (người dùng chạy, mỗi lệnh khoảng 1–5 h, ghi `runs/objectnav/<tên>/REPORT.txt`):
```bash
bash tools/objectnav/paper/run_dev60.sh paper-explore-dev60 explore
bash tools/objectnav/paper/run_dev60.sh paper-b0-dev60 b0
bash tools/objectnav/paper/run_dev60.sh paper-b1r-dev60 b1 configs/objectnav/paper-b1r-v1.json paper-b0-dev60
```

## 1. Mục tiêu và lý do

- **Mục tiêu:** phát triển và so sánh **policy** ObjectNav trên đúng protocol mà các paper (VLFM, ApexNav) dùng, để:
  1. số SR/SPL so được trực tiếp với paper;
  2. thắng/thua giữa hai policy phản ánh policy, không phải tầng chuyển động tự viết.
- **Lý do đổi:** các vòng B1-revisit gần đây chủ yếu sửa tầng thấp, không sửa policy:
  - stuck8;
  - bug clearance float32;
  - floor datum;
  - vật treo che camera 2,0 m;
  - bậc thấp 0,14 m.
  Xem [journal B1-revisit](journal/B1-revisit.md).
- **Cách paper làm:** Habitat tự chặn va chạm bằng navmesh. Agent ra lệnh rời rạc; nếu đâm thì đứng yên
  (`allow_sliding: False`). Không có guard, không có bước chứng nhận chỗ đứng.
- **Không thay thế stack lockstep hiện tại:** chế độ lockstep giữ nguyên, đóng băng làm "robot mode". Chế độ paper là
  một **chế độ đánh giá riêng**, dùng chung bộ chấm, episode, detector và bộ nhớ ứng viên.

## 2. Quyết định cần người dùng chốt trước khi code

| # | Quyết định | Đề xuất | Ghi chú |
|---|---|---|---|
| D1 | Chế độ paper được miễn các invariant robot-thật trong `AGENTS.md`: "thiếu depth/clearance phải chặn chuyển động", "control không chờ detector" | **Có**, chỉ trong chế độ paper; ghi rõ trong `AGENTS.md`/`architecture.md` | Shared contract, do main/người dùng quyết |
| D2 | Bộ episode báo cáo cuối | HM3D **v2** val (ApexNav có báo cáo HM3Dv2); thêm HM3D v1 val nếu muốn so VLFM | Dev vẫn dùng DEV60 (HM3D v2 val) |
| D3 | Detector chạy đồng bộ mỗi bước (giống paper), không mô phỏng độ trễ | **Đồng bộ** | Bỏ `LatencyGate` trong chế độ paper |
| D4 | Có dùng hành động `look_up`/`look_down` (±30°) | **Có trong action space**, policy ban đầu không dùng | Theo action space challenge |
| D5 | Nhánh hạ tầng | Nhánh riêng `kiet/paper-protocol` cắt từ `main`, merge qua teammate rồi các nhánh policy kéo về | Đúng [quy tắc nhánh](policy-branch-rules.md) mục 1 |
| D6 | Trạng thái B1-revisit hiện tại (F+G2, chưa commit) | Bàn với teammate, khoá SHA trên `kiet/B1-revisit`, rồi chuyển sang nhánh mới | Giữ đúng quy tắc "chưa commit trước khi bàn teammate" |
| D7 | Mốc so sánh mới | B0-paper và B1R-paper trên DEV60; mốc cũ (lockstep) không so trực tiếp nữa | Ghi vào `policy-branch-rules.md` |

## 3. Protocol tham chiếu

Cột "nguồn" ghi chỗ cần đối chiếu. Mọi giá trị đánh dấu **(xác minh)** phải được kiểm lại từ config gốc trước khi
khoá vào `configs/objectnav/paper-*.json`:
- habitat-lab `objectnav_hm3d.yaml` / `objectnav_hm3d_v2.yaml`;
- config của repo VLFM;
- phần Experiments của paper ApexNav.

Chỉ đọc tài liệu công khai. **Không chép code ApexNav (GPL-3.0).** Với VLFM, kể cả khi license cho phép, vẫn viết
lại và chỉ ghi nguồn.

Đã đối chiếu 19/11/2026 (đọc config công khai, không chép code). Nguồn:
- habitat-lab `main`: `habitat-lab/habitat/config/benchmark/nav/objectnav/objectnav_hm3d.yaml` (gọi tắt **H**),
  `habitat/config/habitat/task/objectnav.yaml` (**T**), `habitat/config/habitat/dataset/objectnav/hm3d.yaml`.
- VLFM (`rai-opensource/vlfm`, `config/experiments/vlfm_objectnav_hm3d.yaml`): kế thừa toàn bộ thông số dưới đây
  từ H, **không ghi đè** thân, cảm biến, hành động, số bước, success hay sliding.
- habitat-lab `main` không có `objectnav_hm3d_v2.yaml`. Config chuẩn dùng dataset HM3D **v1**. Với HM3D v2 ta
  dùng cùng thông số, chỉ đổi dataset.

| Mục | Giá trị | Nguồn |
|---|---|---|
| Thân agent | trụ cao 0,88 m, bán kính 0,18 m | H |
| Navmesh | navmesh đi kèm scene; **không** recompute, **không** start snap | episode được sinh trên navmesh này |
| RGB | 640×480, HFOV 79°, vị trí [0; 0,88; 0] | H |
| Depth | 640×480, HFOV 79°, vị trí [0; 0,88; 0], kẹp vào [0,5; 5,0] m | H (`min_depth`/`max_depth`) |
| `normalize_depth` | mặc định `True` (chia cho 5 m); ta giữ mét đã kẹp, tương đương thông tin | mặc định dataclass (chưa đọc nguyên văn) |
| Hành động | `stop`, `move_forward`, `turn_left`, `turn_right`, `look_up`, `look_down` | T |
| Bước tiến | 0,25 m | mặc định dataclass (chưa đọc nguyên văn) |
| Góc xoay | 30° | H (`turn_angle: 30`) |
| Góc nhìn lên/xuống | 30° | T (`tilt_angle: 30`) |
| Va chạm | **`allow_sliding: False`**: đâm thì đứng yên, không trượt | H (`habitat_sim_v0.allow_sliding`) |
| Độ cao | agent bám độ cao navmesh (lên được cầu thang) | Habitat mặc định |
| Ngân sách | `max_episode_steps: 500`; mọi hành động (kể cả xoay, nhìn) tính 1 bước | H |
| Pose | GPS + compass; ta dùng pose simulator (tương đương) | challenge |
| Thành công | STOP khi `distance_to_goal` (tới VIEW_POINTS) < `success_distance` 0,1 m; SPL = success · d_opt / max(d_opt, d_đi) | T; đã có trong `evaluation/objectnav_metrics.py` |

**Số tham chiếu từ paper** (theo trí nhớ, **phải đối chiếu bảng trong paper** trước khi trích):
- VLFM: HM3D v1 khoảng SR 52,5 / SPL 30,4.
- ApexNav: HM3D v1 khoảng 59,6 / 33,0; HM3D v2 khoảng 76,2 / 38,0.
- Các số này đo trên toàn bộ val (khoảng 1000–2000 episode). DEV60 chỉ dùng để phát triển.

## 4. Kiến trúc chế độ paper

```text
Episode (category, start)                         bộ chấm hiện có (không đổi)
   │                                                      ▲
   ▼                                                      │ positions (x,y,z), called_stop
PaperSim (habitat interpreter, subprocess)                │
   reset(ep) / act(a) → Obs{rgb, depth, pose, collided, step}
   │
   ▼
PaperRunner (vòng ≤ 500 bước, đồng bộ)
   obs → ObstacleMap.update → policy.act(ctx) → action → PaperSim.act
   │
   ├─ ObstacleMap  (bản đồ 2D từ depth camera trước: obstacle / explored / frontier)
   ├─ Planner      (A* trên bản đồ obstacle đã nở theo bán kính)
   ├─ ActionAdapter(waypoint → turn/forward rời rạc + recovery khi collided)
   └─ Policy       (B0-paper, B1R-paper, sau này policy mới; dùng lại CandidateMemory, detector, stop rule)
```

- **Bỏ trong chế độ paper:**
  - `MotionGuard`, bootstrap, `measure_floor`/floor datum, `start_snap`;
  - quy đổi `StepBudget`, `planar_fixed_y_v1`, camera nhìn xuống 2,0 m;
  - xung vận tốc và đồng hồ lockstep.
- **Dùng lại:**
  - `episodes.py`, `score_trajectories.py`, `objectnav_metrics.py`, offline evidence và funnel;
  - detector worker (YOLOE, `b0/detection.py`, bỏ độ trễ);
  - `b0/memory.py` (CandidateMemory, confirmation), `b0/approach.py`;
  - `tools/objectnav/nsnav.sh`, compare và McNemar.
- **Không sửa:** `sensors/habitat_worker.py` (khoá theo baseline-3dsg-v11), `navigation/safety.py`, `mapping/occupancy.py`.
  Chế độ paper có worker và bản đồ riêng.

## 5. Các bước triển khai

Mỗi bước kết thúc bằng: test, exit code, artifact, cập nhật [journal](journal/) và
[implementation-status](../implementation-status.md). Ghi tách bạch `implemented` / `correctness-verified` /
`runtime-validated`. Các run dài do người dùng chạy theo script ghi `REPORT.txt`.

### P0 — Chuẩn bị (không code)
1. Người dùng chốt D1–D7.
2. Đối chiếu bảng mục 3 với config gốc; sửa bảng, ghi nguồn (URL, commit) vào file này.
3. Khoá SHA B1-revisit (D6); cắt nhánh `kiet/paper-protocol` từ `main`.

### P1 — Config protocol
- `configs/objectnav/paper-hm3d-v1.json`: thân, cảm biến, action space, `allow_sliding`, `max_steps`, depth range,
  id protocol `paper-objectnav-hm3d-v1`.
- Loader có kiểm tra kiểu (theo mẫu `RunnerConfig`). Lưu hash config vào mọi trajectory.
- Test: load, từ chối giá trị sai kiểu, hash ổn định.

### P2 — `PaperSim` (worker Habitat rời rạc)
- File: `src/neusymnav/objectnav/paper/sim_worker.py` (chạy bằng habitat python) và `paper/sim_client.py`.
- Dùng `habitat_sim` trực tiếp (habitat-lab **chưa cài**; không cài thêm khi chưa được phép).
- Cấu hình: thân, cảm biến, action space theo P1; navmesh của scene, không recompute.
- API:
  - `reset(episode)` đặt pose start nguyên bản;
  - `act(name)` trả về rgb, depth, pose (x, y, z, yaw), `collided`, bộ đếm bước;
  - quá 500 bước thì từ chối.
- Test (habitat python, scene val_mini):
  - forward đi đúng 0,25 m trên sàn trống;
  - turn đúng 30°;
  - forward vào tường → `collided` và không xuyên;
  - look_up/down đổi pitch camera, không đổi pose thân;
  - đạt 500 bước thì dừng.
- **Kiểm chứng nối với bộ chấm:**
  - viết agent `oracle_path` / `oracle_greedy` chạy **qua PaperSim**, dùng lại logic `scripted_agents.py`;
  - trên DEV60 phải ra SR ≈ 1 (oracle_path) và SR cao, SPL < 1 (greedy), khớp số đã có khi chạy trực tiếp;
  - đây là bằng chứng worker và bộ chấm nhất quán.

### P3 — `PaperRunner`
- File: `src/neusymnav/objectnav/paper/runner.py`; CLI `tools/objectnav/run_paper_episodes.py`; thêm lệnh
  `nsnav paper ...`.
- Vòng: `obs → map.update → policy.act → sim.act`, tối đa 500 bước; STOP kết thúc episode.
- Trajectory dùng **cùng schema** để `score_trajectories.py` chấm không cần sửa.
  - Thêm diagnostics: số `collided`, hành động theo loại, thời gian theo stage, hash config.
- Resume theo uid như runner hiện tại.
- Test: policy giả (đi thẳng, xoay, STOP) ra trajectory hợp lệ; số bước đúng.

### P4 — Bản đồ, frontier, planner, action adapter
- `paper/obstacle_map.py`:
  - chiếu depth camera trước (đã biết pose, pitch) ra điểm 3D;
  - **obstacle** là điểm có chiều cao trong khoảng (sàn + ngưỡng nhỏ, 0,88 m + lề);
  - **explored** là vùng nằm trong nón nhìn có depth hợp lệ;
  - độ phân giải 5 cm; nở obstacle theo 0,18 m.
- Sàn lấy theo độ cao pose hiện tại (pose z – 0,88 m của camera), không đo floor datum.
- Đổi tầng: khi pose z đổi quá 0,5 m, ghi nhận tầng mới. Phương án mặc định là bản đồ riêng cho mỗi tầng; chốt
  sau khi đo xem có bao nhiêu episode DEV60 cần đổi tầng.
- `paper/frontier.py`: biên giữa explored-free và unexplored; lọc cụm nhỏ.
- `paper/planner.py`: A* trên grid đã nở; nếu không có đường thì nới lề 1 lần.
- `paper/action_adapter.py`:
  - waypoint → xoay tới khi lệch ≤ 15° → forward;
  - `collided` lặp lại thì đánh dấu ô phía trước là obstacle, xoay 30° và lập lại đường;
  - mắc kẹt N bước thì chọn frontier khác.
- Test đơn vị trên grid tổng hợp:
  - chiếu depth giả ra obstacle đúng ô;
  - frontier đúng biên;
  - A* tránh vật;
  - adapter ra đúng chuỗi hành động.
- Kiểm chứng runtime: policy **explore-only** (frontier gần nhất) trên DEV60. Báo cáo diện tích khám phá, số
  `collided`, tỉ lệ thấy đích (từ offline evidence).

### P5 — Port B0 và B1-revisit sang chế độ paper
- `paper/policies/b0.py`: giữ máy trạng thái SPIN, EXPLORE, APPROACH, FACE, VERIFY, STOP, nhưng ra **hành động rời
  rạc** qua adapter.
  - SPIN là 12 lần `turn` 30°.
  - Detector chạy mỗi bước (D3).
- Camera đổi từ 1,2 m / 90° thành 0,88 m / 79°. Kiểm lại ngưỡng confirmation của phase 2 trên DEV (đổi góc nhìn
  có thể đổi recall).
- Chạy lại `tools/objectnav/b0/stop_calibration.py` cho camera 0,88 m và chọn `stop_distance_m` mới.
- `paper/policies/b1_revisit.py`: chỉ thêm luật revisit như bản lockstep.
- Test: dùng lại test policy hiện có trên ctx giả của chế độ paper.

### P6 — Mốc mới
1. Kiểm tra trước (người dùng chạy): oracle qua PaperSim (P2) và explore-only (P4).
2. `b0-paper-dev60` và `b1r-paper-dev60`. Báo SR, SPL, OSR, funnel, failure modes; so cặp B1R với B0 bằng McNemar.
3. Cập nhật `policy-branch-rules.md`: mốc mới là `b0-paper-dev60`; quy tắc giữ net ≥ +3 áp dụng như cũ.
4. Đánh giá lớn hơn sau khi có policy đáng giữ: bộ cố định khoảng 200 episode phân tầng theo scene và category trên
   HM3D v2 val, sau đó toàn bộ val để so với paper. Mỗi lần chạy phải được người dùng duyệt (thời gian GPU).

### P7 — Tài liệu và bàn giao
- `AGENTS.md`/`architecture.md`: mô tả chế độ paper và phạm vi miễn trừ (D1).
- `policy-dev-cheatsheet.md`: lệnh `nsnav paper ...`.
- Journal `docs/objectnav/journal/paper-protocol.md`.
- PR `kiet/paper-protocol` → `main` qua teammate.

## 6. Kiểm chứng tổng thể (điều kiện xong)

| Kiểm tra | Ngưỡng |
|---|---|
| Unit test chế độ paper + toàn bộ test cũ | pass, không thoái lui |
| Oracle path qua PaperSim trên DEV60 | SR ≥ 0,98 (sai khác giải thích được bằng snap view point) |
| Oracle greedy qua PaperSim | khớp ± 2 episode với số chạy trực tiếp đã có |
| Explore-only | không episode nào kẹt ở 0 m vì lỗi tầng thấp; `collided` được xử lý |
| B0-paper / B1R-paper DEV60 | chạy hết 60 episode, invalid 0, có REPORT và so cặp |

## 7. Rủi ro

- **Nhiều tầng:** agent paper lên cầu thang được. Bản đồ 2D đơn giản có thể sai khi đổi tầng. Cần đo tần suất
  trước, rồi chọn cách xử lý (P4).
- **Detector ở góc nhìn mới (0,88 m, 79°):** recall và độ chính xác có thể đổi so với phase 2. Có thể cần chỉnh
  ngưỡng; ghi provenance.
- **Thời gian chạy:** detector đồng bộ mỗi bước có thể tới khoảng 500 lần/episode. Cần đo; nếu quá chậm, chỉ chạy
  detector khi đã đi ≥ 0,25 m hoặc xoay ≥ 30° (vẫn đồng bộ).
- **Lệch protocol nhỏ** (depth chuẩn hoá, sliding, cách đếm STOP) làm số khó so với paper: xử lý ở P0 bước 2 và
  P2 kiểm chứng oracle.
- **License:** chỉ dùng mô tả thuật toán từ paper; không chép code ApexNav (GPL-3.0).

## 8. Ước lượng thứ tự công việc

P0 → P1 → P2 (kèm oracle) → P3 → P4 (kèm explore-only) → P5 → P6 → P7.
- P2 và P4 là phần lớn nhất.
- P1–P3 có thể xong trước rồi chạy oracle để chốt tính đúng của worker và bộ chấm trước khi viết bản đồ.
