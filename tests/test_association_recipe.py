import math

import pytest

from neusymnav.objects.association_recipe import AssociationRecipe


def test_recipe_roundtrip_and_legacy_default():
    assert AssociationRecipe.from_mapping(None).mode == 'legacy'
    recipe = AssociationRecipe.from_mapping({'mode': 'conceptgraphs'})
    assert recipe.nn_distance_m == .03
    assert AssociationRecipe.from_mapping(recipe.to_dict()) == recipe


@pytest.mark.parametrize('value', [
    {}, {'mode': 'bad'}, {'mode': []}, {'mode': 'legacy', 'nn_distance_m': .08},
    {'mode': 'conceptgraphs', 'nn_distance_m': math.nan},
    {'mode': 'conceptgraphs', 'max_points': True},
    {'mode': 'conceptgraphs', 'max_points': 4097},
    {'mode': 'conceptgraphs', 'physical_bias': 1.1},
    {'mode': 'conceptgraphs', 'match_threshold': 0},
    {'mode': 'conceptgraphs', 'min_spatial': -.1},
    {'mode': 'conceptgraphs', 'unknown': 3},
])
def test_recipe_rejects_invalid_configuration(value):
    with pytest.raises(ValueError):
        AssociationRecipe.from_mapping(value)


def test_recipe_numeric_spelling_has_identical_durable_identity():
    assert AssociationRecipe.from_mapping({'mode': 'conceptgraphs', 'physical_bias': 0}).durable_dict() == AssociationRecipe(mode='conceptgraphs').durable_dict()
    import json
    assert json.dumps(AssociationRecipe(mode='conceptgraphs', physical_bias=0).durable_dict(), sort_keys=True) == json.dumps(AssociationRecipe(mode='conceptgraphs').durable_dict(), sort_keys=True)
