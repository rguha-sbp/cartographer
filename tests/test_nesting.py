import json
import xml.etree.ElementTree as ET

from cartographer import gen_drawio, tf_layout, tfdiagram
from cartographer.diagram_model import GREY
from cartographer.tf_check import measure
from cartographer.tf_colors import PALETTE, Colours
from cartographer.tf_geom import groups, leaves


def _group(gid: str, label: str, kind: str | None, parent: str | None, column: int = 0, **extra) -> dict:
    return {"id": gid, "label": label, "kind": kind, "parent": parent, "column": column, **extra}


def _node(nid: str, label: str, service: str, group: str | None) -> dict:
    return {"id": nid, "label": label, "service": service, "group": group, "tf": [], "multi": False}


def _edge(src: str, dst: str, label: str, flow: str = "runtime") -> dict:
    return {"src": src, "dst": dst, "label": label, "flow": flow, "dashed": False, "evidence": []}


def _shop() -> dict:
    return {
        "title": "Layer 7 diagram for Shop",
        "groups": [
            _group("cloud", "AWS Cloud", "cloud", None),
            _group("region", "eu-west-1", "region", "cloud"),
            _group("acct", "Shop account", "account", "region"),
            _group("vpc", "shop-vpc", "vpc", "acct", cidrs=["10.0.0.0/16"]),
            _group("pub", "Public subnets", "subnet", "vpc", tier="public"),
            _group("priv", "Private subnets", "subnet", "vpc", tier="private"),
            _group("store", "Storefront", None, "pub"),
            _group("orders", "Orders", None, "priv"),
            _group("media", "Media", None, "acct", column=1),
        ],
        "nodes": [
            _node("alb", "Load balancer", "elastic_load_balancing", "store"),
            _node("ecs", "Order service", "ecs", "orders"),
            _node("db", "Orders database", "rds", "orders"),
            _node("s3", "Media bucket", "s3", "media"),
        ],
        "externals": [{"id": "user", "label": "Shopper", "icon": "user", "evidence": []}],
        "edges": [_edge("user", "alb", "browse, HTTPS", "web"), _edge("alb", "ecs", "forward, HTTP"),
                  _edge("ecs", "db", "query, SQL", "data"), _edge("ecs", "s3", "store images", "data")],
    }


def _rendered(curated: dict) -> tuple[str, dict]:
    diagram = tf_layout.layout(curated)
    xml = gen_drawio.render(diagram, page_id="shop", page_name="Shop")
    return xml, {g.id: g for g in groups(diagram)}


def _inside(inner, outer) -> bool:
    return (outer.x <= inner.x and outer.y <= inner.y and inner.x + inner.w <= outer.x + outer.w
            and inner.y + inner.h <= outer.y + outer.h)


def _disjoint(a, b) -> bool:
    return a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


def test_schema_has_subnet_kind_tier_cidrs_and_evidence() -> None:
    group = json.loads(tfdiagram.schema_text())["properties"]["groups"]["items"]
    props = group["properties"]
    assert "subnet" in props["kind"]["enum"]
    assert props["tier"]["enum"] == ["public", "private", "isolated"]
    assert props["cidrs"]["items"]["pattern"].startswith("^")
    assert props["evidence"]["items"] == {"$ref": "#/$defs/evidence"}
    assert group["additionalProperties"] is False
    assert group["required"] == ["id", "label", "kind", "parent", "column"]


def test_vpc_and_subnets_nest_workloads_without_overlap() -> None:
    xml, placed = _rendered(_shop())
    assert _inside(placed["priv"], placed["vpc"]) and _inside(placed["pub"], placed["vpc"])
    assert _inside(placed["orders"], placed["priv"]) and _inside(placed["store"], placed["pub"])
    assert _inside(placed["vpc"], placed["acct"]) and _inside(placed["media"], placed["acct"])
    assert _disjoint(placed["pub"], placed["priv"]) and _disjoint(placed["vpc"], placed["media"])
    assert measure(xml).violations == 0


def test_every_node_sits_inside_its_workload_frame() -> None:
    diagram = tf_layout.layout(_shop())
    placed = {g.id: g for g in groups(diagram)}
    for nid, gid in (("alb", "store"), ("ecs", "orders"), ("db", "orders"), ("s3", "media")):
        node = leaves(diagram)[nid]
        assert placed[gid].x <= node.x < node.x + 60 <= placed[gid].x + placed[gid].w


def test_vpc_label_carries_its_cidrs() -> None:
    curated = _shop()
    curated["groups"][3]["cidrs"] = ["10.0.0.0/16", "10.1.0.0/20"]
    xml, _ = _rendered(curated)
    values = {c.get("id"): c.get("value") for c in ET.fromstring(xml).iter("mxCell")}
    assert values["vpc"] == "shop-vpc (10.0.0.0/16, 10.1.0.0/20)"
    assert values["pub"] == "Public subnets"
    assert _rendered(_shop())[0].count("shop-vpc (10.0.0.0/16)") == 1


def test_a_vpc_without_cidrs_keeps_its_plain_label() -> None:
    curated = _shop()
    del curated["groups"][3]["cidrs"]
    values = {c.get("id"): c.get("value") for c in ET.fromstring(_rendered(curated)[0]).iter("mxCell")}
    assert values["vpc"] == "shop-vpc"


def test_subnet_styles_follow_the_tier() -> None:
    curated = _shop()
    curated["groups"].append(_group("iso", "Isolated subnets", "subnet", "vpc", tier="isolated"))
    curated["nodes"].append(_node("ledger", "Ledger database", "rds", "iso"))
    xml, _ = _rendered(curated)
    styles = {c.get("id"): c.get("style") for c in ET.fromstring(xml).iter("mxCell")}
    assert "grIcon=mxgraph.aws4.group_security_group;strokeColor=#7AA116;fillColor=none;fontColor=#248814" in styles["pub"]
    assert "strokeColor=#00A4A6;fillColor=none;fontColor=#147EBA;dashed=0" in styles["priv"]
    assert "strokeColor=#00A4A6;fillColor=none;fontColor=#147EBA;dashed=1" in styles["iso"]


def test_palette_goes_to_outermost_workloads_only() -> None:
    curated = _shop()
    curated["groups"].append(_group("jobs", "Batch jobs", None, "orders"))
    curated["nodes"].append(_node("job", "Batch runner", "ecs", "jobs"))
    colours = Colours(curated)
    assert colours.group("vpc") is None and colours.group("pub") is None and colours.group("priv") is None
    assert colours.group("jobs") == colours.group("orders")
    workloads = {colours.group(g) for g in ("store", "orders", "media")}
    assert len(workloads) == 3 and workloads <= set(PALETTE)
    assert colours.node("db") == colours.group("orders")


def test_vpc_and_subnet_frames_use_the_aws_colour_not_a_palette_stroke() -> None:
    diagram = tf_layout.layout(_shop())
    assert all(g.stroke == GREY for g in diagram.nodes if getattr(g, "kind", None) in ("vpc", "subnet"))


def test_a_workload_split_across_frames_shares_one_colour() -> None:
    curated = _shop()
    curated["groups"].append(_group("orders-s3", "Orders", None, "acct", column=2))
    curated["nodes"].append(_node("archive", "Archive bucket", "s3", "orders-s3"))
    colours = Colours(curated)
    assert colours.group("orders-s3") == colours.group("orders")
    assert colours.node("archive") == colours.node("db")
    assert len({colours.group(g) for g in ("store", "orders", "media")}) == 3
