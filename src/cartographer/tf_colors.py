"""Line colour is the colour of the destination: each top-level purpose group and each external has its own."""

from typing import Any

from cartographer.diagram_model import EDGE_DEFAULT

PALETTE = ("#1F77B4", "#D62728", "#2CA02C", "#9467BD", "#FF7F0E", "#8C564B", "#E377C2", "#008B8B", "#B8860B",
           "#6B8E23")
FRAMES = ("cloud", "region", "account")


class Colours:
    """Palette entries go to the purpose groups in column order, then to the externals, cycling; neighbours in that
    order differ."""

    def __init__(self, curated: dict[str, Any]) -> None:
        groups = {g["id"]: g for g in curated["groups"]}
        order = sorted((g for g in groups.values() if g["kind"] not in FRAMES
                        and (g["parent"] is None or groups[g["parent"]]["kind"] in FRAMES)), key=lambda g: g["column"])
        self._group = {g["id"]: PALETTE[i % len(PALETTE)] for i, g in enumerate(order)}
        for gid, g in groups.items():
            if g["kind"] not in FRAMES and gid not in self._group:
                self._group[gid] = self._group[self._top(groups, gid)]
        self._node = {n["id"]: self._group.get(n["group"], EDGE_DEFAULT) for n in curated["nodes"]}
        start = len(order)
        self._node |= {x["id"]: PALETTE[(start + i) % len(PALETTE)] for i, x in enumerate(curated["externals"])}

    @staticmethod
    def _top(groups: dict[str, Any], gid: str) -> str:
        while groups[gid]["parent"] is not None and groups[groups[gid]["parent"]]["kind"] not in FRAMES:
            gid = groups[gid]["parent"]
        return gid

    def group(self, gid: str) -> str | None:
        return self._group.get(gid)

    def node(self, nid: str) -> str:
        return self._node[nid]
