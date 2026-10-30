# Native backend source availability

The GitHub source tree includes the build recipe and SHA256 source inventory,
not the locally copied `upstream/` dependency closure or compiled libraries.
That closure contains FIST material whose retained notice restricts redistribution;
other parts have unresolved terms. Keeping a repository private does not change
those terms. The MIT notice found for the OccuSG baseline is preserved in
`licenses/OccuSG-MIT.txt`; it does not cover every dependency in the closure.

See `THIRD_PARTY_NOTICES.md`, `source-closure.json` and `docs/github-setup.md`.
Core CPU tests/fixture replay do not require this native tree. Live DuDe execution
requires a separately available, authorized closure and compatible native
libraries/worker, with explicit paths/checksums. This source upload does not claim
a complete, redistributable native build or a turnkey GPU environment.

The ignored local upstream folder is preserved on the development machine.

## Local origin-alignment correction

`patches/origin-alignment.json` pins the original and modified file hashes and
`origin-alignment.patch`. It corrects floating-point truncation of near-integral
sliding-window origin offsets; genuinely fractional offsets keep original
behavior. The original ignored closure is preserved and verified before staging.
The build tool creates a separate patched closure and refuses an existing output
folder or undeclared changes. With the existing authorized local dependencies:

```sh
.venv/bin/python tools/build_native.py \
  --dependency-prefix /home/hiiluo08/Works/NeuSym-Nav/3DSG/third_party/m4-prefix/usr \
  --patch-set native/dude/patches/origin-alignment.json \
  --output-dir .runtime/retained-assets/p06-room-origin-v1
```

Use a new output directory when rebuilding. This command already produced the
worker selected by the three maintained YOLOE11s CG+Visual GPU map profiles.
The manifest records both original source provenance and the local patch; it
is not permission to redistribute the retained dependency closure.
