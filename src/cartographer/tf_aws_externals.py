"""Externals that are AWS managed services (`service` set) are drawn as icons in their own block inside the region."""

from typing import Any

BLOCK_ID = "g_aws_managed"


def adopt(curated: dict[str, Any]) -> dict[str, Any]:
    """The curated data with each AWS-service external moved into a block "AWS managed services" under the region
    frame; edges and ids are unchanged. The block's column is open: placement (`tf_place`) puts it by its callers."""
    managed = [x for x in curated["externals"] if x.get("service")]
    region = next((g["id"] for g in curated["groups"] if g["kind"] == "region"), None)
    if not managed or region is None:
        return curated
    block = {"id": BLOCK_ID, "label": "AWS managed services", "kind": None, "parent": region, "column": None}
    nodes = [{"id": x["id"], "label": x["label"], "service": x["service"], "group": BLOCK_ID, "tf": [], "multi": False}
             for x in managed]
    return {**curated, "groups": [*curated["groups"], block], "nodes": [*curated["nodes"], *nodes],
            "externals": [x for x in curated["externals"] if not x.get("service")]}
