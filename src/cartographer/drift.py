"""`cartographer check`: every page of every .drawio under a folder has an image rendered from exactly that .drawio.
Offline."""

import argparse
from pathlib import Path
from xml.etree import ElementTree

from cartographer import files
from cartographer.svg_export import SOURCE_SHA_ATTR


def _problem(drawio: Path, image: Path) -> str | None:
    if not image.is_file():
        return f"{drawio}: no image, run `cartographer image {drawio}`"
    try:
        recorded = ElementTree.fromstring(image.read_text()).get(SOURCE_SHA_ATTR)
    except ElementTree.ParseError:
        return f"{image}: not valid XML, run `cartographer image {drawio}`"
    if recorded != files.sha256_file(drawio):
        return f"{image}: does not match {drawio.name}, run `cartographer image {drawio}`"
    return None


def problems(folder: Path) -> list[str]:
    drawios = (p for p in sorted(folder.rglob("*.drawio")) if not files.is_side_file(p))
    return [found for drawio in drawios for page in files.pages(drawio, drawio.read_text())
            if (found := _problem(drawio, page.image))]


def run(args: argparse.Namespace) -> int:
    found = problems(args.folder)
    for line in found:
        print(line)
    return 1 if found else 0
