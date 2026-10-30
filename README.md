# cartographer

cartographer turns a Terraform folder into an AWS architecture diagram as draw.io XML (`.drawio`) and a `.drawio.svg`
that GitHub renders and draw.io can still edit. The Terraform is parsed, not planned, so no cloud credentials are
needed. The AI step runs in your own Claude Code session, driven by the plugin skill: it decides what is worth drawing
and how to group it, and every claim it makes is checked against the Terraform and the code before it is drawn. The
Python tool never calls a model.

## Pipeline

| Stage | Module | Uses AI |
|---|---|---|
| 1 extract | `tf_extract.py`, `tf_policies.py` | no |
| 2 curate | your Claude session, following `cartographer prompt` (`curate_prompt.md`) | yes |
| 3 verify | `tf_verify.py`, `secret_patterns.py` | no |
| 4 layout | `tf_layout.py`, `tf_blocks.py`, `tf_lanes.py`, `tf_order.py` | no |
| 5 render | `gen_drawio.py`, `svg_export.py` | no |

The curation is committed as `docs/architecture/<stack>.curated.json` with an `inputs_sha256` key (hash of the facts,
the prompt and the schema). `build` refuses with exit 3 when the Terraform changed since the curation, so a stale
curation is never drawn. Every node and edge must cite evidence that the verify stage can find; anything unproven, and
anything that looks like a secret, is dropped and reported, and `build` then exits 1.

## Use in a repo

Needs `uv`, Chrome or Chromium, and the local draw.io on `http://localhost:8080`.

```
/plugin marketplace add git@github.com:rguha-sbp/cartographer.git
/plugin install cartographer@cartographer
/cartographer
```

The skill asks for the stack name and the Terraform folder, extracts, curates when needed, builds, reviews the
rendered diagram and tells you which three files to commit: `docs/architecture/<stack>.drawio`, `<stack>.drawio.svg`
and `<stack>.curated.json`. It never commits or pushes.

The commands it runs, all through `uvx --from git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0 cartographer`:

| Command | What it does |
|---|---|
| `extract INFRA_DIR --stack NAME [--repo .]` | caches the facts in `~/.cache/cartographer/NAME/` and prints the inputs key |
| `prompt --stack NAME [--repo .]` | writes the schema to the cache and prints the curation prompt |
| `build --stack NAME [--repo .] [--out docs/architecture] [--curated PATH]` | verify, then write `.drawio` and `.drawio.svg` (exit 1 on drops, 3 on a stale curation) |
| `snapshot FILE -o DIR` | PNG and tiles from the local draw.io, for the visual review |
| `view FILE` | opens a `.drawio` or `.drawio.svg` in the local draw.io |
| `docs review\|rules` | prints the path of the packaged review checklist or drawing rules |

If the local draw.io is down, `build` still writes the `.drawio`, prints why the svg was skipped and exits 0.

## Viewing

- GitHub renders `<stack>.drawio.svg` in the repo.
- draw.io at `http://localhost:8080`, the draw.io desktop app and the VS Code draw.io extension open both the
  `.drawio.svg` and the `.drawio`.
- Lucid: File > Import > draw.io.

## Developing

```
uv run pytest -q && uv run ruff check
CARTOGRAPHER_FROM=/path/to/checkout   # the skill then runs your working tree instead of the pinned tag
```

Bump the version in `pyproject.toml`, `.claude-plugin/plugin.json` and the `@vX.Y.Z` pin in
`skills/cartographer/SKILL.md` together; a test checks that they agree.

## Security

- No containers, no network calls except the local draw.io on localhost and `uvx` fetching the tool.
- The tool only reads Terraform and repo files and needs no cloud credentials.
- Evidence snippets, labels and captions that match a secret pattern are dropped and never echoed in the report.
- The diagram never leaves the machine: only the local draw.io is used, never a public draw.io host.

## Repo layout

```
.claude-plugin/     plugin.json, marketplace.json
skills/cartographer the skill
src/cartographer/   pipeline stages, cli, schema, prompt, REVIEW.md, RULES.md, icon tables
tests/              format, extractor, layout, cli and plugin tests
.github/workflows/  ci.yml
DESIGN.md           deep reference
```

See [DESIGN.md](DESIGN.md) for the data formats, verification rules and layout algorithm, and
[src/cartographer/RULES.md](src/cartographer/RULES.md) for the drawing rules and where each one is enforced.
