import re

from cartographer import c4_structurizr

STATED = [{"stated": "the engineer said so"}]


def el(eid: str, kind: str, parent: str | None = None, **extra) -> dict:
    base = {"id": eid, "type": kind, "name": eid.capitalize(), "description": "Does things", "evidence": STATED}
    return base | ({"parent": parent} if parent else {}) | extra


def rel(rid: str, src: str, dst: str, label: str, **extra) -> dict:
    return {"id": rid, "src": src, "dst": dst, "label": label, "dashed": False, "evidence": STATED} | extra


def _shop() -> dict:
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
            el("Cart", "code", "cart", stereotype="class"),
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


def _relationship_lines(dsl: str) -> list[str]:
    return [line.strip().removesuffix(" {") for line in dsl.splitlines() if " -> " in line and line.endswith("{")]


def test_elements_nest_with_their_kind_technology_and_tags():
    dsl = c4_structurizr.workspace(_shop())
    assert dsl.startswith('workspace "Shop" "Does things" {\n')
    assert 'user = person "User" "Does things" {' in dsl
    assert 'psp = softwareSystem "Psp" "Does things" {' in dsl
    assert 'api = container "Api" "Does things" "Python" {' in dsl
    assert 'cart = component "Cart" "Does things" "Python" {' in dsl
    assert re.search(r'psp = softwareSystem .*\n\s+tags "External"', dsl)
    assert re.search(r'db = container .*\n\s+tags "Store"', dsl)
    assert re.search(r'jobs = container .*\n\s+tags "Queue"', dsl)
    assert '"evidence" "stated: the engineer said so"' in dsl


def test_identifiers_are_dsl_safe_and_unique():
    model = _shop()
    model["elements"].append(el("web_app", "container", "shop", technology="Go"))
    dsl = c4_structurizr.workspace(model)
    assert 'web_app = container "Web-app"' in dsl
    assert 'web_app_2 = container "Web_app"' in dsl
    assert "web-app" not in "".join(_relationship_lines(dsl))


def test_implied_relationships_are_off_and_every_rolled_up_edge_is_explicit():
    dsl = c4_structurizr.workspace(_shop())
    assert "!impliedRelationships false" in dsl
    lines = _relationship_lines(dsl)
    # The model's own relationships keep their label and technology.
    assert 'cart -> psp "charges" "HTTPS"' in lines
    assert 'cart -> jobs "queues receipt" "SQS"' in lines
    # Container view: two components reach psp, so the arrow reads their shared summary over both technologies.
    assert 'api -> psp "pays with PSP" "HTTPS, REST"' in lines
    assert 'web_app -> api "logs in" "HTTPS"' in lines
    # Context view: the same summary rolls up to the system.
    assert 'shop -> psp "pays with PSP" "HTTPS, REST"' in lines
    assert 'user -> shop "browses" "HTTPS"' in lines
    assert len(lines) == len(set(lines)), "one relationship per ordered pair and text"


def test_asynchronous_relationships_are_tagged_dashed():
    dsl = c4_structurizr.workspace(_shop())
    assert re.search(r'cart -> jobs "queues receipt" "SQS" \{\n\s+tags "Async"', dsl)
    assert re.search(r'relationship "Async" \{\n\s+dashed true', dsl)


def test_code_elements_are_left_out():
    dsl = c4_structurizr.workspace(_shop())
    assert "Cart = " not in dsl
    assert "4-code" not in dsl


def test_views_mirror_the_drawio_pages():
    dsl = c4_structurizr.workspace(_shop())
    assert 'systemContext shop "1-context" "System Context diagram for Shop" {' in dsl
    assert 'container shop "2-container" "Container diagram for Shop" {' in dsl
    assert 'component api "3-component-api" "Component diagram for Shop: Api" {' in dsl
    assert 'dynamic shop "6-dynamic-buy" "Dynamic diagram for Shop: Buy" {' in dsl


def test_dynamic_steps_are_lifted_to_containers_in_order():
    dsl = c4_structurizr.workspace(_shop())
    block = dsl.split('dynamic shop "6-dynamic-buy"', 1)[1].split("}", 1)[0]
    steps = [line.strip() for line in block.splitlines() if " -> " in line]
    assert steps == ['user -> web_app "browses"', 'web_app -> api "logs in"', 'api -> psp "charges"']


def test_deployment_nodes_nest_and_host_container_instances():
    model = _shop()
    model["deployment"] = {
        "environment": "prod",
        "nodes": [
            {"id": "aws", "name": "AWS", "technology": "Amazon Web Services", "frame": "cloud", "cloud": "aws",
             "evidence": STATED},
            {"id": "lambda", "name": "api fn", "technology": "AWS Lambda", "parent": "aws", "tf": ["aws_lambda_function.api"],
             "evidence": STATED},
            {"id": "cdn", "name": "CDN", "technology": "Amazon CloudFront", "parent": "aws", "evidence": STATED},
        ],
        "instances": [{"container": "api", "node": "lambda"}],
    }
    dsl = c4_structurizr.workspace(model)
    assert 'deploymentEnvironment "prod" {' in dsl
    assert 'node_aws = deploymentNode "AWS" "" "Amazon Web Services" {' in dsl
    assert 'node_lambda = deploymentNode "api fn" "" "AWS Lambda" {' in dsl
    assert '"terraform" "aws_lambda_function.api"' in dsl
    assert "containerInstance api" in dsl
    assert 'node_cdn = infrastructureNode "CDN" "" "Amazon CloudFront" {' in dsl
    assert 'deployment shop "prod" "5-deployment" "Deployment diagram for Shop: prod" {' in dsl


def test_text_is_quoted_safely():
    model = _shop()
    model["elements"][0]["description"] = 'Says "hi"\nand leaves'
    dsl = c4_structurizr.workspace(model)
    assert 'user = person "User" "Says \\"hi\\" and leaves" {' in dsl


def test_dsl_name_sits_beside_the_drawio():
    assert c4_structurizr.dsl_name("shop") == "shop-c4.dsl"
