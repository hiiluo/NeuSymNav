from tools.psg_nav.retirement_admission import select_owner_request


def witnesses():
    return [
        {"first_revision": start, "second_revision": end, "first_native": "O(0)", "second_native": "O(5)",
         "intermediate_revisions": [start + 1, start + 2]}
        for start, end in ((1, 21), (3, 24))
    ]


def test_retired_endpoint_can_resolve_to_live_successor_without_resurrection():
    obs = witnesses()
    live = {"O(5)": 51}
    tombstones = {"O(0)": (40, 21)}
    assert select_owner_request(obs, live, tombstones, {}, set(), revision=23) is None
    assert select_owner_request(obs, live, tombstones, {}, set(), revision=24) == ("O(0)", "O(5)", True)
    assert select_owner_request(obs, live, tombstones, {}, {("O(0)", "O(5)")}, revision=24) is None
    assert select_owner_request(obs, {"O(5)": 40}, tombstones, {}, set(), revision=24) is None


def test_rejects_two_retired_endpoints_and_live_to_retired_reversal():
    obs = witnesses()
    assert select_owner_request(obs, {}, {"O(0)": (40, 21), "O(5)": (51, 24)}, {}, set(), revision=24) is None
    assert select_owner_request(obs, {"O(0)": 40}, {"O(5)": (51, 24)}, {}, set(), revision=24) is None
