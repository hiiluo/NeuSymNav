# Room SLM output consistency và persistent-server KV — 2026-11-08

## Quyết định

Đã triển khai fix output consistency trong backend offline hiện có và đo KV-cache thật trên cùng pinned Qwen3-1.7B Q4_K_M/CPU1. **9/9 completed model outputs structurally valid**, native GBNF và strict host validator đồng thuận; cache giảm mạnh prefill. **Không quality/live promotion:** model vẫn suy roomtype thiếu căn cứ, đầu vào có association/category lỗi, dataset chưađủ12eligiblephysicalrooms. Không đổi model/defaultHydra/exploration/guard hoặc nốiS4/UI.

Persistent server chỉ là diagnostic harness trong task này; product `LlamaCppRoomLabelBackend` vẫn start/close từngrequest. Shared `configs/room-label-slm.experimental.json` giữdisabled. Muốn dùng KV thường xuyên cần bước backend lifecycle riêng, không âm thầm gọi S4 hoàn tất.

## Implemented

- `rooms/output_grammar.py`: deterministic request-bound GBNF `room-output-consistency-v1`. Proposedlabel khácunknown; alternatives0..2canonicalunique sorted, khôngtrùngprimary; support1..8canonicalunique sorted chỉassignedIDs trong boundedcontext; không thểgộp O(7),O(8) thànhmộtID giả. Unknown/insufficient_evidence phảiunknownlabel+emptyarrays. CompactJSON keyorder cốđịnh; reason1..256 với firstdecodedchar printableASCII. Đây là generation subset của v1contract, không là factuality rule.
- Không dựa `uniqueItems/not/if` trongJSONschema vì pinnedllama.cpp khôngsupport. CompilerO(n*k) cho supportsubset;64object grammar52,487bytes, nativeoracle accepts8/rejects9supports, compile~4ms quan sát. RuntimevẫnCPU1, same4096context/384output/nonthinking/seed0greedy.
- `rooms/labels.py`: strict JSON duplicate-key rejection; abstentionkhôngclaim alternatives/support. `contracts/room_semantics.py` cũngreject typedunknown/insufficient với label/claims khôngnhấtquán; stalecheck giữpriority. Khôngstrip/prose/repair output hoặc đổi rawpredictionscũ.
- `rooms/prompt.py`: giải thích abstention/genericclues, giới hạn/sắp xếp lists và khôngghépIDs; không thêmhumanreference, không sửa bed→sofa trongruntimecontext.
- `rooms/slm_backend.py`: shared `build_room_completion_body` dùng grammar thay response_format/json_schema, pinhash/version/bytes, rawoutputSHA, nativetimings/usage/finishreason. Truncated finish_reason=length phảiinvalid_output dùJSONcóvẻcomplete. Legacycapabilityflag `supports_json_schema` giữ conservativegate đểkhông đổiconfigformat; actualGBNF được kiểm trực tiếp trênpinnedruntime, HTTPunsupported failclosed, không fallbackyếu hơn.
- PublicroomIDs, geometry/member assignments và actuator interfaces giữnguyên. Decoderpolicy/hash cần được lưu ngoài generic structural-schemahash; trướcS4cache/publication phảipin grammarpolicy/hash cùng model/prompt/runtime/fullrequestkey. Chưa thêm persistentserviceAPI.

## Controlled runtime protocol

Sources: singleton `runs/room-slm-pilot/S3/00805-r45/request-001.json` và9object `.../00807-r2/request-000.json`. Đây là frozenruntimecontexts; singleton không được gắn humanA1c569 (differentrun). Humanannotation chỉevaluator, khôngvào prompt.

One local127.0.0.1 server,1slot/id_slot0, CPU1/GPUlayers0, process persistent trong9calls. Mỗi context OFF→ON→OFF→ON; requestbody/prompt/grammar/context/decoding giống hệttrừcache_prompt. Sauđó đổi nine→mirror vớiON đểđo sharedprefixkhikháccontext. Source/module hashes pinnedtrướcfirstresponse vàmatchsaucuối; no other inference/benchmark inthis task.

DiagnosticHTTPdeadline100s đểquan sát OFFcompletion của9objects; productionmodeljob60s khôngđổi. Healthstartup2.784s, táchkhỏi tableHTTP. OS pagecache khôngflush; đây không phải cold-diskbenchmark. Nativecache_n cho OFF=0, ONsamecontext405/406 và954/955; crosscontext331/406. KV computationalreuse khônglà resultcache, không chuyểnroomID/source/revision hoặc rewritecapturetime.

## Paired measurements

Seconds; mỗi hàng2calls. Đây small-n diagnostic, không performanceguarantee/p95 hoặc A/B semanticaccuracy. Decodeper-token speed gầnnhưkhôngđổi.

| Context | Cache | n | Mean prefill | Mean decode | Mean HTTP | Decode tokens từngcall |
|---|---|---:|---:|---:|---:|---|
| Singleton mirror | OFF | 2 | 23.356 | 11.345 | 34.709 | 61,61 |
| Singleton mirror | ON | 2 | 0.240 | 11.551 | 11.799 | 61,61 |
| 9 objects /00807 | OFF | 2 | 56.686 | 31.842 | 88.551 | 136,136 |
| 9 objects /00807 | ON | 2 | 0.278 | 15.188 | 15.493 | 67,67 |

