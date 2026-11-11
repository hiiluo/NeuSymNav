# Hydra branch2 — phân rã ba `navigation_source_pending`, map 00805

Ngày: 2026-11-05. Phân tích dùng recording 30 giây đã có; không khởi chạy simulator trong quá trình phân rã. Sau đó chạy một smoke UI-on tối đa 30 giây để kiểm tra ứng viên tối ưu offline.

## Trace ba frame

Freshness gate vẫn là 300 ms. Ba nguồn trong run có depth age 301–306 ms và do đó bị từ chối đúng contract; không dùng map cũ để cấp lệnh.

| Frame | Sensor roundtrip / decode | Capture → map worker start | NavMap update | Raycast | Vote integration |
|---|---:|---:|---:|---:|---:|
| 27 | 72.1 / 91.3 ms | 165.2 ms | 187.1 ms | 109.4 ms | 125.3 ms |
| 92 | 30.6 / 11.5 ms | 42.5 ms | 279.7 ms | 166.3 ms | 58.5 ms |
| 131 | 31.4 / 11.7 ms | 43.6 ms | 339.4 ms | 195.3 ms | 65.7 ms |

Các pha con có thể chồng lấp/đo theo ranh giới instrumentation; không cộng chúng như các pha tuần tự. Frame 27 có chi phí sensor/decode và dispatch cao bất thường. Ở frame 92/131, chậm chủ yếu bên trong map update, đặc biệt raycast; frame 131 là tail lớn nhất. Cả ba trường hợp chạm freshness gate vì tổng thời gian từ capture tới map/control vượt 300 ms, chứ không phải map worker đơn thuần mất 300 ms. Cadence 4 raycast workers đã là lựa chọn tốt nhất trong so sánh offline hiện có; tăng worker count không phải hướng tiếp theo.

## Offline A/B và quyết định

Trên 133 recorded navigation frames, stride free-ray 1/2 có map update p50/p95/max lần lượt 114.3/143.3/161.2 ms và 59.2/73.5/78.8 ms; raycast p50/p95/max lần lượt 81.9/114.4/124.4 ms và 24.4/37.3/44.6 ms. Bản stride 2 giữ mọi endpoint/floor hit, không tạo free cell mà bản chuẩn không có, và giữ nguyên floor support trong phép đối chiếu offline. Tuy vậy số ô FREE cũng ít hơn.

**Bác bỏ stride 2 làm runtime profile:** profile thử chỉ thay `navigation.mapper.free_ray_stride=2` (SHA-256 `2b581e5df3310bba7bec3549b68a9901082659d8f48244be4025742a6c46f32e`). Smoke tối đa 30 giây kết thúc với `outcome=completed`, 349/349 frame recording, Hydra export revision 1 complete, UI final sequence 61 rendered và shutdown sạch. Nhưng actuation ghi nhận 0 accepted command, 227 `expired_or_zero` vì `robot_not_on_observed_free_cell`, body translation lower bound 0.0 m, frontier translation 0.0 m. Vì vậy tốc độ tốt hơn không đạt điều kiện điều khiển an toàn/tiến triển. Stride 2 không được bật mặc định và không được xem là sửa xong pending.

Smoke artifact: `.runtime/hydra_ws/artifacts/hydra-free-ray-stride2-00805-20261105/ui-on-30s/`. GPU sampler vẫn báo `no_usable_provider`; RSS sampler ghi 421 mẫu nhưng chỉ là sampled process-tree RSS, không chứng nhận absolute peak.

## Kết luận và bước tiếp theo

Đã phân biệt được nguyên nhân gần nhất: frame 27 bị kéo dài trước worker; frame 92/131 tốn trong raycast/map core. Giải pháp an toàn chưa được xác nhận. Giữ `free_ray_stride=1`, freshness gate 300 ms và các guard hiện tại. Bước tiếp theo là tối ưu raycast/core integration nhưng giữ toàn bộ ray evidence, rồi kiểm tra playback offline trên recording để chứng minh không đổi occupancy/free-space support cần cho bootstrap; chỉ sau đó mới chạy smoke 30 giây. Không nâng lên 60/120/300/600 giây dựa trên smoke ứng viên thất bại này.

## Kiểm chứng

- `./.venv/bin/python -m pytest tests/test_navmap.py tests/test_parallel_raycast.py tests/test_projection_reuse.py tests/test_local_coverage.py tests/test_local_bootstrap_integration.py -q` — 56 passed, exit 0.
- Candidate live smoke command: pinned Hydra local runner, UI-on, scene 00805, existing seed/start, duration capped at 30 s; exit 0 with completed artifact, but runtime acceptance **failed** as described above.
- `git diff --check` — recorded in implementation status.
- Implemented instrumentation/experimental stride option is present but default remains stride 1; correctness-verified tests do not establish candidate runtime viability. Candidate runtime was measured and rejected. Long-run stability and process-attributed GPU/VRAM sampling remain unproven.
