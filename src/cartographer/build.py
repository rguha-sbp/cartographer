"""`cartographer build`: verify the committed curation against the cached facts, then lay out and write the diagram."""

import argparse
import json
import sys
from pathlib import Path

from cartographer import gen_drawio, snapshot, svg_export, tf_layout, tf_verify, tfdiagram
from cartographer.workdir import cache_dir, write_json

EXIT_VERIFY = 1
EXIT_NO_FACTS = 2
EXIT_STALE = 3
STALE = "Terraform changed since curation: rerun the curation"


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--out", type=Path, default=Path("docs/architecture"), help="relative to --repo")
    ap.add_argument("--curated", type=Path, help="curated file (default <out>/<stack>.curated.json)")
    ap.add_argument("--edge-labels", choices=("on", "off"), default="on", help="print edge captions (default on)")
    ap.add_argument("--drawio-url", default=snapshot.DRAWIO_URL, help="local draw.io for the svg; never a public host")


def _write_svg(drawio_path: Path, drawio_url: str) -> Path | None:
    url = drawio_url.rstrip("/")
    try:
        if not snapshot.drawio_up(url):
            raise svg_export.SvgError(f"{snapshot.DRAWIO_DOWN}, then rerun build")
        svg = svg_export.export_svg(drawio_path, url)
    except (svg_export.SvgError, snapshot.SnapshotError) as err:
        print(f"svg skipped: {err}")
        return None
    svg_path = drawio_path.with_name(drawio_path.name + ".svg")
    svg_path.write_text(svg)
    return svg_path


def run(args: argparse.Namespace) -> int:
    cache = cache_dir(args.stack)
    facts_path = cache / "facts.json"
    if not facts_path.is_file():
        print(f"no facts for stack {args.stack}: run `cartographer extract` first", file=sys.stderr)
        return EXIT_NO_FACTS
    repo = args.repo.resolve()
    out = repo / args.out
    curated_path = args.curated or out / f"{args.stack}.curated.json"
    if not curated_path.is_file():
        print(f"no curated file at {curated_path}: run the curation (`cartographer prompt`)", file=sys.stderr)
        return EXIT_STALE
    curated = json.loads(curated_path.read_text())
    if curated.get("inputs_sha256") != tfdiagram.inputs_sha256(facts_path):
        print(STALE, file=sys.stderr)
        return EXIT_STALE

    verified, report = tf_verify.verify(json.loads(facts_path.read_text()), curated, repo)
    (cache / "verify.txt").write_text(report)
    write_json(cache / "verified.json", verified)
    if tf_verify.needs_attention(curated, verified):
        print(report, end="")
        return EXIT_VERIFY
    print(report.splitlines()[0])

    out.mkdir(parents=True, exist_ok=True)
    drawio_path = out / f"{args.stack}.drawio"
    diagram = tf_layout.layout(verified, edge_labels=args.edge_labels == "on")
    page_id = f"{args.stack}-architecture"
    drawio_path.write_text(gen_drawio.render(diagram, page_id=page_id, page_name=verified["title"]))
    print(drawio_path)
    if svg_path := _write_svg(drawio_path, args.drawio_url):
        print(svg_path)
    return 0
