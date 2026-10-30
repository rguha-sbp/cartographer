"""`cartographer build`: verify the committed curation against the cached facts, then lay out and write the diagram."""

import argparse
import json
import sys
from pathlib import Path

from cartographer import files, gen_drawio, index, snapshot, svg_export, tf_layout, tf_verify, tfdiagram
from cartographer.workdir import cache_dir, write_json

EXIT_VERIFY = 1
EXIT_NO_FACTS = 2
EXIT_STALE = 3
EXIT_HAND_EDITED = 4
EXIT_NO_RENDERER = 5
STALE = "Terraform changed since curation: rerun the curation"


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--out", type=Path, default=Path("docs/architecture/diagrams"), help="relative to --repo")
    ap.add_argument("--curated", type=Path, help="curated file (default <out>/<name>.curated.json)")
    ap.add_argument("--edge-labels", choices=("on", "off"), default="on", help="print edge captions (default on)")
    ap.add_argument("--drawio-url", default=snapshot.DRAWIO_URL, help="local draw.io for the image; never a public host")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="overwrite a .drawio that was edited by hand")
    mode.add_argument("--side-file", action="store_true", help="write <name>.generated.drawio and its image instead")


def run(args: argparse.Namespace) -> int:
    cache = cache_dir(args.name)
    facts_path = cache / "facts.json"
    if not facts_path.is_file():
        print(f"no facts for diagram {args.name}: run `cartographer extract` first", file=sys.stderr)
        return EXIT_NO_FACTS
    repo = args.repo.resolve()
    out = repo / args.out
    curated_path = args.curated or out / f"{args.name}.curated.json"
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

    drawio_path = out / f"{args.name}.drawio"
    if files.hand_edited(drawio_path, curated) and not (args.replace or args.side_file):
        print(f"the .drawio was edited by hand: {drawio_path}", file=sys.stderr)
        print("rerun with --replace to overwrite it or --side-file to write a .generated.drawio beside it", file=sys.stderr)
        return EXIT_HAND_EDITED

    title = tfdiagram.diagram_title(verified)
    diagram = tf_layout.layout({**verified, "title": title}, edge_labels=args.edge_labels == "on")
    mxfile = gen_drawio.render(diagram, page_id=f"{args.name}-architecture", page_name=title)
    try:
        svg = svg_export.export_svg(mxfile, args.drawio_url.rstrip("/"))
    except (svg_export.SvgError, snapshot.SnapshotError) as err:
        print(err, file=sys.stderr)
        return EXIT_NO_RENDERER

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
