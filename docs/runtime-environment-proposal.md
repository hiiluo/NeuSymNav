# Kiểm kê runtime và đề xuất môi trường tối thiểu

2026-10-27 — chưa cài các môi trường dưới đây, chưa tải model/dataset.

## Kết quả kiểm tra read-only

Evidence máy hiện tại: `runs/p00-main/environment-audit.json`, `env-config-files.txt`, `runtime-path-candidates.log` và `env-scan-errors.log`. Đã dò Conda registry `.conda/environments.txt`, `miniforge3/envs`, các venv trong `Works`, `Desktop`, `Documents`, `.local`, `.conda`; không quét toàn bộ filesystem. Cấu hình runtime trong hai nguồn đã được đọc, đường dẫn máy cũ được kiểm tra tồn tại. Không sửa nguồn hay các interpreter đã có. Import probes chạy `-B -I`, không inference/GPU.

| Interpreter thực tế | Phiên bản | Habitat / torch / Ultralytics / OpenCLIP |
| --- | --- | --- |
| `/home/hiiluo08/Works/NeuSym-Nav/NeuSymNav/.venv/bin/python` | 3.12.3 | Cả bốn import thất bại; NumPy, SciPy, pytest, PyQt5.QtWidgets import thành công |
| `/usr/bin/python3` | 3.12.3 | Cả bốn import thất bại |
| `/home/hiiluo08/miniforge3/bin/python` | 3.13.13 | Cả bốn import thất bại; Conda base, không tìm thấy env con |
| `/home/hiiluo08/.local/share/uv/python/cpython-3.10.21-linux-x86_64-gnu/bin/python` | 3.10.21 | Cả bốn import thất bại |

Các đường dẫn `/home/kiettran05/...` trong config là máy cũ, không tồn tại tại đây. Các `.venvs/habitat`, `.venvs/perception`, `.venvs/appearance` khai báo ở runtime example chưa tồn tại trong bản nguồn này. Venv duy nhất tìm thấy trong phạm vi dò là `.venv` core mới tạo trong NeuSymNav.

Native candidate: `/home/hiiluo08/Works/NeuSym-Nav/3DSG/prebuilt/linux-x86_64/bin/occusg_dude_worker`. `ldd` resolve được dependency hiện tại. P06 sau kiểm kê đã build source closure bên trong NeuSymNav và chạy ba native tests cùng request synthetic cho cả source-built/candidate (exit 0); evidence `runs/p06-native/`, report `runs/implementation/p06-native-report.md`. Candidate vẫn là artifact ngoài package; portability ngoài ABI máy này và chất lượng region trong scene thật chưa được chứng minh. OctoMap thuộc extension E1, không dùng thay NavMap core.

Kiểm tra read-only bổ sung tại P09: PCI nhận diện NVIDIA RTX 3060 Mobile/Max-Q và AMD Radeon 680M; `/proc/driver/nvidia/version` báo kernel module 580.178.04. Tuy nhiên NVIDIA-SMI chưa giao tiếp được driver và device GPU không khả dụng trong phiên này, nên chưa xác nhận VRAM/CUDA/EGL hoặc suy ra GPU có thể chạy. Evidence: `runs/p09-main/gpu-pci-readonly.txt`, `nvidia-kernel-readonly.txt`. Không đổi driver hay môi trường.

## Đề xuất để người dùng xem trước khi cài

Các môi trường tách nhau bằng process/IPC; không ép chung Python/NumPy/Torch ABI. Dung lượng dưới đây là **ước lượng dự trù**, chưa phải kết quả solver/download; không bao gồm model/dataset sẵn có hoặc log/replay. Khi được phép cài, cần dry-run solver và chốt lock trước khi tải; không tự chọn phiên bản mới nhất từ các snapshot cũ.

| Môi trường đề xuất | Dependency tối thiểu | Dự trù download / disk sau cài |
| --- | --- | --- |
| Sensor: `NeuSymNav/.runtime/sensor` | Conda Python tương thích build Habitat-Sim 0.3.3; NumPy, numpy-quaternion; headless EGL nếu dùng worker không display. Không cần torch hay habitat-lab nếu chỉ dùng API habitat_sim. Ưu tiên thử Python 3.10 theo New profile; bản 3DSG cũ dùng 3.9 nên phải để solver xác minh build. | Khoảng 0.3–1.5 GiB / 1–3 GiB |
| Detector: `NeuSymNav/.runtime/detector` | Python 3.12 (worker P07 dùng package contracts/YOLOE adapter thực có host requirement>=3.12), cặp torch/torchvision tương thích, ultralytics có YOLOE, NumPy, Pillow, OpenCV, PyYAML và tokenizer CLIP cung cấp `clip.clip.tokenize` theo adapter local. Pin đúng implementation/tokenizer trước khi cài, không chỉ dựa vào tên package `clip`; text encoder dùng MobileCLIP file hiện có. CPU smoke có thể làm trước, GPU build chọn theo driver thực tế. | CPU khoảng 0.3–1 GiB / 1–3 GiB; CUDA khoảng 2–5 GiB / 5–10 GiB |
| Appearance tùy chọn: `NeuSymNav/.runtime/appearance` | Python 3.10 hoặc 3.12, torch/torchvision, open_clip_torch, safetensors, timm, Pillow và dependency tokenizer. Checkpoint metadata trong 3DSG pin model/preprocessing, không tự tải pretrained. | CPU khoảng 0.3–1 GiB / 1–3 GiB; CUDA có thể thêm 4–8 GiB disk nếu tách env |
| UI/core hiện có | Giữ `.venv` Python 3.12 + NumPy/SciPy/PyQt5; không nâng toàn bộ Torch/NumPy | Đã có; chưa cần môi trường UI riêng |
| DuDe native | CMake, C++17, OpenCV core/imgproc, CGAL Core, jsoncpp, GMP/MPFR; FIST archive và notices trong closure đã audit | P06 đã tái dùng dependency prefix local, build serial thành công; không cần cài thêm để chạy CPU/native synthetic trên máy này. Portability máy khác chưa đo |

