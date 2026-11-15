# Sổ tay phát triển policy ObjectNav

Tra cứu nhanh cho nhánh `Kiet_branch_policy_objnav`. Công cụ chính là `nsnav`
(`tools/objectnav/nsnav.sh`). Tài liệu chi tiết: [bàn giao B0](b0-baseline-handoff.md),
[kết quả đã khoá](results/README.md).

## 0. Mốc cần vượt

| | SR | SPL | OSR |
|---|---:|---:|---:|
| B0 v3h, 60 episode DEV | **0,283** (17/60) | **0,064** | 0,417 |

Bộ chấm schema 3 đã đóng băng. Thành công = robot gọi STOP và DTG < 0,1 m tới view point.

## 1. Cài `nsnav` một lần

Thêm alias vào `~/.bashrc` để gõ `nsnav` ở bất kỳ thư mục nào:

```bash
echo "alias nsnav='bash ~/Desktop/test_Room_segmentation/NeuSymNav/tools/objectnav/nsnav.sh'" >> ~/.bashrc && source ~/.bashrc
```

Kiểm tra:

```bash
nsnav help
```

Mỗi run nằm trong `runs/objectnav/<tên>/`. Lần chạy đầu, `nsnav run` ghi vào thư mục đó:

- `nsnav.env`: policy và config đã dùng. Các lệnh sau (`why`) tự đọc lại.
- `code.json`: mã nhận dạng của code đã chạy (tính từ nội dung `src/`, `configs/objectnav/` và
  `tools/objectnav/run_episodes.py`), commit HEAD và danh sách file chưa commit. Nếu có thay đổi
  chưa commit thì kèm `code.diff`.

## 2. Luồng phát triển một policy

```text
 1. Xem B0 thua ở đâu ──────────── nsnav list · nsnav pick · nsnav show
 2. Viết / sửa policy ──────────── src/neusymnav/objectnav/<policy>/  (mục 5)
 3. Tạo run ────────────────────── nsnav new v1 --set smoke        (lần sau: nsnav new v2 --from v1)
 4. Chạy ───────────────────────── nsnav run v1 --policy <P>       (tự chấm, in từng episode, so với B0)
 5. Sai ở đâu? ─────────────────── nsnav why v1 · nsnav why v1 --stuck
        └── sửa tiếp → quay lại 2, rồi bước 3 với tên mới
 6. Test ───────────────────────── nsnav test   (trước khi chạy dài hoặc commit: nsnav test all)
 7. Chạy đủ 60 DEV ─────────────── nsnav dev60 <tên> --policy <P>  (≈ 5 h, qua đêm)
 8. So với B0 ──────────────────── nsnav compare <tên>
        └── không thắng rõ → quay lại 1
 9. Commit ─────────────────────── ghi SR/SPL, thắng/thua vào docs/implementation-status.md
```

Vòng lặp hằng ngày chỉ có hai lệnh:

```bash
nsnav new v1 --set smoke
nsnav run v1 --policy mypolicy
```

Sửa code xong, chạy lại đúng bộ episode đó với tên mới và so hai phiên bản:

```bash
nsnav new v2 --from v1
nsnav run v2 --policy mypolicy
nsnav compare v2 v1
```

Khi muốn tập trung vào một loại lỗi, tự chọn episode thay cho bộ smoke:

```bash
nsnav pick --mode never_seen --scene TEEsavR23oF          # B0 không bao giờ thấy đích ở các episode này
nsnav new explore-v1 $(nsnav pick --mode never_seen --scene TEEsavR23oF --limit 4) LT9Jq6dN3Ea/1 bCPU9suPUw9/2#5
nsnav run explore-v1 --policy mypolicy
nsnav why explore-v1                                       # nếu cần biết vì sao vẫn thua
```

Khi kết quả tốt trên bộ nhỏ:

```bash
nsnav test all
nsnav dev60 explore-v2 --policy mypolicy
nsnav compare explore-v2
```

### Bộ smoke

`configs/objectnav/splits/hm3d_v2-val-dev-smoke.json`: 12 episode cố định, mỗi scene DEV hai
episode (một B0 thành công, một B0 thất bại). B0 đạt 6/12. Với B0, bộ này mất khoảng 55 phút.

