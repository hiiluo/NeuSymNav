"""Select one native merge for an isolated synchronous A3 replay."""

from collections import Counter, defaultdict

from tools.psg_nav.probe_rgbd_continuity import supported_links


def select_merge(links, objects, aliases, cannot_link, *, revision):
    """Return retired/retained raw IDs backed by evidence available at revision."""
    blocked = set()
    for left, right in cannot_link:
        while left in aliases:
            left = aliases[left]
        while right in aliases:
            right = aliases[right]
        blocked.add(tuple(sorted((left, right))))

    witnesses = defaultdict(list)
    for link in links:
        first, second = link["first_revision"], link["second_revision"]
        if not 0 < second - first <= 24 or second > revision or first < revision - 48:
            continue
        mids = {rev for rev in link["intermediate_revisions"] if first < rev < second}
        if len(mids) < 2:
            continue
        left, right = link["first_native"], link["second_native"]
        if left not in objects or right not in objects or objects[left] == objects[right]:
            continue
        witnesses[tuple(sorted((left, right)))].append((first, second))

    admissible = supported_links(witnesses, blocked)
    claims = Counter(endpoint for pair in admissible for endpoint in pair)
    for left, right in sorted(admissible):
        if claims[left] == claims[right] == 1:
            older, newer = sorted((left, right), key=lambda raw: int(raw[2:-1]))
            return newer, older
    return None
