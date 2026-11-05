"""Hub-centred arrangement: when one node carries far more edges than any other, its top block takes the middle column
and every other top block may sit west, north, south or east of it.

A diagram with a hub reads best with the hub in the middle and its neighbours around it, so its lines leave in every
direction instead of fanning out one way across the page (the root-centred idea of a radial layout). The blocks keep
the orthogonal grid: the west and east columns flank the hub's column, and blocks above and below the hub in its own
column are its north and south. Placement (`tf_place`) picks each free block's column and slot for the fewest
crossings; this module only seeds them, alternating west and east by their edges to the hub.
"""

from collections import Counter
from typing import Any

from cartographer.tf_colors import FRAMES

HUB_LEAD = 2  # the hub has at least this many times the edges of the next busiest node
WEST, CENTRE, EAST = 0, 1, 2
Curated = dict[str, Any]


def hub(curated: Curated) -> str | None:
    """The node with at least HUB_LEAD times the edges of every other node or external, if there is one."""
    degree = Counter(end for e in curated["edges"] if e["src"] != e["dst"] for end in (e["src"], e["dst"]))
    ranked = degree.most_common(2)
    if not ranked or ranked[0][0] not in {n["id"] for n in curated["nodes"]}:
        return None
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    return ranked[0][0] if ranked[0][1] >= HUB_LEAD * runner_up else None


def centre(curated: Curated) -> tuple[Curated, frozenset[str]]:
    """The curated data with the hub's top block in the centre column and the other top blocks of its frame seeded
    west and east, and the ids of those other blocks, which placement may move between columns. Without a hub the data
    and no free block come back."""
    hub_id = hub(curated)
    if hub_id is None:
        return curated, frozenset()
    groups = {g["id"]: g for g in curated["groups"]}
    blocks = {gid for gid, g in groups.items() if g["kind"] not in FRAMES}

    def top(gid: str) -> str:
        while groups[gid]["parent"] in blocks:
            gid = groups[gid]["parent"]
        return gid

    hub_group = next(n["group"] for n in curated["nodes"] if n["id"] == hub_id)
    if hub_group not in blocks:
        return curated, frozenset()
    centre_id = top(hub_group)
    frame = groups[centre_id]["parent"]
    node_top = {n["id"]: top(n["group"]) for n in curated["nodes"] if n["group"] in blocks}
    ties = Counter(node_top.get(e["dst"] if e["src"] == hub_id else e["src"]) for e in curated["edges"]
                   if hub_id in (e["src"], e["dst"]))
    free = [g["id"] for g in curated["groups"] if g["id"] in blocks and g["parent"] == frame and g["id"] != centre_id]
    free.sort(key=lambda gid: -ties[gid])  # stable: ties keep the curated order
    column = {centre_id: CENTRE, **{gid: (WEST, EAST)[i % 2] for i, gid in enumerate(free)}}
    return {**curated, "groups": [{**g, "column": column.get(g["id"], g["column"])} for g in curated["groups"]]}, frozenset(free)
