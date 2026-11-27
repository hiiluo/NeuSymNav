# Khả năng gắn CLOSER vào Paper C

Đối chiếu ngày 25/11/2026. Có thể thử verifier của CLOSER ở đầu vào xác minh danh tính của C. Để chạy bản gốc cần checkpoint đã huấn luyện, hướng dẫn inference và phần cứng phù hợp. Tìm theo tiêu đề và arXiv ID trên GitHub, Hugging Face và trang tác giả chưa xác minh được repo chính thức, checkpoint hoặc giấy phép của các tài sản CLOSER. Trang arXiv công khai phương pháp và kết quả. [CLOSER v1](https://arxiv.org/abs/2610.28476v1)

## Thành phần và yêu cầu

| Thành phần | Cấu hình trong paper |
|---|---|
| Theo dõi ứng viên | Grounded-SAM, ByteTrack và SAM |
| Cache góc nhìn | CLIP ViT-L/14 để lọc trùng, tối đa bốn view |
| Xác minh từng view | Qwen2.5-VL-7B-Instruct tinh chỉnh LoRA, nhận ảnh và loại vật, trả xác suất yes/no/uncertain |
| Tổng hợp | MLP được huấn luyện trên xác suất từng view |
| Tiếp cận chủ động | Diffusion Transformer nhận mask và depth, đề xuất cụm tám waypoint |
| Đo verifier | 17,2 GB VRAM và 0,28 s/view ở batch 1 trên A100 40 GB |
| Giao thức | 500 action, ngưỡng thành công 1 m, kết quả rollout trung bình ba seed |

Việc gắn module vào host sử dụng các checkpoint đã huấn luyện sẵn. Theo §III–IV, LoRA, MLP và diffusion policy đều cần huấn luyện trước. Nếu nhận được đầy đủ weights và config, inference có thể dùng chúng trực tiếp. Chạy nguyên profile công bố cần phần cứng lớn hơn RTX 3060 Laptop 6 GiB đã ghi trong hồ sơ máy. Khả năng chạy bản lượng tử hóa hoặc CPU offload còn cần đo về độ trễ, bộ nhớ và chất lượng. [Phương pháp và Bảng IX](https://arxiv.org/html/2610.28476v1) · [Hồ sơ GPU hiện có](../implementation-status.md#live-gpu-demo--bounded-00861-smoke--2026-11-12)

### Tài sản cần xin

- **Thử verifier từng góc.** Cần LoRA hoặc weights đã merge của CLOSER, revision của base, tokenizer/processor, prompt, tiền xử lý ảnh, cách lấy xác suất ba nhãn, license và ví dụ inference. Base Qwen2.5-VL-7B-Instruct công khai với Apache-2.0. Model GGUF Qwen3-VL-2B của NeuSymNav có thể phục vụ đối chứng hiện tại. [Model card Qwen](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) · [Danh mục tài sản NeuSymNav](../local-assets.md)
- **Thử cache và tổng hợp.** Cần checkpoint MLP, thứ tự nhãn và view, cách padding và config CLIP tương ứng với perceiver. Cần ảnh có provenance của cùng vật thể qua nhiều góc để đánh giá.
- **Tái lập tiếp cận của CLOSER.** Cần thêm checkpoint diffusion, cấu hình encoder/sampler, convention depth/waypoint, phụ thuộc detection và tracking, cùng một ví dụ RGB-D/pose và kết quả kỳ vọng từ tác giả. [CLOSER §III-C–F](https://arxiv.org/html/2610.28476v1)

## Phép thử trong NeuSymNav

1. **Replay xác minh trước.** Chọn cùng các frame có TV thật, tranh/màn hình dễ nhầm, sofa/ghế bành và view thiếu bằng chứng. Audit DEV60 cũ ghi 9 crop TV đúng đích đều nhận mismatch. So output của verifier hiện hành với verifier nhận từ tác giả trên cùng frame, ghi rõ cách tạo crop hoặc dùng full frame. Nếu phải dựng lại ảnh Habitat từ pose, đối chiếu depth với log. Semantic GT chỉ thuộc evaluator. [Audit DEV60](../../runs/objectnav/paper-c-last-mile/dev60-full/analysis/failures.md)
2. **Nối verifier vào C nếu replay xác nhận lợi ích.** Điểm nối phù hợp nằm ở worker submit/poll. Dùng CID do CandidateMemory cấp và ràng buộc kết quả với timestamp, calibration, frame, mask và revision model. Cache cần phân theo CID và episode. VisualAdvice hiện trả verdict rời rạc còn MLP cần xác suất đã chuẩn hóa của từng ảnh. Khi đo hiệu quả phần xác minh, dùng cùng YOLOE, planner, 60 UID, cap 500 và scorer DTG <0,1 m. C cấp STOP sau khi kiểm danh tính và RGB-D mới tại pose thực. [C hiện hành](../../src/neusymnav/objectnav/paper/c.py) · [VisualAdvice](../../src/neusymnav/objectnav/b0/vlm.py)
3. **Đánh giá tiếp cận chủ động ở lượt riêng.** C đã có VVD và recovery theo pose. Một ablation dùng cùng verifier để đo giá trị tăng thêm của các waypoint do diffusion đề xuất. Waypoint qua kiểm tra đường đi, clearance và phép đổi hệ tọa độ trước khi sinh action. Fallback dừng ở cự ly gần của paper phải được đánh giá theo giao thức paper. [CLOSER §III-E–F](https://arxiv.org/html/2610.28476v1)

Kết quả nghiên cứu này đối chiếu tài liệu tác giả, code hiện hành và artifact đã lưu. Phần replay của verifier mới, khả năng chạy trên máy hiện tại và tác động lên SR/SPL còn chờ checkpoint và phép đo.
