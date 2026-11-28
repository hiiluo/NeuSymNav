import numpy as np

from tools.psg_nav.probe_temporal_identity import propose_temporal_links


def surface(offset=0.0):
    return np.array([(offset + i * .02, j * .02, 0.) for i in range(4) for j in range(4)])


def test_cross_revision_proposal_requires_two_distinct_confirmations():
    track = surface()
    rows = [(1, {"O(1)": track}, ()), (2, {"O(2)": track}, ()),
            (3, {"O(2)": track}, ())]
    assert not propose_temporal_links(rows[:2])
    assert propose_temporal_links(rows) == {("O(1)", "O(2)"): (2, 3)}


def test_cannot_link_survives_disappearance_and_blocks_later_support():
    track = surface()
    rows = [(1, {"O(1)": track}, (("O(1)", "O(2)"),)),
            (2, {"O(2)": track}, ()), (3, {"O(2)": track}, ())]
    assert not propose_temporal_links(rows)


def test_expired_surface_and_competing_matches_abstain():
    track = surface()
    assert not propose_temporal_links([
        (1, {"O(1)": track}, ()), (14, {"O(2)": track}, ()), (15, {"O(2)": track}, ())
    ])
    assert not propose_temporal_links([
        (1, {"O(1)": track, "O(3)": track}, ()),
        (2, {"O(2)": track}, ()), (3, {"O(2)": track}, ())
    ])
