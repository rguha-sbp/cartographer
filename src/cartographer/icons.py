"""The one place icon names are looked up. A name is qualified: "aws:lambda", "generic:users", "brand:github"."""

from cartographer.clouds import CLOUDS
from cartographer.clouds.base import load_json

# draw.io General Resources shape name -> fill; brand name -> the complete draw.io style of its logo.
_GENERIC: dict[str, str] = load_json(__file__, "generic_icons.json")
_BRAND: dict[str, str] = load_json(__file__, "brand_icons.json")


def namespaces() -> tuple[str, ...]:
    return (*CLOUDS, "generic", "brand")


def _names(namespace: str) -> list[str]:
    if namespace in CLOUDS:
        return list(CLOUDS[namespace].icons)
    return list({"generic": _GENERIC, "brand": _BRAND}.get(namespace, ()))


def _split(icon: str) -> tuple[str, str]:
    namespace, _, name = icon.partition(":")
    return namespace, name


def known(icon: str | None) -> bool:
    if not icon:
        return False
    namespace, name = _split(icon)
    return name in _names(namespace)


def cloud_of(icon: str) -> str | None:
    namespace = _split(icon)[0]
    return namespace if namespace in CLOUDS else None


def style(icon: str) -> str:
    namespace, name = _split(icon)
    if namespace in CLOUDS:
        return CLOUDS[namespace].icon_style(name)
    if namespace == "brand":
        return _BRAND[name]
    return (f"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor={_GENERIC[name]};"
            f"strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
            f"fontSize=12;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.{name};")


def title(icon: str) -> str:
    namespace, name = _split(icon)
    if namespace in CLOUDS:
        return CLOUDS[namespace].icons[name]["title"]
    return name.replace("_", " ").title()


def search(namespace: str, query: str, limit: int = 20) -> list[tuple[str, str]]:
    words = query.lower().split()
    hits = []
    for name in _names(namespace):
        label = title(f"{namespace}:{name}")
        haystack = f"{name} {label}".lower()
        if all(word in haystack for word in words):
            hits.append((name, f"{namespace}:{name}", label))
    hits.sort(key=lambda h: (h[0] != query.lower(), len(h[0]), h[0]))
    return [(qualified, label) for _, qualified, label in hits[:limit]]
