#!/usr/bin/env python3
"""Read-only check of habitat_data after place_kaggle_downloads.py.

Part 1 (plain Python, no habitat_sim):
  * HM3D v0.2 val: scene count, how many have semantic annotations, configs present
  * ObjectNav episodes (hm3d v1/v2, mp3d v1): episode counts per split, and that
    every scene an episode refers to exists on disk
  * MP3D: scene count and the per-scene files Habitat needs (.glb/.navmesh/.house/_semantic.ply)

Part 2 (--sim, needs habitat_sim, i.e. the project's .venv):
  * open one annotated HM3D val scene through hm3d_annotated_val_basis.scene_dataset_config.json:
    navmesh loaded, number of semantic objects / regions, a few categories
  * open one MP3D scene: same, plus the region (room) categories from the .house file
  * for a few episodes of each episode set: geodesic distance start -> nearest goal view
    point on our navmesh vs the episode's stored info.geodesic_distance
    (tells whether those episodes match the scene version we have)

Nothing is written. Exit code 1 if a hard check fails.

  .venv/bin/python tools/datasets/check_habitat_data.py            # part 1 only
  .venv/bin/python tools/datasets/check_habitat_data.py --sim      # part 1 + 2
"""
import argparse, gzip, json, os, sys
from collections import Counter
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--hab", type=Path, default=Path.home() /
                "Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG/artifacts/habitat_data")
ap.add_argument("--sim", action="store_true", help="also open scenes with habitat_sim")
ap.add_argument("--episodes-per-set", type=int, default=5)
a = ap.parse_args()
HAB = a.hab.expanduser()
VAL = HAB / "versioned_data/hm3d-0.2/hm3d/val"
MP3D = HAB / "scene_datasets/mp3d"
EPI = HAB / "datasets/objectnav"
fails, warns = [], []


def ok(cond, msg, hard=True):
    print(("  OK    " if cond else ("  FAIL  " if hard else "  WARN  ")) + msg)
    if not cond:
        (fails if hard else warns).append(msg)
    return cond


def load_gz(p):
    with gzip.open(p, "rt") as f:
        return json.load(f)


def resolve_scene(scene_id):
    """Episode scene_id -> file on disk (episodes are written relative to scene_datasets/)."""
    cands = [HAB / "scene_datasets" / scene_id, HAB / "versioned_data/hm3d-0.2" / scene_id]
    if scene_id.startswith("hm3d_v0.2/"):
        cands.append(HAB / "versioned_data/hm3d-0.2/hm3d" / scene_id.split("/", 1)[1])
    for c in cands:
        if c.is_file():
            return c
    return None


# ---------------- 1. HM3D val ----------------
print(f"\n[HM3D v0.2 val]  {VAL}")
scenes = sorted(p for p in VAL.iterdir() if p.is_dir()) if VAL.is_dir() else []
glb = [s for s in scenes if (s / f"{s.name.split('-', 1)[1]}.basis.glb").is_file()]
nav = [s for s in scenes if (s / f"{s.name.split('-', 1)[1]}.basis.navmesh").is_file()]
ann = [s for s in scenes if (s / f"{s.name.split('-', 1)[1]}.semantic.glb").is_file()
       and (s / f"{s.name.split('-', 1)[1]}.semantic.txt").is_file()]
ok(len(scenes) == 100, f"{len(scenes)} scene folders (expect 100)")
ok(len(glb) == len(scenes) and len(nav) == len(scenes), f"{len(glb)} .basis.glb, {len(nav)} .basis.navmesh")
ok(len(ann) == 36, f"{len(ann)} scenes with semantic.glb + semantic.txt (expect 36)")
for c in ("hm3d_val_basis.scene_dataset_config.json", "hm3d_annotated_val_basis.scene_dataset_config.json"):
    ok((VAL / c).is_file(), c)
print("  annotated:", " ".join(s.name for s in ann[:8]), "..." if len(ann) > 8 else "")

