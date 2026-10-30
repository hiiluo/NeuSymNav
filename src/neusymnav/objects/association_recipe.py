"""Immutable, durable association recipe; legacy is the default."""
from dataclasses import asdict, dataclass
import math
from collections.abc import Mapping


@dataclass(frozen=True)
class AssociationRecipe:
    mode: str = 'legacy'
    nn_distance_m: float = .03
    voxel_m: float = .03
    max_points: int = 4096
    physical_bias: float = 0.
    match_threshold: float = .55
    ambiguity_margin: float = .08
    min_spatial: float = .10

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in {'legacy', 'conceptgraphs'}:
            raise ValueError('unsupported association mode')
        for name, lo, hi in (
            ('nn_distance_m', 0., .10), ('voxel_m', 0., .10),
            ('physical_bias', -1., 1.), ('match_threshold', 0., 1.),
            ('ambiguity_margin', 0., 1.), ('min_spatial', 0., 1.),
        ):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError('invalid association ' + name)
            if name in {'nn_distance_m', 'voxel_m', 'match_threshold'} and value == 0:
                raise ValueError('association ' + name + ' must be positive')
            object.__setattr__(self, name, float(value))
        if type(self.max_points) is not int or not 1 <= self.max_points <= 4096:
            raise ValueError('association max_points must be integer1..4096')
        if self.mode == 'legacy':
            defaults = dict(nn_distance_m=.03, voxel_m=.03, max_points=4096,
                            physical_bias=0., match_threshold=.55,
                            ambiguity_margin=.08, min_spatial=.10)
            if any(getattr(self, k) != v for k, v in defaults.items()):
                raise ValueError('legacy association parameters cannot change')

    @classmethod
    def from_mapping(cls, value=None):
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping) or 'mode' not in value:
            raise ValueError('association requires explicit mode')
        if set(value) - set(cls.__dataclass_fields__):
            raise ValueError('unknown association recipe fields')
        return cls(**value)

    def to_dict(self):
        return asdict(self)

    def durable_dict(self):
        return dict(schema_version=1, recipe_id='neusymnav:association:' + self.mode + ':v1',
                    mixed_features='row-spatial-fallback', **self.to_dict())
