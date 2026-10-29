# P10 — quyết định contract adapter chuyển động mặt phẳng

State: **A được người dùng chọn rõ ràng ngày2026-10-28; đang triển khai, chưa correctness/native-validated**. Đây là lựa chọn mô hình simulator có ảnh hưởng contract, không phải sửa tolerance số học. Main giữ nguyên source hiện hành và mọi run cũ.

## Evidence hiện có

- Source hiện hành đã qua1161CPU/fault/package/nativeDuDe/sourcehash gates; independent pair/retry review ACCEPT. Scene00861 runtime9 thực hiện frontier1.036866531m/60s, raw834/834/event13/RSS513/513/GPU61/61/cleanupcomplete; chưa membership. Không phải frozen campaign.
- Scene00802 runtime9 completed/clean/raw1144/event4/RSS577/577/GPU61/61 nhưng532forwardpulses requested2.54136m/actual0. `runs/p10-native-preparation/collision-filter-00802/report.json` giữ native step_filter candidate đúngXZ nhưng đổiY từ.123999998 xuống.110607646. Strict3Dsegmentresidual1e-7 chặn đúng contract hiện hành. Đây là vertical navmesh projection discrepancy; chưa chứng minh là mặt sàn vật lý.
- Kiểm25spawn lân cận00802 theo thứ tự cố định:0đạt localstrict3Dcontact. Existing00337 fixed25grid:2đạtcontact; RGB-Dbootstrap ởcả2khôngđạt fullfootprint (candidate0 gần khungcửa, candidate11 88/100), tăngres/giảthuyếttrầnkhôngsửađược nên giữblocked. Existing00770 fixed25grid:0đạtcontact. Các probe không detector/navigationtrajectory, không chọn theo performance/membership; không cócampaign2sceneđượcfreeze.
- `runs/p10-native-preparation/planar-actuation-design/design-audit.md` phân tíchA/B/C. Near-ground tolerance.05 của mapper **không tự cho phép** correctionY trongactuator. Currentstrict3Dfilter vẫn giữ nguyên.

## Hai hướng để người dùng quyết định

### A — adapter simulator mặt phẳng có opt-in

Thêm mode được version/pin `planar_fixed_y_v1`; default `strict_3d` giữ nguyên. Đây là simulator robot2D có độcao root cố định, không chứng minh contact/grounding hoặc leo bậc/địa hình3D.

- AnchorY lấy đúng `initial_position[1]` đã pin. Mọi start/end/currentbody phải giữ cùnganchor trong1e-7; parent/body tilt hoặc thayđổiheight không xác minh thì chặn.
- Native collision filter vẫn phải chạy. Candidate hữu hạn; horizontalXZ phải nằm chính xác trên đoạn issued vớifraction[0,1] vàresidual1e-7 như trước; không cho sidewaysslide/overshoot.
- Native candidateY chỉ được khác fixedanchor tối đa.05m, là **giới hạn mới explicit của adapter này**, không mượn mappernear-ground làm quyền ngầm. So với fixedanchor suốt episode, không cộng dồn mỗi bước để leo dốc/cầu thang. Vượtbound thì chặn.
- Return chỉXZ đã kiểm, giữY=anchor trướcactuation; không set_state sau bước, không sửa actualproof/pose. Candidate/nativeY không được seed map/free/region.
- MotionGuard vẫn yêu cầu RGB-Ddepth/floor/clearance thực, robotradius.2/height1.5/margin.05, TTL300ms/horizon100ms/v≤.2/yaw≤30deg/s. Proofv1/epsilon/sign/actualXY đo thực không đổi.
- Effectiveconfig, workerhash/ACKbinding, attempt/campaignrecipe/limitations phải ghi mode/anchor/bound. Không dùng các run này tuyên bố grounding/terrain3D hoặc superiority với strict3D.

Validation trước native: RED→GREEN strictdefaultunchanged; exactXY/height/NaN/tilt/parent/stairdrop/anchor-drift rejections; actualproof/oneusesource/TTL tests; độc lậpSolHighreview trênsnapshot; fullCPU/fault/package/sourcehash; bounded5mmnativeprobe rồicalibration/smoke. Campaign2scene×2seed≤300s chỉfreeze sau đó. Đây không bảo đảm sẽ cómembership hoặcquaP10.

### B — giữ strict3D, chốt giới hạn pilot

Không thêmadapter, khôngnới contract. Core software hiện hành tiếp tụcđượcgiữ; P10native2scene vẫn **incomplete/insufficientdemonstration** vì hiện mới1sceneđạt usefultranslation. Có thể hoàn tất tài liệu/evidence và ghi chínhxáclimitation, nhưng không tuyênbốP10đạt. Không tải thêmscene/model hoặc thayđổiOS để tìm cáchvượtgate.

## Vì sao cần quyết định của người dùng

AGENTS.md dẫn tới `docs/agent-orchestration.md`, mục6: chỉ hỏi khi phải đổi phạmvi/contractquantrọng hoặc hạtiêuchí. A thay cách adapter dùng chiềuY của nativecollisionfilter nên main coi là thay contractquantrọng; independentreview đã chỉra khôngđượcgọi đó là giữ nguyên nativecontactsemantics. Người dùng đã trả lời chọnA sau khi đọc lựa chọn. Triển khaiModeA được phép trongscopeđãnêu; vẫn cần frozenreview/tests/nativevalidation, không tựsuyP10pass. Tài liệu này là phương án cụ thể để review, không phải xinlại quyền cho các task gộp thông thường đã được giao.
