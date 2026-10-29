# GitHub setup và bản clone mới

Repo đích: https://github.com/hiiluo/NeuSymNav. Repo tồn tại, đangPublic và ban đầu
rỗng. Nhánh chính`main`, dùng SSH của tài khoảnhiiluo đã xác thực. Không cần cung
cấp token qua chat; không thay visibility hoặc Git identity đã có trên máy.

## Phần đưa lên

Source Python, test/fixture nhỏ, config mẫu và các config lịch sử, docs, build
recipe/source inventory và lockfiles môi trường. Bốn regression inputs trước
đây nằm trong`runs/` đã được giữ exact-byte ở`tests/fixtures/regressions/` kèm
SHA256/provenance để CPU suite không phụ thuộc các run local.

Không đưa`.runtime/`,`.venv/`,`runs/`, model/dataset, credential files, compiled
libraries hoặc`native/dude/upstream/` lên. Các file local đó được giữ nguyên trên
máy. Không dùng`git add -f` để vượt các loại trừ này. Native FIST notice hạn chế
redistribution; private repo cũng không thay đổi các điều khoản đó. Không suy
MIT cho toàn bộ project từ license OccuSG hoặc tự gán license khi chưa chốt quyền.
Xem`THIRD_PARTY_NOTICES.md` và`native/dude/README.md`.

## Clone và CPU

```sh
git clone https://github.com/hiiluo/NeuSymNav.git
cd NeuSymNav
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,ui]'
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -m pytest tests -q -m 'not native'
.venv/bin/python -m neusymnav.cli --help
.venv/bin/python -m neusymnav.cli preflight --config tests/fixtures/launcher/config.yaml
```

Các lệnh cài dependency là thao tác của người dùng trên máy mới; quá trình chuẩn
bị GitHub trên máy hiện tại không cài thêm dependency hoặc tải model/dataset.
CI tương ứng nằm ở`.github/workflows/cpu.yml`, quyền`contents:read`, actions pin
fullcommitSHA, timeout15phút. CI chỉ chứng minh source/CPU checks, không nghiệm
thu GPU/native/P10. Chưa có bằng chứng remote CI cho tới khi workflow chạy xong.

## Demo GPU và dữ liệu ngoài repo

| Thành phần | Cần cung cấp riêng |
|---|---|
| Host |Python3.12, core dependencies,Numba/PyQt5; mapper nhanh dùng hostNumba|
| Sensor worker |Python3.9,Habitat-Sim0.3.3 và dependency tương ứng|
| Detector worker |Python3.12,Torch2.7.1cu126,Ultralytics8.4.24,CLIP dependencies|
| Model |YOLOE-26m-seg,MobileCLIP2 encoder, đường dẫn/SHA phù hợp|
| Dataset |sceneRGB-D hợp lệ và quyền sử dụng HM3D hoặc scene khác|
| Calibration/start |floor datum, camera/body configuration và pose khởi đầu thật|
| Region backend |DuDe worker/native dependencies có quyền sử dụng, build riêng|
| Measurement GPU |nvidia-smi, GPU UUID và interpreter/executable checksums thật|

`runtime/environments/` giữ recipe/lock đã ghi; detector lock gốc chứaUltralytics
8.3.221, còn demo hiện hành dùng overlay8.4.24 trong`.runtime/detector26`, tái dùng
base dependencies bằng`.pth`. Đây là môi trường của máy hiện tại, không phải
một image hermetic tự có sau clone. Không chạy pip tải lại toàn bộ Torch/model
chỉ vì mở repo. Appearance vẫn optional/off.

`configs/p10/` có đường dẫn tuyệt đối và hashes của máy phát triển; không xem đó
là cấu hình portable. Bắt đầu từ`configs/live.example.json`, sao chép sang
`configs/demo.local.json`(ignored), điền interpreter/assets/hashes, calibration,
scene và GPU UUID. Những giá trịnull cố ý làm preflight fail để tránh chạy với
calibration giả. Không chỉ thay đường dẫn rồi giữ calibration của scene khác.

```sh
.venv/bin/python -m neusymnav.cli preflight --config configs/demo.local.json
# Chỉ khi preflight ready và runtime/assets thật đã được chuẩn bị:
.runtime/host/bin/python -m neusymnav.cli run \
  --config configs/demo.local.json --duration-s 600 --out runs/my-demo
```

Wrapper`bash tools/run_long_demo.sh 600` phục vụ cấu hình đã kiểm chứng trên máy
hiện tại. Nó không tự cài môi trường hoặc tải assets trên máy mới.

## Các lần cập nhật sau

```sh
git status --short
git add src tests configs docs tools runtime pyproject.toml pytest.ini README.md \
  AGENTS.md THIRD_PARTY_NOTICES.md .github .gitignore native
python3 tools/check_github_payload.py
git diff --cached --stat
git commit -m "Describe the change"
git push origin main
```

Checker đọc **đúng Git index blobs** khi kiểm tra staged payload, chặn các root
runtime/raw/nativeclosure, file lớn hơn10MiB, symlink/submodule và một số token/
private-key patterns, chỉ báo path+loại finding. Đây là heuristic, không thay
review nội dung/giấy phép. `--candidates` giúp xem các fileGit sẽ chọn trước
khi stage. CI chạy checker với tracked index sau checkout.

Quy trình Git theo [GitHub Docs](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).
Các action được đối chiếu tag chính thức của [checkout](https://github.com/actions/checkout)
và[setup-python](https://github.com/actions/setup-python), không tự suy phiên bản từ báo cáo cũ.

CPU dependency compatibility: NumPy 1.26.x is currently supported (NumPy 2 is
excluded after a fresh CI failure in huge-integer capsule indexing). Pillow is
required for appearance RGB crops; installed by the core package.
