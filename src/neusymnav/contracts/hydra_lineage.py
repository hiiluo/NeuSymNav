"""Strict wire format for raw native object-owner events."""
from dataclasses import asdict, dataclass
import re

from .hydra_graph import HydraReadToken


MAX_OBJECT_EVENTS = 4096
MAX_RECONCILE_AGE = 24
_NODE = re.compile(r'O\((?:0|[1-9][0-9]{0,16})\)')


def object_id(value):
    if (not isinstance(value, str) or not _NODE.fullmatch(value)
            or int(value[2:-1]) >= 1 << 56):
        raise ValueError('expected Hydra raw object ID')
    return value


@dataclass(frozen=True)
class NativeObjectEvent:
    owner: str
    operation: str
    source: str
    target: str = None

    def __post_init__(self):
        if self.owner not in ('frontend', 'backend') or self.operation not in (
                'create', 'delete', 'merge', 'reconcile'):
            raise ValueError('unknown native object event')
        if self.owner == 'backend' and self.operation != 'merge':
            raise ValueError('backend object event must be a merge')
        object_id(self.source)
        if self.operation in ('merge', 'reconcile'):
            if object_id(self.target) == self.source:
                raise ValueError('self merge is invalid')
        elif self.target is not None:
            raise ValueError('only alias events have a target')


@dataclass(frozen=True)
class NativeObjectBatch:
    token: HydraReadToken
    timestamp_ns: int
    epoch: int
    events: tuple

    @classmethod
    def from_wire(cls, wire, *, token, timestamp_ns):
        if not isinstance(wire, dict) or set(wire) != {'input_prefix_sha256', 'native'}:
            raise ValueError('invalid native object journal envelope')
        raw = wire['native']
        if not isinstance(raw, dict) or set(raw) != {'schema_version', 'status', 'epoch', 'step', 'timestamp_ns', 'events'}:
            raise ValueError('invalid native object journal batch')
        if (wire['input_prefix_sha256'] != token.input_prefix_sha256 or raw['status'] != 'complete'
                or type(raw['schema_version']) is not int or raw['schema_version'] not in (1, 2)
                or type(raw['step']) is not int or raw['step'] != token.graph_revision
                or type(raw['timestamp_ns']) is not int or raw['timestamp_ns'] != timestamp_ns
                or not isinstance(raw['events'], list) or len(raw['events']) > MAX_OBJECT_EVENTS):
            raise ValueError('native object journal does not bind the accepted revision')
        if any(not isinstance(event, dict) or set(event) != {'owner', 'operation', 'source', 'target'}
               for event in raw['events']):
            raise ValueError('invalid native object event fields')
        batch = cls(token, timestamp_ns, raw['epoch'],
                    tuple(NativeObjectEvent(**event) for event in raw['events']))
        if raw['schema_version'] != batch.schema_version:
            raise ValueError('journal schema does not match its alias events')
        return batch

    def __post_init__(self):
        if (not isinstance(self.token, HydraReadToken) or self.token.graph_revision < 1
                or type(self.timestamp_ns) is not int or not 0 <= self.timestamp_ns < 1 << 64
                or type(self.epoch) is not int or not 1 <= self.epoch < 1 << 64
                or not isinstance(self.events, tuple) or len(self.events) > MAX_OBJECT_EVENTS
                or any(not isinstance(event, NativeObjectEvent) for event in self.events)):
            raise ValueError('invalid native object journal batch')

    @property
    def graph_revision(self):
        return self.token.graph_revision

    @property
    def schema_version(self):
        return 2 if any(event.operation == 'reconcile' for event in self.events) else 1

    def to_wire(self):
        return {
            'input_prefix_sha256': self.token.input_prefix_sha256,
            'native': dict(schema_version=self.schema_version, status='complete', epoch=self.epoch,
                           step=self.graph_revision, timestamp_ns=self.timestamp_ns,
                           events=[asdict(event) for event in self.events]),
        }
