"""Admit live merges or recent owner-certified tombstone reconciliations."""

from neusymnav.contracts.hydra_lineage import MAX_RECONCILE_AGE
from tools.psg_nav.owner_admission import select_merge


def select_owner_request(links, objects, tombstones, aliases, cannot_link, *, revision):
    """Return source, target and whether the source is a retired raw ID."""
    retired = {raw: label for raw, (label, stamp) in tombstones.items()
               if 0 <= revision - stamp < MAX_RECONCILE_AGE and raw not in aliases and raw not in objects}
    visible = {**objects, **retired}

    def eligible(link):
        first, second = link["first_native"], link["second_native"]
        if first in objects and second in objects:
            return True
        return (first in retired and second in objects and int(first[2:-1]) < int(second[2:-1])
                and link["first_revision"] < tombstones[first][1])

    pair = select_merge((link for link in links if eligible(link)), visible, aliases, cannot_link,
                        revision=revision)
    if pair is None:
        return None
    newer, older = pair
    return (older, newer, True) if older in retired else (newer, older, False)