Baseline appearance vẫn off. Có thể dùng cùng dependency installation cho detector/appearance nếu thực tế tương thích nhưng vẫn chạy hai worker; chưa quyết định gộp môi trường trước smoke. Không cần ConceptGraphs greedy association hoặc PyTorch3D đầy đủ chỉ để lấy OpenCLIP feature. Không cài environment từ toàn bộ lock legacy vì chứa package thừa và các phiên bản từ máy khác chưa được xác minh ở đây.

Habitat upstream hướng dẫn Conda và biến thể headless/withbullet; chỉ chọn physics nếu adapter thực cần. [Habitat-Sim installation](https://github.com/facebookresearch/habitat-sim#installation).

YOLOE nằm trong package Ultralytics và text encoder có thể bị tải khi gọi lần đầu; adapter NeuSymNav phải pin đường dẫn encoder có sẵn và chặn fallback download. [Ultralytics YOLOE](https://docs.ultralytics.com/models/yoloe/).

OpenCLIP dùng `open_clip_torch`; encoder phải load checkpoint local và `eval()` thay vì dùng tag pretrained có thể tải qua mạng. [OpenCLIP usage](https://github.com/mlfoundations/open_clip#usage).

Torch CPU/CUDA wheel và torchvision phải được chọn thành cặp tương thích với nền tảng thực tế; chưa chọn CUDA version từ metadata máy cũ. [PyTorch installation](https://pytorch.org/get-started/locally/).

## Phần chưa chứng minh

Chưa có sensor capture/model inference thật hoặc GPU budget cho NeuSymNav. P06 đã có DuDe synthetic preprocessing/protocol evidence; chưa có native pipeline hoặc real-scene geometry-quality parity. Chỉ tìm thấy một scene HM3D trong manifest hiện tại; campaign 2 scene × 2 seed còn thiếu support nếu kiểm kê P10 không tìm thêm scene hợp lệ. CPU fixture/replay correctness tiếp tục độc lập, không thay bằng chứng runtime.

## Kết quả thực thi cập nhật — 2026-10-28

Sau yêu cầu người dùng triển khai toàn bộ phần còn lại, các prefix riêng dưới NeuSymNav/.runtime đã được tạo; đề xuất thiếu dependency phía trên là checkpoint trước cài đặt. `.runtime/sensor/bin/python` (Python3.9,Habitat-Sim0.3.3 headless,NumPy1.26.4) đã capture/seed/pose thật trên00802 và00861; `.runtime/detector/bin/python` (Python3.12,torch2.7.1cu126,torchvision0.22.1,Ultralytics8.3.221,localMITCLIP) đã inference CUDA/IPC thật; `.runtime/host/bin/python` (Python3.12,NumPy1.26.4,Numba0.61.2) đã kiểm Python/Numba kernel parity. Exact locks/hashes/cách chạy ở [runtime environments](../runtime/environments/README.md), install/import logs ở runs/p10-native-preparation. Không thay core .venv hoặc source siblings.

Sandbox không thấy NVIDIA driver API; ngoài sandbox được duyệt thấy RTX3060Laptop6GiB,driver580.178.04,UUIDGPU-8ffd4877-4094-2b68-4daa-c1e35c2742e1. Đây là giới hạn execution context, không phải bằng chứng máy thiếu GPU hay cần đổi driver. Audit mở rộng phát hiện thêm ba HM3D basis scenes có sẵn trong NewOH3DSG/data/versioned_data; dùng00861 làm scene thứ hai với calibration depth mới. Không tải model/dataset hay training.

Cài môi trường/import/smoke không thay thế nghiệm thu P10: các diagnostic tích hợp hiện có object commit/room geometry thật nhưng vẫn chưa đạt translation>1m, membership và tài nguyên đủ support. Native acceptance vẫn in_progress.
