"""Load Habitat ObjectNav episode sets (HM3D v1/v2, MP3D v1) into one record type.

Supported layouts (as placed by ``tools/datasets/place_kaggle_downloads.py``)::

    <habitat_data>/datasets/objectnav/<dataset>/<version>/<split>/<split>.json.gz
    <habitat_data>/datasets/objectnav/<dataset>/<version>/<split>/content/<scene>.json.gz

Episodes may live in the top file (MP3D val_mini) or in per-scene content files;
goals live in ``goals_by_category`` keyed ``<scene basename>_<category>``.

The runtime scene dataset config never carries semantics (AGENTS.md: semantic
GT belongs to the offline evaluator only); ``eval_dataset_config`` is the
annotated one and must only be opened by evaluation code.

Python 3.9 compatible (the Habitat interpreter imports this module too).
"""
from __future__ import annotations

import gzip
import json
import math
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]

# name -> (dataset dir, version dir, scene-id prefix family)
EPISODE_SETS = {
    'hm3d_v1': ('hm3d', 'v1'),
    'hm3d_v2': ('hm3d', 'v2'),
    'mp3d_v1': ('mp3d', 'v1'),
}
DEFAULT_HABITAT_DATA = Path.home() / 'Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG/artifacts/habitat_data'
HM3D_ROOT = 'versioned_data/hm3d-0.2/hm3d'


@dataclass(frozen=True)
class ObjectGoal:
    object_id: int
    category: str
    position: Vec3
    view_points: Tuple[Vec3, ...]


@dataclass(frozen=True)
class Episode:
    episode_set: str            # hm3d_v2 / hm3d_v1 / mp3d_v1
    split: str                  # val / val_mini
    episode_id: str             # as in the file; '#<n>' appended to the n-th repeat within a scene
    scene_id: str               # as in the file (relative to scene_datasets/)
    scene_short: str            # e.g. TEEsavR23oF
    scene_path: str             # resolved .glb on disk
    runtime_dataset_config: Optional[str]   # basis config, no semantics
    eval_dataset_config: Optional[str]      # annotated config, evaluator only
    start_position: Vec3        # Habitat world frame (y up)
    start_rotation_xyzw: Tuple[float, float, float, float]
    object_category: str
    stored_geodesic_m: Optional[float]      # info.geodesic_distance from the file
    goals: Tuple[ObjectGoal, ...] = field(default_factory=tuple)

    @property
    def uid(self) -> str:
        """Unique, stable id: set/split/scene/episode_id."""
        return '%s/%s/%s/%s' % (self.episode_set, self.split, self.scene_short, self.episode_id)

    @property
    def view_points(self) -> Tuple[Vec3, ...]:
        return tuple(vp for goal in self.goals for vp in goal.view_points)


def _load_gz(path: Path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def _vec(value, n, name) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != n:
        raise ValueError('%s must have %d numbers' % (name, n))
    out = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in out):
        raise ValueError('%s must be finite' % name)
    return out


def resolve_scene(habitat_data: Path, scene_id: str) -> Path:
    """Episode scene_id -> .glb on disk (episodes are relative to scene_datasets/)."""
    habitat_data = Path(habitat_data)
    candidates = [habitat_data / 'scene_datasets' / scene_id,
                  habitat_data / 'versioned_data/hm3d-0.2' / scene_id]
    if scene_id.startswith('hm3d_v0.2/'):
        candidates.append(habitat_data / HM3D_ROOT / scene_id.split('/', 1)[1])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('scene not found for scene_id %r' % scene_id)


