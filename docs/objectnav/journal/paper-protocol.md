# Nhật ký: chế độ ObjectNav "paper protocol"

Kế hoạch: [paper-protocol-plan.md](../paper-protocol-plan.md). Người dùng duyệt kế hoạch và D1–D7 ngày 19/11/2026.

## 2026-11-19 — P0–P5 triển khai, kiểm chứng ban đầu

- **P0 (protocol):**
  - Đối chiếu với habitat-lab `objectnav_hm3d.yaml` và `task/objectnav.yaml`, cùng config ObjectNav của VLFM (VLFM
    không ghi đè các giá trị này).
  - Khác với kế hoạch ban đầu: **`allow_sliding: False`** (đâm thì đứng yên, không trượt); depth bị kẹp vào
    [0,5; 5,0] m sau khi render. Bảng nguồn ghi trong mục 3 của kế hoạch.
- **Nhánh (D5/D6):**
  - Chưa tách nhánh. Quy tắc "không commit trước khi bàn với teammate" vẫn áp dụng cho B1-revisit, nên mọi file
    paper mode là **file mới, chưa track**, nằm trên cây làm việc `kiet/B1-revisit`.
  - Khi commit sẽ tách: hạ tầng paper sang `kiet/paper-protocol` (cắt từ `main`), B1-revisit khoá SHA riêng.
- **File mới:**
  - `configs/objectnav/paper-hm3d-v1.json`, `paper-b0-v1.json`, `paper-b1r-v1.json`.
  - `src/neusymnav/objectnav/paper/`: `protocol`, `sim_worker`, `sim_client`, `runner`, `obstacle_map`,
    `planner`, `nav`, `policies`, `b0`.
  - `tools/objectnav/run_paper_episodes.py`.
  - `tools/objectnav/paper/`: `oracle_check`, `failure_evidence`, `stop_calibration`, `summary`, `run_dev60.sh`.
  - Test: `tests/test_objectnav_paper.py`, `tests/test_objectnav_paper_b0.py`.
- **File đã có bị sửa:** `AGENTS.md` (thêm ngoại lệ D1). Runner lockstep, guard, mapper, bộ chấm và
  `habitat_worker` không đổi. Tool evidence và stop calibration được dùng lại qua wrapper, không sửa file gốc.
- **Kiểm chứng:**
  - Unit test paper: 26 passed. Toàn bộ suite CPU: 3148 passed, 40 skipped (exit 0).
  - Smoke worker (val_mini TEEsavR23oF/7):
    - forward đúng 0,25 m, turn 30°, look_down nghiêng camera 30°;
    - `collided` = True khi bị chặn, và sau đó dịch chuyển 0 m;
    - STOP kết thúc episode, sau STOP thì từ chối mọi hành động;
    - khoảng 0,07 s mỗi bước.
  - **Oracle qua cấu hình PaperSim trên DEV60** (`runs/objectnav/paper-oracle-dev60`):
    - SR 0,950, SPL 0,875, OSR 0,983; mọi episode có min-DTG < 0,25 m.
    - 3 ca thất bại là `stopped_too_far` (DTG 0,14–0,17 m): greedy follower dao động sát đích khi không trượt.
    - Kết luận: simulator paper và bộ chấm khớp nhau về navmesh, vị trí và success.
  - **Smoke B0-paper** (2 episode val_mini, `runs/objectnav/paper-b0-smoke`):
    - Chạy hết pipeline: run, chấm điểm, evidence offline (pose check 139/144 khung khớp với camera paper), summary.
    - SR 0/2: cả hai `wrong_object_stop` sau khi khám phá hết frontier sớm rồi rơi vào `fallback_target`.
- **Lỗi đã sửa khi thử:**
  1. Lặp lại forward bị chặn: ô đích nằm trong vùng thân bị ép free. Giờ vùng ép free chỉ còn 0,1 m; sau 2 lần
     forward bị chặn liên tiếp thì trả về `blocked`. APPROACH bị chặn khi đã trong `far_stop_distance` thì coi
     là `arrived_far`.
  2. Frontier bị bỏ vì "unreachable" (bản đồ đổi) cũng bị đưa vào blacklist. Giờ chỉ blacklist khi `stuck` hoặc
     `blocked`.
  3. Không còn frontier tới được thì thử lại một lần với lề nở 0,08 m (kế hoạch P4).
  4. Luật "điểm thấp hơn thân 0,25 m là vật cản" biến sàn thành tường khi robot đứng trên bậc thang. Đã bỏ,
     giống VLFM. Chạy lại explore trên TEEsavR23oF/10: khối sọc đen giữa nhà biến mất, robot xuống cầu thang
     và khám phá tầng dưới (5 lớp độ cao trong bản đồ).