# ---------------- 2. episodes ----------------
episode_sets = {}
for rel in ("hm3d/v1", "hm3d/v2", "mp3d/v1"):
    root = EPI / rel
    print(f"\n[ObjectNav {rel}]  {root}")
    cats = {}
    for split in ("val", "val_mini"):
        top = root / split / f"{split}.json.gz"
        if not ok(top.is_file(), f"{rel} {split}/{split}.json.gz", hard=(split == "val")):
            continue
        t = load_gz(top)
        cats = t.get("category_to_task_category_id", {})
        eps = list(t.get("episodes", []))
        content = sorted((root / split / "content").glob("*.json.gz"))
        for c in content:
            eps += load_gz(c).get("episodes", [])
        sids = Counter(e["scene_id"] for e in eps)
        missing = [s for s in sids if resolve_scene(s) is None]
        ok(len(eps) > 0, f"{rel} {split}: {len(eps)} episodes, {len(sids)} scenes, {len(content)} content files, "
                         f"{len(cats)} categories")
        if sids:
            print(f"        scene_id example: {next(iter(sids))}")
        ok(not missing, f"{rel} {split}: every episode scene found on disk"
                        + (f" ({len(missing)} missing, e.g. {missing[0]})" if missing else ""))
        if split == "val" and eps:
            episode_sets[rel] = (eps, content)
    if cats:
        print("  categories:", ", ".join(sorted(cats)))

# ---------------- 3. MP3D ----------------
print(f"\n[MP3D habitat]  {MP3D}")
mp = sorted(p for p in MP3D.iterdir() if p.is_dir()) if MP3D.is_dir() else []
ok(len(mp) == 90, f"{len(mp)} scan folders (expect 90)")
need = {"glb": ".glb", "navmesh": ".navmesh", "house": ".house", "semantic": "_semantic.ply"}
for k, suf in need.items():
    n = sum((s / f"{s.name}{suf}").is_file() for s in mp)
    ok(n == len(mp), f"{n}/{len(mp)} have <scan>{suf}", hard=(k in ("glb", "navmesh")))
ok((MP3D / "mp3d.scene_dataset_config.json").is_file(),
   "mp3d.scene_dataset_config.json (optional; habitat-lab objectnav_mp3d works without it)", hard=False)

