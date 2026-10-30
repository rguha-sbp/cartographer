"""`cartographer build`: verify the committed curation (against the cached facts for a Terraform diagram, by its own
structure and evidence for a described one), then lay out and write the diagram."""

import argparse
import json
import sys
from pathlib import Path

from cartographer import (
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
from cartographer.verify_shared import needs_attention
from cartographer.workdir import cache_dir, write_json

EXIT_VERIFY = 1
EXIT_NO_FACTS = 2
EXIT_STALE = 3
EXIT_HAND_EDITED = 4
EXIT_NO_RENDERER = 5
STALE = "Terraform changed since curation: rerun the curation"


class Refusal(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _verify_terraform(name: str, curated: dict, repo: Path) -> tuple[dict, str]:
    facts_path = cache_dir(name) / "facts.json"
    if not facts_path.is_file():
        raise Refusal(EXIT_NO_FACTS, f"no facts for diagram {name}: run `cartographer extract` first")
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
    ap.add_argument("--drawio-url", default=snapshot.DRAWIO_URL, help="local draw.io for the image; never a public host")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="overwrite a .drawio that was edited by hand")
    mode.add_argument("--side-file", action="store_true", help="write <name>.generated.drawio and its image instead")


def run(args: argparse.Namespace) -> int:
    try:
        return _build(args)
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return refusal.code


def _build(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    out = repo / args.out
    curated_path = args.curated or out / f"{args.name}.curated.json"
    if not curated_path.is_file():
        raise Refusal(EXIT_STALE, f"no curated file at {curated_path}: run the curation (`cartographer prompt`)")
    curated = json.loads(curated_path.read_text())
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
    try:
        svg = svg_export.export_svg(mxfile, args.drawio_url.rstrip("/"))
    except (svg_export.SvgError, snapshot.SnapshotError) as err:
        raise Refusal(EXIT_NO_RENDERER, str(err)) from err

    target = out / f"{args.name}.generated.drawio" if args.side_file else drawio_path
    out.mkdir(parents=True, exist_ok=True)
    target.write_bytes(mxfile.encode())
    files.image_path(target).write_text(svg)
    if not args.side_file:
        files.record_sha256(curated_path, files.sha256_text(mxfile))
    index.write_index(out)
    print(target)
    print(files.image_path(target))
    return 0
