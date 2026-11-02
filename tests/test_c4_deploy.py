import pytest

from cartographer import gen_drawio, tf_layout
from cartographer.c4_styles import C4
from cartographer.c4_views import views
from cartographer.clouds import CLOUDS

FACT = [{"fact": "x"}]


def el(eid, kind, parent=None, **extra):
    base = {"id": eid, "type": kind, "name": eid, "description": "Does things", "evidence": FACT}
    return base | ({"parent": parent} if parent else {}) | extra


def node(nid, parent=None, **extra):
    base = {"id": nid, "name": nid, "technology": "AWS", "evidence": FACT}
    return base | ({"parent": parent} if parent else {}) | extra


def _model():
    rel = {"id": "r1", "src": "api", "dst": "orders", "label": "writes", "dashed": False, "evidence": FACT}
    ext = {"id": "r2", "src": "user", "dst": "api", "label": "uses", "dashed": False, "evidence": FACT}
    return {
        "source": "description",
        "elements": [el("user", "person"), el("shop", "system"), el("api", "container", "shop"),
                     el("orders", "container", "shop", shape="store")],
        "relationships": [rel, ext],
        "deployment": {
            "environment": "prod",
            "nodes": [node("cloud", frame="cloud", cloud="aws"), node("region", "cloud", frame="region", cloud="aws"),
                      node("acct", "region", frame="account", cloud="aws"),
                      node("vpc", "acct", frame="network", cloud="aws"),
                      node("priv", "vpc", frame="subnet", tier="private", cloud="aws"),
                      node("fn", "priv", technology="Lambda"), node("tbl", "acct", technology="DynamoDB"),
                      node("alb", "priv", icon="aws:elastic_load_balancing"), node("bare", "priv")],
            "instances": [{"container": "api", "node": "fn"}, {"container": "orders", "node": "tbl"}],
        },
    }


def _view():
    return next(v for v in views(_model()) if v.slug == "5-deployment")


def test_title_names_the_environment():
    assert _view().title == "Deployment diagram for shop: prod"
    assert _view().curated["title"] == "Deployment diagram for shop: prod"


def test_instances_sit_in_their_deployment_node():
    c = _view().curated
    node_ = next(n for n in c["nodes"] if n["id"] == "fn.api")
    group = next(g for g in c["groups"] if g["id"] == "fn")
    assert node_["group"] == "fn" and node_["icon"] == "container" and group["kind"] == "deployment"
    assert group["label"] == "fn\n[Deployment Node: Lambda]"
    assert next(n for n in c["nodes"] if n["id"] == "tbl.orders")["icon"] == "container_store"


def test_frames_keep_their_kinds_and_cloud():
    groups = {g["id"]: g for g in _view().curated["groups"]}
    assert {g["kind"] for g in groups.values()} >= {"cloud", "region", "account", "network", "deployment"}
    assert {g.get("cloud") for g in groups.values() if g["kind"] != "deployment"} == {"aws"}
    assert groups["priv"]["tier"] == "private" and groups["priv"]["parent"] == "vpc"
    assert "tier" not in groups["vpc"]


def test_infrastructure_without_instances_is_an_aws_icon():
    nodes = {n["id"]: n for n in _view().curated["nodes"]}
    assert nodes["alb"]["icon"] == "aws:elastic_load_balancing"
    assert nodes["alb"]["group"] == "priv"


@pytest.mark.parametrize("icon", [None, "aws:key_management_typo", "azure:nope"])
def test_infrastructure_without_an_icon_is_an_infrastructure_node_box(icon):
    model = _model()
    kms = {"id": "kms", "name": "Key", "technology": "AWS KMS", "evidence": [{"stated": "said so"}], "parent": "priv"}
    model["deployment"]["nodes"].append(kms | ({"icon": icon} if icon else {}))
    view = next(v for v in views(model) if v.slug == "5-deployment")
    box = next(n for n in view.curated["nodes"] if n["id"] == "kms")
    assert (box["icon"], box["label"], box["group"]) == ("infrastructure", "Key\n[Infrastructure Node: AWS KMS]", "priv")
    xml = gen_drawio.render(tf_layout.layout(view.curated, notation=C4), page_id="p", page_name="t", notation=C4)
    assert "Infrastructure node" in xml


def test_an_azure_deployment_draws_azure_icons_in_azure_frames():
    model = _model()
    model["deployment"]["nodes"] = [
        node("az", frame="cloud", cloud="azure"), node("we", "az", frame="region", cloud="azure"),
        node("vnet", "we", frame="network", cloud="azure"),
        node("app", "vnet", frame="subnet", tier="private", cloud="azure"),
        node("func", "app", technology="Function App"), node("kv", "we", icon="azure:key_vaults"),
    ]
    model["deployment"]["instances"] = [{"container": "api", "node": "func"}]
    view = next(v for v in views(model) if v.slug == "5-deployment")
    assert next(n for n in view.curated["nodes"] if n["id"] == "kv")["icon"] == "azure:key_vaults"
    xml = gen_drawio.render(tf_layout.layout(view.curated, notation=C4), page_id="p", page_name="t", notation=C4)
    azure = CLOUDS["azure"]
    assert azure.icon_style("key_vaults") in xml
    for kind in ("cloud", "region", "network", "subnet-private"):
        assert azure.frame_styles[kind] in xml
    assert "mxgraph.aws4" not in xml


def test_relationships_join_instances():
    c = _view().curated
    assert [(e["src"], e["dst"]) for e in c["edges"]] == [("fn.api", "tbl.orders")]
    assert c["externals"] == []


def test_every_instance_pair_is_joined():
    model = _model()
    model["deployment"]["instances"].append({"container": "api", "node": "alb"})
    model["deployment"]["nodes"] = [n for n in model["deployment"]["nodes"] if n["id"] != "bare"]
    edges = next(v for v in views(model) if v.slug == "5-deployment").curated["edges"]
    assert {(e["src"], e["dst"]) for e in edges} == {("fn.api", "tbl.orders"), ("alb.api", "tbl.orders")}


def test_no_deployment_no_view():
    model = _model()
    del model["deployment"]
    assert "5-deployment" not in [v.slug for v in views(model)]


def test_deployment_view_renders():
    gen_drawio.render(tf_layout.layout(_view().curated, notation=C4), page_id="p", page_name="t", notation=C4)
