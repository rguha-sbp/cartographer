"""Crossing-aware placement: the orders of nodes, blocks and externals whose straight lines cross least.

The objective of a placement is the number of proper crossings between the straight centre-to-centre lines of its
edges plus their total length, weighed at a given number of pixels per crossing. Barycentric sweeps (`tf_order`) give
a start; a greedy local search then tries every swap of two nodes in one block, two blocks in one column slot and two
externals in one lane, every move of an external to the other lane, and every slot for a block whose column is open
(`column` None, see `tf_aws_externals`), keeping each change that lowers the objective, until a whole sweep finds
none. Every candidate is a full placement by the caller's `build`, so the objective sees the real grid.
"""

from collections.abc import Callable, Iterator
from itertools import combinations
from typing import Any

from cartographer.diagram_model import Diagram
from cartographer.tf_colors import FRAMES
from cartographer.tf_lanes import split
from cartographer.tf_order import centres, reorder

PASSES = 4  # barycentric sweeps before the local search
SWEEPS = 30  # the local search stops after this many sweeps even if one still improves
Curated = dict[str, Any]
Build = Callable[[Curated], Diagram]
Move = Callable[[Curated], Curated | None]


def _side(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> int:
    v = (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    return (v > 0) - (v < 0)


def _cross(p: tuple, q: tuple) -> bool:
    """Whether two segments cross at a point inside both; segments sharing an end never do."""
    (a, b), (c, d) = p, q
    if {a, b} & {c, d}:
        return False
    return _side(a, b, c) * _side(a, b, d) < 0 and _side(c, d, a) * _side(c, d, b) < 0


def objective(diagram: Diagram, px_per_crossing: float) -> float:
    """Crossings between the edges drawn as straight lines between node centres, plus their total length at
    `px_per_crossing` pixels of line per crossing."""
    pos = centres(diagram)
    lines = [(pos[e.src], pos[e.dst]) for e in diagram.edges if e.src != e.dst]
    length = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in lines)
    return sum(_cross(p, q) for p, q in combinations(lines, 2)) + length / px_per_crossing


def _tops(curated: Curated) -> list[dict]:
    """Blocks placed straight in the innermost frame: those whose parent is not a block."""
    blocks = {g["id"] for g in curated["groups"] if g["kind"] not in FRAMES}
    return [g for g in curated["groups"] if g["kind"] not in FRAMES and g["parent"] not in blocks]


def _block_slot(curated: Curated) -> Callable[[dict], Any]:
    """Blocks that may trade places: top blocks of one column, or children of one block."""
    top = {g["id"] for g in _tops(curated)}
    return lambda g: ("col", g["column"]) if g["id"] in top else ("in", g["parent"])


def _lane_slot(curated: Curated) -> Callable[[dict], Any]:
    left = {x["id"] for x in split(curated)[0]}
    return lambda x: x["id"] in left


def _node_slot(_: Curated) -> Callable[[dict], Any]:
    return lambda n: n["group"]


SLOTS = {"groups": _block_slot, "nodes": _node_slot, "externals": _lane_slot}


def _swap(key: str, a: str, b: str) -> Move:
    """Swap the items with ids a and b, if they still share a slot."""
    def move(c: Curated) -> Curated | None:
        items = list(c[key])
        i, j = (next(k for k, it in enumerate(items) if it["id"] == x) for x in (a, b))
        slot = SLOTS[key](c)
        if slot(items[i]) != slot(items[j]):
            return None
        items[i], items[j] = items[j], items[i]
        return {**c, key: items}
    return move


def _swaps(curated: Curated, key: str) -> Iterator[Move]:
    slot = SLOTS[key](curated)
    for p, q in combinations(curated[key], 2):
        if slot(p) == slot(q):
            yield _swap(key, p["id"], q["id"])


def _relocate(bid: str, column: int, before: str | None) -> Move:
    """Move a block into `column`, in front of block `before` (None: at the bottom of the column)."""
    def move(c: Curated) -> Curated:
        block = next(g for g in c["groups"] if g["id"] == bid)
        rest = [g for g in c["groups"] if g["id"] != bid]
        at = next((k for k, g in enumerate(rest) if g["id"] == before), len(rest))
        return {**c, "groups": [*rest[:at], {**block, "column": column}, *rest[at:]]}
    return move


def _relocations(curated: Curated, open_ids: set[str]) -> Iterator[Move]:
    tops = _tops(curated)
    for bid in sorted(open_ids):
        for column in sorted({g["column"] for g in tops}):
            members = [g["id"] for g in tops if g["column"] == column and g["id"] != bid]
            for before in [*members, None]:
                yield _relocate(bid, column, before)


def _flip(xid: str) -> Move:
    """Move an external to the other lane."""
    def move(c: Curated) -> Curated:
        left = {x["id"] for x in split(c)[0]}
        return {**c, "externals": [{**x, "lane": "right" if xid in left else "left"} if x["id"] == xid else x
                                   for x in c["externals"]]}
    return move


def _moves(curated: Curated, open_ids: set[str]) -> Iterator[Move]:
    yield from _relocations(curated, open_ids)
    yield from (_flip(x["id"]) for x in curated["externals"])
    for key in SLOTS:
        yield from _swaps(curated, key)


def _opened(curated: Curated) -> tuple[Curated, set[str]]:
    """Blocks with an open column start in the last column; the search then picks their slot."""
    open_ids = {g["id"] for g in curated["groups"] if g["kind"] not in FRAMES and g.get("column", 0) is None}
    last = max((g["column"] for g in curated["groups"] if g["id"] not in open_ids), default=0)
    groups = [{**g, "column": last} if g["id"] in open_ids else g for g in curated["groups"]]
    return {**curated, "groups": groups}, open_ids


def place(curated: Curated, build: Build, px_per_crossing: float) -> Curated:
    """The curated data reordered (and open columns filled in) for the lowest `objective`."""
    current, open_ids = _opened(curated)
    best = objective(build(current), px_per_crossing)
    candidate = current
    for _ in range(PASSES):
        candidate = reorder(candidate, build(candidate))
        score = objective(build(candidate), px_per_crossing)
        if score < best:
            current, best = candidate, score
    for _ in range(SWEEPS):
        improved = False
        for move in list(_moves(current, open_ids)):
            candidate = move(current)
            if candidate is None:
                continue
            score = objective(build(candidate), px_per_crossing)
            if score < best:
                current, best, improved = candidate, score, True
        if not improved:
            break
    return current
