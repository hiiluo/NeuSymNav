# Chuẩn bị model và dataset trong `local-assets`

Chạy các lệnh từ thư mục gốc của NeuSymNav sau khi clone. Git tạo sẵn
`local-assets/models/` và `local-assets/datasets/` bằng hai file `.gitkeep` rỗng.
Mỗi thành viên tự tải asset vào các đường dẫn dưới đây. Profile CPU và GPU
dùng cùng file.

## Detector dùng chung

Tải hai file từ [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/tag/v8.4.0).

```bash
mkdir -p local-assets/models/{yoloe,mobileclip}
release=https://github.com/ultralytics/assets/releases/download/v8.4.0
curl -fL "$release/yoloe-26m-seg.pt" -o local-assets/models/yoloe/yoloe-26m-seg.pt
curl -fL "$release/mobileclip2_b.ts" -o local-assets/models/mobileclip/mobileclip2_b.ts

sha256sum -c <<'EOF'
585f5ec9028fd358035da8d860c27c56be285a795cba2076fba536a4391c2c83  local-assets/models/yoloe/yoloe-26m-seg.pt
35d7f213e4d75f38514e4656ad3cb91158bd33e3805d8ac349f23b186f66982f  local-assets/models/mobileclip/mobileclip2_b.ts
EOF
```

Sau khi SHA-256 báo `OK`, tạo hai symlink dưới đây nếu chưa có. Các profile
Hydra hiện tại đọc qua hai symlink này.

```bash
ln -s yoloe/yoloe-26m-seg.pt local-assets/models/yoloe-26m-seg.pt
ln -s mobileclip/mobileclip2_b.ts local-assets/models/mobileclip2_b.ts
```

## Qwen3-VL

Dùng cặp GGUF từ [Qwen3-VL-2B-Instruct-GGUF tại revision `52d6c8f`](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/tree/52d6c8ffea26cc873ac5ad116f8631268d7eb503).
Tải cả model Q4_K_M và projector F16.

```bash
vl_dir=local-assets/models/qwen3-vl/gguf-52d6c8f
mkdir -p "$vl_dir"
revision=52d6c8ffea26cc873ac5ad116f8631268d7eb503
source_url="https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/$revision"
curl -fL "$source_url/Qwen3VL-2B-Instruct-Q4_K_M.gguf" \
  -o "$vl_dir/Qwen3VL-2B-Instruct-Q4_K_M.gguf"
curl -fL "$source_url/mmproj-Qwen3VL-2B-Instruct-F16.gguf" \
  -o "$vl_dir/mmproj-Qwen3VL-2B-Instruct-F16.gguf"

sha256sum -c <<'EOF'
089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae  local-assets/models/qwen3-vl/gguf-52d6c8f/Qwen3VL-2B-Instruct-Q4_K_M.gguf
c3d5afbef5287953acd57b4043d2269456e5761a4eaccb3b71b062996970aea5  local-assets/models/qwen3-vl/gguf-52d6c8f/mmproj-Qwen3VL-2B-Instruct-F16.gguf
EOF
```

Khi cấu hình profile VLM, điền đường dẫn tuyệt đối và SHA-256 tương ứng vào
`model_path`, `model_sha256`, `mmproj_path`, `mmproj_sha256`. Ghi nguồn và revision
của bản GGUF đã chọn, rồi cập nhật `ui.room_label_debug.config_sha256` trong
profile demo sau khi sửa file cấu hình VLM. Bản GGUF tự convert đã dùng trong
[benchmark KSS](results/room-vlm-kss-20261112.md) nằm trong
`local-assets/models/qwen3-vl/gguf-8964489/` và có bộ SHA-256 riêng.

Nếu chạy handoff SLM cũ, chuẩn bị Qwen3-1.7B theo
[checkpoint SLM](results/room-slm-pilot-2026-11-08.md), với
`Qwen3-1.7B-Q4_K_M.gguf` đặt tại
`local-assets/models/qwen3-1.7b/Qwen3-1.7B-Q4_K_M.gguf`. Handoff SLM đọc
file này qua đường dẫn runtime. Tạo symlink sau khi đã có model.

