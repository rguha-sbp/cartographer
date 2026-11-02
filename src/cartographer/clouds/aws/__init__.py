from cartographer.clouds.aws.network import network_facts
from cartographer.clouds.aws.permissions import permission_edges
from cartographer.clouds.aws.rules import RULES
from cartographer.clouds.base import Catalog, Cloud, Spec, load_json
from cartographer.diagram_model import FRAME_TITLE_LEFT


def _frame(gr_icon: str, stroke: str, font: str, dashed: int) -> str:
    return (f"points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],"
            f"[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
            f"fontSize=12;fontStyle=1;container=1;pointerEvents=0;collapsible=0;recursiveResize=0;"
            f"shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};strokeColor={stroke};fillColor=none;"
            f"fontColor={font};dashed={dashed};verticalAlign=top;align=left;spacingLeft={FRAME_TITLE_LEFT};")


FRAME_STYLES = {
    "cloud": _frame("group_aws_cloud_alt", "#232F3E", "#232F3E", 0),
    "region": _frame("group_region", "#00A4A6", "#147EBA", 1),
    "account": _frame("group_account", "#CD2264", "#CD2264", 0),
    "network": _frame("group_vpc2", "#8C4FFF", "#AAB7B8", 0),
    "subnet-public": _frame("group_security_group", "#7AA116", "#248814", 0),
    "subnet-private": _frame("group_security_group", "#00A4A6", "#147EBA", 0),
    "subnet-isolated": _frame("group_security_group", "#00A4A6", "#147EBA", 1),
}

EDGE_SPECS = {
    "aws_cloudwatch_event_target": [Spec("trigger", "rule", "arn")],
    "aws_lambda_event_source_mapping": [Spec("trigger", "event_source_arn", "function_name")],
    "aws_s3_bucket_notification": [Spec("trigger", "bucket", a) for a in ("lambda_function", "queue", "topic")],
    "aws_scheduler_schedule": [Spec("trigger", None, "target", "arn")],
    "aws_lambda_permission": [Spec("trigger", "source_arn", "function_name")],
    "aws_cloudfront_distribution": [Spec("route", None, "origin")],
    "aws_lambda_function_url": [Spec("route", None, "function_name")],
}
NETWORK_ATTRS = frozenset({"vpc_config", "network_configuration", "subnet_ids", "security_group_ids", "subnet_id", "vpc_id"})


class AwsCloud(Cloud):
    def network_facts(self, ex):
        return network_facts(ex)

    def permission_edges(self, ex):
        permission_edges(ex)


AWS = AwsCloud(
    "aws", "AWS", ("aws",), load_json(__file__, "icons.json"), FRAME_STYLES, "AWS managed services",
    provider_types=load_json(__file__, "provider_types.json"), catalog=Catalog(load_json(__file__, "catalog.json")),
    rules=RULES, modules=load_json(__file__, "modules.json"), edge_specs=EDGE_SPECS, network_attrs=NETWORK_ATTRS,
    data_ref_types=frozenset({"aws_iam_policy_document"}),
    param_types=frozenset({"aws_ssm_parameter", "aws_secretsmanager_secret"}),
)