# ---------------- 4. habitat_sim ----------------
if a.sim:
    import numpy as np
    import habitat_sim

    def open_sim(scene, dataset=None):
        cfg = habitat_sim.SimulatorConfiguration()
        cfg.scene_id = str(scene)
        if dataset:
            cfg.scene_dataset_config_file = str(dataset)
        cfg.load_semantic_mesh = True
        cfg.enable_physics = False
        cfg.gpu_device_id = 0
        return habitat_sim.Simulator(habitat_sim.Configuration(cfg, [habitat_sim.agent.AgentConfiguration()]))

    def cat_name(x):
        try:
            return x.category.name() if x.category is not None else ""
        except Exception:
            return ""

    def describe(sim, label):
        ss = sim.semantic_scene
        objs = [o for o in ss.objects if o is not None]
        cats = Counter(n for n in map(cat_name, objs) if n)
        regs = [r for r in ss.regions if r is not None]
        rcats = Counter(n for n in map(cat_name, regs) if n)
        ok(sim.pathfinder.is_loaded, f"{label}: navmesh loaded, navigable area "
                                     f"{sim.pathfinder.navigable_area:.1f} m2")
        ok(len(objs) > 0, f"{label}: {len(objs)} semantic objects, {len(regs)} regions")
        print("        top object categories:", ", ".join(f"{c}({n})" for c, n in cats.most_common(8)))
        print("        region categories:", ", ".join(f"{c}({n})" for c, n in rcats.most_common(10))
              or "(none - regions are unlabelled groups)")

    def geodesic_check(sim, eps, label):
        """Our navmesh geodesic vs the stored one, for episodes of the scene that is open."""
        if not eps:
            return
        ratios = []
        for e in eps[:a.episodes_per_set]:
            goals = e["_goals"]
            ends = [np.array(v["agent_state"]["position"], dtype=np.float32)
                    for g in goals for v in g.get("view_points", [])]
            if not ends:
                continue
            p = habitat_sim.MultiGoalShortestPath()
            p.requested_start = np.array(e["start_position"], dtype=np.float32)
            p.requested_ends = ends
            found = sim.pathfinder.find_path(p)
            stored = e.get("info", {}).get("geodesic_distance")
            if found and stored:
                ratios.append(p.geodesic_distance / stored)
                print(f"        ep {e['episode_id']:>6} {e['object_category']:<12} ours {p.geodesic_distance:6.2f} m"
                      f"  stored {stored:6.2f} m")
            else:
                print(f"        ep {e['episode_id']:>6} {e['object_category']:<12} no path (found={found})")
        good = sum(0.9 <= r <= 1.1 for r in ratios)
        ok(ratios and good == len(ratios), f"{label}: {good}/{len(ratios)} episodes within 10% of stored "
                                           f"geodesic distance", hard=False)

    def episodes_for(rel, scene_name):
        """Episodes of one scene with their goal list attached (goals live in the content file)."""
        if rel not in episode_sets:
            return []
        _, content = episode_sets[rel]
        for c in content:
            if c.name.split(".")[0] in scene_name:
                d = load_gz(c)
                out = []
                for e in d["episodes"]:
                    key = f"{os.path.basename(e['scene_id'])}_{e['object_category']}"
                    e["_goals"] = d.get("goals_by_category", {}).get(key, [])
                    out.append(e)
                return out
        return []

    print("\n[habitat_sim]", habitat_sim.__version__)
    # HM3D: an annotated scene that also has v2 episodes
    v2_scenes = {c.name.split(".")[0] for c in episode_sets.get("hm3d/v2", ([], []))[1]}
    pick = next((s for s in ann if s.name.split("-", 1)[1] in v2_scenes), ann[0] if ann else None)
    if pick is not None:
        short = pick.name.split("-", 1)[1]
        sim = None
        try:
            sim = open_sim(pick / f"{short}.basis.glb", VAL / "hm3d_annotated_val_basis.scene_dataset_config.json")
            describe(sim, f"HM3D {pick.name}")
            geodesic_check(sim, episodes_for("hm3d/v2", short), f"objectnav hm3d/v2 on {pick.name}")
            geodesic_check(sim, episodes_for("hm3d/v1", short), f"objectnav hm3d/v1 on {pick.name}")
        except Exception as ex:  # report, keep going
            ok(False, f"HM3D {pick.name}: {type(ex).__name__}: {ex}")
        finally:
            if sim is not None:
                sim.close()
    # MP3D: a scan that has val episodes
    mp_val = {c.name.split(".")[0] for c in episode_sets.get("mp3d/v1", ([], []))[1]}
    scan = next((s for s in mp if s.name in mp_val), mp[0] if mp else None)
    if scan is not None:
        sim = None
        try:
            ds = MP3D / "mp3d.scene_dataset_config.json"
            sim = open_sim(scan / f"{scan.name}.glb", ds if ds.is_file() else None)
            describe(sim, f"MP3D {scan.name}")
            geodesic_check(sim, episodes_for("mp3d/v1", scan.name), f"objectnav mp3d/v1 on {scan.name}")
        except Exception as ex:
            ok(False, f"MP3D {scan.name}: {type(ex).__name__}: {ex}")
        finally:
            if sim is not None:
                sim.close()

print(f"\nSUMMARY: {len(fails)} fail, {len(warns)} warn")
for m in fails:
    print("  FAIL", m)
for m in warns:
    print("  WARN", m)
sys.exit(1 if fails else 0)
