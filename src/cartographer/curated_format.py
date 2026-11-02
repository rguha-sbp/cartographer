"""Curated file formats: format 2 qualifies icons ("aws:lambda") and names the cloud of each frame."""

import copy
from typing import Any

from cartographer import icons

FORMAT = 2
FRAME_KINDS = ("cloud", "region", "account", "network", "subnet")
LEGACY_CLOUD = "aws"


def _legacy_icon(name: str) -> str:
    return next((f"{ns}:{name}" for ns in ("generic", "brand") if icons.known(f"{ns}:{name}")), name)


def _upgrade_group(group: dict[str, Any]) -> dict[str, Any]:
    kind = "network" if group["kind"] == "vpc" else group["kind"]
    return {**group, "kind": kind, **({"cloud": LEGACY_CLOUD} if kind in FRAME_KINDS else {})}


def _upgrade_node(node: dict[str, Any]) -> dict[str, Any]:
    service, icon = node.pop("service", "other"), node.pop("icon", None)
    if icon is None and service != "other":
        icon = f"{LEGACY_CLOUD}:{service}"
    elif icon is not None:
        icon = None if icon == "none" else _legacy_icon(icon)
    return {**node, **({"icon": icon} if icon else {})}


def _upgrade_external(external: dict[str, Any]) -> dict[str, Any]:
    service, icon = external.pop("service", None), external.pop("icon", None)
    if service:
        icon = f"{LEGACY_CLOUD}:{service}"
    elif icon not in (None, "none"):
        icon = _legacy_icon(icon)
    return {**external, **({"icon": icon} if icon else {})}


def upgrade(curated: dict[str, Any]) -> dict[str, Any]:
    """The curated data in format 2; a file that already is format 2 is returned as it is."""
    if "format" in curated:
        if curated["format"] != FORMAT:
            raise ValueError(f"curated file is format {curated['format']}: this cartographer reads format {FORMAT}, or a file with no "
                             "format key (the first format)")
        return curated
    old = copy.deepcopy(curated)
    return {**old, "format": FORMAT,
            "groups": [_upgrade_group(g) for g in old["groups"]],
            "nodes": [_upgrade_node(n) for n in old["nodes"]],
            "externals": [_upgrade_external(x) for x in old["externals"]]}