| Scene | B0 thành công | B0 thất bại |
|---|---|---|
| TEEsavR23oF | `4#5` chair | `2#6` toilet, never_seen |
| wcojb4TFT35 | `0#3` tv_monitor | `1#4` sofa, never_seen |
| k1cupFYWXJ6 | `3#3` plant | `4` sofa, wrong_object_stop |
| qyAac8rV8Zk | `3#5` toilet | `3#4` sofa, stopped_too_far |
| bCPU9suPUw9 | `2#5` bed | `2#2` toilet, never_seen |
| LT9Jq6dN3Ea | `1` chair | `1#6` bed, budget_exhausted (đã tới đích, không STOP) |

Mọi phiên bản policy chạy cùng bộ này thì so được với nhau. Bộ smoke chỉ để kiểm tra nhanh:
12 episode không đủ để kết luận một policy tốt hơn B0.

### Quy tắc

- **Mỗi lần sửa code dùng một tên run mới** (`nsnav new v2 --from v1`). `nsnav run` nhận ra code
  đã đổi qua `code.json` và từ chối chạy tiếp run cũ, để một run không trộn hai phiên bản code.
  Nó cũng từ chối nếu policy hay config khác lần đầu. Nếu code không đổi, chạy lại cùng tên chỉ
  chạy các episode còn thiếu.
- **Bộ thử luôn gồm cả vài episode B0 đang làm được**, để thấy policy mới có làm hỏng chúng không.
- **Không tinh chỉnh trên TEST.** Chỉ chạy TEST (180 episode) một lần cho mỗi phiên bản đã chốt.
- **Chỉ một tác vụ GPU/sim tại một thời điểm.** `nsnav run` và `nsnav dev60` tự từ chối nếu đang
  có sim hoặc demo chạy (`nsnav ps`).
- **Không sửa bộ chấm** (`evaluation/objectnav_metrics.py`, `score_trajectories.py`). Ngoại lệ:
  có bằng chứng nó đo sai, và khi sửa thì phải tăng schema rồi chấm lại mọi run đang so sánh.
- **Đánh giá policy trên 60 DEV, không phải trên bộ thử nhỏ.** Bộ nhỏ chỉ để debug. Với 60
  episode, khoảng tin cậy của SR vẫn rộng khoảng ±0,1, nên hãy nhìn số thắng/thua và giá trị p
  của `nsnav compare`.
- Trước khi sửa `navigation/safety.py`, `controller.py` hay `mapping/occupancy.py`, phải thống
  nhất với teammate (mỗi file một người sửa).

## 3. Lệnh `nsnav`

| Lệnh | Làm gì |
|---|---|
| `nsnav list [dev\|test]` | liệt kê uid; với `dev` có kèm kết quả B0 |
| `nsnav pick --mode M --scene S --cat C --limit N` | in uid DEV theo kết quả B0, scene, category; dùng làm đầu vào cho `nsnav new` |
| `nsnav show <uid \| scene>` | số liệu B0 của một episode (`LT9Jq6dN3Ea/1` cũng được), hoặc danh sách episode của một scene (`LT9Jq6dN3Ea`) |
| `nsnav new <tên> [--set smoke\|dev] [--from <run>] [uid ...]` | tạo `runs/objectnav/<tên>/manifest.json`. `--set smoke`: bộ 12 episode; `--set dev`: cả 60 DEV; `--from`: lấy episode của một run cũ; uid viết đầy đủ hoặc rút gọn (`LT9Jq6dN3Ea/1`). Các nguồn ghép được với nhau; uid sai bị từ chối |
| `nsnav run <tên> [--policy P] [--cfg C] [--pol F]` | chạy, rồi tự chấm, in bảng từng episode và so cặp với B0. Mặc định `b0`, `lockstep-b0-v3h`, `b0-policy-v3` |
| `nsnav why <tên>` | tìm nguyên nhân thất bại, ghi `report.md` (cần thư mục `evidence/` dạng B0) |
| `nsnav why <tên> --stuck` | chẩn đoán robot kẹt hoặc đứng yên |
| `nsnav score <tên>` | chấm lại SR/SPL/OSR; ghi đè file chấm cũ |
| `nsnav eps <tên>` | mỗi episode một dòng: kết quả, SPL, DTG, min-DTG, quãng đường, thời gian, kết quả B0 |
| `nsnav compare <tên> [<tên khác>]` | so cặp với B0 (hoặc với run khác): SR, SPL, thắng/thua, McNemar p |
| `nsnav runs` | liệt kê các run: SR, SPL, policy, config, mã code (dấu `+` = có thay đổi chưa commit) |
| `nsnav dev60 <tên> [--policy P] ...` | chạy đủ 60 DEV, kèm bản chụp code, test, chấm và báo cáo |
| `nsnav test [all]` | test ObjectNav (`all` = toàn bộ test CPU, khoảng 4 phút) |
| `nsnav ps` | có sim hoặc demo nào đang chạy không |

