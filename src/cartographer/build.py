"""`cartographer build`: verify the committed curation (against the cached facts for a Terraform diagram, by its own
structure and evidence for a described one), then lay out and write the diagram."""

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cartographer import (
    drawio_app,
    files,
    gen_drawio,
    index,
    snapshot,
    svg_export,
    tf_layout,
    tf_verify,
    tfdiagram,
    verify_description,
)
from cartographer.curated_format import upgrade
from cartographer.verify_shared import needs_attention
from cartographer.workdir import cache_dir, write_json

EXIT_VERIFY = 1
EXIT_NO_FACTS = 2
EXIT_STALE = 3
EXIT_HAND_EDITED = 4
EXIT_NO_RENDERER = 5
STALE = "Terraform changed since curation: rerun the curation"


class Refusal(Exception):
    """A command stopping with an exit code and a message; `cli.main` prints the message and returns the code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def cached_facts(name: str) -> Path:
    """The facts `cartographer extract` cached for diagram `name`."""
    facts_path = cache_dir(name) / "facts.json"
    if not facts_path.is_file():
        raise Refusal(EXIT_NO_FACTS, f"no facts for diagram {name}: run `cartographer extract` first")
    return facts_path


@contextmanager
def renderer(drawio_url: str | None) -> Iterator[str]:
    """The url of one draw.io, the caller's own at `drawio_url` else the bundled one; failing to start it or to
    render with it is a Refusal with EXIT_NO_RENDERER."""
    try:
        with drawio_app.drawio_at(drawio_url) as url:
            yield url
    except (svg_export.SvgError, snapshot.SnapshotError, drawio_app.DrawioError) as err:
        raise Refusal(EXIT_NO_RENDERER, str(err)) from err


def render_images(drawio: Path, mxfile: str, drawio_url: str | None) -> dict[Path, str]:
    """The images of `mxfile`, to be written as `drawio`, from one draw.io."""
    with renderer(drawio_url) as url:
        return svg_export.images(drawio, mxfile, url)


def publish(drawio: Path, mxfile: str, images: dict[Path, str]) -> None:
    """Write the .drawio and its images, refresh the folder index and print every written path."""
    drawio.parent.mkdir(parents=True, exist_ok=True)
    drawio.write_bytes(mxfile.encode())
    for image, svg in images.items():
        image.write_text(svg)
    index.write_index(drawio.parent)
    print(drawio, *images, sep="\n")


def _verify_terraform(name: str, curated: dict, repo: Path) -> tuple[dict, str]:
    facts_path = cached_facts(name)
    if curated.get("inputs_sha256") != tfdiagram.inputs_sha256(facts_path):
        raise Refusal(EXIT_STALE, STALE)
    return tf_verify.verify(json.loads(facts_path.read_text()), curated, repo)


def _verify_description(name: str, curated: dict, repo: Path) -> tuple[dict, str]:
    return verify_description.verify(curated, repo)


VERIFIERS = {"terraform": _verify_terraform, "description": _verify_description}


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--out", type=Path, default=Path("docs/architecture/diagrams"), help="relative to --repo")
    ap.add_argument("--curated", type=Path, help="curated file (default <out>/<name>.curated.json)")
    ap.add_argument("--edge-labels", choices=("on", "off"), default="on", help="print edge captions (default on)")
    ap.add_argument("--drawio-url", default=None, help="your own local draw.io (never a public host); default: the bundled one")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="overwrite a .drawio that was edited by hand")
    mode.add_argument("--side-file", action="store_true", help="write <name>.generated.drawio and its image instead")


def run(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    out = repo / args.out
    curated_path = args.curated or out / f"{args.name}.curated.json"
    if not curated_path.is_file():
        raise Refusal(EXIT_STALE, f"no curated file at {curated_path}: run the curation (`cartographer prompt`)")
    curated = upgrade(json.loads(curated_path.read_text()))
    verifier = VERIFIERS.get(curated.get("source"))
    if verifier is None:
        raise Refusal(EXIT_VERIFY, f"{curated_path}: source must be one of {', '.join(VERIFIERS)}")

    cache = cache_dir(args.name)
    verified, report = verifier(args.name, curated, repo)
    (cache / "verify.txt").write_text(report)
    write_json(cache / "verified.json", verified)
    if needs_attention(curated, verified):
        print(report, end="")
        return EXIT_VERIFY
    print(report.splitlines()[0])

    drawio_path = out / f"{args.name}.drawio"
    if files.hand_edited(drawio_path, curated) and not (args.replace or args.side_file):
        raise Refusal(
            EXIT_HAND_EDITED,
            f"the .drawio was edited by hand: {drawio_path}\n"
            "rerun with --replace to overwrite it or --side-file to write a .generated.drawio beside it",
        )

    title = tfdiagram.diagram_title(verified)
    diagram = tf_layout.layout({**verified, "title": title}, edge_labels=args.edge_labels == "on")
    mxfile = gen_drawio.render(diagram, page_id=f"{args.name}-architecture", page_name=title)
    target = out / f"{args.name}.generated.drawio" if args.side_file else drawio_path
    publish(target, mxfile, render_images(target, mxfile, args.drawio_url))
    if not args.side_file:
        files.record_sha256(curated_path, files.sha256_text(mxfile))
    return 0
