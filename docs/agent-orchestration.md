# Chính sách điều phối agent

## 1. Chính sách do người dùng yêu cầu

| Vai trò | Model ID | Effort | Phạm vi |
| --- | --- | --- | --- |
| Main | Do người dùng chọn | Do người dùng chọn | Giữ mục tiêu, contracts, tích hợp, kiểm chứng và trả lời |
| Worker thông thường, dễ thực hiện | `gpt-6-luna` | `xhigh` | Mặc định cho task có phạm vi và tiêu chí rõ |
| Worker/reviewer cho task khó hơn | `gpt-6.1-terra` | Theo task | Lựa chọn chính cho implementation phức tạp, debugging, contracts và review |
| Worker/reviewer ngoại lệ | `gpt-6.1-sol` | Theo task | Chỉ khi có lý do cụ thể Terra chưa đủ phù hợp |

**Astra không bị cấm ở main session. Chỉ cấm mọi model/alias chứa `astra` (không phân biệt hoa thường) ở subagent do main tạo ra, bao gồm subagent làm reviewer hoặc fallback. Main dùng Astra vẫn được tự thực hiện công việc và review.** Chỉ dispatch model công cụ hỗ trợ; luôn đặt rõ model/effort, không để subagent kế thừa Astra từ main.

Ưu tiên phân bổ: **Luna xhigh cho phần lớn việc dễ–bình thường; Terra chiếm phần lớn các task còn lại; Sol là ngoại lệ, có thể bằng 0 lượt trong một chiến dịch.** Không áp tỷ lệ phần trăm cứng vì độ khó thay đổi; không tạo task giả để đạt tỷ lệ. Luna được dùng thoải mái cho công việc độc lập hữu ích, không có quota nội bộ hoặc giới hạn số lượt tùy ý; vẫn tuân thủ slots/RAM, ownership và một GPU workload.

Main model do người dùng/công cụ cấu hình; Markdown không chuyển model. Nếu model worker không khả dụng, ưu tiên model được phép phù hợp hoặc main tự xử lý; không tự nâng lên Sol chỉ vì tiện. Ghi lý do fallback và giữ điều kiện dùng Sol bên dưới.

## 2. Phân công theo rủi ro

- **Luna xhigh:** task thông thường có contract và oracle rõ, như inventory, serialization, fixtures, UI, CLI và tổng hợp evidence.
- **Terra:** mặc định cho task vượt Luna, kể cả geometry, identity, concurrency, contracts và reviewer độc lập. Effort `medium` cho phạm vi rõ; `high` cho phân tích sâu/rủi ro xuyên module; `xhigh` khi cần reasoning đặc biệt sâu. Chọn theo task, không mặc định effort cao nhất.
- **Sol:** chỉ dùng khi Terra với effort phù hợp đã có điều tra có căn cứ nhưng còn nút thắt, hoặc main xác định ngay một vấn đề đặc biệt khó cần Sol và ghi lý do cụ thể. Dispatch phải nêu evidence, câu hỏi còn mở và vì sao Terra chưa phù hợp. Không mặc định Sol cho review cuối, task quan trọng hay mọi thay đổi safety.
- **Main:** chốt public contracts; quản lý dependency/environment; resolve interface conflicts; kiểm tra báo cáo worker; cập nhật integration status. Main có thể tự làm task nhỏ thay vì dispatch.
- **Nâng cấp:** chuyển evidence từ Luna sang Terra khi độ khó vượt phạm vi phù hợp; ưu tiên điều chỉnh effort/phạm vi của Terra, chỉ chuyển Sol khi đáp ứng điều kiện ngoại lệ trên. Không retry vô hạn; effort cao không thay thế reproduction.

## 3. Song song và ownership

1. Main chọn task có dependencies đã pass; khóa interface trước khi mở các nhánh phụ thuộc.
2. Dùng khoảng 2–4 workers nếu có đủ nhánh độc lập, điều chỉnh theo slots và RAM thực tế; đây không phải giới hạn cứng. Mỗi file một writer. `contracts/`, schema, dependency lock và config mặc định có một owner do main chỉ định.
3. Worker được đọc chéo; không sửa ngoài danh sách giao. Main làm phần độc lập, không lặp toàn bộ công việc của worker.
4. Chỉ một GPU workload và một owner thay môi trường tại một thời điểm. Benchmark latency chạy độc lập với workload khác; CPU tests chỉ song song khi không tranh output/port/RAM.
5. Subagent không tự tạo agent con trừ khi main cho phép rõ ràng; quyền đó phải giữ cùng allowlist model và ownership.
6. Ưu tiên subagent trong phiên. Không tạo chat mới của người dùng hoặc gửi tin nhắn ngoài task để thay delegation.

Các nhánh có thể song song được ghi ở cuối kế hoạch. Main không dispatch task chỉ vì nó nằm cạnh task khác trong tài liệu.

## 4. Mẫu dispatch

Khi công cụ hỗ trợ `collaboration.spawn_agent`, đặt rõ `model`, `reasoning_effort`; dùng `fork_turns="none"` khi override theo schema hiện tại. Đọc schema thực tế nếu công cụ khác. Không để worker kế thừa model không xác định.

