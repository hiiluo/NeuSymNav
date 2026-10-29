# NeuSymNav

Kế hoạch hợp nhất online hierarchical 3D scene graph từ `NewOH3DSG` và bộ `3DSG`. Ngày soạn: **2026-10-27**.

**Trạng thái:** có demo native RGB-D/simulator với YOLOE-26m, observation640×480, UI và full raw replay. P10 vẫn chưa nghiệm thu toàn bộ; xem [trạng thái và evidence](docs/implementation-status.md) để phân biệt correctness, runtime và chất lượng.

Demo dài có profile riêng:

```sh
bash tools/run_long_demo.sh --preflight
bash tools/run_long_demo.sh 600
```

Lệnh dùng môi trường/model/dataset đã khai báo trên máy hiện tại. Nhịp control thực đo và giới hạn hiển thị được ghi trong [checkpoint long demo](docs/results/long-demo-2026-10-29.md); xem [hướng dẫn chạy](docs/running.md) cho ngân sách và cấu hình.

## Clone mới: chạy kiểm chứng CPU

```sh
git clone https://github.com/hiiluo/NeuSymNav.git
cd NeuSymNav
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,ui]'
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -m 'not native'
.venv/bin/python -m neusymnav.cli preflight --config tests/fixtures/launcher/config.yaml
```

CI kiểm chứng CPU/Qt offscreen, không tải model/dataset hoặc chạy GPU. Xem
[hướng dẫn GitHub và các asset ngoài repo](docs/github-setup.md). Demo native cần
môi trường sensor/detector/host, scene/calibration và backend DuDe riêng; một bản
clone source chưa tự có những thành phần này. `configs/live.example.json` là
mẫu cần điền thông tin thật, không phải cấu hình được phép chạy ngay.

[Checkpoint demo600s](docs/results/long-demo-2026-10-29.md) giữ số đo và source pins;
raw recording và môi trường local không upload. Repository chưa gán giấy phép
MIT/Apache chung; xem [third-party notices](THIRD_PARTY_NOTICES.md). Native upstream
có thành phần hạn chế tái phân phối được giữ local.

## Đọc theo thứ tự

1. [Kiến trúc và phạm vi](docs/architecture.md): chọn gì, bỏ gì, ai sở hữu state và contract tích hợp.
2. [Kế hoạch triển khai](docs/implementation-plan.md): task, dependency, files, kiểm chứng và gate.
3. [Hướng dẫn sử dụng agent](docs/agent-orchestration.md): model/effort, phân công, review và mẫu prompt.
4. [Trạng thái triển khai](docs/implementation-status.md): checkpoint cho phiên tiếp theo.

Agent bắt đầu tại [AGENTS.md](AGENTS.md). Người dùng chọn **GPT-6.1 Sol / Medium** cho main trong công cụ đang dùng; tài liệu không tự đổi model của phiên.

## Phạm vi bàn giao đầu tiên

Một pipeline single-floor, pose simulator, frontier exploration, object graph có ID/bằng chứng bền vững, appearance tùy cấu hình, phân vùng DuDe, object–room membership bảo thủ và UI quan sát độ trễ. Có replay, provenance, tests và đánh giá đối chứng. Room semantics nâng cao, OctoMap bổ sung, ObjectNav chủ động, SLAM và multi-floor được tách khỏi gate lõi.

Đầu ra cuối phải chạy bằng entrypoint của `NeuSymNav`, không cần import source từ hai folder gốc. Model/dataset có thể là tài sản ngoài package được khai báo rõ đường dẫn và checksum; không sao chép hoặc tải toàn bộ dữ liệu theo mặc định.

## Chạy và kiểm chứng core

Host CPU dùng Python 3.12.3 và `.venv/` đã có trong folder này. Lệnh kiểm chứng:

```sh
.venv/bin/python -m pytest tests -q -m "not native"
.venv/bin/python tools/verify_package.py --source-only
.venv/bin/python -m neusymnav.cli --help
```

Xem [hướng dẫn chạy](docs/running.md) cho preflight, live run, replay và UI. Template live yêu cầu điền interpreter/asset paths, SHA-256 và floor calibration thật; giá trị thiếu chặn launch. Replay fixture CPU không chứng nhận Habitat/model inference hoặc chất lượng graph thật. Appearance giữ optional/off mặc định.

[Đề xuất môi trường runtime](docs/runtime-environment-proposal.md) ghi kết quả dò interpreter và dependency/dung lượng dự trù trước khi cài. Habitat, detector, DuDe và GPU đã có evidence native theo từng checkpoint; appearance giữ optional. Các môi trường hiện hành và quyền cài đặt đã thực hiện được ghi trong implementation-status.md; không suy nghiệm thu P10 từ một lượt demo.
