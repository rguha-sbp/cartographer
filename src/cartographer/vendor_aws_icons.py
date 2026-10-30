"""Vendor draw.io's AWS icon tables: aws_icons.json {"<resIcon name>": "#FILL"} and generic_icons.json
{"<shape name>": "#FILL"} (the General Resources shapes drawn as `shape=mxgraph.aws4.<name>`: users, client, ...).

Source: Sidebar-AWS4.js from the pinned draw.io image (jgraph/drawio:32.5.5). Refresh with:

    docker cp drawio:/usr/local/tomcat/webapps/draw/js/diagramly/sidebar/Sidebar-AWS4.js <dir>/Sidebar-AWS4.js
    python -m cartographer.vendor_aws_icons <dir>/Sidebar-AWS4.js

Each addAWS4<Category>Palette function defines style vars (n, n2, ...) carrying the category fillColor and adds
entries like createVertexTemplateEntry(n2 + 'resourceIcon;resIcon=' + gn + '.lambda;', ...). The fill of an entry is
the fillColor of the style var it is built from, in the function it sits in; the first palette to define a name wins.
The retired-icons palette builds its styles with helper functions and is deliberately not read.
Generic shapes are the General Resources entries of the form createVertexTemplateEntry(n + 'users;', ...), with the
fill of the style var they are built from; the resourceIcon entries of that palette stay in aws_icons.json.
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).with_name("aws_icons.json")
GENERIC_OUT = Path(__file__).with_name("generic_icons.json")
GENERAL = re.compile(
    r"Sidebar\.prototype\.addAWS4GeneralResourcesPalette = function(.*?)(?=Sidebar\.prototype\.|\Z)", re.DOTALL
)
GENERIC_ENTRY = re.compile(r"createVertexTemplateEntry\((\w+) \+ '(\w+);'")
FUNCTION = re.compile(r"Sidebar\.prototype\.addAWS4\w*Palette = function")
STYLE_VAR = re.compile(r"var (\w+) = '[^\n]*?fillColor=(#[0-9A-Fa-f]{6})")
ENTRY = re.compile(r"createVertexTemplateEntry\((\w+) \+ '[^']*?resIcon=' \+ gn \+ '\.(\w+)")


def parse(source: str) -> dict[str, str]:
    icons: dict[str, str] = {}
    for body in FUNCTION.split(source)[1:]:
        fills = {name: fill.upper() for name, fill in STYLE_VAR.findall(body)}
        for style_var, icon in ENTRY.findall(body):
            icons.setdefault(icon, fills[style_var])
    return dict(sorted(icons.items()))


def parse_generic(source: str, taken: dict[str, str]) -> dict[str, str]:
    """Generic shapes; names that are also resIcon names (marketplace, all_products) stay AWS icons so lookups are unambiguous."""
    body = GENERAL.search(source).group(1)
    fills = {name: fill.upper() for name, fill in STYLE_VAR.findall(body)}
    return dict(sorted((icon, fills[style_var]) for style_var, icon in GENERIC_ENTRY.findall(body) if icon not in taken))


if __name__ == "__main__":
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    aws = parse(text)
    for out, icons in ((OUT, aws), (GENERIC_OUT, parse_generic(text, aws))):
        out.write_text(json.dumps(icons, indent=2) + "\n", encoding="utf-8")
        print(f"{len(icons)} icons -> {out}")
