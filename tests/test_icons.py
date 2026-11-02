from cartographer import clouds, icons
from cartographer.diagram_model import AWS_ICONS

TODAY_LAMBDA_STYLE = (
    f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={AWS_ICONS['lambda']};"
    "strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
    "fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.resourceIcon;"
    "resIcon=mxgraph.aws4.lambda;"
)
TODAY_USERS_STYLE = (
    "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor=#232F3D;"
    "strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
    "fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.users;"
)


def test_style_of_an_aws_icon_is_todays_style():
    assert icons.style("aws:lambda") == TODAY_LAMBDA_STYLE


def test_generic_and_brand_styles_unchanged():
    assert icons.style("generic:users") == TODAY_USERS_STYLE
    assert icons.style("brand:github").startswith("shape=mxgraph.webicons.github;")


def test_unknown_and_unqualified_names_are_not_known():
    assert not icons.known("lambda") and not icons.known("aws:nope") and not icons.known(None)
    assert icons.known("aws:lambda") and icons.known("generic:users") and icons.known("brand:github")


def test_title_uses_drawio_title():
    assert icons.title("aws:elasticsearch_service") == "OpenSearch Service"
    assert icons.title("generic:users") == "Users"


def test_search_is_capped_and_ranked():
    hits = icons.search("aws", "s")
    assert len(hits) == 20
    assert icons.search("aws", "opensearch")[0] == ("aws:elasticsearch_service", "OpenSearch Service")
    assert icons.search("aws", "lambda")[0] == ("aws:lambda", "Lambda")


def test_namespaces_and_cloud_of():
    assert icons.namespaces() == ("aws", "generic", "brand")
    assert icons.cloud_of("aws:lambda") == "aws" and icons.cloud_of("generic:users") is None


def test_cloud_of_type():
    assert clouds.cloud_of_type("aws_lambda_function").name == "aws" and clouds.cloud_of_type("random_id") is None
