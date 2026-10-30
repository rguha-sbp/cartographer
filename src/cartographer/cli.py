"""The `cartographer` command: extract, prompt, build, snapshot, view, docs."""

import argparse
import sys
import webbrowser
from pathlib import Path
from xml.etree import ElementTree

from cartographer import build, snapshot, tf_extract, tfdiagram
from cartographer.workdir import cache_dir, write_json

HERE = Path(__file__).parent
DOCS = {"review": HERE / "REVIEW.md", "rules": HERE / "RULES.md"}
EXIT_NO_FACTS = 2


def _extract(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    facts_path = cache_dir(args.stack) / "facts.json"
    write_json(facts_path, tf_extract.extract(repo / args.infra_dir, repo))
    print(f"facts: {facts_path}")
    print(f"inputs key: {tfdiagram.inputs_sha256(facts_path)}")
    return 0


def _prompt(args: argparse.Namespace) -> int:
    cache = cache_dir(args.stack)
    facts_path = cache / "facts.json"
    if not facts_path.is_file():
        print(f"no facts for stack {args.stack}: run `cartographer extract` first", file=sys.stderr)
        return EXIT_NO_FACTS
    repo = args.repo.resolve()
    schema_path = cache / "curated.schema.json"
    schema_path.write_text(tfdiagram.schema_text())
    output = repo / "docs" / "architecture" / f"{args.stack}.curated.json"
    print(tfdiagram.render_prompt(facts_path, repo, schema_path, output, tfdiagram.inputs_sha256(facts_path)))
    return 0


def _mxfile(path: Path) -> str:
    text = path.read_text()
    if path.suffix == ".svg":
        return ElementTree.fromstring(text).attrib["content"]
    return text


def _view(args: argparse.Namespace) -> int:
    url = args.drawio_url.rstrip("/")
    if not snapshot.drawio_up(url):
        print(snapshot.DRAWIO_DOWN, file=sys.stderr)
        return 2
    webbrowser.open(snapshot.viewer_url(url, _mxfile(args.file)))
    return 0


def _docs(args: argparse.Namespace) -> int:
    print(DOCS[args.name])
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cartographer", description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    def command(name: str, handler, help_: str, *, stack: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(handler=handler)
        if stack:
            p.add_argument("--stack", required=True, help="diagram name, used for the cache folder and the file names")
            p.add_argument("--repo", type=Path, default=Path("."), help="repository root (default .)")
        return p

    p = command("extract", _extract, "read the Terraform and cache its facts")
    p.add_argument("infra_dir", type=Path, help="Terraform folder, relative to --repo")
    command("prompt", _prompt, "print the curation prompt for the cached facts")
    build.add_arguments(command("build", build.run, "verify the curated file and write the diagram"))
    p = command("snapshot", snapshot.run, "screenshot a .drawio file in the local draw.io", stack=False)
    snapshot.add_arguments(p)
    p = command("view", _view, "open a .drawio or .drawio.svg in the local draw.io", stack=False)
    p.add_argument("file", type=Path)
    p.add_argument("--drawio-url", default=snapshot.DRAWIO_URL, help="local draw.io; never a public host")
    p = command("docs", _docs, "print the path of a packaged document", stack=False)
    p.add_argument("name", choices=sorted(DOCS))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