NineobjectOFF136tokens vsON67tokens: phầngiảmHTTP gồm cảítdecode tokens hơn, không quy toàn bộ88.55→15.49s choKVcache. Prefixprefill56.69→.278s làbenefit trực tiếp; native4.24→4.35decode tokens/s gầnnhưkhôngđổi. Pinnednative docs cũngnêu batch/cache cóthểlàm khác logits/outputs dùgreedy. MirrorOFF/ON đều61tokens, prefill23.356→.240s, HTTP34.709→11.799s cho thấy benefit màkhông thay độdàioutput.

CrosscontextmirrorON:331tokensreused/75prefill, prefill4.869s+decode11.438s, HTTP~16.315s. Đây1observation, không guarantee cho mọi contextchanges. PeakprocessRSS2,691,002,368bytes (~2.51GiB), PSS2,685,563,904; memory đo toànserverlife, khôngper-call. Không đo Nav/controlcontention hoặc hostmemorypressure trong task này.

## Semantics còn chưa đạt

Tất cả9responses finishstop vàlabel structurallyavailable. Mirror outpututility từmộtmirror thiếu discriminatingevidence, khôngđạt kỳvọngabstention dùpromptnhắc; không có humanreferenceđúngrun cho singletonnày, không gọiđó làroomaccuracy measurement. Nineobject00807 outputbedroom cảOFF/ON, trái humanreferencephòngkhách; objectO0 tronginput vẫnbed nhưng userxácnhậnsofa. Đây là end-to-end failure gắninputcategory/associationerror, không chứngminh model hiểuđúngphòng chỉvìID/schemađúng.

Không feed correction/roomlabel vào prompt, khôngtínhrepeatedcalls thành independentrooms, không báomacroF1 hoặc pass12rooms. Room label không geometry proof. Nhanh hơn/JSONvalid làhai gate nhỏ; chấtlượngevidence/abstention/semantics vẫn cần xửlý trướclive.

## Correctness và review

- Main RED6hostregressions và5publiccontractregressions trướcfix; parser/compilerREDimport trướcimplementation. Native26tests cover invalidprimary/alternatives/status/support, escaping/Unicode, missingassignedIDs, reasonlimits,64objects. Validator biên dịch từupstream unchanged `tests/test-gbnf-validator.cpp` linkedpinnedlib; source/binarysha/command/exit trong `grammar/native/build-record.json`. Noteupstreamvalidator exit0eveninvalid; test/oracle so firststdoutline chínhxác, khôngdựa exit hoặc substring.
- Combinedcommand với `ROOM_SLM_NATIVE_VALIDATOR=.../grammar/native/validator PYTHONPATH=.:src .venv/bin/python -m pytest` trên12relatedtestfiles: **97distincttests passed2.05s/exit0**, no nativeskip.2tests responsepolicy đượcrerun sau movehelper sang `tools/room_slm_response_policy.py` đểfreshcheckout khôngphụthuộc ignoredruns; khôngdoublecount thành99. Logs `final-tests.log`, `kv-policy-portable-green.log`.
- Một Luna xhigh implementer compiler và một independentLuna xhigh read-onlyreview. Review phát hiện conditionalbenchmarkharness không rejectfinishlength nhưbackend. Actual9casesđều stop nênkhông ảnhhưởngdata. Đãarchive exactexecutedscript `runtime/benchmark-executed.py` đúngprotocolscriptSHA; futureharness gọi `tools/room_slm_response_policy.py` rejecttruncation;2regressiontests confirm evenvalidJSON+lengthinvalid. Reread/rawvalidation dùngstrictpolicy cả9responses; khôngrerunmodel hoặc sửaraw/timings đểchefinding.
- `PYTHONPATH=.:src .venv/bin/python runs/room-slm-consistency-kv-20261108/verify.py` exit0:9source/context/request/hashbindings,9nativegrammaracceptances, samebodyexceptcache, cachecounts/timings reconciliation, cleanserverexit0,6geometry/profileSHAunchanged, coordinator/safety/sharedconfigSHAunchanged. SharedSLMconfigdisabled; noGPU/simulator/live/modeldownload/training/commit/push.

## Artifacts và bước tiếp

`runs/room-slm-consistency-kv-20261108/verification.json` là bảngsốliệu/individualcases; `runtime/` giữbody/raw/prompt/grammar/protocol/log/sourcehashes/reviewresolution; `grammar/` giữnativeoracles; `source-before.json` và tests logs giữcheckpoint. Completedruntimefolder khôngđượcoverwrite; rerun cầnfreshartifactfolder vàpincurrent sourceversion, khônggiảvờarchiveoldadapterlàcurrent.

Tiếp theo có thể làm persistentbackend offline opt-in với bounded lifecycle/reset/timeout/restart vàexactresultidentity, tận dụngKV đãđo. Không cần nâng4B/đưaUIlive đểlàm bướcđó. Song song nâng chấtlượngobjectevidence, kiểm selectiveabstention và frozenhumanlabelset đủsupport; không dùng geometry hoặcSLMlabel như navcertificate. LiveS4/S5/model5s budgets/roomlabelaccuracy chưađạt vàkhông đượcpromote trong task này.
