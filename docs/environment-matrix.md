# P00 environment matrix

Snapshot date: 2026-10-27. This matrix describes bounded import and asset
presence probes. The preflight itself is read-only. The main task prepared the
project-local `.venv` and installed NeuSymNav there before this audit; no
system or sibling-source environment was changed by P00. No GPU, simulator,
native workload, model inference, or display workload was run. See
[runtime provenance](source-provenance.json) for hashes and detailed status.

## Host and contracts profile

| Capability | Observed value | P00 result |
| --- | --- | --- |
| Selected interpreter | `.venv/bin/python` | Python 3.12.3 |
| Base interpreter | `/usr/bin/python3` | Python 3.12.3 |
| Required host imports | `neusymnav`, NumPy 1.26.4, SciPy 1.11.4 | All imports passed |
| Test/build imports | pytest 7.4.4, setuptools 68.1.2, PyYAML 6.0.1 | Imports passed |
| Other available imports | OpenCV 4.6.0, Pillow, PyQt5 / Qt | Imports available; UI behavior not tested |
| Commands | `uv`, `cmake`, `g++`, `pkg-config` | Present |
| Package manager support | host Python has no `pip`, `ensurepip`, or `wheel` | Existing cached wheel used by main for local editable install |

The tested host package versions are captured in
[host constraints](../configs/host-constraints.txt). These are constraints for
the current Linux/Python host, not a resolved wheel-hash lock or an instruction
to install optional packages. Sensor, detector and appearance environments
remain separate and unresolved until an installation is authorized.

Two known alternate interpreters were probed from existing machine configuration:

| Interpreter | Optional imports missing |
| --- | --- |
| `/home/hiiluo08/Works/NeuSym-Nav/NeuSymNav/.venv/bin/python` | `habitat_sim`, `torch`, `ultralytics`, `open_clip` |
| `/usr/bin/python3` | `habitat_sim`, `torch`, `ultralytics`, `open_clip` |
| `/home/hiiluo08/miniforge3/bin/python` (3.13.13) | `habitat_sim`, `torch`, `ultralytics`, `open_clip` |
| `/home/hiiluo08/.local/share/uv/python/cpython-3.10.21-linux-x86_64-gnu/bin/python` | `habitat_sim`, `torch`, `ultralytics`, `open_clip` |

The read-only environment audit also checked Conda registry entries, the
`miniforge3/envs` directory, venv candidates in `Works`, `Desktop`,
`Documents`, `.local`, and `.conda`, plus declared runtime paths from the two
sibling sources. It found no additional usable runtime environment in that
bounded search. Paths under the old `/home/kiettran05/...` machine are absent;
source runtime examples point to venvs that do not exist. The audit and a
proposed minimal set of isolated environments with disk estimates are recorded
in [environment audit](../runs/p00-main/environment-audit.json) and
[runtime environment proposal](runtime-environment-proposal.md). No environment
was installed from that proposal.

## System resources observed

| Resource | Read-only observation | Runtime implication |
| --- | --- | --- |
| RAM | 15.9 GB total; 7.1 GB available at probe time | Import probes only; no memory stress test |
| Filesystem | 202 GiB available on the measured workspace filesystem | Does not include future model or dependency downloads |
| NVIDIA driver | `nvidia-smi` query failed with exit 9: driver could not be reached | GPU visibility and the planned 5 GiB VRAM cap remain unverified |

Evidence is saved under `runs/p00-main/{memory,disk,gpu}.txt`. No GPU
inference was attempted.

## Optional runtime capabilities

| Profile | Import / artifact evidence | P00 status |
| --- | --- | --- |
| Habitat sensor | `habitat_sim` missing in all four interpreter probes; HM3D GLB and route navmesh present | Runtime blocked on probed interpreters; no simulator capture run |
| YOLOE11s detector | `torch` and `ultralytics` missing in all four probed interpreters; YOLOE11s and MobileCLIP text encoder present | Runtime blocked; no model load or inference |
| OpenCLIP appearance | `open_clip` missing; manifest-declared safetensors checkpoint absent; a separate NewOH3DSG ViT-B/32 checkpoint is present | Deferred; format/model compatibility and license are unverified |
| Native DuDe | Prebuilt `occusg_dude_worker` candidate is present at `../3DSG/prebuilt/linux-x86_64/bin/occusg_dude_worker`; SHA-256 matches `ASSET_MANIFEST.json`; `ldd` resolved dependencies including bundled GMP/MPFR | Candidate artifact and ABI dependencies found; worker execution, request/output contract, and parity unverified |
| Desktop UI | PyQt5, QtWidgets, QtGui, and QtCore import | Import available; no display/offscreen behavior tested |

The selected native source is
`../3DSG/projects/Rebuild_3DScene_OccuSG/native/dude`; Python Fusion
resolution remains `../3DSG/projects/Fusion_Concept_OccuSG/src/standalone_sg`.
Do not mix the two standalone scene-graph package roots on one `sys.path`.
The directory `../3DSG/third_party/m4-prefix` exists, and the Rebuild CMake
target also names its own expected dependency prefix. Prefix compatibility
with this selected source and the needed CGAL development packages is not
verified. The prebuilt binary is not proof of source-build reproducibility or
runtime correctness.

The HM3D navmesh is route support only and must not seed map free space.
Semantic GT files were not present in the selected scene directory. Technical
runtime gaps above are separate from unresolved licenses; see
[third-party notices](../THIRD_PARTY_NOTICES.md).

## Profiles pinned for later work

- `core-frontier-yoloe11s`: proposed detector baseline, appearance off, local
  HM3D 00802 candidate. Required optional imports are missing in the probed
  interpreters, so no NeuSymNav quality result exists.
- `appearance-openclip`: deferred optional comparison. The declared checkpoint
  is missing; the alternate local checkpoint has unverified compatibility and
  `open_clip` is missing.
- `geometry-only`: deferred ablation profile for later CPU fixture work, not a
  runtime result.

P00 contracts preflight passed. The source inventory and preflight tools passed
focused correctness tests. Optional sensor, detector, appearance, native worker,
and UI runtime validation remains pending.
