"""Vendor draw.io's AWS icon tables: icons.json {"<resIcon name>": {"fill": "#FILL", "title": "<draw.io title>"}} and
the shared generic_icons.json
{"<shape name>": "#FILL"} (the General Resources shapes drawn as `shape=mxgraph.aws4.<name>`: users, client, ...).

Source: Sidebar-AWS4.js of the pinned draw.io web app (drawio_pin.json), the same sha256-checked build that renders
the diagrams, so the tables never name an icon that build lacks. Refresh after a bump with:

    uv run python -m cartographer.clouds.aws.vendor

Each addAWS4<Category>Palette function defines style vars (n, n2, ...) carrying the category fillColor and adds
entries like createVertexTemplateEntry(n2 + 'resourceIcon;resIcon=' + gn + '.lambda;', ...). The fill of an entry is
the fillColor of the style var it is built from, in the function it sits in; the first palette to define a name wins.
The retired-icons palette builds its styles with helper functions and is deliberately not read.
Generic shapes are the General Resources entries of the form createVertexTemplateEntry(n + 'users;', ...), with the
fill of the style var they are built from; the resourceIcon entries of that palette stay in icons.json.

provider_types.json is every resource type of hashicorp/aws 6.71.0, sorted. A newer provider adds types: replace the list,
then run `python -m cartographer.clouds.aws.vendor --draft-catalog` to print candidate rows for the types with no
catalog row. It never writes the catalog; read every candidate and add the row to catalog.json by hand.
"""

import json
import re
import sys
from pathlib import Path

from cartographer import drawio_app

OUT = Path(__file__).with_name("icons.json")
GENERIC_OUT = Path(__file__).parents[2] / "generic_icons.json"
SIDEBAR = "js/diagramly/sidebar/Sidebar-AWS4.js"
CATALOG = Path(__file__).with_name("catalog.json")
PROVIDER_TYPES = Path(__file__).with_name("provider_types.json")
GENERAL = re.compile(
    r"Sidebar\.prototype\.addAWS4GeneralResourcesPalette = function(.*?)(?=Sidebar\.prototype\.|\Z)", re.DOTALL
)
GENERIC_ENTRY = re.compile(r"createVertexTemplateEntry\((\w+) \+ '(\w+);'")
FUNCTION = re.compile(r"Sidebar\.prototype\.addAWS4\w*Palette = function")
STYLE_VAR = re.compile(r"var (\w+) = '[^\n]*?fillColor=(#[0-9A-Fa-f]{6})")
ENTRY = re.compile(
    r"createVertexTemplateEntry\((\w+) \+ '[^']*?resIcon=' \+ gn \+ '\.(\w+);',\s*[^,']+, [^,']+, '[^']*', '((?:[^'\\]|\\.)*)'"
)


def parse(source: str) -> dict[str, dict[str, str]]:
    icons: dict[str, dict[str, str]] = {}
    for body in FUNCTION.split(source)[1:]:
        fills = {name: fill.upper() for name, fill in STYLE_VAR.findall(body)}
        for style_var, icon, title in ENTRY.findall(body):
            icons.setdefault(icon, {"fill": fills[style_var], "title": title.replace("\\'", "'")})
    return dict(sorted(icons.items()))


def parse_generic(source: str, taken: dict[str, dict[str, str]]) -> dict[str, str]:
    """Generic shapes; names that are also resIcon names (marketplace, all_products) stay AWS icons so lookups are unambiguous."""
    body = GENERAL.search(source).group(1)
    fills = {name: fill.upper() for name, fill in STYLE_VAR.findall(body)}
    return dict(sorted((icon, fills[style_var]) for style_var, icon in GENERIC_ENTRY.findall(body) if icon not in taken))


def draft_catalog() -> list[str]:
    """One candidate row per family key of the types with no catalog row; the icon is the longest icon name that is a
    token prefix of the type, else "?" for the curator to fill."""
    from cartographer.clouds.base import Catalog

    catalog = Catalog(json.loads(CATALOG.read_text(encoding="utf-8")))
    names = json.loads(OUT.read_text(encoding="utf-8"))
    rows: dict[str, str] = {}
    for tf_type in json.loads(PROVIDER_TYPES.read_text(encoding="utf-8")):
        if catalog.row(tf_type) is None:
            tokens = tf_type.split("_")
            family = "_".join(tokens[:2])
            guess = next(("_".join(tokens[1:n]) for n in range(len(tokens), 1, -1) if "_".join(tokens[1:n]) in names), "?")
            rows.setdefault(family, guess)
    return [f"  {json.dumps(key)}: {json.dumps({'icon': icon})}," for key, icon in sorted(rows.items())]


if __name__ == "__main__" and sys.argv[1:] == ["--draft-catalog"]:
    print("\n".join(draft_catalog()))
elif __name__ == "__main__":
    text = (drawio_app.ensure() / SIDEBAR).read_text(encoding="utf-8")
    aws = parse(text)
    lines = [f"  {json.dumps(name)}: {json.dumps(icon)}" for name, icon in aws.items()]
    OUT.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    print(f"{len(aws)} icons -> {OUT}")
    generic = parse_generic(text, aws)
    GENERIC_OUT.write_text(json.dumps(generic, indent=2) + "\n", encoding="utf-8")
    print(f"{len(generic)} icons -> {GENERIC_OUT}")
