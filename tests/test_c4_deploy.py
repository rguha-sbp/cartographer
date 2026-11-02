from cartographer import tf_layout
from cartographer.c4_styles import C4
from cartographer.c4_views import views

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
            "nodes": [node("cloud", frame="cloud"), node("region", "cloud", frame="region"),
                      node("acct", "region", frame="account"), node("vpc", "acct", frame="vpc"),
                      node("priv", "vpc", frame="subnet", tier="private"),
                      node("fn", "priv", technology="Lambda"), node("tbl", "acct", technology="DynamoDB"),
                      node("alb", "priv", service="application_load_balancer"), node("bare", "priv")],
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
    assert node_["group"] == "fn" and node_["service"] == "container" and group["kind"] == "deployment"
    assert group["label"] == "fn\n[Deployment Node: Lambda]"
    assert next(n for n in c["nodes"] if n["id"] == "tbl.orders")["service"] == "container_store"


def test_frames_keep_aws_kinds():
    groups = {g["id"]: g for g in _view().curated["groups"]}
    assert {g["kind"] for g in groups.values()} >= {"cloud", "region", "account", "deployment"}
    assert groups["priv"]["tier"] == "private" and groups["priv"]["parent"] == "vpc"
    assert "tier" not in groups["vpc"]


def test_infrastructure_without_instances_is_an_aws_icon():
    nodes = {n["id"]: n for n in _view().curated["nodes"]}
    assert nodes["alb"]["service"] == "application_load_balancer"
    assert nodes["alb"]["group"] == "priv"
    assert nodes["bare"]["service"] == "other"


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


def test_deployment_view_lays_out():
    tf_layout.layout(_view().curated, notation=C4)
