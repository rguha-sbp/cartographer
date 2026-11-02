"""Attribute rules: a catalog row names one, and it picks the icon from the resource's own literal attributes.
Returning None keeps the row's icon. An attribute that is not a literal is handled by Cloud.resolve, not here."""

from cartographer.clouds.base import Getter, Resolution, Rule


def _ecs_service(get: Getter) -> Resolution | None:
    launch_type = get("launch_type")
    if launch_type == "FARGATE":
        return Resolution("icon", "aws:fargate", 'rule aws_ecs_service launch_type = "FARGATE"')
    provider = get("capacity_provider_strategy.capacity_provider")
    if isinstance(provider, str) and provider.startswith("FARGATE"):
        return Resolution("icon", "aws:fargate", "rule aws_ecs_service capacity_provider_strategy names FARGATE")
    return None


def _database(tf_type: str) -> Rule:
    def rule(get: Getter) -> Resolution | None:
        engine = get("engine")
        if isinstance(engine, str) and engine.startswith("aurora"):
            return Resolution("icon", "aws:aurora", f'rule {tf_type} engine = "{engine}"')
        return None

    return rule


RULES: dict[str, Rule] = {
    "aws_ecs_service": _ecs_service,
    "aws_db_instance": _database("aws_db_instance"),
    "aws_rds_cluster": _database("aws_rds_cluster"),
}
