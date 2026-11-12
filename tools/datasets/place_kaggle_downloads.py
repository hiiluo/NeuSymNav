#!/usr/bin/env python3
"""Move the Kaggle-downloaded HM3D val / ObjectNav episodes / MP3D into habitat_data.

Kaggle auto-extracted every archive on upload:
  * .tar / .zip   -> plain directories
  * X.json.gz     -> directory "X.json/" holding "X.json"
This script restores the layout Habitat expects (episodes re-gzipped) and MOVES
(no copy, same filesystem) the data into habitat_data. Nothing is overwritten.

  python3 place_kaggle_downloads.py                 # dry run: print the plan only
  python3 place_kaggle_downloads.py --apply         # do it
  python3 place_kaggle_downloads.py --apply --with-train   # also keep train episodes (~8 GB json)
"""
import argparse, filecmp, gzip, os, shutil, sys
from pathlib import Path

HOME = Path.home()
DL = HOME / "dl"
HAB = HOME / "Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG/artifacts/habitat_data"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--with-train", action="store_true", help="also place train episodes (not needed for evaluation)")
ap.add_argument("--dl", type=Path, default=DL)
ap.add_argument("--hab", type=Path, default=HAB)
a = ap.parse_args()
DL, HAB = a.dl.expanduser(), a.hab.expanduser()
plan, problems = [], []


def move(src: Path, dst: Path):
    if not src.exists():
        if dst.exists():
            plan.append(f"skip (already placed)  {dst}")
        else:
            problems.append(f"missing source: {src}")
        return
    if dst.exists():
        if src.is_file() and dst.is_file() and filecmp.cmp(src, dst, shallow=False):
            plan.append(f"skip (identical)  {dst}")
            return
        problems.append(f"exists, NOT overwritten: {dst}")
        return
    plan.append(f"move  {src}  ->  {dst}")
    if a.apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def gz_episode_file(src_dir_or_file: Path, dst_gz: Path):
    """Kaggle turned X.json.gz into X.json/X.json (or left X.json); write X.json.gz."""
    inner = src_dir_or_file / src_dir_or_file.name if src_dir_or_file.is_dir() else src_dir_or_file
    if src_dir_or_file.is_dir() and not inner.is_file():
        # gzip kept its original member name (e.g. hm3d v1 val.json.gz -> val.json/val_2000.json)
        only = [f for f in src_dir_or_file.iterdir() if f.is_file() and f.suffix == ".json"]
        if len(only) == 1:
            inner = only[0]
    if not inner.is_file():
        problems.append(f"missing episode json: {inner}")
        return
    if dst_gz.exists():
        with gzip.open(dst_gz, "rb") as fo, open(inner, "rb") as fi:
            same = fo.read() == fi.read()
        if same:
            plan.append(f"skip (already placed)  {dst_gz}")
        else:
            problems.append(f"exists, NOT overwritten: {dst_gz}")
        return
    plan.append(f"gzip  {inner}  ->  {dst_gz}")
    if a.apply:
        dst_gz.parent.mkdir(parents=True, exist_ok=True)
        with open(inner, "rb") as fi, gzip.open(dst_gz, "wb", compresslevel=6) as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)


# ---------------- HM3D val v0.2 ----------------
hm = DL / "hm3d"
VAL = HAB / "versioned_data/hm3d-0.2/hm3d/val"
for part in ("hm3d-val-habitat-v0.2", "hm3d-val-semantic-annots-v0.2"):
    root = hm / part
    if not root.is_dir():
        problems.append(f"missing {root}")
        continue
    for scene in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(scene.iterdir()):
            move(f, VAL / scene.name / f.name)
for f in (hm / "hm3d-val-configs/hm3d_val_basis.scene_dataset_config.json",
          hm / "hm3d-val-semantic-configs-v0.2/hm3d_annotated_val_basis.scene_dataset_config.json"):
    move(f, VAL / f.name)
# Shared annotated config: the minival download already placed one in hm3d/.
f = hm / "hm3d-val-semantic-configs-v0.2/hm3d_annotated_basis.scene_dataset_config.json"
if f.exists():
    move(f, HAB / "versioned_data/hm3d-0.2/hm3d" / f.name)

# ---------------- ObjectNav episodes ----------------
ep = DL / "episodes"
SETS = {  # (downloaded root, destination)
    "hm3d/v1": (ep / "objectnav_hm3d_v1/objectnav_hm3d_v1", HAB / "datasets/objectnav/hm3d/v1"),
    "hm3d/v2": (ep / "objectnav_hm3d_v2/objectnav_hm3d_v2", HAB / "datasets/objectnav/hm3d/v2"),
    "mp3d/v1": (ep / "objectnav_mp3d_v1", HAB / "datasets/objectnav/mp3d/v1"),
}
splits = ["val", "val_mini"] + (["train"] if a.with_train else [])
for name, (src, dst) in SETS.items():
    if not src.is_dir():
        problems.append(f"missing {src}")
        continue
    for split in splits:
        s = src / split
        if not s.is_dir():
            continue
        top = s / f"{split}.json"
        gz_episode_file(top, dst / split / f"{split}.json.gz")
        content = s / "content"
        if content.is_dir():
            for c in sorted(content.iterdir()):
                if c.name.endswith(".json"):
                    gz_episode_file(c, dst / split / "content" / (c.name + ".gz"))

# ---------------- MP3D (habitat task) ----------------
mp = DL / "mp3d/mp3d_habitat/mp3d"
MP3D = HAB / "scene_datasets/mp3d"
if mp.is_dir():
    for scene in sorted(p for p in mp.iterdir() if p.is_dir()):
        move(scene, MP3D / scene.name)
    readme = DL / "mp3d/mp3d_habitat/README.txt"
    if readme.exists():
        move(readme, MP3D / "README.mp3d_habitat.txt")
else:
    problems.append(f"missing {mp}")

# ---------------- report ----------------
kinds = {}
for p in plan:
    kinds[p.split()[0]] = kinds.get(p.split()[0], 0) + 1
print("\n".join(plan[:12]), f"\n... ({len(plan)} actions: {kinds})" if len(plan) > 12 else "")
print(f"\nHM3D val -> {VAL}\nEpisodes -> {HAB / 'datasets/objectnav'}\nMP3D     -> {MP3D}")
if problems:
    print("\nPROBLEMS:"); print("\n".join("  " + p for p in problems))
print("\n" + ("DONE (applied)." if a.apply else "DRY RUN only. Re-run with --apply to execute."))
sys.exit(1 if problems and a.apply else 0)
