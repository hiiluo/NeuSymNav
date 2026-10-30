# Third-party notices and P00 license status

This records notices found in the bounded P00 source and asset closure. A
notice for one component does not grant rights to a separately bundled
component. The selected filesystem hashes and per-file license evidence are
recorded in [source provenance](docs/source-provenance.json). Where the
inspected files do not resolve terms, P00 records the uncertainty and does not
infer permission.

| Component | P00 status and evidence |
| --- | --- |
| NewOH3DSG selected Python source | No LICENSE/NOTICE was found in the selected source ancestor scope. Rights remain unresolved. |
| Fusion `standalone_sg` and `integration_v2` source | No LICENSE/NOTICE was found in the selected source ancestor scope. Rights remain unresolved. |
| ConceptGraphs reference code | `../3DSG/projects/Fusion_Concept_OccuSG/ref_ConceptGraph/concept-graphs/LICENSE` declares MIT for that reference tree. |
| OccuSG baseline | `../3DSG/projects/Rebuild_3DScene_OccuSG/ref_OccuSG/OccuSG/LICENSE` declares MIT for baseline source; it does not resolve separately bundled dependencies. |
| Incremental DuDe ROS package | `package.xml` declares `<license>TODO</license>`. No package-specific license was resolved. |
| FIST archive and headers | `Third_Party/dude_final/FIST/makefile` lines 943–953 contain the notice restricting use to non-commercial use internal to an institution and academic evaluation with author/copyright credit. It prohibits duplication, alteration, sale, and redistribution without prior written consent, and requires a commercial license for commercial use. The selected `libFIST.linux64.a` SHA-256 is `84875da959aae5a1abdddc993075d0f91d4afdbdda1a29dd856f77254a63c684`. The parent DuDe README is a paper citation; the earlier P00 attribution to that README was incorrect. |
| Prebuilt native worker | Candidate SHA-256 is `e41f5824c70b968f65b71a448ff46dde47450cb4a3027892f31c569717a96125`, matching the local asset manifest. This establishes artifact identity only; it does not resolve source, dependency, or redistribution rights. |
| mathtool | Rebuild source lock refers to a license file that is absent from the inspected package scope. Status unresolved. |
| CGAL, GMP, MPFR | Native dependencies are present through local prefix/prebuilt artifacts, but P00 did not resolve exact package licenses or prefix compatibility. |
| OctoMap | Rebuild source metadata records New BSD and the system package is 1.9.7. It remains a deferred extension, not a substitute for the selected DuDe worker. |
| YOLOE11s checkpoint | The selected backend config declares AGPL-3.0. The local checkpoint is hashed; execution rights beyond that notice were not assessed. |
| MobileCLIP text encoder | The selected profile references the locally present, hashed text encoder. Its separate license was not found in the selected profile metadata. |
| YOLO11n reference checkpoint | The Rebuild detector profile declares AGPL-3.0 and local-experiment-only status. This checkpoint is deferred. |
| HM3D v0.2 minival scene | The local route profile records academic non-commercial use and a Matterport EULA publication notice. P00 did not locate the EULA itself or infer further permissions. No semantic mesh/descriptor was present in the selected scene directory. The navmesh is route-only and must not seed map free space. |
| OpenCLIP checkpoints | The manifest-declared safetensors file is absent. A separate NewOH3DSG ViT-B/32 checkpoint is present but compatibility and its license were not assessed in P00. |

A prebuilt native worker and libraries are present, but execution was not
attempted. Redistribution, cloud use, and license scope remain unresolved.

## ConceptGraphs-inspired association (2026-10-30)

The directional nearest-neighbor overlap and spatial/visual aggregation in
`src/neusymnav/objects/conceptgraphs.py` are adapted from ConceptGraphs
`conceptgraph/slam/{utils,mapping}.py`. Local reference revision and exact source
hashes are recorded in `docs/superpowers/specs/2026-10-30-conceptgraphs-association-design.md`.
NeuSymNav retains its own canonical owner, Hungarian assignment and bounded fusion.

MIT License

Copyright (c) 2023 concept-graphs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### Local CLIP runtime provenance

The optional `openai_clip` backend uses an existing installed `clip` package
(an Ultralytics fork of OpenAI CLIP) and an existing read-only local ViT-B-32
checkpoint. No package source or model weights are vendored by this change.
Actual implementation/checkpoint/preprocessing hashes and runtime versions are
recorded in feature metadata; this backend is separate from OpenCLIP safetensors.
See `docs/results/conceptgraphs-visual-completion-2026-10-30.md` for evidence.
