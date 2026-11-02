"""Vendor draw.io's Azure icon table: icons.json {"<name>": {"path": "<category>/<File>.svg", "title": "<draw.io title>"}}.

Source: the pinned, sha256-checked draw.io web app (drawio_pin.json) that renders the diagrams, unpacked at <app>: the
files under <app>/img/lib/azure2/ and the titles in <app>/js/diagramly/sidebar/Sidebar-Azure2.js. Refresh after a bump
with:

    uv run python -m cartographer.clouds.azure.vendor

A name is the lower-cased file stem with anything but letters, digits and "_" removed; a stem that exists in two
categories belongs to the first category in sorted order. The title is the sidebar title, else the stem with spaces.

provider_types.json is every resource type of hashicorp/azurerm 5.12.0 plus the azapi resource types, sorted. A newer
provider adds types: replace the list, then run `python -m cartographer.clouds.azure.vendor --draft-catalog` to print
candidate rows for the types with no catalog row. It never writes the catalog; read every candidate and add the row to
catalog.json by hand. arm_types.json (ARM resource type -> icon name) is curated by hand.
"""

import json
import re
import sys
from pathlib import Path

from cartographer import drawio_app

OUT = Path(__file__).with_name("icons.json")
CATALOG = Path(__file__).with_name("catalog.json")
PROVIDER_TYPES = Path(__file__).with_name("provider_types.json")
SIDEBAR = "js/diagramly/sidebar/Sidebar-Azure2.js"
PALETTE_CALL = re.compile(r"this\.(addAzure2\w+Palette)\(gn, r, sb, s \+ '(\w+)/'\)")
PALETTE_BODY = re.compile(r"Sidebar\.prototype\.(addAzure2\w+Palette) = function")
ENTRY = re.compile(r"createVertexTemplateEntry\(s \+ '([^;']+\.svg);[^']*',\s*[^,]+,[^,]+, '', '((?:[^'\\]|\\.)*)'")


def sidebar_titles(source: str) -> dict[str, str]:
    """category/File.svg -> title."""
    categories = dict(PALETTE_CALL.findall(source))
    parts = PALETTE_BODY.split(source)
    return {f"{categories[fn]}/{file}": title.replace("\\'", "'")
            for fn, body in zip(parts[1::2], parts[2::2]) if fn in categories for file, title in ENTRY.findall(body)}


def parse(app: Path) -> dict[str, dict[str, str]]:
    titles = sidebar_titles((app / SIDEBAR).read_text(encoding="utf-8"))
    icons: dict[str, dict[str, str]] = {}
    for svg in sorted((app / "img/lib/azure2").glob("*/*.svg")):
        path = f"{svg.parent.name}/{svg.name}"
        name = re.sub(r"[^a-z0-9_]", "", svg.stem.lower())
        icons.setdefault(name, {"path": path, "title": titles.get(path, svg.stem.replace("_", " "))})
    return dict(sorted(icons.items()))


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
    azure = parse(drawio_app.ensure())
    lines = [f"  {json.dumps(name)}: {json.dumps(icon)}" for name, icon in azure.items()]
    OUT.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    print(f"{len(azure)} icons -> {OUT}")
