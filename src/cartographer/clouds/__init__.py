from cartographer.clouds.aws import AWS
from cartographer.clouds.base import Cloud, Resolution

CLOUDS: dict[str, Cloud] = {cloud.name: cloud for cloud in (AWS,)}
IGNORED_PROVIDERS = ("random", "tls", "time", "null", "local", "archive")


def cloud_of_type(tf_type: str) -> Cloud | None:
    provider = tf_type.split("_", 1)[0]
    return next((cloud for cloud in CLOUDS.values() if provider in cloud.providers), None)


def resolve_module(source: str) -> Resolution:
    matches = [(prefix, cloud, icon) for cloud in CLOUDS.values() for prefix, icon in cloud.modules.items()
               if source == prefix or source.startswith(prefix + "/")]
    if not matches:
        return Resolution("none", marked=True, reason="unknown module", decided_by="curator, unknown module")
    prefix, cloud, icon = max(matches, key=lambda m: len(m[0]))
    return Resolution("icon", f"{cloud.name}:{icon}", f"module {prefix}")