def dataset_configs(habitat_data: Path, scene_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """(runtime basis config, evaluator annotated config) for one scene file."""
    habitat_data = Path(habitat_data)
    hm3d = (habitat_data / HM3D_ROOT).resolve()
    try:
        rel = scene_path.resolve().relative_to(hm3d)
    except ValueError:
        return None, None            # MP3D: Habitat's default dataset, semantics from .house
    part = rel.parts[0]              # val / minival / train
    runtime = hm3d / part / ('hm3d_%s_basis.scene_dataset_config.json' % part)
    annotated = hm3d / part / ('hm3d_annotated_%s_basis.scene_dataset_config.json' % part)
    return (str(runtime) if runtime.is_file() else None,
            str(annotated) if annotated.is_file() else None)


def _goals_for(goals_by_category: dict, scene_id: str, category: str) -> Tuple[ObjectGoal, ...]:
    key = '%s_%s' % (scene_id.rsplit('/', 1)[-1], category)
    goals = []
    for raw in goals_by_category.get(key, []):
        vps = tuple(_vec(v['agent_state']['position'], 3, 'view point') for v in raw.get('view_points', []))
        goals.append(ObjectGoal(int(raw.get('object_id', -1)), str(raw.get('object_category', category)),
                                _vec(raw['position'], 3, 'goal position'), vps))
    return tuple(goals)


def load_episode_set(episode_set: str, split: str, habitat_data: Path = DEFAULT_HABITAT_DATA,
                     *, scenes: Optional[Iterable[str]] = None) -> List[Episode]:
    """All episodes of one set/split, in file order (scene files sorted by name)."""
    if episode_set not in EPISODE_SETS:
        raise ValueError('unknown episode set %r (known: %s)' % (episode_set, ', '.join(EPISODE_SETS)))
    habitat_data = Path(habitat_data)
    dataset, version = EPISODE_SETS[episode_set]
    root = habitat_data / 'datasets/objectnav' / dataset / version / split
    top_path = root / ('%s.json.gz' % split)
    if not top_path.is_file():
        raise FileNotFoundError(top_path)
    wanted = None if scenes is None else set(scenes)
    sources = [_load_gz(top_path)]
    content = root / 'content'
    if content.is_dir():
        for path in sorted(content.glob('*.json.gz')):
            short = path.name.split('.')[0]
            if wanted is None or short in wanted:
                sources.append(_load_gz(path))
    episodes, seen, scene_cache = [], set(), {}
    for data in sources:
        goals_by_category = data.get('goals_by_category', {})
        for raw in data.get('episodes', []):
            scene_id = raw['scene_id']
            short = scene_id.rsplit('/', 1)[-1].split('.')[0]
            if wanted is not None and short not in wanted:
                continue
            if scene_id not in scene_cache:
                path = resolve_scene(habitat_data, scene_id)
                scene_cache[scene_id] = (path, dataset_configs(habitat_data, path))
            path, (runtime_cfg, eval_cfg) = scene_cache[scene_id]
            category = str(raw['object_category'])
            info = raw.get('info') or {}
            stored = info.get('geodesic_distance')
            episode = Episode(
                episode_set=episode_set, split=split, episode_id=str(raw['episode_id']),
                scene_id=scene_id, scene_short=short, scene_path=str(path),
                runtime_dataset_config=runtime_cfg, eval_dataset_config=eval_cfg,
                start_position=_vec(raw['start_position'], 3, 'start_position'),
                start_rotation_xyzw=_vec(raw['start_rotation'], 4, 'start_rotation'),
                object_category=category,
                stored_geodesic_m=None if stored is None else float(stored),
                goals=_goals_for(goals_by_category, scene_id, category))
            if episode.uid in seen:
                # HM3D v2 val repeats episode_id values inside one scene file.
                # Keep every episode (habitat-lab evaluates them all) and make
                # the uid unique with the occurrence number, in file order.
                n = 2
                while '%s#%d' % (episode.uid, n) in seen:
                    n += 1
                episode = replace(episode, episode_id='%s#%d' % (episode.episode_id, n))
            if not episode.view_points:
                raise ValueError('episode %s has no goal view points' % episode.uid)
            seen.add(episode.uid)
            episodes.append(episode)
    return episodes


def select(episodes: Sequence[Episode], *, categories: Optional[Iterable[str]] = None,
           limit: Optional[int] = None, per_scene: Optional[int] = None,
           seed: Optional[int] = None) -> List[Episode]:
    """Deterministic subset: filter by category, optional seeded shuffle, caps."""
    chosen = [e for e in episodes if categories is None or e.object_category in set(categories)]
    if seed is not None:
        chosen = sorted(chosen, key=lambda e: e.uid)
        random.Random(seed).shuffle(chosen)
    if per_scene is not None:
        counts: Dict[str, int] = {}
        kept = []
        for e in chosen:
            if counts.get(e.scene_short, 0) < per_scene:
                counts[e.scene_short] = counts.get(e.scene_short, 0) + 1
                kept.append(e)
        chosen = kept
    return chosen[:limit] if limit is not None else chosen


def write_manifest(episodes: Sequence[Episode], path: Path) -> None:
    """Freeze an episode list (dev/test split) as uids; re-loaded with ``read_manifest``."""
    Path(path).write_text(json.dumps({'schema_version': 1, 'uids': [e.uid for e in episodes]}, indent=1) + '\n')


def read_manifest(path: Path, episodes: Sequence[Episode]) -> List[Episode]:
    data = json.loads(Path(path).read_text())
    if data.get('schema_version') != 1:
        raise ValueError('unsupported manifest')
    by_uid = {e.uid: e for e in episodes}
    missing = [u for u in data['uids'] if u not in by_uid]
    if missing:
        raise ValueError('manifest names %d unknown episodes, e.g. %s' % (len(missing), missing[0]))
    return [by_uid[u] for u in data['uids']]
