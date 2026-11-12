# Đánh dấu reference rooms cho00806/00807

Mở ảnh gốc, giữ trục XY/lưới và kích thước nếu có thể:

- [00806 observed map](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/recordings/00806/annotation-map.png) và [RGB contact sheet](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/recordings/00806/review-contact-sheet.png).
- [00807 observed map](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/recordings/00807/annotation-map.png) và [RGB contact sheet](/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2/runs/hydra-objectnav/B1-multiscene-20261107/recordings/00807/review-contact-sheet.png).

Khoanh phần lòng phòng mà bạn chắc chắn:00806 dùng hai màu cho hai vùng hai phía lối nối, đỏ cho opening-range. Nếu lối giữa là một hành lang riêng, có thể khoanh màu thứ ba hoặc để unknown.00807 khoanh vùng open footprint bạn coi là cùng một phòng; bỏ các opening/phòng kế bên nếu chưa chắc. Không cần suy đoán phần chưa nhìn thấy hoặc tô kín mọi vùng; phần không đánh dấu là unknown.

TênA/B/C đủ cho geometry; chưa cần nhãn loại phòng. Dùng bản đồ không có predicted room colors để tránh chép ranh giới thuật toán. Đường đỏ là reference opening, không phải occupancy wall. Gửi lại ảnh đã đánh dấu hoặc polygon XY (m); evaluator chạyoffline, không bơm reference vào runtime.

Numbers màu vàng là selected-camera sample indices; mỗi selected frame lấy đều từ capture rồi thêm frame cuối. Registration JSON cạnh PNG giữ exact world bounds/pixel bounds/hash. Các reference này sẽ là partial positive cores có uncertainty margin, không tuyên bố full-roomGT.
