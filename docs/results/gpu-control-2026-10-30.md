# Demo GPU — kết quả ngày 30/10/2026

Đã tích hợp raycasting CUDA vào luồng chạy thật và kiểm chứng một phiên 60 giây.
Control đạt trung bình **17,70 Hz**, vượt mục tiêu tối thiểu 10 Hz đã chọn,
nhưng **chưa đạt 20 Hz ổn định**. P10 chưa được nghiệm thu toàn bộ.

| Chỉ số | Kết quả |
| --- | ---: |
| Control trung bình | 17,698 Hz |
| Khoảng cách giữa các lần gọi control, p95 / p99 | 98,20 / 124,40 ms |
| Vượt deadline 50 ms | 436/1.060 khoảng, 41,13% |
| Vượt deadline 100 ms | 49/1.060 khoảng, 4,62% |
| Lệnh có chuyển động và proof hoàn chỉnh | 1.053 |
| Quãng đường tối thiểu quan sát từ pose | 1,985 m |
| Frame raw ghi và đọc kiểm chứng đầy đủ | 1.332/1.332 |
| Detector commit / object evidence commit | 42 / 23 |

Hz tính từ thời điểm bắt đầu các lần gọi control thật, bao gồm cả kết quả zero.
Phiên này có 1.053 kết quả executed và 8 expired_or_zero; không có vòng lặp
control_rejected bị tính thành chuyển động. Tám kết quả expired_or_zero không
có actuation proof, nên cờ tổng hợp actuation.complete vẫn là false; không suy
chứng nhận quỹ đạo đầy đủ từ 1.053 proof đã kiểm tra. Detector, semantic graph và UI có
nhịp riêng; các chỉ số trên không có nghĩa segmentation chạy 17,7 FPS.

GPU thực tế là RTX 3060 Laptop, dùng worker Torch/Triton riêng cho raycasting;
YOLOE-26m cũng tiếp tục dùng CUDA. RGB giữ 640×480, depth điều hướng 240×180.
Profile yêu cầu primary 5 Hz và navigation 30 Hz để bù thời gian chụp RGB xen kẽ;
đây là trần yêu cầu, không phải kết quả đo. Mỗi lệnh vẫn cần frame mới, pose đúng
nguồn và các gate RGB-D, TTL 300 ms, footprint, clearance cùng proof hợp lệ.
Không có fallback CPU âm thầm nếu worker GPU lỗi.

Các tối ưu bổ sung gồm tái sử dụng phép chiếu trong cùng frame, cache hình học
thuần túy có giới hạn, giảm chi phí kiểm tra mask và gộp publication graph.
Đã sửa việc chờ region cuối phiên trước khi xuất canonical hierarchy/map.

Kiểm chứng: **1.859 test CPU pass**, hai test skip, ba native test deselect;
**31 test worker pass trong lượt bật kiểm tra CUDA thật**. Các thay đổi quan trọng đã qua review độc lập.
Phiên native kết thúc sạch, toàn bộ raw/proof/export được kiểm tra offline,
559/559 mẫu RSS và 63/63 mẫu GPU hợp lệ. Các file code/test/profile đã chốt
khớp 223 hash trước và sau chạy. Đây là bộ đo tài nguyên theo mẫu, không chứng
nhận peak tuyệt đối giữa các mẫu.

Chạy demo trên môi trường local đã cấu hình:

```sh
bash tools/run_gpu_demo.sh --preflight
bash tools/run_gpu_demo.sh 60
```

Bản CPU vẫn chạy bằng `bash tools/run_long_demo.sh 60`.

Giới hạn: lần đo này dùng Qt offscreen, một scene/seed và 60 giây. Chưa đo lại
600 giây với GPU hoặc thời gian trên cửa sổ desktop thật. Deadline 50 ms vẫn
bị vượt nhiều; cần tiếp tục giảm chi phí capture/IPC/map/control trước khi
chốt 20 Hz. Campaign P10 đầy đủ và assigned room membership vẫn chưa được
chứng minh; adapter planar không mô phỏng grounding hoặc địa hình 3D.
Không suy chất lượng detection/segmentation tăng từ số đo tốc độ.

Artifact local: `runs/realtime-motion-20261030/report.md`, `gpu-final60/`,
`gpu-final60-audit.json`, `final-freeze/` và các thư mục review tương ứng.
