"""`review.json`: what each drawn icon stands for, so the visual review judges it against the right resource and view."""

from pathlib import Path

from cartographer import icons
from cartographer.diagram_model import Diagram, Group, Icon
from cartographer.tfdiagram import VIEW_SUMMARIES
from cartographer.workdir import write_json


def _frame(icon: Icon, groups: dict[str, Group]) -> str:
    labels, parent = [], icon.parent
    while parent in groups:
        labels.insert(0, groups[parent].label)
        parent = groups[parent].parent
    return " > ".join(labels)


def _tf(item: dict, facts: dict | None) -> list[dict]:
    if facts is None:
        return [{"type": item["tf_type"]}] if item.get("tf_type") else []
    by_address = {r["address"]: r for r in facts["resources"]}
    return [{k: by_address[a][k] for k in ("address", "type", "file", "line")} for a in item.get("tf", [])]


def write(cache: Path, verified: dict, facts: dict | None, diagram: Diagram) -> Path:
    groups = {n.id: n for n in diagram.nodes if isinstance(n, Group)}
    items = {i["id"]: i for i in (*verified["nodes"], *verified["externals"])}
    entries = []
    for icon in (n for n in diagram.nodes if isinstance(n, Icon)):
        item = items[icon.id]
        entries.append({
            "id": icon.id, "label": item["label"], "cloud": icons.cloud_of(icon.icon), "icon": icon.icon,
            "icon_title": icons.title(icon.icon), "tf": _tf(item, facts), "decided_by": item.get("decided_by", ""),
            "marked": item.get("marked", False), "reason": item.get("reason"), "override": item.get("override"), "frame": _frame(icon, groups),
            "tiles": [],
        })
    sheet = {"view": verified["view"], "view_name": VIEW_SUMMARIES[verified["view"]],
             "clouds": sorted({g.cloud for g in groups.values() if g.cloud}), "icons": entries}
    path = cache / "review.json"
    write_json(path, sheet)
    return path