`score`, `eps` và `compare` đã nằm trong `nsnav run`; chỉ gọi riêng khi muốn xem lại một run cũ
hoặc so hai run với nhau. Hai lệnh cũ `try` và `stuck` đã bỏ: dùng `new` + `run` và `why --stuck`.

`--cfg` và `--pol` nhận tên file trong `configs/objectnav/`, không cần `.json`.
`--policy` phải là tên đã đăng ký trong `tools/objectnav/run_episodes.py` (hiện có `b0`, `explore`).

Thời gian: khởi động detector mất khoảng 30 s; mỗi episode mất 1–10 phút. Episode B0 thành công
nhanh nhất mất khoảng 2 phút thực. `dev60` với B0 mất khoảng 5 giờ 20 phút. Ctrl-C để dừng; chạy
lại đúng lệnh để tiếp tục.

## 4. Đọc kết quả

### uid

Định dạng: `hm3d_v2/val/<scene>/<episode_id>`, ví dụ `hm3d_v2/val/LT9Jq6dN3Ea/0#2`. Phần `#n`
đánh dấu lần lặp thứ n của cùng một episode id trong scene, phải chép nguyên.

| File | Episode | Dùng để |
|---|---:|---|
| `configs/objectnav/splits/hm3d_v2-val-dev.json` | 60 (6 scene) | phát triển, thử policy |
| `configs/objectnav/splits/hm3d_v2-val-dev-smoke.json` | 12 (trong 60 DEV) | kiểm tra nhanh mỗi lần sửa (`--set smoke`) |
| `configs/objectnav/splits/hm3d_v2-val-test.json` | 180 (30 scene) | đánh giá cuối, chạy một lần |
| `configs/objectnav/splits/hm3d_v2-val-split.json` | — | cách chia scene, số episode theo category |

### Kết quả từng episode

| Kết quả | Nghĩa | Lỗi nằm ở | B0 (60) |
|---|---|---|---:|
| `OK` | STOP và DTG < 0,1 m | — | 17 |
| `never_seen` | đích chưa bao giờ hiện trong khung hình ở ≤ 3 m | khám phá | 26 |
| `budget_exhausted` | hết 500 s mô phỏng mà chưa STOP | khám phá hoặc quyết định dừng | 6 |
| `wrong_object_stop` | STOP cạnh vật bị nhận nhầm (armchair → sofa) | detector, quy tắc xác nhận | 5 |
| `stopped_too_far` | STOP khi cách đích 0,1–1 m | tiếp cận, vị trí dừng | 3 |
| `seen_not_detected` | đích có trong khung hình, detector không báo | detector | 2 |
| `stopped_elsewhere` | STOP xa đích, không có dấu hiệu nhận nhầm | quyết định dừng | 1 |
| `stuck` | không tiến triển trong cửa sổ kẹt | chuyển động, guard | 0 |
| `invalid_episode`, `start_not_navigable` | episode không chấm được | dữ liệu | 0 |

`never_seen`, `seen_not_detected` và `wrong_object_stop` chỉ xuất hiện sau `nsnav why`. Nếu chỉ
`nsnav score` thì các episode này hiện là `budget_exhausted` hoặc `stopped_elsewhere`.

### Các dòng khi chấm

| Dòng | Ý nghĩa |
|---|---|
| `SR=… [lo, hi]` | tỉ lệ thành công, khoảng tin cậy 95 % (bootstrap) |
| `SPL` | thành công có tính độ dài đường đi: 1 = đi đường ngắn nhất |
| `SoftSPL` | như SPL nhưng có điểm cho việc tiến gần đích dù không thành công |
| `DTG` | khoảng cách geodesic tới view point gần nhất lúc kết thúc |
| `OSR` | tỉ lệ episode robot từng vào < 0,1 m của đích, có STOP hay không |
| `reached-without-success` | đã tới đích nhưng không thành công (không STOP ở đó) |
| `min-DTG below radius` | tỉ lệ episode từng vào dưới 0,1 / 0,25 / 0,5 / 1 m |

OSR cao mà SR thấp: robot tới nơi nhưng dừng sai lúc. OSR thấp: robot không tới được đích.

### `nsnav compare`

```text
SR   ref 17/60 (0.283)   new 21/60 (0.350)
paired: new wins 6, new losses 2, exact McNemar p = 0.289
```

