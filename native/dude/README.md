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