```json
{
  "task_name": "port_replay",
  "fork_turns": "none",
  "model": "gpt-6-luna",
  "reasoning_effort": "xhigh",
  "message": "Đọc NeuSymNav/AGENTS.md và docs/agent-orchestration.md. Task P02 theo docs/implementation-plan.md; contract P01 đã khóa. Mục tiêu: replay lossless có source identity và completeness. Được sửa: src/neusymnav/recording/ và tests/test_replay.py. Chỉ đọc: contracts và hai folder nguồn. Chạy tests được giao; không GPU, không đổi dependency. Không Astra; không agent con. Trả files changed, commands/exit codes, evidence, bất định và phần còn thiếu."
}
```

Mỗi dispatch thực tế phải thêm: snapshot/commit hoặc source hashes đang review, inputs, signatures cần dùng, tiêu chí pass, output directory riêng, dependencies đã sẵn sàng và lý do chọn model. Chọn Luna, Terra hoặc Sol theo độ khó và effort phù hợp; không tái sử dụng nguyên ví dụ khi scope khác.

## 5. Review và tiêu chí hoàn thành

- Chính sách chọn model ở đây ưu tiên hơn nhãn Sol owner/reviewer trong kế hoạch cũ khi dispatch mới; giữ yêu cầu review độc lập, không sửa báo cáo model đã thực sự dùng trong lịch sử.
- Task nhỏ theo contract đóng: main đọc diff, xem assertion và output kiểm tra; không bắt tạo reviewer mới cho mọi file tài liệu.
- Các gate **P01, P04, P06, P07, P10** cần reviewer độc lập với model và effort theo độ khó trên snapshot ổn định. Reviewer khác implementer, không sửa đồng thời với writer. Phát hiện phải kèm path, tình huống gây lỗi, hậu quả và test/reproduction đề nghị.
- Main xác minh findings; không chấp nhận hay bác chỉ dựa vào kết luận của agent. Sửa lỗi thật và chạy test liên quan; chỉ mở rộng tests khi có rủi ro mới.
- Bàn giao task gồm: code đã nối vào đường chạy nào, tests/exit code, source/runtime profile, artifact, limitations. Unit pass không thay native runtime validation; số test cũ của hai repo không phải kết quả NeuSymNav.
- Không tự commit/push/publish nếu chưa có yêu cầu tương ứng. Khi người dùng đã cho phép commit, main điều phối checkpoint sau gate; subagent không tự commit chung workspace.

## 6. Checkpoint và xử lý blocker

`docs/implementation-status.md` là nguồn trạng thái hiện hành: task/state, owner, evidence path, command/exit code, quyết định, blocker, bước tiếp. Lưu log dài trong `runs/<run-id>/`, chỉ link từ status. Sau compact đọc lại AGENTS, hướng dẫn này và status, không chạy lại GPU/run đã hoàn tất.

Routine bug trong phạm vi được giao: tự chẩn đoán và sửa, giữ invariant. Nếu thiếu model/data/toolchain, ghi chính xác thứ thiếu và tiếp tục fixture/replay hoặc task độc lập. Chỉ hỏi người dùng khi phải đổi phạm vi/contract quan trọng, hạ tiêu chí đã chốt, sửa folder nguồn, tải lớn/training, hoặc phát sinh hành động ngoài quyền đã giao. Không tự nới TTL, sửa denominator hoặc đổi default để biến fail thành pass.

## 7. Prompt giao cho main ở phiên triển khai

Chỉ dùng prompt này khi người dùng quyết định bắt đầu thực thi; tài liệu hiện tại không kích hoạt nó.

```text
Triển khai pipeline NeuSymNav theo NeuSymNav/docs/architecture.md và
NeuSymNav/docs/implementation-plan.md. Đọc NeuSymNav/AGENTS.md,
docs/agent-orchestration.md và docs/implementation-status.md trước.

Main dùng model do tôi chọn trong công cụ. Tôi cho phép chủ động phân công Luna xhigh
cho việc bình thường, GPT-6.1 Terra cho việc khó hơn và GPT-6.1 Sol
chỉ khi thật sự cần theo điều kiện ngoại lệ, với effort theo task.
Astra được phép ở main session; chỉ cấm ở subagent do main tạo ra, kể cả reviewer/fallback. Không tự tạo agent con
ngoài điều phối của main. Chỉ sửa NeuSymNav; hai folder nguồn giữ nguyên.

Bắt đầu P00, làm theo dependency/gate tới P10 trong phạm vi core. Khóa các
contract trước khi song song. Tự xử lý lỗi implementation trong phạm vi;
không tự training, tải lớn, hạ gate hoặc bật các extension E1–E4.
Dùng tài sản/môi trường sẵn có cho smoke và benchmark hữu hạn theo kế hoạch;
nếu thiếu hãy báo cụ thể và tiếp tục phần độc lập. Cập nhật checkpoint cùng
lệnh, exit code, artifacts; phân biệt implemented/correctness/runtime.
Không tự commit, push hoặc publish. Báo các quyết định kỹ thuật khác tài liệu
trước khi đổi contract quan trọng. Không suy pipeline đã đạt từ test mock.
```
