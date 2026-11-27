# VLM chia subtask cho ObjectNav — nghiên cứu ngày 25/11/2026

## Kết luận và phạm vi

**Đáng thử dùng VLM chọn bước tái quan sát khi C thiếu bằng chứng.** VLM có thể dùng ảnh hiện tại, mục tiêu và lịch sử để đề xuất bước kế tiếp, rồi cập nhật sau khi có quan sát mới. Hiệu quả tăng SR/SPL trong NeuSymNav **chưa được đo**. Audit mới nhất cho thấy phần lớn ca lỗi đã tới gần đích, với các lỗi phổ biến ở bước VERIFY, mask hoặc depth, và xác minh danh tính.

Dữ liệu chính là snapshot và artifact của lượt DEV60 chạy ngày 25/11/2026.

## Bằng chứng từ nguồn sơ cấp

### WMNav: nguồn gần nhất với câu hỏi

[WMNav v4 §III-D](https://arxiv.org/html/2503.02247v4#S3.SS4) xét single-goal ObjectNav. PlanVLM nhận ảnh hướng đã chọn và subtask trước, sinh subtask mới cùng GoalFlag; ReasonVLM chọn hành động. Table II báo:

| Memory | SD tắt → bật | SR (%) | SPL (%) |
|---|---|---:|---:|
| None | a → b | 65,8 → 67,4 | 25,8 → 33,1 |
| CVM | d → e | 69,5 → 70,1 | 34,9 → 34,7 |

Đây là ablation SD trên HM3D v0.2; SD có lợi SR ở hai cặp, SPL phụ thuộc memory. [Table II, §IV-D](https://arxiv.org/html/2503.02247v4#S4.SS4).

Khả năng chuyển kết quả cần kiểm tra: WMNav dùng panorama sáu hướng, Gemini và action tọa độ cực, tối đa 40 bước. §III-E định nghĩa khoảng cách Euclidean; §IV-B ghi `d_thres=1.0` rồi mô tả thành công `<0.1m`, tạo bất nhất cần tác giả/code giải thích. [§III–IV](https://arxiv.org/html/2503.02247v4#S4.SS2).

**Suy luận cho NeuSymNav:** Có cơ sở thử subtask cập nhật theo quan sát và lịch sử. Các cặp số chưa chứng minh lợi ích của một planner thêm vào C hiện tại; chúng cũng chưa tách hiệu quả riêng của việc sinh câu subtask khỏi việc truyền GoalFlag và cấu hình prompt.

### InstructNav: phân công đúng LLM và mô hình thị giác

[InstructNav v1 §3.2](https://arxiv.org/html/2406.04882v1#S3.SS2) dùng **LLM** để cập nhật action và landmark của Dynamic Chain-of-Navigation theo instruction và objects đã quan sát. [§3.3.4](https://arxiv.org/html/2406.04882v1#S3.SS3.SSS4) dùng **GPT-4V** trên panorama để chọn hướng cho Intuition Value Map. Các value map được kết hợp rồi A* tạo đường (§3.4). Đây là hệ generic instruction navigation, có thí nghiệm ObjectNav cùng R2R-CE/DDN.

**Suy luận cho NeuSymNav:** Cơ chế phù hợp để tham khảo là lập lại bước kế tiếp từ bằng chứng mới, giữ landmark có grounding. Một yêu cầu ObjectNav chỉ cho category như `chair` vẫn cần suy luận nơi tìm và cách quan sát, nhưng không chứa sẵn chuỗi mệnh lệnh dài để phân rã. Nhận diện đúng vai trò từng mô hình giúp tránh quy toàn bộ kết quả hệ thống cho “VLM decomposition”.

### GOAT-Bench: ý nghĩa khác của nhiều subtask

[GOAT-Bench, Figure 1 và định nghĩa task](https://openaccess.thecvf.com/content/CVPR2024/papers/Khanna_GOAT-Bench_A_Benchmark_for_Multi-Modal_Lifelong_Navigation_CVPR_2024_paper.pdf) cung cấp **chuỗi mục tiêu** theo category, mô tả hoặc ảnh trong cùng môi trường; benchmark nghiên cứu cả bộ nhớ giữa các mục tiêu.

**Suy luận cho NeuSymNav:** Thành công theo chuỗi goal trong GOAT-Bench hỗ trợ nghiên cứu memory/lifelong navigation. Khi dùng bài đó làm dẫn chứng, phải ghi rõ chuỗi goal đến từ benchmark. Thử nghiệm hiện tại vẫn giữ một category goal và reset map/graph theo episode; những subtask được đề xuất ở đây là bước nội bộ để hoàn thành goal đó.

### Đối chứng hình học có giá trị thực nghiệm

[When Engineering Outruns Intelligence v2, §5–6](https://arxiv.org/html/2507.20021v2#S5) thay DCoN/Intuition bằng FPE hình học. Trên HM3D, Table 1 báo InstructNav-GT 60,6/33,8 SR/SPL, FPE 61,4/36,0 và SHF 61,2/36,2. Các lượt này dùng semantic GT, kể cả approach/stop; success 0,25 m và bước tiến 0,20 m. Đây là điều kiện nghiên cứu của tác giả. [Table 1 và semantic sensor](https://arxiv.org/html/2507.20021v2#S6).

**Suy luận cho NeuSymNav:** Kết quả đủ để yêu cầu đối chứng rules/geometry khi thử planner; không dùng các con số này làm dự báo SR của NeuSymNav. Semantic GT tiếp tục chỉ ở evaluator offline theo invariant của repo.

## NeuSymNav hiện có gì, còn thiếu gì?

C hiện có các bước khám phá, tiếp cận, xác minh và phục hồi. Trong thiết kế C/A/S, A xếp hạng frontier khả thi và S quyết định tiếp tục tìm trong vùng hay chuyển vùng. S tương ứng với quyết định cấp cao của SOR-Nav khi chưa có ứng viên đáng tin. CLOSER là nguồn gần với nhánh tái quan sát vì họ kiểm tra tác động của việc chủ động thu thêm view khi xác minh chưa đủ bằng chứng. [Thiết kế C](c-executive-design.md) · [Kế hoạch C/A/S](../superpowers/plans/2026-11-14-hierarchical-objectnav.md) · [SOR-Nav §III-C](https://arxiv.org/html/2609.34707v1) · [CLOSER Bảng IV](https://arxiv.org/html/2610.28476v1).

[DEV60 C full ngày 25/11](../../runs/objectnav/paper-c-last-mile/dev60-full/analysis/failures.md) chốt 60 UID, sáu scene, cap 500 action, scorer schema 3 với STOP khi geodesic DTG <0,1 m. [Status kết quả](../implementation-status.md#c-chọn-sớm-điểm-quan-sát-và-xác-minh-tại-pose-thực--2026-11-25) ghi SR 30/60, SPL 0,1943, OSR 53/60; B0 v2 đạt 37/60. Đây là **kết quả đã đo**, dùng để đặt giả thuyết:

| Nhóm lỗi trong 30 ca | Số ca | Giả thuyết cần kiểm với subtask |
|---|---:|---|
| Chưa vào vùng STOP | 7 | Lựa chọn hướng/ứng viên có thể có ích; cần tách khám phá, đường và theo đuổi sai |
| Đã vào vùng, thiếu VERIFY hợp lệ | 9 | Bước quan sát lại và trigger chuyển trạng thái có thể có ích |
| VERIFY trong vùng nhưng mọi lần trượt RGB-D | 10 | Cần giải thích mask/depth/pose; một planner chỉ đổi route chưa bảo đảm sửa được |
| Qua RGB-D, thiếu xác minh đúng vật | 4 | Cần audit bằng chứng ảnh và verdict trước khi quy cho planning |

Audit còn ghi 131 frame thuộc 14 episode có đích đủ pixel/depth theo tiêu chí offline nhưng runtime thiếu nhãn đích; 9 crop TV đúng instance đều bị `mismatch`. Hai STOP sai ngưỡng ở DTG 0,168/0,199 m. Đây là evidence về điểm nghẽn quan sát/xác minh. Audit chưa tách detector khỏi bộ lọc, hoặc crop/prompt/model khỏi nhau; không thể kết luận VLM planner sẽ sửa các điểm này. [Bảng và mô tả audit](../../runs/objectnav/paper-c-last-mile/dev60-full/analysis/failures.md).

## Đề xuất phép thử có giới hạn

### Câu hỏi và seam

**Giả thuyết.** Với cùng ảnh, danh sách pose khả thi và ngân sách, VLM có thể chọn cách quan sát lại giúp C thu bằng chứng nhanh hơn bộ chọn theo luật. Ở `qyAac8rV8Zk/2#5`, robot đã qua RGB-D tại DTG 0,034 m nhưng box sofa chạm mép ảnh nên crop không đủ điều kiện gửi Qwen. Một lựa chọn có thể kiểm chứng là ưu tiên góc nhìn cho thấy trọn phần ghế hơn trong ngân sách của lần tiếp cận. [Trace DEV60](../../runs/objectnav/paper-c-last-mile/dev60-full/trajectories.jsonl) · [audit mask](../../runs/objectnav/paper-c-last-mile/dev60-full/analysis/mask-audit.jsonl).

Đề xuất advisor chỉ trả một enum cùng ID có trong input: `select_frontier`, `select_candidate`, `reobserve_candidate`, `continue`, `abstain`. “Tới doorway rồi tìm chair” chỉ được thực thi qua frontier/đích có grounding đã quan sát và có đường hợp lệ. Host quản lý trạng thái subtask, completion/failure và CID aliases; mỗi decision chỉ có một subtask đang hoạt động.

Input đề xuất gồm category goal; ảnh nguồn có frame/pose/calibration; ID ứng viên/frontier, path cost hiện tại; bằng chứng còn thiếu; subtask trước và kết quả thực thi. Output phải gắn request/source revision, ID hợp lệ và lý do ngắn. Revalidate path cùng bằng chứng trước khi áp dụng. Timeout, ảnh cũ, ID không tồn tại hoặc thiếu grounding dẫn về lựa chọn rules. Advisor không được cấp canonical ID, phát STOP, thay nhãn room geometry hoặc tạo chứng nhận motion. C tiếp tục sở hữu VERIFY/STOP; planner hiện tại sở hữu đường đi.

### Các arm và ngân sách đề xuất

| Arm | Hành vi | Điều cần tách |
|---|---|---|
| C hiện tại | B0 v2 + C full đã khóa | Mốc thực thi hiện hành |
| C chọn theo luật | Host tạo các lựa chọn tái quan sát, luật chọn pose | Hiệu quả của danh sách pose và cơ chế thực thi |
| C chọn bằng VLM | Qwen chọn trong đúng danh sách của đối chứng theo luật | Phần đóng góp của Qwen vào việc chọn pose |

Bộ chọn theo luật dùng chất lượng hình học và chi phí đi/quay của các pose do C sinh. Qwen nhận cùng danh sách, ngân sách và chỉ mục ảnh. Hai lượt dùng cùng Qwen verifier, detector, giao thức, scorer và cap 500 action. Có thể thử xếp hạng frontier ở A khi muốn đo tác động lên khâu tìm kiếm.

Giới hạn nghiên cứu đề xuất để chốt trước implementation: tối đa 4 lựa chọn/request, 1 request in-flight, 8 decision/episode, 2 retry/candidate; thao tác quan sát tính trong cap 500 và budget C hiện có. Decision chỉ có hiệu lực ở boundary hợp lệ, chưa cho advisor ngắt một motion đang chạy. TTL/deadline sử dụng contract nguồn hiện có; không tự nới freshness để chờ VLM. Dùng async worker có fallback rules để control tiếp tục theo contract; phải đo cạnh tranh tài nguyên với Qwen verifier. Các con số trên là **đề xuất budget**, chưa là config đã được chấp thuận.

### Trình tự kiểm chứng và điều kiện tiếp tục

1. **Offline:** lấy decision context từ trace đã có, kiểm ID/source/path binding và lập bảng rules/VLM disagreement. Đánh giá giải thích có grounding, schema valid, abstention và số request; GT chỉ dùng evaluator. Trace replay không chứng minh tác động quỹ đạo hoặc SR.
2. **Correctness:** khi được giao triển khai, fixture phải bắt stale result, alias merge, path mất khả thi, budget hết, timeout/invalid và STOP chỉ do C cấp. Giữ source pins và action accounting ở mọi arm.
3. **Runtime.** Khóa snapshot, config, model, prompt và manifest. So hai bộ chọn trên cùng DEV60 theo từng UID. Đo số ca lấy lại và mất, bằng chứng mới thu được trước khi hết budget, SR, SPL, false STOP, action và p95 độ trễ. Mỗi lượt native/GPU dùng khóa chung.
4. **Quyết định.** Giữ bộ chọn Qwen nếu nó thu được bằng chứng tốt hơn trong cùng ngân sách và cải thiện kết quả so theo từng UID với chi phí đủ thấp. DEV60 phục vụ phát triển. Xác nhận trên TEST180 sau khi khóa lựa chọn.

## Trạng thái nghiên cứu và phần chưa chứng minh

- **Correctness-verified trong phạm vi nghiên cứu.** Đối chiếu số với nguồn sơ cấp và audit đã lưu. Kiểm link local và whitespace.
- **Phạm vi runtime.** Các số DEV60 và paper đến từ kết quả đã lưu. Chất lượng chọn pose, chi phí chạy và tác động lên SR/SPL của đề xuất còn chờ phép đo.
