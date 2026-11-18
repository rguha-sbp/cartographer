import re

from c4_structurizr_cases import (
    el,
    no_containers,
    outsider_pair,
    own_pair_and_lifted,
    own_pair_rolled_up,
    root_leaf,
    same_label_two_technologies,
    shop,
    sibling_edge,
)

from cartographer import c4_structurizr


def _block(dsl: str, opener: str) -> str:
    """The lines of the block that `opener` starts, up to its closing brace."""
    start = dsl.index(opener)
    depth, end = 0, start
    for end in range(start, len(dsl)):
        depth += {"{": 1, "}": -1}.get(dsl[end], 0)
        if dsl[end] == "}" and depth == 0:
            break
    return dsl[start:end + 1]


def _relationships(dsl: str) -> dict[str, str]:
    """Relationship identifier -> 'src -> dst "text" ["technology"]'."""
    return dict(re.findall(r'^\s+(rel_\d+) = (.+?) \{$', dsl, re.MULTILINE))


def _view(dsl: str, slug: str) -> str:
    (opener,) = re.findall(rf'^\s+(\w+ [\w*]+(?: "[^"]*")? "{re.escape(slug)}") \{{$', dsl, re.MULTILINE)
    return _block(dsl, opener)


def test_elements_nest_with_their_kind_technology_and_tags():
    dsl = c4_structurizr.workspace(shop())
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
    model = shop()
    model["elements"].append(el("web_app", "container", "shop", technology="Go"))
    dsl = c4_structurizr.workspace(model)
    assert 'web_app = container "Web-app"' in dsl
    assert 'web_app_2 = container "Web_app"' in dsl
    assert "web-app" not in "".join(_relationships(dsl).values())


def test_relationships_are_the_arrows_the_pages_draw():
    dsl = c4_structurizr.workspace(shop())
    assert "!impliedRelationships false" in dsl
    arrows = set(_relationships(dsl).values())
    # Container page: two components reach psp, so the arrow reads their shared summary over both technologies.
    assert 'api -> psp "pays with PSP" "HTTPS, REST"' in arrows
    assert 'web_app -> api "logs in" "HTTPS"' in arrows
    # Context page: the same summary rolls up to the system.
    assert 'shop -> psp "pays with PSP" "HTTPS, REST"' in arrows
    # Component page: each component keeps its own label.
    assert 'cart -> psp "charges" "HTTPS"' in arrows
    assert 'cart -> jobs "queues receipt" "SQS"' in arrows
    assert len(arrows) == len(_relationships(dsl)), "one relationship per arrow"


def test_relationships_keep_what_rolled_up_onto_them():
    dsl = c4_structurizr.workspace(shop())
    (ident,) = (i for i, line in _relationships(dsl).items() if line.startswith('api -> psp "pays with PSP"'))
    block = _block(dsl, f"{ident} = ")
    assert '"relationships" "r4, r5"' in block
    assert '"evidence" "charges: stated: the engineer said so | verifies card: stated: the engineer said so"' in block


def test_two_relationships_of_one_pair_are_one_arrow_under_their_summary():
    dsl = c4_structurizr.workspace(own_pair_rolled_up())
    pair = {line: i for i, line in _relationships(dsl).items() if line.startswith("web_app -> api")}
    # The scenario steps through "reads", so that step has its own relationship; "writes" is drawn on no page.
    assert set(pair) == {'web_app -> api "uses" "HTTPS, gRPC"', 'web_app -> api "reads" "HTTPS"'}
    container = _view(dsl, "2-container")
    assert re.search(rf'exclude .*\b{pair['web_app -> api "reads" "HTTPS"']}\b', container)
    assert not re.search(rf'\b{pair['web_app -> api "uses" "HTTPS, gRPC"']}\b', container)


def test_a_relationship_lifted_onto_an_own_pair_shares_its_summary():
    dsl = c4_structurizr.workspace(own_pair_and_lifted())
    container = _view(dsl, "2-container")
    (ident,) = (i for i, line in _relationships(dsl).items() if line == 'web_app -> api "uses API"')
    assert not re.search(rf"\b{ident}\b", container), "the arrow the page draws is not excluded"
    (calls,) = (i for i, line in _relationships(dsl).items() if line == 'web_app -> api "calls"')
    assert re.search(rf"exclude .*\b{calls}\b", container), "the Dynamic step's own arrow is not on this page"


def test_one_label_over_two_technologies_is_one_relationship():
    arrows = [a for a in _relationships(c4_structurizr.workspace(same_label_two_technologies())).values()
              if a.startswith("web_app -> api")]
    assert arrows == ['web_app -> api "calls" "HTTPS, gRPC"']


def test_static_views_include_exactly_the_pages_elements():
    dsl = c4_structurizr.workspace(outsider_pair())
    context = _view(dsl, "1-context")
    assert set(re.search(r"include (.+)\n", context).group(1).split()) == {"shop", "user", "psp", "admin"}
    assert "include *" not in context


