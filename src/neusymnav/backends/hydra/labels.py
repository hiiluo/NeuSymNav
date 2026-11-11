"""Deterministic predicted semantic raster and matching Hydra labelspace."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from ...contracts.observations import (DetectionBatch, Observation, Taxonomy,
                                      validate_detection_batch)


@dataclass(frozen=True)
class HydraSemanticLabels:
    labels: np.ndarray
    labelspace_id: str
    labelspace_hash: str
    class_to_label: dict[str, int]
    object_labels: frozenset[int]
    invalid_labels: frozenset[int]


class HydraLabelRasterizer:
    """Rasterize existing YOLOE masks; this class never invokes a detector."""

    LABELSPACE_ID = 'neusymnav:hydra-labelspace:v1'
    UNKNOWN_LABEL = 0
    INVALID_LABEL = 1
    FIRST_CATEGORY_LABEL = 2

    def __init__(self, taxonomy: Taxonomy):
        if not isinstance(taxonomy, Taxonomy):
            raise ValueError('taxonomy must be a versioned Taxonomy')
        self.taxonomy = taxonomy
        self.class_to_label = {
            category: self.FIRST_CATEGORY_LABEL + index
            for index, category in enumerate(taxonomy.categories)
        }
        payload = {
            'schema': self.LABELSPACE_ID,
            'vocabulary_id': taxonomy.vocabulary_id,
            'taxonomy_provenance': taxonomy.provenance,
            'categories': list(taxonomy.categories),
            'unknown': {'id': self.UNKNOWN_LABEL, 'name': 'unknown_static'},
            'invalid': {'id': self.INVALID_LABEL, 'name': 'invalid'},
            'class_to_label': self.class_to_label,
            'object_labels': sorted(self.class_to_label.values()),
            'invalid_labels': [self.INVALID_LABEL],
        }
        self._payload = payload
        self.labelspace_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        ).hexdigest()

    def rasterize(self, observation: Observation, batch: DetectionBatch) -> HydraSemanticLabels:
        validate_detection_batch(observation, batch)
        if batch.vocabulary_id != self.taxonomy.vocabulary_id:
            raise ValueError('batch vocabulary mismatch with pinned taxonomy')

        shape = observation.depth_m.shape
        labels = np.zeros(shape, dtype=np.int32)
        claimed = np.zeros(shape, dtype=np.bool_)
        # Sorting before painting makes the result independent of detector batch order.
        # Unknown detections still claim pixels and therefore occlude lower-ranked masks.
        detections = sorted(batch.detections, key=lambda item: (-item.score, item.detection_id))
        for detection in detections:
            mask = detection.mask & ~claimed
            canonical = (self.taxonomy.canonicalize(detection.category)
                         if detection.category is not None else None)
            if canonical is None:
                canonical = self.taxonomy.canonicalize(detection.raw_label)
            label = self.class_to_label.get(canonical, self.UNKNOWN_LABEL)
            labels[mask] = label
            claimed |= detection.mask

        # Invalid/no-return/far-plane depth must never be integrated as an object or
        # unknown static surface. H2 converts its metric depth value to Hydra's NaN.
        labels[~observation.valid_depth] = self.INVALID_LABEL
        labels.setflags(write=False)
        return HydraSemanticLabels(
            labels=labels,
            labelspace_id=self.LABELSPACE_ID,
            labelspace_hash=self.labelspace_hash,
            class_to_label=dict(self.class_to_label),
            object_labels=frozenset(self.class_to_label.values()),
            invalid_labels=frozenset({self.INVALID_LABEL}),
        )

    def write_labelspace(self, path: str | Path) -> Path:
        """Write the native Hydra YAML configuration for these semantic IDs."""
        path = Path(path)
        names = {self.UNKNOWN_LABEL: 'unknown_static', self.INVALID_LABEL: 'invalid'}
        names.update({label: category for category, label in self.class_to_label.items()})
        lines = [
            f'# Generated from {self.taxonomy.vocabulary_id}; do not edit by hand.',
            f'# NeuSymNav labelspace id: {self.LABELSPACE_ID}',
            f'# NeuSymNav labelspace SHA256: {self.labelspace_hash}',
            f'total_semantic_labels: {len(self.class_to_label) + self.FIRST_CATEGORY_LABEL}',
            'dynamic_labels: []',
            'invalid_labels: [1]',
            'object_labels: [' + ', '.join(str(i) for i in sorted(self.class_to_label.values())) + ']',
            'surface_places_labels: []',
            'label_names:',
        ]
        for label, name in sorted(names.items()):
            escaped = json.dumps(name, ensure_ascii=False)
            lines.append(f'  - {{label: {label}, name: {escaped}}}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return path
