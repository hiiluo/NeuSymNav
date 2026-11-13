"""Frozen detector-label -> ObjectNav goal-category mapping."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_MAPPING = Path(__file__).resolve().parents[4] / 'configs/objectnav/goal-categories-v1.json'


class GoalCategories:
    def __init__(self, data: dict, dataset: str = 'hm3d'):
        if data.get('schema_version') != 1:
            raise ValueError('goal category mapping needs schema_version 1')
        table = data.get(dataset)
        if not isinstance(table, dict) or not table:
            raise ValueError('mapping has no %r table' % dataset)
        self.name = data['name']
        self.dataset = dataset
        self.labels: Dict[str, List[str]] = {c: list(v) for c, v in table.items()}
        self.near_miss: Dict[str, List[str]] = {c: list(v) for c, v in data.get('near_miss', {}).items()}
        owner: Dict[str, str] = {}
        for category, labels in self.labels.items():
            for label in labels:
                if label in owner and dataset == 'hm3d':
                    raise ValueError('label %r maps to two goal categories' % label)
                owner[label] = category
        self._owner = owner

    @classmethod
    def load(cls, path: Path = DEFAULT_MAPPING, dataset: str = 'hm3d') -> 'GoalCategories':
        return cls(json.loads(Path(path).read_text()), dataset)

    @property
    def categories(self) -> List[str]:
        return sorted(self.labels)

    def goal_category(self, detector_label: str) -> Optional[str]:
        return self._owner.get(detector_label)

    def is_near_miss(self, category: str, detector_label: str) -> bool:
        return detector_label in self.near_miss.get(category, [])