`wins` là số episode policy mới làm được mà B0 không, `losses` thì ngược lại. p < 0,05 cho thấy
khác biệt khó là ngẫu nhiên. Ví dụ trên tăng SR nhưng chưa đủ bằng chứng: thắng 6, thua 2, p = 0,29.

## 5. Thêm một policy mới

1. Viết class có `reset(episode)` và `act(ctx) -> PolicyAction` (xem `src/neusymnav/objectnav/runner.py`:
   `StepContext`, `PolicyAction`, `ExplorePolicy`). Mẫu đầy đủ: `src/neusymnav/objectnav/b0/policy.py`.
2. Chỉ được đọc `ctx.episode.object_category` từ episode. Input hợp lệ: RGB-D, pose simulator,
   bản đồ do robot tự dựng, Hydra/3DSG dựng từ chính các quan sát đó. **Không** dùng semantic GT,
   navmesh, view point hay tour.
3. Control không được chờ detector, CLIP, Hydra hay worker phòng.
4. Đăng ký tên mới trong `tools/objectnav/run_episodes.py`: thêm vào `choices` của `--policy` và
   viết một nhánh tạo policy (xem `if a.policy == 'b0':`). Sau đó `nsnav run <tên> --policy <tên mới>`.
5. Muốn dùng `nsnav why` thì policy ghi thư mục `evidence/` theo định dạng của B0
   (`src/neusymnav/objectnav/b0/policy.py`, tham số `evidence_dir`).
6. Giữ runner config `lockstep-b0-v3h` khi so với B0. Nếu đổi guard, ghi rõ trong kết quả.

## 6. Môi trường trên máy này

- Python của project: `.venv/bin/python`. Habitat (chấm, chẩn đoán): `~/miniconda3/envs/habitat/bin/python`
  (đổi bằng biến `HABITAT_PYTHON`).
- Asset nặng là symlink tới worktree `.runtime/worktrees/Kiet_branch2`: `.runtime/hydra_ws` (13 GB),
  `.runtime/room-slm`, `runs/hydra-objectnav/B1-stability-20261107/native`. **Không xoá worktree đó.**
- Profile detector của B0: `configs/demo-00806.hydra-tour-slm.experimental.local.json`. File này
  là file local do `handoff/3dsg-v11/install.py` sinh ra; chạy lại installer nếu nó bị mất.
- Cảnh HM3D: `~/Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG/artifacts/habitat_data`.

## 7. Lỗi hay gặp

| Triệu chứng | Cách xử lý |
|---|---|
| `nsnav: runs/objectnav/X already exists` | tên run đã dùng; chọn tên mới |
| `was started with other settings` | run cũ đã chạy với policy hoặc config khác; chọn tên mới |
| `the code changed since run "X" started` | code đã sửa sau lần chạy đầu của run đó; `nsnav new <tên mới> --from X` |
| `episodes: N total, N already done, 0 to run` | run đã xong hết; chọn tên mới nếu code đã đổi |
| `a simulator/demo is already running` | đợi lần chạy kia xong; `nsnav ps` để xem |
| `evidence missing` khi `nsnav why` | policy chưa ghi `evidence/` dạng B0; kết quả của `run` (chấm, từng episode, so với B0) vẫn dùng được |
| `unknown uid` | sai uid; xem `nsnav list` |
| detector không khởi động | kiểm tra file profile ở mục 6 và `.runtime/detector26`; chạy lại installer |
| SR thay đổi khi chấm lại run cũ | run cũ được chấm bằng schema ≤ 2; chỉ so các kết quả cùng schema 3 |

## Phụ lục: lệnh gốc mà `nsnav` gọi

Chạy:

```bash
PYTHONPATH=src .venv/bin/python tools/objectnav/run_episodes.py --set hm3d_v2 --split val --manifest $OUT/manifest.json --policy b0 --run-id $RUN_ID --out-dir $OUT --config configs/objectnav/lockstep-b0-v3h.json --b0-config configs/objectnav/b0-policy-v3.json
```

Chấm:

```bash
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/score_trajectories.py $OUT/trajectories.jsonl --set hm3d_v2 --split val
```

Tìm nguyên nhân và báo cáo:

```bash
PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/b0/failure_evidence.py $OUT --set hm3d_v2 --split val --runner-config configs/objectnav/lockstep-b0-v3h.json
```

```bash
PYTHONPATH=src .venv/bin/python tools/objectnav/b0/summarize_run.py $OUT
```

60 DEV:

```bash
OUT=runs/objectnav/<id> RUN_ID=<id> POLICY=<tên> bash tools/objectnav/b0/run_dev60.sh
```
