"""The Deployment view: AWS frames and icons as in the layer 7 diagrams, with container instances in deployment nodes."""

from cartographer import icons
from cartographer.c4_boxes import box_node, element_node
from cartographer.c4_model import Model, elements, rollup
from cartographer.c4_styles import element_label


def _group(node: dict, kind: str, label: str) -> dict:
    return {"id": node["id"], "label": label, "kind": kind, "parent": node.get("parent"), "column": 0}


def _frame(node: dict) -> dict:
    kind = "network" if node["frame"] == "vpc" else node["frame"]
    return _group(node, kind, node["name"]) | {"cloud": "aws"} | ({"tier": node["tier"]} if "tier" in node else {})


def _host(node: dict) -> dict:
    return _group(node, "deployment", f"{node['name']}\n[Deployment Node: {node['technology']}]")


def _leaf(node: dict) -> dict:
    """Infrastructure that hosts no container: its AWS icon, else a C4 infrastructure node box."""
    if icons.known(icon := f"aws:{node.get('service')}"):
        return {"id": node["id"], "label": node["name"], "icon": icon, "group": node.get("parent"),
                "tf": node.get("tf", []), "multi": False}
    label = element_label(node["name"], f"[Infrastructure Node: {node['technology']}]", "")
    return box_node(node["id"], "infrastructure", label, node.get("parent"))


def deployment(model: Model, title: str) -> dict:
    """The deployment nodes, then one box per container instance and an edge for every instance pair whose
    containers have a rolled-up relationship. People and external systems are not deployed, so not drawn."""
    nodes, instances = model["deployment"]["nodes"], model["deployment"]["instances"]
    by_id = elements(model)
    occupied = {i["node"] for i in instances} | {n["parent"] for n in nodes if "parent" in n}
    groups = [_frame(n) if "frame" in n else _host(n) for n in nodes if "frame" in n or n["id"] in occupied]
    leaves = [_leaf(n) for n in nodes if "frame" not in n and n["id"] not in occupied]
    boxes = [{**element_node(by_id[i["container"]], i["node"]), "id": f"{i['node']}.{i['container']}"}
             for i in instances]
    hosted: dict[str, list[str]] = {}
    for i in instances:
        hosted.setdefault(i["container"], []).append(f"{i['node']}.{i['container']}")
    edges = [{**e, "src": src, "dst": dst, "evidence": []}
             for e in rollup(model, set(hosted)) for src in hosted[e["src"]] for dst in hosted[e["dst"]]]
    return {"title": title, "groups": groups, "nodes": [*leaves, *boxes], "externals": [], "edges": edges}
