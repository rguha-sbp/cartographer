"""The box a C4 element or an infrastructure node is drawn as, shared by every view that draws one."""

from cartographer.c4_model import type_line
from cartographer.c4_styles import element_label, element_size


def kind(element: dict) -> str:
    if element["type"] == "container":
        return {"store": "container_store", "queue": "container_queue"}.get(element.get("shape"), "container")
    return f"{element['type']}_ext" if element.get("external") else element["type"]


def box_node(nid: str, shape: str, label: str, group: str | None) -> dict:
    """A curated node drawn as a C4 box of `shape`, sized for its label."""
    return {"id": nid, "label": label, "service": shape, "group": group, "tf": [], "multi": False,
            "box": list(element_size(label, shape))}


def element_node(element: dict, group: str | None) -> dict:
    description = "" if element["type"] == "code" else element["description"]  # a class is named, not described
    return box_node(element["id"], kind(element), element_label(element["name"], type_line(element), description),
                    group)
