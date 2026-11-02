"""The box a C4 element is drawn as, shared by every view that draws elements."""

from cartographer.c4_model import type_line
from cartographer.c4_styles import element_label, element_size


def kind(element: dict) -> str:
    if element["type"] == "container":
        return {"store": "container_store", "queue": "container_queue"}.get(element.get("shape"), "container")
    return f"{element['type']}_ext" if element.get("external") else element["type"]


def element_node(element: dict, group: str | None) -> dict:
    label = element_label(element["name"], type_line(element), element["description"])
    shape = kind(element)
    return {"id": element["id"], "label": label, "service": "other", "group": group, "tf": [], "multi": False,
            "box": list(element_size(label, shape)), "c4": shape}
