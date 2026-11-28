from tools.psg_nav.owner_admission import select_merge


def link(first, second, left="O(12)", right="O(17)"):
    return {
        "first_revision": first, "second_revision": second,
        "first_native": left, "second_native": right,
        "intermediate_revisions": [first + 1, first + 2],
    }


def test_requires_two_independent_available_witnesses():
    links = [link(101, 124), link(101, 132), link(110, 133)]
    objects = {"O(12)": 18, "O(17)": 51}
    assert select_merge(links, objects, {}, set(), revision=132) is None
    assert select_merge(links, objects, {}, set(), revision=133) == ("O(17)", "O(12)")
    assert select_merge(links, {"O(12)": 18}, {}, set(), revision=133) is None


def test_checks_cannot_link_across_canonical_components():
    links = [link(101, 124), link(110, 133)]
    objects = {"O(12)": 18, "O(17)": 51}
    aliases = {"O(4)": "O(12)"}
    assert select_merge(links, objects, aliases, {("O(4)", "O(17)")}, revision=133) is None
    assert select_merge(links, objects, {}, {("O(12)", "O(17)")}, revision=133) is None
    assert select_merge(links, {"O(12)": 18, "O(17)": 18}, {}, set(), revision=133) is None


def test_shared_witnesses_through_a_retired_endpoint_cannot_support_new_pair():
    links = [link(101, 124), link(110, 133, left="O(4)")]
    objects = {"O(12)": 18, "O(17)": 51}
    assert select_merge(links, objects, {"O(4)": "O(12)"}, set(), revision=133) is None


def test_rejects_competing_pairs_and_expired_evidence():
    links = [link(101, 124), link(110, 133),
             link(102, 125, right="O(19)"), link(111, 134, right="O(19)")]
    objects = {"O(12)": 18, "O(17)": 51, "O(19)": 25}
    assert select_merge(links, objects, {}, set(), revision=134) is None
    assert select_merge(links, objects, {}, set(), revision=160) is None
