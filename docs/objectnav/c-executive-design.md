# Thiết kế C cho thí nghiệm B0+C

> Hồ sơ lịch sử. Mã và tùy chọn chạy của C, A, S đã được gỡ khỏi checkout hiện tại.

C bổ sung lớp quản lý ứng viên và quyết định theo đuổi, xác minh, phục hồi và STOP
trên B0 dùng paper mode. So cặp với B0 DEV60 đã đạt SR 34/60 và SPL 0,2187. Đây là
thiết kế áp dụng trên `hiiluo-policy`. Runner paper chọn lớp C qua `--policy b0+c`.
Thêm `--vlm-config configs/room-label-vlm.cpu.local.json` để dùng Qwen3-VL.
Baseline mặc định vẫn chọn qua `--policy b0`.

## Nguồn đã rà soát

- **Paper ConsistNav v2.** §3.3–3.5 mô tả bộ nhớ ứng viên liên khung, giữ ứng viên
  khi còn đủ cơ sở theo đuổi, xác minh sau khi đến gần và phục hồi có ngân sách.
  §4.1 dùng BLIP-2 ITM, depth 0–5 m và success 0,2 m. Các số này thuộc stack và
  giao thức của tác giả. [Paper v2](https://arxiv.org/html/2605.09869v2#S3).
- **Repo mang tên ConsistNav.** API GitHub xác nhận nhánh public tại
  `a20e0c5bccff1eca5cfeb46f9c40fa91a6accf63` chứa README, ảnh và các file
  `.gitkeep`. Không có tag hay release tại thời điểm kiểm tra.
  [Cây file public](https://github.com/wanghaosen0813/ConsistNav-anonymous-release/tree/a20e0c5bccff1eca5cfeb46f9c40fa91a6accf63).
- **Mã tham khảo có thật.** Tài khoản tác giả công khai Navigation-Memory trong
  repo `2026nips-nav` tại `d09db0d3af3d147e891da4715eb69947576be272`. README mô
  tả cùng bài toán và bộ điều khiển FSE, xây trên ApexNav. Chưa có bằng chứng
  commit này tái tạo đúng bảng trong ConsistNav v2. Repo có GPL-3.0, nên thiết kế
  dưới đây chỉ vận dụng ý tưởng bằng mã có sẵn của NeuSymNav.
  [README](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/README.md),
  [LICENSE](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/LICENSE).

| Cơ chế đã đọc trong Navigation-Memory | Cách áp dụng vào C |
|---|---|
| `updateObjectMemory` ghép theo tâm XY gần nhất, làm mượt vị trí, cộng quan sát thuận/nghịch. `computeCandidatePriority` trừ điểm khi cũ hoặc đã thất bại. | Dùng `CandidateMemory` với đối chiếu support RGB-D của cùng vật, alias chính thức và nguồn ảnh riêng biệt. Không gộp hai vật cạnh nhau chỉ do tâm gần. Quan sát lặp cùng nguồn hoặc do đứng yên không tăng số góc nhìn. |
| `executeSuspectState` giữ một ứng viên và chuyển sang APPROACH khi có xác nhận mới hoặc vẫn đứng đầu đủ lâu. Failover lưu cooldown và phạt subgoal đã thử. | Cho cue yếu có depth cơ hội quan sát thêm ở vị trí đi tới được. Giữ một CID khi đang tiến gần. Phân biệt bị khuất, nhãn cạnh tranh và đường bị chặn. Cooldown giữ lý do, vị trí thất bại và chỉ mở lại khi có ảnh mới đủ giá trị hoặc đường khả thi khác. |
| `executeVerifyState` mở cửa sổ đếm hỗ trợ mới, theo dõi khoảng cách và tích lũy ITM. Nhánh cuối có thể tiếp tục docking, phục hồi hoặc dừng. | Dùng ảnh của đúng ứng viên tại pose gần đích và kiểm khoảng cách trên depth hiện tại. Qwen3-VL là phần xác minh bổ sung của NeuSymNav. Không dùng score toàn cảnh hoặc lặp verdict cũ làm bằng chứng cho object khác. |

[Mã nhớ ứng viên](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/src/planner/exploration_manager/src/exploration_fsm.cpp#L756-L811),
[xếp ứng viên](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/src/planner/exploration_manager/src/exploration_fsm.cpp#L889-L903),
[SUSPECT](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/src/planner/exploration_manager/src/exploration_fsm.cpp#L1984-L2045),
[VERIFY](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/src/planner/exploration_manager/src/exploration_fsm.cpp#L2211-L2258).

Hai sai khác của mã tham khảo ảnh hưởng đến phép so sánh. ITM hiện được nhận qua
callback scalar và được đọc lại trong cập nhật ứng viên hoặc cửa sổ VERIFY. Khi
áp dụng vào C, mỗi phản hồi model phải gắn với UID, CID, nguồn ảnh, crop và pose.
Bộ đánh giá trong snapshot tham khảo cũng có nhánh nâng Habitat success=0 thành
success=1 khi nhận cờ `verified_stop` của planner. NeuSymNav giữ bộ chấm schema 3,
chỉ tính success bằng STOP thật và geodesic DTG cuối < 0,1 m. Đọc mã này
không đủ để kết luận tác giả đã dùng nhánh override cho số liệu trong paper.
[Callback ITM](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/src/planner/exploration_manager/src/exploration_fsm.cpp#L3388-L3391),
[Nhánh chấm điểm](https://github.com/wanghaosen0813/2026nips-nav/blob/d09db0d3af3d147e891da4715eb69947576be272/habitat_evaluation.py#L1004-L1027).

## Thiết kế cho paper mode

Tích hợp C qua lựa chọn tường minh trên entrypoint paper. B0 mặc định đi qua code
cũ. Dùng chung YOLOE, map, frontier hình học, `PaperNav`, navmesh, camera,
manifest, giới hạn 500 hành động và scorer. C giữ nguyên ranking frontier trong
SEARCH. Các quyết định đi tới vật và góc nhìn xác minh có thể đổi theo ứng viên.
C không lấy vị trí hay nhãn GT từ evaluator. A, S và room graph không tham gia
phép thử đầu tiên.

1. **Ghi nhận và giữ ứng viên.** Dùng cùng detector và mapping. Tách bằng chứng
   3D của vật khỏi quyết định đã xác nhận. Cho ứng viên có depth và điểm còn
   dưới ngưỡng xác nhận vào SUSPECT để lấy tối đa một góc nhìn bổ sung có đường
   đi. Phản hồi VLM hoặc một detection yếu có thể mở việc kiểm tra tiếp, còn
   chuyển sang theo đuổi và STOP có các cổng riêng. Sau khi chọn CID, mất dấu
   ngắn lúc còn tiến triển không đồng nghĩa với sai nhãn. Theo dõi tiến triển
   theo pose và action đã thực thi, rồi thử tối đa một viewpoint khác trong
   lần theo đuổi trước khi cooldown. Chặn lặp lại cùng pose hoặc subgoal thất bại.
2. **Xác minh tại điểm đứng.** Tái sử dụng ý tưởng `verify_target` và logic alias
   của lockstep, đưa phần kiểm nguồn bằng chứng về API dùng chung khi phù hợp.
   Điều kiện riêng của paper dùng ảnh RGB-D của chính episode, sau khi đã
   đến/hướng về vật, với pose hiện tại và support 3D khớp CID. Không áp dụng
   ngưỡng 10° của FACE lockstep cho góc quay 30° của paper. Giữ điều kiện
   geometry bằng khoảng cách đo mới đến vật và ghi rõ nó là heuristic runtime,
   khác với DTG tới viewpoint dùng ở scorer. Một lần nhìn lại có giới hạn;
   nếu thiếu bằng chứng thì phục hồi hoặc tiếp tục khám phá. Khi hết frontier,
   tách lý do kết thúc tìm kiếm khỏi target STOP để scorer không nhận nhầm.
   Ở near STOP, cổng khoảng cách từ bản đồ tích lũy của C là 0,50 m, gồm ngưỡng
   nền 0,40 m và dung sai 0,10 m. Điểm 3D cùng CID
   trong ảnh mới phải nằm trong dải camera có thể đo, tới 0,75 m với depth
   tối thiểu 0,5 m cộng một bước 0,25 m. Cổng 0,50 m áp dụng riêng cho pose
   của robot với support tích lũy. Quy tắc scorer DTG < 0,1 m giữ nguyên.
   Khi thiếu nhãn cuối, C dùng tối thiểu hai góc dương tính của cùng CID trong
   tám frame gần nhất. C chiếu lại điểm 3D từ chính các detection đã xác nhận,
   đối chiếu depth còn hợp lệ ở frame hiện tại và bỏ pixel có detection cạnh
   tranh. Cần sai số depth tối đa 6,5 cm, ít nhất 12 pixel khớp, ít nhất 25%
   số pixel đo được và độ phủ tối thiểu bốn ô voxel 5 cm. Nếu chưa đủ, C thử
   một góc trái và một góc phải bằng action quay thật.
   `arrived_far` xét một đích gần hơn có đường đi trên map, tối đa tám action
   trước khi xác minh lại ở pose thực tế.
3. **Qwen3-VL theo ứng viên.** Dùng recipe local đã ghim và crop theo mask.
   Gửi tối đa một yêu cầu đang xử lý. Ưu tiên trường hợp sofa/ghế bành và cue
   dưới ngưỡng có support depth, gửi sớm khi đủ ảnh thay vì đợi cổng STOP.
   Với sofa, hỏi loại đồ nội thất trực tiếp (`sofa`, `armchair` hoặc `unclear`).
   Hoãn query nếu khung cắt mất biên ngang của ghế. Kiểm lại overlap voxel
   của ứng viên trước khi dùng verdict đã lưu.
   Có thể dùng verdict còn hiệu lực làm bằng chứng phân loại. Trước khi STOP,
   vẫn kiểm pose, ID và bằng chứng RGB-D mới tại chỗ đứng. Với vật đã được
   xác nhận qua nhiều góc, verdict `match` có thể bổ sung phần phân loại khi
   detection hiện tại yếu. Frame hiện tại vẫn phải cho thấy cùng vật, có depth,
   và không có nhãn cạnh tranh chiếm ưu thế trên cùng support. `mismatch` chỉ loại
   hoặc hạ ưu tiên đúng CID. `uncertain` và timeout cho phép nhìn lại nếu còn
   ngân sách. Nếu đường C yêu cầu VLM xác minh, thiếu `match` hợp lệ không cấp
   quyền STOP; các ca không yêu cầu VLM đi qua cổng RGB-D riêng.
   C lưu ngắn hạn crop rõ và hình học của detection đã tạo crop. Khi gửi
   hoặc dùng lại ảnh, kiểm tra đúng CID, nguồn, pose và overlap với geometry
   hiện tại. Ở bước xác minh cuối khi đã có RGB-D đủ và chỉ còn thiếu Qwen,
   C chờ tối đa 2 giây trên pose đó, tối đa một lần mỗi attempt và ba lần mỗi
   episode. Thời gian này được ghi trong trace và không gửi action tới Habitat.
   Launcher làm nóng Qwen trước rollout và ghi chi phí riêng vào
   `vlm-warmup.json`. Khi Qwen chưa phản hồi đúng hạn tại pose xác minh,
   policy tiếp tục theo luật phục hồi và ngân sách hiện hành.
   Khi ứng viên TV cần xác minh thêm, prompt đánh dấu vật rồi phân loại màn
   hình điện tử, tranh, vật khác hoặc chưa rõ. Ứng viên TV đủ bằng chứng RGB-D
   vẫn đi qua cổng xác minh hiện có. Với sofa ở nhánh dùng depth chiếu lại, C cần xác nhận từ hai
   góc khác nhau. Ít nhất một crop phải gắn đúng frame và detection đã tạo
   anchor RGB-D, có thể dùng một lượt query dành riêng cho bước này. Nếu query
   cho anchor vẫn đang xử lý sau lượt chờ, robot quan sát thêm một góc và quay
   về hướng xác minh, tối đa hai action quay cho mỗi attempt. C kiểm tra lại
   depth và nguồn bằng chứng ở frame mới trước khi STOP. Các ca sofa có
   detection hiện tại theo cổng chuẩn vẫn dùng một verdict hợp lệ.
   Khi phục hồi sau thiếu bằng chứng, C xóa lịch sử kẹt của đích trước rồi thử
   đích tiếp cận hiện có. Nếu bộ lập đường không có action hợp lệ, C thử quay
   lại một pose quan sát gần đã thấy đúng CID và còn đường đi. C dùng cùng
   ngân sách phục hồi và xác minh lại từ ảnh RGB-D mới khi tới pose đó.
4. **Đếm action theo paper.** Dùng step, pose và tiến triển thay các TTL/cutoff
   theo giây của lockstep. Runner paper hiện phải nhận một action hợp lệ
   mỗi lần gọi policy. Gửi VLM bất đồng bộ và poll trong các bước tiếp cận
   hoặc quan sát hợp lệ. Không thêm action giả “đứng chờ”, quay vô nghĩa
   để đốt ngân sách, hoặc trộn thời gian tường vào số bước. Ghi riêng timeout
   worker, số bước quan sát và số verdict hữu ích. Vì model bất đồng bộ có
   thể trả ở bước khác nhau giữa các lần chạy, log step gửi/nhận và kiểm đi
   kiểm lại decision trên replay có lịch trả cố định.

**Phạm vi kỳ vọng.** 5 STOP nhầm sofa là nhóm để đo khả năng xác minh. 4 ca
hết bước có detection khớp vật thật nhưng không xác nhận đúng ứng viên là nhóm
để đo SUSPECT/commitment. 5 ca cây có ảnh thấy đích mà log không có nhãn
`plant` cần thí nghiệm riêng về tạo ứng viên. Ví dụ có thể cho detector tạo
proposal yếu từ một bộ nhãn đã định trước, rồi xác minh bằng VLM. Thêm proposal
là một thay đổi perception và cần so riêng. Không quy mọi ca dừng xa cho
bước tiến cuối. Phân tích hình học chỉ tìm được một ca rời vùng success ở bước
tiến cuối, nên giữ `early_stop` ngoài lượt C đầu.
[Bằng chứng DEV60](../../runs/objectnav/b0-dev60/analysis/failure-analysis.json).

## Xác minh khi đang tiếp cận

C kiểm tra RGB-D trước hành động kế tiếp trong APPROACH, FACE và FINAL_APPROACH
khi footprint đã vào ngưỡng near (0,50 m với config hiện tại). Mọi nhánh STOP
dùng chung phép kiểm hình học và nhận dạng. Khoảng cách bề mặt mới tối đa là
0,75 m ở near. Pixel phải thuộc frame hiện tại, từ detection cùng CID hoặc
từ đối chiếu depth với bề mặt đã quan sát. Ứng viên có bằng chứng mâu thuẫn
vẫn qua các quy tắc bác bỏ. Việc kiểm khi đang đi dùng ngưỡng near ngay cả
khi robot đang tìm đường từ một vị trí far.

Trong VERIFY, khi mất bề mặt, C quay về hướng bề mặt đã đo gần nhất và có
thể cúi/ngước một nấc. Khi có depth nhưng còn xa, C chỉ tiến nếu điểm đo có
thể vào ngưỡng sau một bước, mảng bề mặt dự kiến còn trong ảnh và khoảng đo
camera, và PaperNav cho phép tiến. Mỗi lần chỉnh đòi hỏi đo lại. Các hành động
này dùng chung ngân sách bốn bước quan sát. Khi trở lại EXPLORE, C đưa camera
về ngang. Trajectory ghi pha phát hiện bằng chứng trong `c.verify_checks[].phase`.

Sau match sofa đầu tiên, C có thể gửi ảnh độc lập thứ hai ngay trong APPROACH.
Lượt gửi thứ ba được dành cho detection liên quan lúc VERIFY. Khi dùng bề mặt
nhớ lại cho sofa, hai match phải hợp lệ cho cùng CID. Nếu ảnh đã ra khỏi tập
anchor tám bước, C còn có thể đối chiếu **đúng bề mặt của detection đã hỏi**
với depth và mask loại trừ hiện tại. Tuổi, pose, nguồn ảnh, mâu thuẫn và voxel
của ứng viên vẫn giới hạn việc dùng câu trả lời Qwen.

## VVD cho đoạn tiếp cận cuối

`--policy b0+c --c-vvd` bật chọn viewpoint trong RECOVER sau lỗi mất
RGB-D, mất dấu mục tiêu hoặc quá ngân sách FACE. C giữ đường trực tiếp khi
đang APPROACH và FINAL_APPROACH. Khi cần tìm lại góc nhìn, C xét tối đa mười
ô có đường đi và các hướng quay rời rạc của robot. Xếp hạng dùng phần bề mặt
cùng CID đã đo được, khoảng cách VERIFY near, frustum camera, bằng chứng tia
nhìn từ tối đa bốn frame và chi phí đường đi/quay. Phần chưa quan sát đóng góp
0. Budget phục hồi là tám action. Tại ô đã chọn, robot quay về heading dự kiến
và đo lại bằng RGB-D. Dữ liệu chẩn đoán nằm ở `diagnostics.policy.vvd`.
[Đối chiếu với MSGNav](msgnav-vvd-audit.md).

## Duy trì bằng chứng và tìm ứng viên tiếp theo

Một mask chair có điểm thấp vẫn có thể cung cấp depth cho CID đã được
xác nhận khi nó chiếu khớp bề mặt từ ít nhất hai góc nhìn trước đó. C tìm
bằng chứng liên quan trong tối đa 16 frame, loại nguồn trước hoặc cùng
thời điểm mâu thuẫn và chỉ đo pixel nằm trong mask chair hiện tại. Khi
CandidateMemory hợp nhất hai CID, bề mặt có nguồn còn nằm trong bằng chứng
của CID chuẩn được giữ lại. Kết quả Qwen được đối chiếu lại theo CID của ảnh
đã hỏi. Trace VERIFY ghi lý do bỏ kết quả Qwen theo phạm vi nguồn, pose,
mâu thuẫn hoặc thay đổi bề mặt.

Khi một CID chair nhận nhãn mâu thuẫn, hai góc nhìn detector độc lập
sau mâu thuẫn mới cho phép kiểm STOP trở lại. Prompt Qwen phân loại trực
tiếp chair, display, other hoặc unclear. Nếu phát hiện một ứng viên
chair khác đủ điểm và trong tầm tiếp cận, C có thể rời CID đang mâu thuẫn.

RECOVER lưu lý do VVD thiếu bề mặt hoặc pose phù hợp. Xếp hạng xét ngân sách
đi, quay và action STOP còn lại. Khi đường tới pose VVD bị chặn, C có thể
quay về đường trực tiếp nếu ước tính còn đủ bước. C giữ các pose RGB-D gần
đây có quan sát bề mặt của ứng viên để bộ xếp hạng có thể dùng chúng sau khi
mất dấu trong đoạn tiếp cận cuối.

Ứng viên bị Qwen bác chỉ được xem lại khi hai góc nhìn mới đủ mạnh và có
detection hiện tại. C yêu cầu một xác minh Qwen mới cho lần thử lại. Ở
khoảng cách tương đương, ứng viên mới có detection hiện tại được ưu tiên.

Với mục tiêu plant, detector có thể dùng label vase từ 0,35 trở lên để tạo
đề xuất. Đề xuất giữ raw label và nguồn ảnh riêng, không được tính vào lượt
xác nhận trực tiếp của detector. Đường STOP qua đề xuất cần hai góc nhìn
RGB-D, Qwen phân biệt cây với bình rỗng và depth mới khớp bề mặt của
detection đã gửi. Khi đang khám phá, C có thể cúi camera 30° ở tối đa tám
vị trí cách nhau ít nhất 1,5 m và cách ít nhất 16 action. [Đo detector
trên tập DEV](phase2-detector-results.md).

## Chuyển ứng viên chair và quan sát theo mục tiêu

Trong khi theo một CID chair có bằng chứng mâu thuẫn, C chỉ xếp hạng
ứng viên thay thế có mask cùng loại đạt ngưỡng trên frame hiện tại và
bề mặt đã đo nằm trong 2,25 m. C chuyển thẳng sang CID được chọn. Mỗi
lần thử có tối đa năm action, tối đa hai lần trong một episode. Nếu
trong thời hạn này bộ nhớ ghi nhận hai góc nhìn đủ mạnh sau lúc chuyển
và mâu thuẫn đã được giải quyết, robot tiếp tục APPROACH thông thường.
Mọi STOP vẫn phải qua VERIFY. CandidateMemory xét độ phủ voxel khi
một mask chair khớp nhiều CID. Nó chỉ gán mask vào CID khớp vượt trội
và giữ quy tắc một detection khác nhau trên cùng CID trong cùng frame.

Với TV và plant, C xét tối đa sáu frontier có đường đi theo PaperNav.
Điểm ưu tiên kết hợp độ phủ vùng chưa quan sát theo hướng nhìn, chi phí
đi/quay và tín hiệu mục tiêu mới. Điểm TV có thêm trọng số theo bề mặt
chắn nhìn. Plant có thêm lựa chọn cúi camera một nấc. Chiếu tia dừng ở
ô vật cản. Vùng chưa quan sát được xét như thông tin có thể thu được.
PaperNav tiếp tục xác định các ô có thể di chuyển tới. Khi tới frontier
hoặc hết frontier, C có thể quan sát lại tại chỗ với tối đa hai bước
quay và một nhịp cúi/trả camera. C ghi vị trí, hướng và pitch của các
frame đã đo và giới hạn 20 action quan sát bổ sung.

Khi camera cúi hoặc ngước, frame giữ mã hiệu chuẩn đo tại pose đó.
Để nối các pose thuộc cùng rig, C bỏ góc pitch theo command và so
intrinsics, hướng và vị trí lắp camera với rig đầu episode. Một frame
có thay đổi ngoài góc pitch rời rạc của giao thức bị loại. Depth và
mask luôn được chiếu theo extrinsics của chính frame.

Trajectory ghi lần chuyển ứng viên, số bước scan và bước đầu tiên có
detector dự đoán nhãn mục tiêu. Audit offline đối chiếu bước đầu tiên
thấy đối tượng thật và mask dùng để STOP với dữ liệu semantic.

## Mốc ablation B0

B0 chính thức dùng `configs/objectnav/paper-b0-v1.json`. Khi đo đóng góp
của C, chọn cùng cấu hình B0, detector, protocol và manifest cho cả hai
arm. Arm B0+C bật policy C cùng các tùy chọn của C đã khóa cho lượt đo.
Một bước phát hiện bổ sung chỉ chạy ở arm có C cần được ghi nhận là
thành phần của C trong cấu hình và báo cáo.

## Thí nghiệm nền dùng chung Paper B0 v2

Trong thí nghiệm này, cả hai arm nhận cùng `--policy-config configs/objectnav/paper-b0-v2.json`.
Trong episode plant, YOLOE dùng vocabulary plant bổ sung potted plant,
houseplant và flowers in a vase. Checkpoint và encoder giữ nguyên. Detector
chỉ dùng một vocabulary cho mỗi episode. Nhãn vase chung không ánh xạ
thành plant. Runner pin cả hai recipe và C lấy SHA-256 recipe/vocabulary
đúng với episode khi ghi nguồn detection.

B0 chọn ô tiếp cận từ thành phần thực sự tới được theo PaperNav, cùng
điều kiện mà C dùng. Bước tiến thăm dò cần qua kiểm tra traversable.
C bổ sung một lần chờ ngắn cho query sofa độc lập thứ hai ngay tại
VERIFY, trong ngân sách chờ toàn episode. C xếp crop sofa thứ hai theo
điểm detector và bề rộng phần ghế trong ảnh. Với sofa hoặc toilet hết
frontier, C có thể lấy thêm hướng nhìn mới trong ngân sách scan hiện có.

Với plant trên nền v2, C kiểm lại RGB-D khi footprint đã vào vùng giữa
ngưỡng near và `depth_min + forward_step / 2`. Cần hai góc nhìn detector
độc lập gần đây. Nếu chưa có depth phù hợp, C dùng tối đa hai action
quay hoặc ngước/cúi tại chỗ để lấy phép đo mới trước khi đi tiếp.
Điều kiện về RGB-D hiện tại và ngưỡng thành công offline vẫn áp dụng.

Lượt plant v2 đo tác động của C trên cấu hình thử v2. Nhánh kiểm plant
sát vùng cắt depth được bật khi cấu hình có taxonomy plant riêng.
Kết quả v2 được lưu trong thư mục `runs/objectnav/paper-shared-upgrade/`.

## Kiểm tra trước khi mở B0+C

Lượt tiếp cận có xác minh dùng mặc định `--c-last-mile full` với
`--policy b0+c`. `--c-last-mile off` dùng hành vi cũ với bộ ngưỡng hiện
tại, còn `--c-last-mile viewpoint` bật riêng việc chọn một điểm quan sát
dọc tuyến. Preflight và khóa run ghi `c_last_mile` để đối chiếu đúng arm.
Với `--c-vvd`, recovery tiếp tục dùng bộ xếp hạng điểm đứng lân cận.

Khi ứng viên đã xác nhận còn trong ảnh, C lấy mẫu các ô dọc đường
`PaperNav`. Xếp hạng dùng frustum, độ sâu, các tia có bằng chứng từ RGB-D
và chi phí đi hoặc quay. Điểm đã chọn gắn với CID. C quay về hướng dự kiến
và có thể chỉnh pitch một lần ở điểm đến. Attempt dành tối đa tám action
cho nhánh này và chừa một action cho STOP.

Ở chế độ `full`, C thử quan sát tại chỗ khi ứng viên đã xác nhận tạm mất
mask ngay gần vật. C đo lại tại pose đang đứng trước khi rời đi trong
`RECOVER`. Qwen xác minh cả sofa và TV khi được cấu hình. Nếu Qwen còn chờ
tại pose đạt RGB-D, C cho thêm tối đa 0,35 giây một lần trong attempt,
tính trong ngân sách chờ của episode. Khi có mâu thuẫn, ảnh trước mâu
thuẫn hết tư cách xác nhận. Query dự phòng dùng ảnh mới của đúng vật.
Trace `c.observation_views` ghi việc chọn pose. `c.verify_checks` ghi
khoảng cách, độ mới, occlusion, pixel khớp và sai số depth khi chiếu lại.
[Cơ sở thiết kế và cách chấm](c-last-mile-research.md).

- Kiểm parity B0 khi C tắt. Kiểm bốn nhóm fixture gồm sofa cạnh ghế bành,
  ứng viên đúng bị khuất rồi xuất hiện, mất đường rồi tìm được góc khác,
  và ảnh đến muộn/sai CID/sai pose. Kiểm luôn một trường hợp đúng phải STOP
  và một trường hợp timeout không được STOP. Replay để xác nhận mỗi lần
  quan sát, phục hồi và kết thúc đều giữ đúng cách đếm action paper.
- Chạy một smoke giới hạn khi triển khai xong để xác nhận đường đi thật
  qua runner paper và có trace bằng chứng cho STOP. Mức nhận ảnh/veto của
  Qwen cần kiểm trên ảnh B0, vì detection log hiện chỉ lưu pose, mask và
  mẫu depth. Nếu cần dựng lại RGB, dùng cảnh BASIS và góc nhìn gốc, chỉ
  dùng nhãn semantic offline để chấm.
- Khóa config C và manifest trước khi chạy DEV60. So từng UID với mốc
  B0 34/60, SPL 0,2187, báo cả ca cứu được và ca mất thành công. Theo dõi
  riêng số STOP nhầm, số ứng viên đúng được xác nhận, số ca từng đạt ngưỡng
  nhưng rời đi, và ngân sách retry/VLM. Giữ bước kiểm chứng hold-out riêng.
- Về sau có thể bật/tắt Qwen trên cùng C để đo giá trị riêng của VLM.
  Kết quả `B0+C` với Qwen bật đo hiệu quả cả lớp C dùng Qwen.

Lệnh preflight cho cấu hình thử nghiệm đầy đủ.

```bash
.venv/bin/python tools/objectnav/run_paper_episodes.py --preflight \
  --policy 'b0+c' --vlm-config configs/room-label-vlm.cpu.local.json \
  --manifest configs/objectnav/splits/hm3d_v2-val-dev.json
```

Snapshot DEV60 và launcher nằm ở `runs/objectnav/b0-c-dev60/`. Launcher kiểm
SHA-256, dùng khóa native chung, tiếp tục theo UID đã hoàn tất, chấm schema 3
và xuất đối chiếu cặp với B0 trong `comparison.json` sau khi đủ 60 ca.
