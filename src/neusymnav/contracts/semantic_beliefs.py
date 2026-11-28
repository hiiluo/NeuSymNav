"""Read-only hard-vote beliefs over a pinned semantic vocabulary."""

from dataclasses import dataclass
from math import fsum, log
from typing import NamedTuple

from .observations import FrameKey


class VoteKey(NamedTuple):
    run_id: str
    source: FrameKey
    detection_id: str


@dataclass(frozen=True)
class ObjectSemanticBelief:
    object_key: object
    vocabulary_id: str
    vocabulary: tuple[str, ...]
    counts: tuple[tuple[str, int], ...]
    top_k: int
    first_observed_ns: int | None = None
    last_observed_ns: int | None = None
    source_revision: int | None = None
    status: str = 'available'
    reason: str | None = None
    method: str = 'hard_votes_v1'
    schema_version: int = 1

    @property
    def observation_count(self):
        return sum(n for _, n in self.counts)

    @property
    def distribution(self):
        total = self.observation_count
        return tuple((category, n / total) for category, n in self.counts) if total else None

    @property
    def top_hypotheses(self):
        distribution = self.distribution
        return () if distribution is None else tuple(sorted(distribution, key=lambda row: (-row[1], row[0])))[:self.top_k]

    @property
    def most_likely_category(self):
        return self.top_hypotheses[0][0] if self.counts else None

    @property
    def entropy_nats(self):
        distribution = self.distribution
        return None if distribution is None else -fsum(p * log(p) for _, p in distribution)

    def probability(self, category):
        if category not in self.vocabulary:
            raise ValueError('category is outside the belief vocabulary')
        distribution = self.distribution
        return None if distribution is None else dict(distribution).get(category, 0.)
