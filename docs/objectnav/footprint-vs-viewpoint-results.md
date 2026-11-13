# ObjectNav — footprint robot so với view point (13/11/2026)

Nhánh `objectnav`. Đo offline, chỉ evaluator. Không đổi policy, guard,
runner hay định nghĩa của bộ chấm.

## Câu hỏi

Ở các run B0, nhiều episode có min-DTG 0,10–0,17 m nhưng không bao giờ dưới
0,1 m ([chỉ số oracle](oracle-metrics-results.md)). Giả thuyết: thân robot
(planner r 0,20 + margin 0,05 m, cao 1,5 m) không đứng được vào view point
mà agent habitat-lab (r 0,18 m, cao 0,88 m) đứng được.

## 1. Footprint: giả thuyết bị bác bỏ

`tools/objectnav/b0/footprint_ceiling.py` tính lại navmesh của scene cho từng
thân (cách làm như sensor worker). Với mỗi view point, probe kiểm tra điểm
snap có cùng tầng, đi tới được từ start và cách view point < 0,1 m theo
phương ngang hay không.

```bash
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/footprint_ceiling.py \
    --manifest runs/objectnav/b0/dev4h-diag/manifest.json \
    --out runs/objectnav/b0/footprint-20261113/footprint_ceiling-dev9.json \
    --outcomes runs/objectnav/b0/dev{2,3,4h}-diag/oracle-v2-outcomes.jsonl   # mỗi file một --outcomes
```

| Thân | Episode còn view point đứng được |
|---|---:|
| challenge r 0,18 h 0,88 | 9/9 |
| robot r 0,20 h 1,5 | 9/9 |
| planner r 0,25 h 1,5 | 9/9 |
| planner + pad r 0,2875 h 1,5 | 5/9 |
| r 0,25 h 0,88 | 8/9 |

Ở footprint planner thật (r 0,25 m), ba episode hụt sát vẫn còn nhiều view
point đứng được: chair `LT9Jq6dN3Ea/1` 8326/8659, toilet `qyAac8rV8Zk/3#5`
162/162, plant `TEEsavR23oF/3#6` 956/1009. Pad 0,75 ô chỉ có trong phần
start-footprint tolerance, không có trong planner. Các ô `inf` ở hàng r
0,2875 và h 0,88 là do start bị đẩy ra khỏi navmesh ở thân đó.

## 2. Nguyên nhân thật: lệch độ cao giữa view point và navmesh của bộ chấm

`runs/objectnav/b0/footprint-20261113/nearmiss.py` và `ycheck.py`:

- Ở vị trí gần đích nhất, robot cách view point gần nhất chỉ 0,2–2 cm theo
  phương ngang. Riêng toilet trong dev2-diag cách 0,58 m. Phần DTG còn lại
  bằng đúng độ chênh độ cao: 0,05 / 0,10 / 0,15 m.
- Robot chạy ở y hằng số (planar adapter), đúng bằng mặt navmesh basis mà
  bộ chấm dùng (snap dy = 0).
- Mặt navmesh basis cao hơn view point của episode: trung vị +0,15 m ở 7/9
  episode, +0,10 m ở `LT9Jq6dN3Ea`, +0,05 m ở `k1cupFYWXJ6`.
- `ht.distance_to_goal` truyền view point thô làm `requested_ends`, nên
  geodesic cộng thêm độ chênh đó. Với ngưỡng < 0,1 m, episode có độ chênh
  ≥ 0,1 m không thể thành công, dù robot đứng đúng chỗ. Episode duy nhất từng
  thành công (`k1cupFYWXJ6/4#3`) có độ chênh 0,05 m.
- `stop_calibration.py` dùng khoảng cách ngang nên không thấy lỗi này.

## 3. Chấm chẩn đoán với view point snap lên cùng navmesh

`runs/objectnav/b0/footprint-20261113/snapped_score.py`. Biến thể này chỉ là
chẩn đoán, không phải bộ chấm chính thức. View point được snap lên navmesh
của bộ chấm khi dịch ngang < 0,05 m và |dy| < 0,3 m.