```bash
mkdir -p .runtime/room-slm/models/qwen3-1.7b-hf-70d244c
ln -s "$PWD/local-assets/models/qwen3-1.7b/Qwen3-1.7B-Q4_K_M.gguf" \
  .runtime/room-slm/models/qwen3-1.7b-hf-70d244c/Qwen3-1.7B-Q4_K_M.gguf
```

## Cảnh HM3D

Tải từ [Matterport HM3D](https://github.com/matterport/habitat-matterport-3dresearch).
Chọn bản **Habitat v0.2**. Scene 00770 nằm trong
`hm3d-example-habitat-v0.2.tar`. Scene 00806 nằm trong
`hm3d-minival-habitat-v0.2.tar` và cần quyền tải minival của tài khoản Matterport.
Chỉ tải archive của scene muốn chạy.

Giải nén archive vào thư mục tạm, rồi chép hai file `.basis.glb` và
`.basis.navmesh` từ thư mục của scene vào đúng vị trí bên dưới. Demo RGB-D
dùng hai file hình học này.

```text
local-assets/datasets/
├── hm3d-example/hm3d/example/
│   └── 00770-NBg5UqG3di3/
│       ├── NBg5UqG3di3.basis.glb
│       └── NBg5UqG3di3.basis.navmesh
└── hm3d-minival/versioned_data/hm3d-0.2/hm3d/minival/
    └── 00806-tQ5s4ShP627/
        ├── tQ5s4ShP627.basis.glb
        └── tQ5s4ShP627.basis.navmesh
```

Đối chiếu SHA-256 của scene vừa tải.

| Scene | `.basis.glb` | `.basis.navmesh` |
| --- | --- | --- |
| 00770 | `86ef9e300ae48e67c13899ecb0c6038b6f1addaf282bf9ef22ee34eb36cd49b1` | `622bdeba91d1408b3ea3b70d9d1464d4e18bf5cd61f52f66368de35bdf67b515` |
| 00806 | `81c42f0e2d6a471643107682c3673588dd34c523891f1a341d62c0809542f532` | `dcfa4ec162273edd7e1529bb580aaf49b4d05f1bfa9e694ae89e54ec664b4310` |

Tạo file cấu hình scene cho Habitat cạnh thư mục scene. Chọn `00770` hoặc
`00806` ở dòng đầu. Lệnh giữ nguyên file cấu hình nếu nó đã tồn tại.

```bash
python3 - 00770 <<'PY'
import json
import sys
from pathlib import Path

datasets = Path("local-assets/datasets")
layout = {
    "00770": ("hm3d-example/hm3d/example", "00770-NBg5UqG3di3", "hm3d_00770"),
    "00806": ("hm3d-minival/versioned_data/hm3d-0.2/hm3d/minival",
              "00806-tQ5s4ShP627", "hm3d_minival"),
}
directory, scene, name = layout[sys.argv[1]]
parent = datasets / directory
stem = scene.split("-", 1)[1]
for ext in ("glb", "navmesh"):
    path = parent / scene / f"{stem}.basis.{ext}"
    if not path.is_file():
        raise SystemExit(f"Thiếu {path}")

target = parent / f"{name}_basis.scene_dataset_config.json"
if not target.exists():
    config = {
        "stages": {
            "paths": {".glb": [f"{scene}/*.basis.glb"]},
            "default_attributes": {
                "shader_type": "flat", "up": [0, 0, 1], "front": [0, 1, 0],
                "origin": [0, 0, 0],
            },
        },
        "objects": {},
        "light_setups": {},
        "scene_instances": {"default_attributes": {"default_lighting": "no_lights"}},
    }
    target.write_text(json.dumps(config, indent=2) + "\n")
print(target)
PY
```

## Kiểm tra trước khi chạy

Xem [hướng dẫn Hydra](../handoff/3dsg-v11/README.md) để chuẩn bị các môi trường,
build Hydra và chạy preflight với profile local của scene. Với installer SLM
00806, dùng `--habitat-data "$PWD/local-assets/datasets/hm3d-minival"`.

Kiểm tra Git bằng `git ls-files local-assets`. Kết quả phải gồm đúng
`local-assets/datasets/.gitkeep` và `local-assets/models/.gitkeep`.