- **Chưa chứng minh:**
  - explore-only, B0-paper và B1R-paper trên DEV60 (người dùng chạy);
  - stop calibration cho camera 0,88 m;
  - chất lượng khám phá (vẫn dừng sớm ở vài nhà nhiều tầng).

## 2026-11-19 — P6a: stop calibration + explore-only DEV60 (người dùng chạy, `run_p6a.sh`)

- **Stop calibration** (`runs/objectnav/paper-stop-calibration.md`, camera 0,88 m, exit 0):
  - 60/60 episode có điểm success trên tầng xuất phát.
  - P(success | có điểm trong D) giảm dần theo D: 0,94 ở 0,4 m, 0,85 ở 0,9 m; P(success) theo khoảng cách
    tụt mạnh sau 1,0 m (0,78 → 0,39 ở 1,1–1,2 m).
  - Giữ nguyên `stop_distance_m` 0,4 và `far_stop_distance_m` 0,9 trong `paper-b0-v1.json`/`paper-b1r-v1.json`.
- **Explore-only DEV60** (`runs/objectnav/paper-explore-dev60`):
  - SR 2/60, **OSR 32/60**; 49/60 kết thúc `frontiers_exhausted`, 11 hết 500 bước.
  - Trung vị 180 bước, 15 va chạm, 16,7 m; ~20 episode dừng trước 120 bước với < 45 m² đã khám phá.
- **Chẩn đoán dừng sớm** (LT9Jq6dN3Ea/2, bCPU9suPUw9/2, k1cupFYWXJ6/7; dump bản đồ + navmesh của scene):
  - Robot không ra khỏi phòng xuất phát. Lối ra **có** trên navmesh nhưng là khe hẹp: dải tâm robot được
    phép chỉ rộng ~0,3–0,4 m, tức cửa thật ~0,7 m.
  - Không trượt (`allow_sliding: false`), bước quay 30° và bước 0,25 m. Planner hiện nhắm waypoint với sai
    số hướng 15°, nên đâm vào khung cửa.
  - Sau 2 lần đâm, frontier bị blacklist (bán kính 0,5 m). Vài lần như vậy là hết frontier.
  - Probe navmesh tại điểm kẹt: 5–6/12 hướng bị từ chối, các hướng còn lại đi được. Robot không bị nhốt thật.
- **Thử sửa** (chưa chạy DEV60, đang trong cây làm việc):
  1. `blocked` → quay tránh (`PaperNav.escape_turn`), chỉ blacklist sau 3 lần (`NavConfig.blocked_give_up`).
     Bộ đếm `stuck` không bị reset khi chọn lại cùng frontier.
  2. Vết va chạm hai mức: lần đầu là đĩa 0,1 m. Đâm lại trong vòng 0,35 m thì thành đoạn chắn 0,5 m, luôn
     nở đủ 0,18 m (`_Level.bumps`), để planner nới lề không xuyên qua mép navmesh vô hình.
  - Kết quả trên 4 episode: TEEsavR23oF/2#4 tăng từ 60 lên 260 m² (6 tầng). Ba ca cửa hẹp **không đổi**
    (vẫn dừng ở 19, 18 và 33 m²).
  - Bản trung gian "vết chắn rộng ngay lần đầu" bịt luôn cửa (robot đâm chéo khung cửa một lần), nên đã bỏ.
  - Bản đầu tiên (chỉ quay tránh, vết va chạm vẫn là đĩa nhỏ) **tệ hơn**: LT9Jq6dN3Ea/2 và bCPU9suPUw9/2
    chạy hết 500 bước nhưng đứng yên tại chỗ, khoảng 230 va chạm mỗi ca, quãng đường không đổi (1,6 m và 3,0 m).
    Lý do: planner nới lề đi lách giữa các vết nhỏ, rồi quay ngược lại đúng hướng vừa đâm. Bộ đếm "kẹt"
    không bao giờ kích hoạt vì bị reset mỗi lần chọn lại frontier. Đã bỏ biến thể này.
