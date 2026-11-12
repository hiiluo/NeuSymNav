# Occupancy history comparison for 00770

The tracked [older 00770 mapper profile](../../configs/p10/demo-yoloe11s-conceptgraphs-visual-gpu-00770.json#L99) sets a 2 m snapshot radius and omits `local_retention_s`. It is the profile selected by [run_map_demo.sh](../../tools/run_map_demo.sh#L19) in this checkout, where the machine-local override is absent. [NavMapper](../../src/neusymnav/mapping/occupancy.py#L287) only applies a rolling evidence window when retention is configured. The [vote integrator](../../src/neusymnav/mapping/_occupancy_core.py#L715) accumulates planar and height log odds and retains measured floor support. Missing votes leave the stored components unchanged. Conflicting votes can change the classification.

The old Rebuild M3/M5 tab is a separate case. Its [launcher](../../tools/run_rebuild_rgbd_map_demo.sh#L46) selects the OctoMap-backed M2/M3 worker. The read-only 3DSG reference at `projects/Rebuild_3DScene_OccuSG/native/occupancy/fixture_runner.cpp:535` constructs one map per server and projects its tree at line 581. `occupancy_map.cpp:89` builds the sets of free and occupied keys for the scan and updates those keys at lines 112–119. The [old tab](../../src/neusymnav/visualization/desktop.py#L472) renders the published M3 states and overlays the matching M5 regions. The M3 raster therefore also carries accumulated evidence between scans, under its own projection rules.

The machine-local 00770 Hydra/SLM CPU and GPU profiles, `configs/demo-00770.hydra-slm.{cpu,gpu}.local.json`, set a 2 m local radius, a 10 s evidence lifetime and a 2 s overview refresh period, matching the [handoff template](../../handoff/3dsg-v11/templates/configs/demo-00806.hydra-tour-slm.experimental.local.json.template#L70). The [rolling integrator](../../src/neusymnav/mapping/_occupancy_core.py#L481) expires or evicts evidence before applying the new votes. The [overview](../../src/neusymnav/mapping/overview.py#L51) copies the classifications of vote-touched cells from the rolling map, including UNKNOWN. A previously FREE cell can remain visible during a gap and be overwritten by UNKNOWN when the next scan supplies only part of the evidence needed to reclassify it.

The paired probe ran under `PYTHONPATH=src:tests .venv/bin/python` using the existing synthetic collector from [test_navmap_rolling.py](../../tests/test_navmap_rolling.py#L34). It called `NavMapper.update()` and `build_overview()` at every step on two mappers differing only in `local_retention_s` (omitted and 10.0). All expected pairs matched, exit 0. The table shows NavMapper local/overview, not the separate current-depth command guard.

| Capture time | Votes | Legacy local / overview | Rolling local / overview |
| --- | --- | --- | --- |
| 1 s | Full free evidence | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |
| 2 s | Full free evidence | FREE / FREE | FREE / FREE |
| 12 s | None | FREE / FREE | UNKNOWN / FREE |
| 13 s | Floor and one height bin | FREE / FREE | UNKNOWN / UNKNOWN |
| 14 s | Occupied hit | UNKNOWN / UNKNOWN | OCCUPIED / OCCUPIED |
| 15 s | Occupied hit | OCCUPIED / OCCUPIED | OCCUPIED / OCCUPIED |

For display, retain previously observed geometry through incomplete observations and revise it when adequate new evidence supports a change. For control, retain the [current measured-depth and motion proof requirements](../../docs/architecture.md#L296). The same raw tiles currently serve the optional room input through [NavMapper](../../src/neusymnav/mapping/occupancy.py#L348), so a future display change must explicitly account for this consumer. This was a source comparison and one-cell probe. No live accuracy or performance comparison was run.
