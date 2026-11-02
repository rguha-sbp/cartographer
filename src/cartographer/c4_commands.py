"""`cartographer prompt --c4` and `cartographer build --c4`: curate one C4 model of a system, then write every view
it supports, replacing the views an earlier model wrote."""

import argparse
import json
from pathlib import Path

from cartographer import c4_model, c4_styles, c4_verify, c4_views, files, gen_drawio, index, tf_layout, tfdiagram
from cartographer.build import EXIT_STALE, EXIT_VERIFY, Refusal, cached_facts, render_svgs
from cartographer.workdir import cache_dir

PROMPT = Path(__file__).with_name("c4_prompt.md")
EXIT_USAGE = 2  # as argparse exits on a bad command line


def prompt(args: argparse.Namespace, interview_path: Path) -> int:
    cache = cache_dir(args.name)
    facts_path = "none" if args.describe else cached_facts(args.name)
    schema_path = cache / "c4.schema.json"
    schema_path.write_text(c4_model.SCHEMA.read_text())
    print(tfdiagram.fill(PROMPT, schema_path=schema_path, model_path=cache / "model.json", repo_root=args.repo.resolve(),
                         facts_path=facts_path, interview_path=interview_path))
    return 0


def build(args: argparse.Namespace) -> int:
    if args.side_file or args.curated or args.replace:
        raise Refusal(EXIT_USAGE, "--side-file/--curated/--replace do not apply to --c4")
    repo = args.repo.resolve()
    out = repo / args.out
    model_path = cache_dir(args.name) / "model.json"
    if not model_path.is_file():
        raise Refusal(EXIT_STALE, f"no C4 model at {model_path}: run the curation (cartographer prompt --c4)")
    model = json.loads(model_path.read_text())
    facts = json.loads(cached_facts(args.name).read_text()) if model.get("source") == "terraform" else None

    errors = c4_verify.verify(model, facts, repo)
    report = c4_verify.report(errors, c4_verify.stated_only(model))
    if errors:
        print(report, end="")
        return EXIT_VERIFY
    print(report.splitlines()[0])
    views = c4_views.views(model)

    # Every view is laid out and rendered before anything is written, so a failure leaves the folder as it was.
    edge_labels = args.edge_labels == "on"
    mxfiles = {
        out / f"{args.name}-{v.slug}.drawio": gen_drawio.render(
            tf_layout.layout(v.curated, edge_labels=edge_labels, notation=c4_styles.C4),
            page_id=f"{args.name}-{v.slug}", page_name=v.title)
        for v in views
    }
    svgs = render_svgs(list(mxfiles.values()), args.drawio_url)

    out.mkdir(parents=True, exist_ok=True)
    for (drawio, mxfile), svg in zip(mxfiles.items(), svgs, strict=True):
        drawio.write_bytes(mxfile.encode())
        files.image_path(drawio).write_text(svg)
    for stale in out.glob(f"{args.name}-[1-6]-*.drawio"):
        if stale not in mxfiles and not files.is_side_file(stale):
            stale.unlink()
            files.image_path(stale).unlink(missing_ok=True)
    index.write_index(out)
    for drawio in mxfiles:
        print(drawio)
        print(files.image_path(drawio))
    return 0
