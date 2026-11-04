# HM3D semantic ground truth acquisition for active perception

Checked 2026-11-03 against the official Habitat-Sim dataset guide, Habitat
dataset downloader, AI Habitat HM3DSem page, Matterport's dataset terms/access
page, and Matterport's official dataset repository.

## Official source and access

HM3DSem v0.2 provides 142,646 object-instance annotations across 216 HM3D
spaces, mapped to 40 Matterport categories. Its published terms describe
academic, non-commercial research use. This is the relevant semantic source
for generating scene-grounded labels in Habitat. The current 00861 example
scene is already the development scene, so it cannot serve as an independent
held-out scene.

Matterport requires access to the Habitat-Matterport dataset and an API token.
The official Habitat guide says to request access through a Matterport
account, generate an API token in the account's Developer Tools, then use the
token ID as downloader username and token secret as password. The secret is
shown only once. This account step is required for HM3D train/val/minival
archives. This worktree cannot create a token or authenticate on the user's
behalf.

Official sources:

- [AI Habitat HM3D Semantics](https://aihabitat.org/datasets/hm3d-semantics/)
- [Habitat-Sim dataset and access instructions](https://github.com/facebookresearch/habitat-sim/blob/main/DATASETS.md#habitat-matterport-3d-research-dataset-hm3d)
- [Official Matterport/Habitat download repository and archive sizes](https://github.com/matterport/habitat-matterport-3dresearch/blob/main/README.md)
- [Matterport academic research access and terms](https://matterport.com/partners/meta)
- [Habitat official downloader source](https://github.com/facebookresearch/habitat-sim/blob/main/src_python/habitat_sim/utils/datasets_download.py)

## Smallest official candidate cohort

Use HM3D v0.2 minival, whose official inventory contains ten scenes,
00800 through 00809. Exclude 00861 as the active-perception development scene. Also exclude
00800-TEEsavR23oF and 00802-wcojb4TFT35 because prior smoke or reliability
runs used them. Three candidate scenes for a still-untouched confirmatory cohort
are:

- 00801-HaxA7YrQdEC
- 00803-k1cupFYWXJ6
- 00804-BHXhpBwSMLh

These identifiers appear in the official Habitat-Sim dataset guide's minival
directory listing. Freeze these scene IDs and three start/seed pairs before
running inference/evaluation, and check the campaign manifest to ensure no
other historical use exists before designating them confirmatory. Check each
scene's annotation config and semantic
mesh actually exist and load before admitting it to the cohort. This choice is
a candidate, not a claim that its object composition or annotation matches the
existing 00861 taxonomy one-to-one.

The official archive table lists minival Habitat meshes at 390 MB,
semantic annotations at 240.6 MB, and semantic configs at 30 KB. Downloading
these four split components is approximately 631 MB before extraction.
The filesets cover all ten minival scenes because the supported downloader
operates by split. The same archive table lists validation semantic
annotations at 2.0 GB and training annotations at 8.1 GB, so those splits are
unnecessary for this initial three-scene cohort. Existing local free space
should be checked again immediately before transfer.

After access is granted, use the authenticated Matterport browser to obtain
the minival archives or use the official Habitat downloader with UID
`hm3d_minival_v0.2` and data directory
`.runtime/retained-assets/p10-hm3d-minival`. The local
`.runtime/sensor/bin/python -m habitat_sim.utils.datasets_download --help`
exits 0. The UID includes Habitat scene assets, scene configs, semantic
annotations and semantic configs. The `_full` suffix adds raw GLBs and is
unnecessary here. Keep credentials out of chat, the worktree and logs.

## How to turn semantic meshes into evaluator ground truth

HM3DSem supplies scene-level annotated semantic meshes and per-scene
.semantic.txt mappings. Habitat-Sim documents enabling a semantic sensor
with the hm3d_annotated_basis.scene_dataset_config.json configuration and
the matching scene basis mesh. For every retained RGB-D/pose source frame,
render the semantic sensor from the same simulator state and calibration,
then bind the semantic labels to the exact frame key and capture timestamp.
Map HM3D instance IDs through the scene's semantic mapping, and rasterize
instance masks and boxes. Store source hashes, scene ID, semantic asset/config
hashes, taxonomy/mapping version, sensor configuration and renderer version.

The new sensor output belongs only in offline evaluator data preparation.
The live robot must continue to consume RGB-D and pose only. Do not seed the
runtime graph, admission, or object memory from semantic labels. Verify label
render alignment against RGB/depth and calibration, then freeze exhaustive
annotation scope and unsupported/background handling before evaluating any
predictions.

The three scene-level annotation archives do not themselves provide a
pre-approved NeuSymNav frame annotation bundle or the frozen metric-ready
masks for its trajectory. A source-bound offline rendering/export and
validation step is still needed after download. Reuse the current semantic GT
preparation validator and keep all outputs under .runtime/.

## Local inventory performed

The source reference folder
../NewOH3DSG/data/versioned_data/hm3d-0.2/hm3d is read-only. Its only
scene-level semantic mesh/text pair found is the development scene
00861-GLAQ4DNUx5U. No minival semantic mesh or per-scene annotation configs
were found in that tree. A scoped search of this repository's .runtime
found synthetic semantic fixtures only, not HM3D held-out assets. Therefore
there is no existing local GT from which to complete the three-scene
confirmatory evaluation.

The local official project source assets do not constitute the held-out
annotated scene cohort. A direct request for the official minival semantic
config archive returned HTTP 200 with a Matterport login HTML page, and tar
exited 2 because the response was not an archive. Thus HTTP 200 did not mean
that the asset was available. The public example config and 60 MiB semantic archive were downloaded into
`.runtime/active-object-perception/gt-acquisition/`. The archive SHA-256
matches the official Git LFS pointer and its only mesh/text pair is 00861. No credentials were inspected.
Dataset authorization and an authenticated download remain necessary.

## Handoff after access is available

1. Confirm Matterport academic non-commercial access for the intended use and
   verify a token is present without printing it.
2. Download only hm3d_minival_v0.2 to
   .runtime/retained-assets/p10-hm3d-minival, preserving downloader logs
   without credentials.
3. Verify the official downloaded file list, scene/config/semantic mesh
   completeness and hashes. Select 00801, 00803, and 00804 only after all
   three load with semantics.
4. Produce exhaustive, frame-bound semantic GT from exact RGB-D/pose frames
   offline. Independently validate mask projection/alignment and taxonomy
   mapping. Do not tune detector/active-perception settings on these scenes.
5. Freeze 3 seeds/starts per scene and run the existing B/M/R/C protocol.
   Retain failures and evaluate the promotion gates as written.

At present, official URLs and exact access process are identified, but the
minival semantic config download attempt was served a login page rather than
the archive. No full minival data was downloaded. This file is a source and
acquisition note, not evidence that the held-out cohort or quality gate has
passed.
