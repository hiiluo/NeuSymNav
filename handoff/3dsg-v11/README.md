# Bàn giao baseline-3dsg-v11 (Hydra + SLM + chuyển động realtime)

Nhánh này là tag `baseline-3dsg-v11` (11/11/2026) cộng thêm một commit bàn giao. Đây là trạng thái **trước** kế hoạch ObjectNav; code ObjectNav nằm trên nhánh `objectnav` và không có ở đây.

## Có gì trong PR

| Commit | Nội dung |
|---|---|
| `8d7409d` | Pipeline phòng Rebuild RGB-D M1–M5 |
| `1347ff2` | Sửa lỗi CI (portability, timing) |
| `62f16fc` | M5 là nguồn phân vùng phòng duy nhất |
| `517e5cc` | Khoá baseline-3dsg-v11: Hydra backend (worker riêng, room finder ổn định), nhãn phòng bằng SLM (Qwen3-1.7B, llama.cpp), sửa chuyển động realtime + tour navmesh, profile 00806 |
| commit bàn giao | thư mục này, test của nó, `tools/run_hydra_map_demo.sh` chấp nhận nhánh `main` và `handoff/*` |

Tài liệu nên đọc: `docs/results/realtime-navigation-tour-2026-11-09.md` (chuyển động), `docs/hydra-python-bindings.md` và `docs/results/hydra-branch2-h1.md` (build Hydra), `docs/results/room-slm-pilot-2026-11-08.md` (SLM), `docs/baselines/baseline-3dsg-v11.lock.json` (49 file + 13 asset đã khoá).

## Những gì KHÔNG có trong git (phải tự chuẩn bị)

| Thứ | Ở máy gốc | Cách có |
|---|---|---|
| `.venv` (Python 3.12.3, NeuSymNav editable, NumPy 1.26.4, SciPy 1.17.1, Numba 0.61.2, PyQt5 5.15.11) | `<repo>/.venv` | `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev,ui]' numba==0.61.2`; xem `docs/local-demo-setup-20261030.md` |
| Habitat (Python 3.9, habitat-sim 0.3.3) | `~/miniconda3/envs/habitat` | conda; sensor chạy với `gpu_device_id=-1` (Mesa EGL) |
| Cảnh HM3D 00806 (`minival/00806-tQ5s4ShP627`) | `.../habitat_data/versioned_data/hm3d-0.2/hm3d/minival/` | tải bằng tài khoản HM3D/Matterport **của chính bạn** (điều khoản HM3D không cho chia sẻ lại) |
| Detector env (Python 3.12, Torch 2.7.1+cpu, Ultralytics 8.4.24, OpenVINO 2026.4.1, CLIP) | `<nsn-home>/.runtime/detector26` | venv riêng |
| `yoloe-26m-seg.pt`, `mobileclip2_b.ts` | `<nsn-home>/local-assets/models/` | Ultralytics assets v8.4.0 (sha256 có trong profile) |
| Model OpenVINO đã export (XML/BIN + `end2end-metadata.json`) | `.runtime/hydra_ws/artifacts/hydra-cpu-resolution-ab-00805-20261104/openvino-model/` | xin Kiệt thư mục này; hoặc chạy detector bằng Torch CPU (`--detector-backend torch`, chậm hơn, khác baseline) |
| SLM: `llama-server` (llama.cpp `80d2c0c`) và `Qwen3-1.7B-Q4_K_M.gguf` (rev `70d244c`) | `.runtime/room-slm/` | build/convert theo `docs/results/room-slm-pilot-2026-11-08.md`, hoặc xin Kiệt |
| Workspace Hydra (ROS 2 Jazzy, Hydra `2e58a35`, Spark-DSG `3c40997`, …) | `.runtime/hydra_ws/` | build theo `docs/results/hydra-branch2-h1.md`; các lock nằm trong `hydra_ws/` ở đây |
| `libhydra.so` có room finder ổn định | `runs/hydra-objectnav/B1-stability-20261107/native/` | sau khi build workspace: `python3 tools/native/hydra_room_stability/build.py` |

## Các bước

1. Checkout nhánh, chuẩn bị các thứ ở bảng trên (Hydra workspace là phần lâu nhất). Yêu cầu: Ubuntu 24.04, ROS 2 Jazzy ở `/opt/ros/jazzy`, ≥ 16 GB RAM.
2. Chép lock Hydra và `env.sh` vào chỗ build (bước 4 tự chép nếu chưa có): `.runtime/hydra_ws/{env.sh,dependencies.lock.yaml,ros2-deps-https.yaml,system-dependencies.lock.json,vendor-lock.json,wheelhouse-python/requirements.lock}`.
3. Build Hydra workspace rồi `libhydra.so` (xem bảng).
4. Sinh các file local và ghim lại sha256 theo máy của bạn:
   ```bash
   python3 handoff/3dsg-v11/install.py --habitat-data /đường/dẫn/habitat_data
   # thêm --nsn-home nếu detector26/ và local-assets/ không nằm trong repo
   # thêm --detector-backend torch nếu máy không có GPU Intel
   ```
   Tool in từng file đã ghim: `same` (giống hệt baseline), `changed` (khác — bình thường với interpreter Python và `libhydra.so` tự build; **không** bình thường với model, cảnh, taxonomy), `MISSING` (chưa có). Exit 0 khi không thiếu gì. Chạy lại với `--force` sau khi bổ sung.
5. Preflight, rồi chạy demo:
   ```bash
   NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00806.hydra-tour-slm.experimental.local.json" \
     bash tools/run_hydra_map_demo.sh 00806 --preflight
   NEUSYMNAV_HYDRA_DEMO_CONFIG="$PWD/configs/demo-00806.hydra-tour-slm.experimental.local.json" \
     bash tools/run_hydra_map_demo.sh 00806 300
   ```
   Không đặt `NEUSYMNAV_BASELINE_LOCK`: các asset trên máy bạn có sha khác máy gốc nên kiểm tra khoá sẽ từ chối chạy.

## Lưu ý

- Tour navmesh trong profile là dữ liệu đặc quyền của simulator, dùng để đánh giá 3DSG; **không** phải kết quả ObjectNav.
- Profile giữ nguyên guard an toàn (TTL 300 ms, footprint, unknown ≠ free, tốc độ ≤ 0,2 m/s).
- `templatize.py` chỉ dùng một lần trên máy gốc để tạo `templates/`; máy mới chỉ cần `install.py`.
- Test: `.venv/bin/python -m pytest -q tests/test_handoff_3dsg_v11.py`.