def test_static_views_exclude_relationships_their_page_does_not_draw():
    dsl = c4_structurizr.workspace(sibling_edge())
    component = _view(dsl, "3-component-api")
    (sibling,) = (i for i, line in _relationships(dsl).items() if line.startswith('web_app -> db "reads stock"'))
    assert re.search(rf"exclude .*\b{sibling}\b", component)


def test_asynchronous_relationships_are_tagged_dashed():
    dsl = c4_structurizr.workspace(shop())
    assert re.search(r'= cart -> jobs "queues receipt" "SQS" \{\n\s+tags "Async"', dsl)
    assert re.search(r'relationship "Async" \{\n\s+dashed true', dsl)


def test_code_elements_and_views_are_left_out():
    dsl = c4_structurizr.workspace(shop())
    assert "cart_model" not in dsl
    assert "4-code" not in dsl


def test_views_carry_the_pages_key_and_title():
    dsl = c4_structurizr.workspace(shop())
    assert re.search(r'systemContext shop "1-context" \{\n\s+title "System Context diagram for Shop"\n', dsl)
    assert re.search(r'container shop "2-container" \{\n\s+title "Container diagram for Shop"\n', dsl)
    assert re.search(r'component api "3-component-api" \{\n\s+title "Component diagram for Shop: Api"\n', dsl)
    assert re.search(r'dynamic shop "6-dynamic-buy" \{\n\s+title "Dynamic diagram for Shop: Buy"\n', dsl)


def test_dynamic_steps_keep_their_number_label_and_technology():
    model = shop()
    model["relationships"].append({"id": "r9", "src": "auth", "dst": "cart", "label": "hands over", "dashed": False,
                                   "evidence": [{"stated": "x"}]})
    model["scenarios"][0]["steps"] = ["r1", "r9", "r2", "r4"]  # r9 stays inside api, so the page skips number 2
    dsl = c4_structurizr.workspace(model)
    steps = [line.strip() for line in _view(dsl, "6-dynamic-buy").splitlines() if " -> " in line]
    assert steps == ['1: user -> web_app "browses" "HTTPS"', '3: web_app -> api "logs in" "HTTPS"',
                     '4: api -> psp "charges" "HTTPS"']


def test_a_dynamic_step_has_a_relationship_of_its_own_hidden_from_other_views():
    dsl = c4_structurizr.workspace(shop())
    (step,) = (i for i, line in _relationships(dsl).items() if line == 'api -> psp "charges" "HTTPS"')
    assert re.search(rf'{step} = .*\{{\n\s+tags "Step"', dsl)
    assert re.search(rf"exclude .*\b{step}\b", _view(dsl, "2-container"))


def test_a_system_without_containers_builds():
    dsl = c4_structurizr.workspace(no_containers())
    assert 'user -> shop "buys"' in _relationships(dsl).values()
    dynamic = _view(dsl, "6-dynamic-buy")
    assert dynamic.startswith('dynamic * "6-dynamic-buy" {')
    assert '1: user -> shop "buys"' in dynamic


def test_a_root_node_that_holds_nothing_is_a_deployment_node():
    dsl = c4_structurizr.workspace(root_leaf())
    environment = _block(dsl, 'deploymentEnvironment "prod"')
    assert 'node_cdn = deploymentNode "CDN" "" "CloudFront" {' in environment
    assert "infrastructureNode" not in environment


def test_deployment_nodes_nest_and_host_container_instances():
    model = shop()
    stated = [{"stated": "x"}]
    model["deployment"] = {
        "environment": "prod",
        "nodes": [
            {"id": "aws", "name": "AWS", "technology": "Amazon Web Services", "frame": "cloud", "cloud": "aws",
             "evidence": stated},
            {"id": "lambda", "name": "api fn", "technology": "AWS Lambda", "parent": "aws",
             "tf": ["aws_lambda_function.api"], "evidence": stated},
            {"id": "cdn", "name": "CDN", "technology": "Amazon CloudFront", "parent": "aws", "evidence": stated},
        ],
        "instances": [{"container": "api", "node": "lambda"}],
    }
    dsl = c4_structurizr.workspace(model)
    assert 'node_aws = deploymentNode "AWS" "" "Amazon Web Services" {' in dsl
    assert 'node_lambda = deploymentNode "api fn" "" "AWS Lambda" {' in dsl
    assert '"terraform" "aws_lambda_function.api"' in dsl
    assert "containerInstance api" in dsl
    assert 'node_cdn = infrastructureNode "CDN" "" "Amazon CloudFront" {' in dsl
    deployment = _view(dsl, "5-deployment")
    assert 'title "Deployment diagram for Shop: prod"' in deployment
    assert 'exclude "relationship.tag==Step"' in deployment


def test_text_is_quoted_safely():
    model = shop()
    model["elements"][0]["description"] = 'Says "hi"\r\nand\tleaves'
    dsl = c4_structurizr.workspace(model)
    assert 'user = person "User" "Says \\"hi\\" and leaves" {' in dsl


def test_dsl_name_sits_beside_the_drawio():
    assert c4_structurizr.dsl_name("shop") == "shop-c4.dsl"
