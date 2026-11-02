import pytest

from cartographer.clouds.aws import AWS
from cartographer.clouds.base import UNRESOLVED

LB = "aws:elastic_load_balancing"


def attrs(**values):
    return lambda attr: values.get(attr)


@pytest.mark.parametrize("tf_type", ["aws_lb", "aws_alb"])
@pytest.mark.parametrize("value", [None, "application", "network", "gateway", "${var.kind}"])
def test_a_load_balancer_has_one_icon_whatever_its_type(tf_type, value):
    r = AWS.resolve(tf_type, attrs(load_balancer_type=value))
    assert (r.kind, r.icon, r.marked, r.decided_by) == ("icon", LB, False, f"catalog {tf_type}")


@pytest.mark.parametrize("tf_type", ["aws_alb_listener", "aws_alb_listener_certificate", "aws_alb_listener_rule",
                                     "aws_alb_target_group", "aws_alb_target_group_attachment"])
def test_the_provider_aws_alb_aliases_are_listed_types(tf_type):
    assert not AWS.resolve(tf_type, attrs()).marked


@pytest.mark.parametrize(("attributes", "icon"), [
    ({"launch_type": "FARGATE"}, "aws:fargate"),
    ({"launch_type": "EC2"}, "aws:ecs"),
    ({"capacity_provider_strategy.capacity_provider": "FARGATE_SPOT"}, "aws:fargate"),
    ({"capacity_provider_strategy.capacity_provider": "my-ec2-provider"}, "aws:ecs"),
    ({}, "aws:ecs"),
])
def test_ecs_service_rule(attributes, icon):
    r = AWS.resolve("aws_ecs_service", attrs(**attributes))
    assert (r.icon, r.marked) == (icon, False)


@pytest.mark.parametrize("missing", ["launch_type", "capacity_provider_strategy.capacity_provider"])
def test_ecs_service_unresolved_marks_and_keeps_base_icon(missing):
    r = AWS.resolve("aws_ecs_service", lambda a: UNRESOLVED if a == missing else None)
    assert (r.icon, r.marked, r.reason) == ("aws:ecs", True, f"{missing} is not a literal")


@pytest.mark.parametrize("tf_type", ["aws_db_instance", "aws_rds_cluster"])
@pytest.mark.parametrize(("engine", "icon"), [
    ("aurora-postgresql", "aws:aurora"), ("aurora-mysql", "aws:aurora"), ("aurora", "aws:aurora"),
    ("postgres", "aws:rds"), ("mysql", "aws:rds"), (None, "aws:rds"),
])
def test_rds_rules(tf_type, engine, icon):
    assert AWS.resolve(tf_type, attrs(engine=engine)).icon == icon


@pytest.mark.parametrize("tf_type", ["aws_db_instance", "aws_rds_cluster"])
def test_rds_unresolved_marks_and_keeps_base_icon(tf_type):
    r = AWS.resolve(tf_type, lambda a: UNRESOLVED)
    assert (r.icon, r.marked, r.reason) == ("aws:rds", True, "engine is not a literal")


def test_every_rule_icon_exists():
    from cartographer import icons
    for tf_type in ("aws_lb", "aws_ecs_service", "aws_db_instance"):
        for value in (None, "network", "FARGATE", "aurora"):
            r = AWS.resolve(tf_type, attrs(load_balancer_type=value, launch_type=value, engine=value))
            assert icons.known(r.icon)