- **Chưa giải quyết:** đi qua cửa hẹp với hành động rời rạc không trượt. Hướng đề xuất: planner lattice
  (x, y, 12 hướng) dùng đúng mô hình hành động (tiến 0,25 m / quay 30°) và kiểm tra va chạm từng đoạn trên
  bản đồ, thay cho bám waypoint với sai số hướng.

## 2026-11-19 — "Cách 1": chi phí sát tường + chấm điểm hành động (kiểu ApexNav)

- **Checkpoint trước khi sửa:** `runs/objectnav/checkpoints/paper-ckpt0-before-nav-fix.tar.gz` (sha256
  `ff96301b…`; cách khôi phục ghi trong README cùng thư mục). Người dùng yêu cầu: thử lần lượt từng cách,
  cách nào không cải thiện thì khôi phục checkpoint để code không phình.
- **Tham khảo** (chỉ đọc, không chép code; ApexNav là GPL-3.0):
  - ApexNav (bài báo): A* tới đích cục bộ, mỗi hành động rời rạc chấm điểm theo tiến độ + chi phí an toàn
    lấy mẫu trên ESDF.
  - VLFM: PointNav học bằng RL, không có xử lý va chạm riêng.
  - SG-Nav / SemExp: FMM + luật quay; va chạm ghi khối vào bản đồ, SemExp nới rộng khối khi đâm lặp lại.
- **Thay đổi:**
  - `planner.py`:
    - Dijkstra nhận `penalty` theo ô: chi phí bước × (1 + penalty).
    - `wall_penalty` từ ESDF: bằng 4 tại vật cản, giảm tuyến tính về 0 ở 0,5 m.
  - `nav.py`:
    - `NavConfig.controller = 'scored'` (mặc định; `'heading'` là luật cũ).
    - `_scored_action`: trường chi phí tới đích (Dijkstra từ đích, có phạt). Với 12 hướng (yaw + k·30°),
      mô phỏng đúng một bước tiến 0,25 m, lấy mẫu mỗi 2,5 cm trên bản đồ traversable. Chấm điểm đầu mút
      bằng chi phí tới đích cộng 0,125 m cho mỗi bước quay; quay về hướng tốt nhất hoặc tiến. Không hướng
      nào tiến bộ thì dùng luật cũ.
    - `path_metres`: độ dài hình học dùng cho kiểm tra "tới nơi"; trường có phạt chỉ để xếp hạng.
  - Test mới:
    - lối qua 0,62 m (mỏng, và dài 1 m), 3 hướng xuất phát: tới đích, 0 va chạm;
    - đường đi qua cửa 1,2 m nằm gần giữa cửa.
    - Paper tests: 33 passed.
- **Thử trên 4 episode thật** (explore-only):

  | Episode | Khám phá (m²) trước → sau | Va chạm trước → sau | Kết thúc |
  |---|---|---|---|
  | LT9Jq6dN3Ea/2 | 19 → 153 | 5 → 0 | hết frontier → hết 500 bước |
  | bCPU9suPUw9/2 | 18 → 46 | 3 → 0 | hết frontier |
  | k1cupFYWXJ6/7 | 33 → 68 | 14 → 10 | hết frontier |
  | TEEsavR23oF/2#4 | 60 → 318 | 8 → 3 | hết frontier → hết 500 bước |

- **Ghi chú:**
  - Với lối hẹp tổng hợp (tường là đường mảnh), luật cũ cũng qua được. Lợi ích trên ca thật có lẽ đến từ
    việc đi giữa lối, tránh xa vật cản nhiễu và mép bản đồ, hơn là từ việc căn hướng. Chưa tách riêng được
    hai yếu tố này.
