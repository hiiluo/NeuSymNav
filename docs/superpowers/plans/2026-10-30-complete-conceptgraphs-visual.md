# Complete real ConceptGraphs visual association

Continuation of the approved ConceptGraphs design; user explicitly requests finishing the missing real visual path promptly. No additional approval loop. The prior spatial-only completion claim did not satisfy this requirement.

Goal: use existing local OpenAI ViT-B/32 checkpoint and installed clip library with an explicit backend recipe, then prove real RGB→feature→point-cloud association in runtime and compare the same79keyframe inputs.

- [x] Backend worker/client: explicit openai_jit format and preprocessing ID; hash-bound local TorchScript-only loading, architecture verification, CPUfloat eval, actual package/transform/implementation provenance and distinct feature-space. Keep OpenCLIP safetensors behavior compatible. RED/GREEN tests. Owner: complete_visual_backend, SolHigh.
- [x] Runtime/owner/config: explicit appearance_mode=openai_clip, matching backend validation and interpreter probes; pass format to client; native runnable visual profile with local assets only. Owner: main. RED/GREEN runtime tests.
- [x] Read-only fixed-input real feature extraction/cache and four-mode replay: all79frames,154detections/137projected, noGT in matcher, exact exclusions and all223GT kept by evaluator. Owner: visual_fixed_replay, SolHigh. Unit bindings tests and actual CPUcheckpoint execution.
- [x] Native live proof with appearance enabled: accepted real features stored durably and visual_pairs>0, no silent whole-run fallback; safety/TTL unchanged. Main singleGPUslot. No claim quality gain until measured.
- [x] Independent SolHigh review, fresh frozen fullCPU suite, metric comparison and status/results/usage. No downloads/install/training/source-sibling writes/commit/push. Keep default legacy unless separately justified; concrete visual profile must be usable.

Public recipe: appearance_mode=openai_clip; worker.checkpoint_format=openai_jit; model_name=ViT-B-32; preprocessing_id=openai-clip-vit-b-32-eval-224-maskbboxpad20-v1; existing crop_recipe_id and512dimensions; CPU device. Existing OpenCLIP checkpoint format and space remain separate. Old checkpoint files/ledgers never silently reinterpreted.

Existing local asset probe already succeeds: TorchScript ViT224/patch32/width768/12blocks/output512, finite real image vector. Checkpoint SHA40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af. No dependencies installed.
