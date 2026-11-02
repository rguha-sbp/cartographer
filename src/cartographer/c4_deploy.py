"""The Deployment view: AWS frames and icons as in the layer 7 diagrams, with container instances in deployment nodes."""

from cartographer.c4_boxes import element_node
from cartographer.c4_model import Model, elements, rollup


def _group(node: dict, kind: str, label: str) -> dict:
    return {"id": node["id"], "label": label, "kind": kind, "parent": node.get("parent"), "column": 0}


def _frame(node: dict) -> dict:
    return _group(node, node["frame"], node["name"]) | ({"tier": node["tier"]} if "tier" in node else {})


def _host(node: dict) -> dict:
    return _group(node, "deployment", f"{node['name']}\n[Deployment Node: {node['technology']}]")


def _icon(node: dict) -> dict:
    return {"id": node["id"], "label": node["name"], "service": node.get("service", "other"),
            "group": node.get("parent"), "tf": node.get("tf", []), "multi": False}


def deployment(model: Model, title: str) -> dict:
    """The deployment nodes, then one box per container instance and an edge for every instance pair whose
    containers have a rolled-up relationship. People and external systems are not deployed, so not drawn."""
    nodes, instances = model["deployment"]["nodes"], model["deployment"]["instances"]
    by_id = elements(model)
    occupied = {i["node"] for i in instances} | {n["parent"] for n in nodes if "parent" in n}
    groups = [_frame(n) if "frame" in n else _host(n) for n in nodes if "frame" in n or n["id"] in occupied]
    icons = [_icon(n) for n in nodes if "frame" not in n and n["id"] not in occupied]
    boxes = [{**element_node(by_id[i["container"]], i["node"]), "id": f"{i['node']}.{i['container']}"}
             for i in instances]
    hosted: dict[str, list[str]] = {}
    for i in instances:
        hosted.setdefault(i["container"], []).append(f"{i['node']}.{i['container']}")
    edges = [{**e, "src": src, "dst": dst, "evidence": []}
             for e in rollup(model, set(hosted)) for src in hosted[e["src"]] for dst in hosted[e["dst"]]]
    return {"title": title, "groups": groups, "nodes": [*icons, *boxes], "externals": [], "edges": edges}
