# NeuSymNav — hướng dẫn cho agent

## Bắt đầu hoặc tiếp tục công việc

1. Đọc [điều phối agent](docs/agent-orchestration.md) trước khi phân công, gọi subagent hoặc chọn model. Main mong muốn **GPT-6.1 Sol / medium**; Luna luôn **xhigh**; **cấm mọi model/alias chứa `astra`**, kể cả fallback và reviewer.
2. Đọc [trạng thái](docs/implementation-status.md) để biết bước đã làm, quyền thực thi và blocker. Khi bắt đầu triển khai hoặc thay contract, đọc [thiết kế](docs/architecture.md) và task tương ứng trong [kế hoạch](docs/implementation-plan.md).
3. Chỉ sửa trong `NeuSymNav/` cho công việc gộp. `../NewOH3DSG/` và `../3DSG/` là nguồn tham khảo chỉ đọc; giữ nguyên chúng. Không mang các chiến dịch, backlog hoặc lệnh training trong AGENTS/docs cũ sang làm nhiệm vụ hiện hành.
4. Mỗi task kết thúc bằng cập nhật trạng thái, lệnh kiểm chứng, exit code, artifact và phần chưa được chứng minh. Tách `implemented`, `correctness-verified`, `runtime-validated`; không suy pass từ báo cáo cũ.

## Invariants

- Source frame, calibration, timestamp, coordinate convention và semantic vocabulary phải có version/provenance. Runtime dùng RGB-D và pose simulator; semantic GT chỉ thuộc evaluator offline.
- Một owner duy nhất cấp và hợp nhất canonical object ID; alias được truyền tới hierarchy, verification và consumers. Geometry region ID độc lập nhãn loại phòng.
- Graph/map khởi đầu rỗng theo episode. Sensor cũ không được phát hành lại như dữ liệu điều khiển mới; control không chờ detector, CLIP hoặc room worker.
- Giữ unknown khác free; cạnh liên thông cấu trúc không phải chứng nhận robot đi qua được. Thiếu depth/clearance hợp lệ phải chặn chuyển động theo contract.
- Mỗi file một writer; shared contracts do main quản lý. Chỉ một GPU workload/benchmark tại một thời điểm. Chính sách model, review, nâng cấp và handoff nằm trong tài liệu điều phối.
- Khởi đầu chỉ có tài liệu. Yêu cầu tạo kế hoạch không tự cho phép triển khai pipeline, training, tải dữ liệu/model mới hoặc publish. Khi người dùng giao thực thi kế hoạch, tiến hành các bước trong phạm vi đó mà không xin lại từng task.