| Run | SR hiện tại | SR (snap) | OSR hiện tại | OSR (snap) |
|---|---:|---:|---:|---:|
| dev1-diag | 1/9 | 1/9 | 1/9 | 1/9 |
| dev2-diag | 0/9 | 1/9 | 1/9 | 3/9 |
| dev3-diag | 1/9 | 2/9 | 1/9 | 3/9 |
| dev4h-diag | 0/9 | 2/9 | 1/9 | 4/9 |

Với view point đã snap, chair `LT9Jq6dN3Ea/1` thành công ở dev2, dev3 và
dev4h (DTG 0,03 m), và toilet `qyAac8rV8Zk/3#5` thành công ở dev4h (DTG
0,04 m).

## Quyết định 13/11/2026: sửa bằng snap

Người dùng chọn hướng 1. Bộ chấm chính thức (`objectnav_metrics.snap_view_points`,
quy tắc `snap-to-scorer-navmesh-v1`, summary `schema_version` 3) snap view
point lên navmesh của bộ chấm khi dịch ngang ≤ 0,05 m và dịch đứng ≤ 0,3 m;
nếu không thì giữ điểm thô. Ngưỡng success vẫn là 0,1 m.

Validation phase 1 (val_mini, 30 episode), chấm lại vào `runs/objectnav/validation/<agent>-snap-v1-*`:

| Agent | SR cũ | SR mới | SPL mới | OSR mới |
|---|---:|---:|---:|---:|
| oracle_path | 1,000 | 1,000 | 0,996 | 1,000 |
| oracle_greedy | 0,233 | 0,233 | 0,220 | 1,000 |
| random | 0,033 | 0,067 | 0,006 | 0,300 |

35737/35795 view point được snap. oracle_greedy tới đích ở 30/30 episode
nhưng chỉ STOP ở 7, vì `tools/objectnav/scripted_agents.py` quyết định STOP
bằng DTG thô và bị cùng lỗi độ cao. Đã sửa: hai agent oracle nhắm vào view
point đã snap theo đúng quy tắc của bộ chấm. Chạy lại (`<agent>-v2.jsonl`,
log `runs/objectnav/validation/log-snap-v1.txt`):

| Agent (chạy lại) | SR | SPL | OSR | DTG cuối |
|---|---:|---:|---:|---:|
| oracle_path-v2 | 1,000 | 1,000 | 1,000 | 0,00 m |
| oracle_greedy-v2 | 1,000 | 0,944 | 1,000 | 0,05 m |

Kết quả khớp kỳ vọng thiết kế phase 1 (oracle_path SR 1, SPL ≈ 1;
oracle_greedy SR cao, SPL < 1).

B0, chấm lại bằng bộ chấm chính thức vào `runs/objectnav/b0/<run>/score-snap-v1-*`:

| Run | SR | SPL | OSR | Lỗi |
|---|---:|---:|---:|---|
| dev1-diag | 1/9 | 0,080 | 1/9 | stopped_elsewhere 8 |
| dev2-diag | 1/9 | 0,044 | 3/9 | elsewhere 5, too_far 2, budget 1 |
| dev3-diag | 2/9 | 0,053 | 3/9 | elsewhere 6, budget 1 |
| dev4h-diag | 2/9 | 0,051 | 4/9 | budget 4, elsewhere 3 |

18311/18686 view point được snap. Các bảng SR/OSR trong
[chỉ số oracle](oracle-metrics-results.md) dùng DTG thô (schema 2) và đã bị
thay thế bởi bảng này.

## Trạng thái

- **Implemented:** `tools/objectnav/b0/footprint_ceiling.py`, cùng các script
  chẩn đoán trong `runs/objectnav/b0/footprint-20261113/`.
- **Runtime-validated:** probe chạy với exit 0 trên 9 episode DEV. Bốn run B0
  được chấm lại bằng biến thể snap.
- **Correctness-verified:** `tests/test_objectnav_metrics.py` (quy tắc snap, xoá độ chênh khỏi DTG), 49 test ObjectNav pass.
- **Chưa chứng minh:** nguồn gốc độ lệch (cách sinh navmesh basis hay
  episode); ảnh hưởng trên tập DEV lớn; validation phase 1 (oracle path
  val_mini) có đi qua cùng lỗi này hay không.
