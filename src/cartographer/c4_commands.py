"""`cartographer prompt --c4` and `cartographer build --c4`: curate one C4 model of a system, then write every view
it supports as a page of one .drawio, replacing the views an earlier model wrote."""

import argparse
import json
from pathlib import Path

from cartographer import c4_model, c4_styles, c4_verify, c4_views, files, gen_drawio, tf_layout, tfdiagram
from cartographer.build import EXIT_VERIFY, Refusal, cached_facts, publish, read_curation, render_images
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
    model = read_curation(model_path, f"no C4 model at {model_path}: run the curation (cartographer prompt --c4)")
    facts = json.loads(cached_facts(args.name).read_text()) if model.get("source") == "terraform" else None

    errors = c4_verify.verify(model, facts, repo)
    print(c4_verify.report(errors, [] if errors else c4_verify.stated_only(model)), end="")
    if errors:
        return EXIT_VERIFY
    views = c4_views.views(model)

    # Every view is laid out and rendered before anything is written, so a failure leaves the folder as it was.
    edge_labels = args.edge_labels == "on"
    drawio = out / c4_views.drawio_name(args.name)
    mxfile = files.mxfile([
        gen_drawio.page(tf_layout.layout(v.curated, edge_labels=edge_labels, notation=c4_styles.C4),
                        page_id=v.slug, page_name=v.title, notation=c4_styles.C4)
        for v in views
    ])
    images = render_images(drawio, mxfile, args.drawio_url)

    for stale in out.glob("*"):
        if stale not in images and c4_views.written_by_c4(args.name, stale):
            stale.unlink()
    publish(drawio, mxfile, images)
    return 0
