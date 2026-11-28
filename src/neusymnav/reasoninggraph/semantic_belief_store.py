"""Single-writer belief publication on consecutive, authoritative Hydra revisions."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import islice
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from types import MappingProxyType

from ..contracts.hydra_evidence import ObservationEvidence
from ..contracts.hydra_graph import HydraReadToken
from ..contracts.hydra_lineage import NativeObjectBatch, object_id
from ..contracts.observations import FrameKey, Taxonomy
from ..contracts.reasoninggraph import GraphReadToken
from .association_receipts import CategoryVoteReceipt, lineage_digest
from .lifecycle import validate_progress
from .native_lineage import CanonicalObjectId, ObjectLineageView
from .semantic_beliefs import summarize_votes, validate_vote
from .store import _read


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def receipt_from_wire(raw):
    payload = dict(raw)
    source = dict(payload.pop('source_token'))
    token = GraphReadToken(native=HydraReadToken(**source.pop('native')),
                           source=FrameKey(**source.pop('source')), **source)
    evidence = dict(payload.pop('evidence'))
    ref = ObservationEvidence(source=FrameKey(**evidence.pop('source')), **evidence)
    return CategoryVoteReceipt(token, CanonicalObjectId(**payload.pop('canonical_object')),
                               evidence=ref, **payload)


def _resolve(raw, aliases):
    visited = set()
    while raw in aliases:
        if raw in visited:
            raise ValueError('cyclic owner alias')
        visited.add(raw)
        raw = aliases[raw]
    return raw


def _vote_order(key):
    return key.run_id, key.source.episode_id, key.source.sensor_id, key.source.frame_index, key.detection_id


@dataclass(frozen=True)
class SemanticBeliefView:
    token: GraphReadToken
    lineage: ObjectLineageView
    taxonomy: Taxonomy
    _groups: MappingProxyType

    def evidence(self, raw):
        endpoint = _resolve(raw, self.lineage.aliases)
        return self._groups.get(endpoint, ()) if endpoint in self.lineage.objects else ()

    def belief(self, raw, *, top_k=5):
        endpoint = _resolve(raw, self.lineage.aliases)
        identity = self.lineage.objects.get(endpoint)
        return None if identity is None else summarize_votes(
            self.taxonomy, identity, self._groups.get(endpoint, ()), top_k=top_k)


class SemanticBeliefStore:
    def __init__(self, taxonomy, *, max_receipts=16384, max_payload_bytes=16 * 1024**2,
                 native_is_current=None):
        if not isinstance(taxonomy, Taxonomy):
            raise TypeError('expected Taxonomy')
        if (type(max_receipts) is not int or not 1 <= max_receipts <= 16384
                or type(max_payload_bytes) is not int or not 1 <= max_payload_bytes <= 16 * 1024**2
                or (native_is_current is not None and not callable(native_is_current))):
            raise ValueError('invalid belief limits or freshness reader')
        self.taxonomy = taxonomy
        self._max_receipts, self._max_bytes = max_receipts, max_payload_bytes
        self._current = native_is_current or (lambda _: True)
        self._lock = RLock()
        self._view = None
        self._ledger = {}
        self._aliases = {}
        self._last_keys = ()
        self._last_journal = None
        self._lost = False

    def _valid(self, token, lineage):
        return (isinstance(token, GraphReadToken) and token.vocabulary_id == self.taxonomy.vocabulary_id
                and isinstance(lineage, ObjectLineageView) and lineage.token == token.native
                and bool(token.native.source_sha256 and token.native.build_sha256 and token.native.config_sha256))

    def _snapshot(self, token, lineage, ledger, aliases):
        groups = defaultdict(list)
        for key in sorted(ledger, key=_vote_order):
            receipt, valid = ledger[key]
            if valid:
                endpoint = _resolve(receipt.canonical_object.native_id, aliases)
                if endpoint in lineage.objects:
                    groups[endpoint].append(receipt)
        return SemanticBeliefView(token, lineage, self.taxonomy,
                                  MappingProxyType({key: tuple(values) for key, values in groups.items()}))

    def _payload(self, view, ledger, aliases, last, journal):
        return _encode({"schema_version": 1, "token": asdict(view.token), "lineage": lineage_digest(view.lineage),
                        "vocabulary": self.taxonomy.categories, "taxonomy": self.taxonomy.to_dict(),
                        "aliases": aliases, "last_revision": [asdict(ledger[key][0]) for key in last],
                        "journal": journal.to_wire(),
                        "receipts": [{"receipt": asdict(ledger[key][0]), "valid": ledger[key][1]}
                                     for key in sorted(ledger, key=_vote_order)]})

    def apply_revision(self, token, lineage, receipts, *, revision_complete, journal):
        with self._lock:
            if self._lost or not isinstance(token, GraphReadToken) or not self._current(token.native):
                return False
            old = self._view
            if old is not None and token.native.graph_revision < old.token.native.graph_revision:
                return False
            if (revision_complete is not True or not self._valid(token, lineage)
                    or not isinstance(journal, NativeObjectBatch) or journal.token != token.native
                    or journal.epoch != lineage.epoch or journal.timestamp_ns != token.capture_monotonic_ns):
                self._lost = True
                return False
            try:
                entries = {}
                incoming = tuple(islice(receipts, 257))
                if len(incoming) > 256:
                    return False
                lineage_sha = lineage_digest(lineage) if incoming else None
                for receipt in incoming:
                    key = validate_vote(self.taxonomy, receipt)
                    if (receipt.source_token != token or lineage.objects.get(receipt.canonical_object.native_id)
                            != receipt.canonical_object or receipt.evidence.native_lineage_sha256 != lineage_sha
                            or entries.get(key, receipt) != receipt
                            or (key in self._ledger and self._ledger[key][0] != receipt)):
                        return False
                    entries[key] = receipt
                last = tuple(sorted(entries, key=_vote_order))
                if old is not None and token == old.token:
                    return old.lineage == lineage and last == self._last_keys and journal == self._last_journal
                prior_revision = old.token.native.graph_revision if old is not None else 0
                if token.native.graph_revision != prior_revision + 1:
                    self._lost = True
                    return False
                if old is not None:
                    validate_progress(old.token, token)
                    if old.lineage.epoch != lineage.epoch:
                        self._lost = True
                        return False

                aliases = dict(self._aliases)
                invalid = set()
                for event in journal.events:
                    if event.operation in ('merge', 'reconcile') and lineage.aliases.get(event.source) != event.target:
                        return False
                    if event.operation == 'reconcile':
                        aliases[event.source] = event.target
                    elif event.operation == 'merge':
                        invalid.update((event.source, event.target))
                if any(receipt.canonical_object.native_id in invalid for receipt in entries.values()):
                    return False
                ledger = {key: (receipt, prior and _resolve(receipt.canonical_object.native_id, aliases) not in invalid)
                          for key, (receipt, prior) in self._ledger.items()}
                ledger.update({key: (receipt, True) for key, receipt in entries.items()})
                if len(ledger) > self._max_receipts:
                    return False
                view = self._snapshot(token, lineage, ledger, aliases)
                if len(self._payload(view, ledger, aliases, last, journal)) > self._max_bytes or not self._current(token.native):
                    return False
            except (TypeError, ValueError, AttributeError):
                return False
            self._view, self._ledger, self._aliases = view, ledger, aliases
            self._last_keys, self._last_journal = last, journal
            return True

    def read(self, token):
        with self._lock:
            view = self._view
            native = token.native if isinstance(token, GraphReadToken) else token
            if (self._lost or view is None or view.token.native != native or not self._current(native)
                    or (isinstance(token, GraphReadToken) and token != view.token)):
                return None
            return view

    def seal(self, path, token):
        path = Path(path)
        with self._lock:
            view = self.read(token)
            if view is None:
                raise ValueError('cannot seal unavailable belief state')
            payload = self._payload(view, self._ledger, self._aliases, self._last_keys, self._last_journal)
        with NamedTemporaryFile('wb', dir=path.parent) as staged:
            staged.write(payload)
            staged.flush()
            os.fsync(staged.fileno())
            try:
                os.link(staged.name, path)
            except FileExistsError:
                if _read(path, self._max_bytes) != payload:
                    raise ValueError('belief path already seals different state') from None
        return sha256(payload).hexdigest()

    def restore(self, path, expected_token, expected_sha256, *, lineage):
        with self._lock:
            try:
                if not self._valid(expected_token, lineage) or not self._current(expected_token.native):
                    return False
                payload = _read(Path(path), self._max_bytes)
                if sha256(payload).hexdigest() != expected_sha256:
                    return False
                raw = json.loads(payload)
                if (raw["schema_version"] != 1 or raw["token"] != asdict(expected_token)
                        or raw["lineage"] != lineage_digest(lineage) or raw["taxonomy"] != self.taxonomy.to_dict()
                        or len(raw["receipts"]) > self._max_receipts or len(raw["last_revision"]) > 256):
                    return False
                journal = NativeObjectBatch.from_wire(raw["journal"], token=expected_token.native,
                                                      timestamp_ns=expected_token.capture_monotonic_ns)
                if journal.epoch != lineage.epoch:
                    return False
                ledger = {}
                for entry in raw["receipts"]:
                    receipt = receipt_from_wire(entry["receipt"])
                    key = validate_vote(self.taxonomy, receipt)
                    validate_progress(receipt.source_token, expected_token)
                    if (key in ledger or type(entry["valid"]) is not bool
                            or receipt.canonical_object.epoch != lineage.epoch):
                        return False
                    ledger[key] = (receipt, entry["valid"])
                aliases = raw["aliases"]
                if any(lineage.aliases.get(object_id(k)) != object_id(v) for k, v in aliases.items()):
                    return False
                last = tuple(validate_vote(self.taxonomy, receipt_from_wire(item)) for item in raw["last_revision"])
                view = self._snapshot(expected_token, lineage, ledger, aliases)
                if self._payload(view, ledger, aliases, last, journal) != payload:
                    return False
                if self._view is not None and self._payload(self._view, self._ledger, self._aliases,
                                                           self._last_keys, self._last_journal) != payload:
                    return False
                if not self._current(expected_token.native):
                    return False
            except (OSError, TypeError, ValueError, KeyError, AttributeError, RecursionError):
                return False
            self._view, self._ledger, self._aliases = view, ledger, aliases
            self._last_keys, self._last_journal, self._lost = last, journal, False
            return True
