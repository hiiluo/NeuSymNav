# ObjectNav — chỉ số oracle trong bộ chấm (13/11/2026)

Nhánh `objectnav`. Chỉ thêm chỉ số chẩn đoán offline vào bộ chấm. Định nghĩa
SR / SPL / SoftSPL / DTG giữ nguyên (habitat-lab, thành công khi STOP và
DTG < 0,1 m tới view point). Policy, guard và runner không đổi.

## Định nghĩa

- **min-DTG**: DTG geodesic nhỏ nhất trên mọi vị trí đã ghi trong
  `trajectories.jsonl` (`positions`). Cùng navmesh và cùng view point với DTG.
- **Oracle success (OSR)**: min-DTG < 0,1 m (chặt, cùng ngưỡng với success),
  có STOP hay không. OSR cao mà SR thấp: robot đã tới đích nhưng không dừng.
  OSR thấp: explore/approach không đưa robot tới đích.
- **oracle_not_success**: số episode có oracle success nhưng không success.
- **oracle_within_m**: tỉ lệ episode có min-DTG < 0,1 / 0,25 / 0,5 / 1,0 m.
  Chỉ dùng để tách "hụt vài cm" khỏi "không tới gần". Không phải success.

Mã: `src/neusymnav/evaluation/objectnav_metrics.py` (summary `schema_version`
2), `tools/objectnav/score_trajectories.py`. Mỗi vị trí khác nhau chỉ truy vấn
geodesic một lần.

## Chấm lại các run B0 đã có (cùng 9 episode DEV)

> Đã bị thay thế 13/11/2026: bảng dưới dùng DTG thô (schema 2). Bảng chính thức
> sau khi sửa snap ở [footprint-vs-viewpoint-results.md](footprint-vs-viewpoint-results.md).

Lệnh (Habitat interpreter, từ gốc worktree; ghi prefix mới, không ghi đè
kết quả cũ):

```bash
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/score_trajectories.py \
    runs/objectnav/b0/<run>/trajectories.jsonl --set hm3d_v2 --split val \
    --out-prefix runs/objectnav/b0/<run>/oracle-v2
```

| Run | SR | OSR | min-DTG < 0,25 m | < 0,5 m | < 1 m | Tới đích không thành công |
|---|---:|---:|---:|---:|---:|---:|
| dev1-diag | 1/9 | 1/9 | 1/9 | 1/9 | 1/9 | 0 |
| dev2-diag | 0/9 | 1/9 | 3/9 | 3/9 | 4/9 | 1 |
| dev3-diag | 1/9 | 1/9 | 3/9 | 3/9 | 3/9 | 0 |
| dev4h-diag | 0/9 | 1/9 | 4/9 | 4/9 | 4/9 | 1 |

Artifact: `runs/objectnav/b0/<run>/oracle-v2-{outcomes.jsonl,summary.json}`.

## Đọc kết quả

- Chỉ 1 episode (`k1cupFYWXJ6/4#3`, plant) từng vào dưới 0,1 m. Ở dev2 và
  dev4h robot đã tới 0,05 m rồi không STOP ở đó (dev2 dừng muộn ở 0,83 m,
  dev4h hết budget ở 0,16 m). Đây là lỗi quyết định STOP của policy.
- Ở dev4h, 3 episode khác có min-DTG 0,10–0,17 m nhưng không bao giờ dưới
  0,1 m: `LT9Jq6dN3Ea/1` chair (0,10 m ở cả dev2, dev3, dev4h),
  `qyAac8rV8Zk/3#5` toilet (0,15 m), `TEEsavR23oF/3#6` plant (0,15–0,17 m).
  Việc nhiều lần dừng ở đúng 0,10 m gợi ý một giới hạn hình học. Có thể thân
  robot phẳng (lề an toàn 0,3375 m) không vào được view point mà agent
  habitat-lab (bán kính nhỏ hơn) vào được. **Chưa chứng minh**: cần đo
  khoảng cách từ view point tới chướng ngại so với footprint của robot.
- Các episode còn lại kết thúc xa đích (min-DTG ≥ 2 m): explore hoặc detector
  nhận nhầm (`stopped_elsewhere`), không phải hụt ở bước cuối.
- 9 episode quá ít: khoảng tin cậy 95 % của OSR là [0, 0,333] ở mọi run.
  Không dùng bảng này để xếp hạng cấu hình.

## Trạng thái

- **Implemented**: min-DTG, OSR, oracle_not_success, oracle_within_m.
- **Correctness-verified**: `tests/test_objectnav_metrics.py` 8 passed, cùng
  với `test_objectnav_runner.py` và `test_objectnav_b0.py` 41 passed.
- **Runtime-validated**: chấm lại 4 run B0 có sẵn, exit 0, SR/SPL/SoftSPL/DTG
  trùng với kết quả của scorer v1 trên cùng run (dev4h: SR 0, SoftSPL 0,059,
  DTG 4,65 m).
- **Chưa chứng minh**: giới hạn footprint vs view point; OSR trên tập DEV lớn.
