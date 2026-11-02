"""The files of one diagram: the .drawio, its pages and their images, the fingerprint and the hand-edit guard."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

SIDE_FILE_SUFFIX = ".generated.drawio"
MXFILE = {"host": "app.diagrams.net"}


@dataclass(frozen=True)
class Page:
    """One page of a .drawio: its name, its image and the mxfile the image is drawn from."""

    name: str
    image: Path
    mxfile: str


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_path(drawio: Path) -> Path:
    return drawio.with_suffix(".svg")


def mxfile(pages: list[ElementTree.Element], attrs: dict[str, str] = MXFILE) -> str:
    """The text of an mxfile holding `pages`, as cartographer writes it."""
    root = ElementTree.Element("mxfile", attrs)
    root.extend(pages)
    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="unicode").replace("'", "&#39;") + "\n"


def pages(drawio: Path, xml: str) -> list[Page]:
    """The pages of `xml`, the content of `drawio`. A file of one page (or none, or not XML) is drawn whole into the
    sibling image. Each page of a file of several is drawn alone into `<stem>-<page id>.svg`: page `1-context` of
    `shop-c4.drawio` into `shop-c4-1-context.svg`."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        root = ElementTree.Element("mxfile")
    diagrams = root.findall("diagram")
    if len(diagrams) < 2:
        return [Page(diagrams[0].get("name", "") if diagrams else "", image_path(drawio), xml)]
    return [Page(d.get("name", ""), drawio.with_name(f"{drawio.stem}-{d.get('id', '')}.svg"),
                 mxfile([d], root.attrib)) for d in diagrams]


def is_side_file(drawio: Path) -> bool:
    """A .generated.drawio written beside a hand-edited diagram: never indexed, checked or deleted."""
    return drawio.name.endswith(SIDE_FILE_SUFFIX)


def hand_edited(drawio: Path, curated: dict) -> bool:
    """True when a .drawio exists that the curated file does not vouch for."""
    return drawio.is_file() and sha256_file(drawio) != curated.get("drawio_sha256")


def record_sha256(curated_path: Path, sha256: str) -> None:
    curated = json.loads(curated_path.read_text())
    curated["drawio_sha256"] = sha256
    curated_path.write_text(json.dumps(curated, indent=2, ensure_ascii=False) + "\n")
