"""Externals whose `icon` belongs to a cloud are drawn as icons in a per-cloud managed-services block inside its region."""

from typing import Any

from cartographer import icons
from cartographer.clouds import CLOUDS


def block_id(cloud: str) -> str:
    return f"g_{cloud}_managed"


def adopt(curated: dict[str, Any]) -> dict[str, Any]:
    """The curated data with each cloud-icon external moved into that cloud's managed-services block under its first
    region frame, or under a new cloud frame when it has none; edges and ids are unchanged. A block's column is open:
    placement (`tf_place`) puts it by its callers."""
    groups, nodes, externals = list(curated["groups"]), list(curated["nodes"]), list(curated["externals"])
    for cloud in CLOUDS.values():
        managed = [x for x in externals if icons.cloud_of(x.get("icon", "")) == cloud.name]
        if not managed:
            continue
        region = next((g["id"] for g in groups if g["kind"] == "region" and g.get("cloud") == cloud.name), None)
        if region is None:
            region = f"g_{cloud.name}_cloud"
            groups.append({"id": region, "label": cloud.label, "kind": "cloud", "cloud": cloud.name, "parent": None,
                           "column": None})
        block = block_id(cloud.name)
        groups.append({"id": block, "label": cloud.managed_label, "kind": None, "parent": region, "column": None})
        nodes += [{"id": x["id"], "label": x["label"], "icon": x["icon"], "group": block, "tf": [], "multi": False}
                  for x in managed]
        taken = {x["id"] for x in managed}
        externals = [x for x in externals if x["id"] not in taken]
    return {**curated, "groups": groups, "nodes": nodes, "externals": externals}
