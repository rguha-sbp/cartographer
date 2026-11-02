from cartographer.clouds.aws import AWS
from cartographer.clouds.base import Cloud

CLOUDS: dict[str, Cloud] = {cloud.name: cloud for cloud in (AWS,)}
IGNORED_PROVIDERS = ("random", "tls", "time", "null", "local", "archive")


def cloud_of_type(tf_type: str) -> Cloud | None:
    provider = tf_type.split("_", 1)[0]
    return next((cloud for cloud in CLOUDS.values() if provider in cloud.providers), None)
