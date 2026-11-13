# Kết quả ObjectNav đã khoá (bộ chấm schema 3)

Bản sao nhỏ của các file trong `runs/` (thư mục bị git ignore), để ai cũng có số
và dữ liệu theo episode mà không cần chạy lại. Đọc kèm
[trang bàn giao](../b0-baseline-handoff.md).

| | Commit |
|---|---|
| Bộ chấm + agent kiểm tra | `85cb146`, tag `objectnav-scorer-v3` |
| Code B0 của mốc | `2dcb0ea`, tag `objectnav-b0-v3h-dev60` |

Các file sao chép nguyên từ lần chạy (`b0-dev60-v3h/head.txt`, `run.json`, `report.md`) ghi
`a1f6c50`. Đó là mã cũ của commit bộ chấm, trước khi lịch sử được viết lại để bỏ trailer
co-author. Tree không đổi (`a3a7ea1`), nên `a1f6c50` và `85cb146` có cùng nội dung.

Nhánh `objectnav` đã được rebase lên `main` (`6f54f12`) để PR không xung đột, nên các
commit trên nhánh có mã khác với hai tag. Tag giữ đúng code đã chạy. So với tag
`objectnav-b0-v3h-dev60`, code ObjectNav trên nhánh chỉ khác ở `src/neusymnav/mapping/occupancy.py`:
`main` thêm tham số `NavMapper(preserve_known_overview=False)`. Tham số mặc định tắt và runner
ObjectNav không dùng nó, nên hành vi B0 không đổi. Mốc chưa được chạy lại trên code đã rebase.

## 1. Bộ chấm đúng: validation val_mini (30 episode)

Thư mục `validation-val_mini/`. Agent đặc quyền trong `tools/objectnav/scripted_agents.py`,
chấm bằng `tools/objectnav/score_trajectories.py`, quy tắc `snap-to-scorer-navmesh-v1`.

| Agent | Kỳ vọng | SR | SPL | File |
|---|---|---:|---:|---|
| oracle_path (đường ngắn nhất) | SR 1, SPL ≈ 1 | **1,000** | **1,000** | `oracle_path-v2-{summary.json,outcomes.jsonl}` |
| oracle_greedy (bước rời rạc) | SR cao, SPL < 1 | 1,000 | 0,944 | `oracle_greedy-v2-*` |
| random (500 bước) | SR ≈ 0 | 0,067 | 0,006 | `random-snap-v1-summary.json` |

Tái lập (Habitat interpreter, từ gốc repo):

```bash
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/scripted_agents.py \
    --set hm3d_v2 --split val_mini --agent oracle_path --out runs/objectnav/validation/oracle_path-v2.jsonl
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/score_trajectories.py \
    runs/objectnav/validation/oracle_path-v2.jsonl --set hm3d_v2 --split val_mini
```

Unit test: `PYTHONPATH=src:.:tests .venv/bin/python -m pytest -q tests/test_objectnav_metrics.py
tests/test_objectnav_episodes.py tests/test_objectnav_runner.py tests/test_objectnav_b0.py`.

## 2. Mốc B0 dev60

Thư mục `b0-dev60-v3h/`. Chạy 13/11/2026 01:09–06:58 bằng `tools/objectnav/b0/run_dev60.sh`
(lúc đó nằm ở `runs/_phase3/step9_dev60_official.sh`), qua cả 7 bước tới `report`, exit 0.

| Thành phần | Giá trị |
|---|---|
| Code | `2dcb0ea`. Lúc chạy là HEAD `85cb146` cộng thay đổi chưa commit; bản chụp được kiểm tra trùng từng byte với `2dcb0ea` |
| Runner config | `configs/objectnav/lockstep-b0-v3h.json` sha256 `fbcaa23586d51bd7779ddf5b4c83e047269683b98d8c3e3d0be16806fb3fabd1` |
| Policy config | `configs/objectnav/b0-policy-v3.json` sha256 `47a946aaf208d604d5809b7fcb83702d0006549665265be46b8c6cbcc0a404b5` |
| Split | `configs/objectnav/splits/hm3d_v2-val-dev.json` (60 episode, 6 scene) sha256 `0491818e95dd7cc9a13a6d5ab2f90b8f201dd46eb9a7f3fa45aebf1ecf5830eb` |
| Bộ chấm | schema 3, 91721/93191 view point được snap |

| | SR [95 % CI] | SPL [95 % CI] | SoftSPL | OSR | DTG cuối |
|---|---|---|---:|---:|---:|
| **B0 v3h** | **0,283 [0,183, 0,400]** | **0,064 [0,036, 0,099]** | 0,114 | 0,417 | 3,48 m |
| B0 v1 (dev1, chấm lại schema 3) | 0,167 [0,083, 0,267] | 0,065 [0,029, 0,109] | 0,129 | 0,217 | 3,80 m |

So cặp với v1: thắng 8, thua 1 (McNemar chính xác p = 0,039).

File: `trajectories+evidence-summary.json` (tổng hợp, theo category, theo scene, lỗi),
`trajectories+evidence-outcomes.jsonl` (từng episode, dùng để so cặp),
`report.md` (funnel, lý do kết thúc, chi phí), `run.json`, `manifest.json`, `configs.sha256`,
`head.txt`, `dev1-v1-reference-summary.json`.

Tập TEST (`hm3d_v2-val-test.json`, 180 episode, sha256
`8c27268fea18c6678708feba1474435758173a633864db179811a7fbfc24053f`) chưa chạy.