- **Explore DEV60 với cách 1** (người dùng chạy, `runs/objectnav/paper-explore-c1-dev60`, exit 0; 33 test passed):

  | Chỉ số | Trước (`paper-explore-dev60`) | Cách 1 |
  |---|---|---|
  | OSR | 32/60 (0,533) | **50/60 (0,833)** [0,733; 0,917] |
  | SR (explore không có detector, chỉ tham khảo) | 2/60 | 6/60 |
  | `frontiers_exhausted` / `max_steps` | 49 / 11 | 33 / 27 |
  | Trung vị bước / va chạm / quãng đường | 180 / 15 / 16,7 m | 368 / 2 / 57,6 m |
  | Episode dừng trước 120 bước | ~20 | 9 |
  | Thời gian | 0,9 h (35 s/ep) | 1,4 h (99 s/ep) |

  - So từng cặp: OSR thêm 24 episode, mất 6. Hai ca mất sát ngưỡng (min-DTG 0,10 và 0,20 m); 4 ca mất do
    robot đi hướng khác hoặc dừng sớm (TEEsavR23oF/3#4, wcojb4TFT35/3, k1cupFYWXJ6/8#2, LT9Jq6dN3Ea/1#2).
  - OSR theo scene (trước → sau): LT9Jq6dN3Ea 3 → 8, TEEsavR23oF 5 → 9, bCPU9suPUw9 6 → 9, k1cupFYWXJ6 7 → 8,
    qyAac8rV8Zk 5 → 8, wcojb4TFT35 6 → 8.
  - Còn lại: k1cupFYWXJ6 vẫn ~18–29 va chạm/episode (trước là 65–81); 9 episode vẫn hết frontier dưới 120 bước.
  - **Quyết định: giữ cách 1** (checkpoint `paper-ckpt1-cach1`). Chưa thử cách 2 (lattice).

## 2026-11-19 — B0-paper DEV60 (người dùng chạy, `runs/objectnav/paper-b0-dev60`, exit 0)

- Dùng cách 1 (`paper-ckpt1-cach1`), config `paper-b0-v1.json` (stop 0,4 m / far 0,9 m); 33 test passed; 1,9 h
  (78 s/episode).
- **SR 36/60 (0,600) [0,483; 0,717], SPL 0,231, SoftSPL 0,277, OSR 44/60, DTG 2,19 m.**
  - Kết thúc: 47 `confirmed_target`, 6 `max_steps`, 6 `frontiers_exhausted`, 1 `fallback_target`.
  - Trung vị 99 bước, 0 va chạm, 12,7 m. Episode thành công: trung vị 80 bước, SPL trung vị 0,39.
  - Mốc lockstep B0 v3h (DEV60, giao thức khác nên không so trực tiếp): SR 0,283, SPL 0,064, OSR 0,417.
- **Kiểu lỗi** (evidence offline camera paper; 24 ca):

  | Kiểu | Số ca | Episode | Nhận xét |
  |---|---|---|---|
  | `wrong_object_stop` | 7 | 5 ở k1cupFYWXJ6 (4 sofa), 2 wcojb4TFT35 sofa, TEEsavR23oF/4#6 | detector nhận nhầm, phần lớn là "sofa" |
  | `stopped_too_far` | 5 | DTG cuối 0,11 / 0,37 / 0,42 / 0,43 / 0,70 m | đúng vật, dừng hơi xa (bán kính success 0,1 m tới view point) |
  | `never_seen` | 5 | TEEsavR23oF/3#4, wcojb4TFT35/1#2, /3, k1cupFYWXJ6/8#2, qyAac8rV8Zk/3#5 | trùng các ca explore dừng sớm / mất OSR |
  | `seen_not_detected` | 3 | k1cupFYWXJ6 plant ×3 (min-DTG ≈ 0) | đi qua sát cây nhưng detector không bắt |
  | `budget_exhausted` | 3 | TEEsavR23oF/1#3, LT9Jq6dN3Ea/0#6, /1#2 | hết 500 bước |
  | `stopped_elsewhere` | 1 | qyAac8rV8Zk/3 | |

  - Evidence tổng: seen 49, detected 45, stop_on_goal 34, stop_on_wrong 12; pose check 4762/4890 khung khớp.
- **Chưa chứng minh:** B1R-paper DEV60; số liệu toàn bộ val (DEV60 chỉ 6 scene, khoảng tin cậy rộng).

## 2026-11-19 — Chốt B0-paper làm baseline B0

- Người dùng chốt B0-paper (`paper-b0-v1.json` + cách 1) làm baseline B0 chính, thay B0 lockstep v3h trong vai
  trò mốc so sánh. Code lockstep không đổi (AGENTS: "Runtime và chế độ lockstep không đổi").
- Code paper trong cây làm việc khớp sha256 với snapshot `runs/objectnav/paper-b0-dev60/provenance/untracked.sha256`
  (23 file); diff file tracked chỉ khác ở `docs/implementation-status.md`.
- B1R-paper DEV60 chưa chạy. Commit đã soạn sẵn (`runs/objectnav/paper-commit/`), **chưa commit**: chờ bàn kết quả
  DEV60 với teammate.
