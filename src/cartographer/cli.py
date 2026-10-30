"""The `cartographer` command: extract, prompt, build, image, check, snapshot, view, docs."""

import argparse
import sys
import webbrowser
from pathlib import Path

from cartographer import build, drift, files, index, snapshot, svg_export, tf_extract, tfdiagram
from cartographer.workdir import cache_dir, write_json

HERE = Path(__file__).parent
DOCS = {"review": HERE / "REVIEW.md", "rules": HERE / "RULES.md", "interview": HERE / "INTERVIEW.md"}
EXIT_NO_FACTS = 2
VIEW_NOTE = ("Read-only view. To edit, open the .drawio in your local draw.io (never a public host) "
             "and run `cartographer image` after.")


def _extract(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    facts_path = cache_dir(args.name) / "facts.json"
    write_json(facts_path, tf_extract.extract(repo / args.infra_dir, repo))
    print(f"facts: {facts_path}")
    print(f"inputs key: {tfdiagram.inputs_sha256(facts_path)}")
    return 0


def _prompt(args: argparse.Namespace) -> int:
    cache = cache_dir(args.name)
    repo = args.repo.resolve()
    output = repo / "docs" / "architecture" / "diagrams" / f"{args.name}.curated.json"
    schema_path = cache / "curated.schema.json"
    if args.describe:
        schema_path.write_text(tfdiagram.schema_text())
        print(tfdiagram.render_describe_prompt(schema_path, output, DOCS["interview"]))
        return 0
    facts_path = cache / "facts.json"
    if not facts_path.is_file():
        print(f"no facts for diagram {args.name}: run `cartographer extract` first", file=sys.stderr)
        return EXIT_NO_FACTS
    schema_path.write_text(tfdiagram.schema_text())
    print(tfdiagram.render_prompt(facts_path, repo, schema_path, output, tfdiagram.inputs_sha256(facts_path)))
    return 0


def _view(args: argparse.Namespace) -> int:
    if args.file.suffix != ".drawio":
        print("view takes a .drawio file", file=sys.stderr)
        return 2
    url = args.drawio_url.rstrip("/")
    if not snapshot.drawio_up(url):
        print(snapshot.DRAWIO_DOWN, file=sys.stderr)
        return 2
    webbrowser.open(snapshot.viewer_url(url, args.file.read_text()))
    print(VIEW_NOTE)
    return 0


def _image(args: argparse.Namespace) -> int:
    try:
        svg = svg_export.export_svg(args.file.read_bytes().decode(), args.drawio_url.rstrip("/"))
    except (svg_export.SvgError, snapshot.SnapshotError) as err:
        print(err, file=sys.stderr)
        return build.EXIT_NO_RENDERER
    files.image_path(args.file).write_text(svg)
    index.write_index(args.file.parent)
    print(files.image_path(args.file))
    return 0


def _docs(args: argparse.Namespace) -> int:
    print(DOCS[args.name])
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cartographer", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    def command(name: str, handler, help_: str, *, named: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(handler=handler)
        if named:
            p.add_argument("--name", required=True, help="diagram name, used for the cache folder and the file names")
            p.add_argument("--repo", type=Path, default=Path("."), help="repository root (default .)")
        return p

    p = command("extract", _extract, "read the Terraform and cache its facts")
    p.add_argument("infra_dir", type=Path, help="Terraform folder, relative to --repo")
    p = command("prompt", _prompt, "print the curation prompt for the cached facts, or the describe prompt")
    p.add_argument("--describe", action="store_true", help="describe a new solution: no facts needed")
    build.add_arguments(command("build", build.run, "verify the curated file and write the diagram"))
    p = command("snapshot", snapshot.run, "screenshot a .drawio file in the local draw.io", named=False)
    snapshot.add_arguments(p)
    p = command("view", _view, "open a .drawio in the local draw.io", named=False)
    p.add_argument("file", type=Path)
    p.add_argument("--drawio-url", default=snapshot.DRAWIO_URL, help="local draw.io; never a public host")
    p = command("image", _image, "regenerate the .svg image next to a .drawio", named=False)
    p.add_argument("file", type=Path, help="the .drawio file")
    p.add_argument("--drawio-url", default=snapshot.DRAWIO_URL, help="local draw.io; never a public host")
    p = command("check", drift.run, "fail when a .drawio has no image or a stale one (offline)", named=False)
    p.add_argument("folder", type=Path, help="diagrams folder, searched recursively")
    p = command("docs", _docs, "print the path of a packaged document (review, rules, interview)", named=False)
    p.add_argument("name", choices=sorted(DOCS))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
