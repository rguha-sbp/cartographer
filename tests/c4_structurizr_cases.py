"""C4 models for the Structurizr workspace tests: the shop, and the review cases where a workspace once differed from
the pages or did not parse."""

import json
from pathlib import Path

STATED = [{"stated": "the engineer said so"}]
FIXTURE = Path(__file__).parent / "fixtures" / "c4" / "model.json"


def el(eid: str, kind: str, parent: str | None = None, **extra) -> dict:
    base = {"id": eid, "type": kind, "name": eid.capitalize(), "description": "Does things", "evidence": STATED}
    return base | ({"parent": parent} if parent else {}) | extra


def rel(rid: str, src: str, dst: str, label: str, **extra) -> dict:
    return {"id": rid, "src": src, "dst": dst, "label": label, "dashed": False, "evidence": STATED} | extra


def shop() -> dict:
    return {
        "source": "description",
        "elements": [
            el("user", "person"),
            el("psp", "system", external=True),
            el("shop", "system"),
            el("web-app", "container", "shop", technology="TypeScript"),
            el("api", "container", "shop", technology="Python"),
            el("db", "container", "shop", technology="Postgres", shape="store"),
            el("jobs", "container", "shop", technology="SQS", shape="queue"),
            el("auth", "component", "api", technology="Python"),
            el("cart", "component", "api", technology="Python"),
            el("cart-model", "code", "cart", stereotype="class"),
        ],
        "relationships": [
            rel("r1", "user", "web-app", "browses", technology="HTTPS"),
            rel("r2", "web-app", "auth", "logs in", technology="HTTPS"),
            rel("r3", "cart", "db", "stores carts", technology="SQL"),
            rel("r4", "cart", "psp", "charges", technology="HTTPS", summary="pays with PSP"),
            rel("r5", "auth", "psp", "verifies card", technology="REST", summary="pays with PSP"),
            rel("r6", "cart", "jobs", "queues receipt", technology="SQS", dashed=True),
        ],
        "scenarios": [{"id": "buy", "name": "Buy", "steps": ["r1", "r2", "r4"]}],
    }


def root_leaf() -> dict:
    """A root deployment node that holds nothing, beside one that hosts two containers."""
    model = shop()
    model["deployment"] = {
        "environment": "prod",
        "nodes": [{"id": "cdn", "name": "CDN", "technology": "CloudFront", "evidence": STATED},
                  {"id": "vm", "name": "VM", "technology": "EC2", "evidence": STATED}],
        "instances": [{"container": "api", "node": "vm"}, {"container": "web-app", "node": "vm"}],
    }
    return model


def no_containers() -> dict:
    """The system in scope has no containers, and the one scenario step reaches it."""
    return {
        "source": "description",
        "elements": [el("user", "person"), el("shop", "system"), el("psp", "system", external=True)],
        "relationships": [rel("r1", "user", "shop", "buys"), rel("r2", "user", "psp", "pays")],
        "scenarios": [{"id": "buy", "name": "Buy", "steps": ["r1"]}],
    }


def _web_to_api(*relationships: dict) -> dict:
    model = shop()
    model["relationships"] = [r for r in model["relationships"] if r["id"] != "r2"] + list(relationships)
    model["scenarios"] = [{"id": "buy", "name": "Buy", "steps": ["r1", relationships[0]["id"], "r4"]}]
    return model


def own_pair_rolled_up() -> dict:
    """Two relationships of one pair roll up onto that same pair, under their summary."""
    return _web_to_api(rel("r7", "web-app", "api", "reads", technology="HTTPS", summary="uses"),
                       rel("r8", "web-app", "api", "writes", technology="gRPC", summary="uses"))


def own_pair_and_lifted() -> dict:
    """A relationship of a pair and one lifted onto it from a component share a summary."""
    return _web_to_api(rel("r7", "web-app", "api", "calls", summary="uses API"),
                       rel("r8", "web-app", "auth", "logs in", summary="uses API"))


def same_label_two_technologies() -> dict:
    return _web_to_api(rel("r7", "web-app", "api", "calls", technology="HTTPS"),
                       rel("r8", "web-app", "api", "calls", technology="gRPC"))


def outsider_pair() -> dict:
    """A person linked only to an external system: the Context page draws both."""
    model = shop()
    model["elements"].append(el("admin", "person"))
    model["relationships"].append(rel("r9", "admin", "psp", "reconciles"))
    return model


def sibling_edge() -> dict:
    """A container-to-container edge the Component page of a third container does not draw."""
    model = shop()
    model["relationships"].append(rel("r9", "web-app", "db", "reads stock", technology="SQL"))
    return model


def fixture() -> dict:
    return json.loads(FIXTURE.read_text())


CASES = {f.__name__: f for f in (shop, root_leaf, no_containers, own_pair_rolled_up, own_pair_and_lifted,
                                 same_label_two_technologies, outsider_pair, sibling_edge, fixture)}
