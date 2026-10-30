# cartographer

cartographer draws Layer 7 AWS architecture diagrams as draw.io files, either from the Terraform in your repo or from
a solution you describe to Claude. Claude does the curation and, in describe mode, an interview. The tool does layout,
routing and verification and never calls a model. A diagram is only called ready after a visual review loop in which
Claude looks at the rendered image, fixes what is wrong and looks again.

## View and edit a diagram

- In Claude Code: `/cartographer:view` (the only diagram) or `/cartographer:view shop-l7`.
- From the repo root: `cartographer view` or `cartographer view shop-l7` (a path to a .drawio works too).

This serves a pinned draw.io on `127.0.0.1` only while the window is open. Save writes the .drawio and regenerates the
image. Closing the window stops the server.

## What you need

- Claude Code.
- `uv` (`uv --version` should work). No git, no SSH key and no Python install are needed.
- Google Chrome, used headless for images and screenshots.

## What gets installed

Diagrams are rendered and edited by a pinned draw.io web app run with `offline=1`. A local server on `127.0.0.1`
serves it only while a command runs, and its Content Security Policy limits the page to `127.0.0.1`, so diagrams are
never sent to a public draw.io host. No Docker.

### With the plugin

On the first command, cartographer downloads:

- Its Python dependencies from PyPI, through `uv` (about 11 MB of uv cache).
- A Python interpreter, only if `uv` finds none on the machine.
- The pinned draw.io build (version in the SBOM below), about 49 MB to download, checked against its sha256 and
  unpacked to about 118 MB on disk.

All of it lives in the plugin data folder, `~/.claude/plugins/data/<id>/` (`cartographer-cartographer` for this
marketplace), under `drawio/`, `uv/` and `python/`. So do the intermediates (facts, schema, screenshots), in
`<name>/`. Nothing is written to `~/.cache` or to uv's global directories. The folder survives plugin updates and
`claude plugin uninstall cartographer` deletes it, unless you pass `--keep-data`.

### Without the plugin (standalone CLI)

`uvx --from git+ssh://...` keeps its environment in uv's cache (`uv cache dir`, `~/.cache/uv` on Linux and macOS)
and cartographer keeps draw.io and the intermediates in `${XDG_CACHE_HOME:-~/.cache}/cartographer/`. To remove them:

```
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/cartographer"
uv cache clean cartographer
```

Set `CARTOGRAPHER_HOME=/some/dir` to move the cartographer folder elsewhere.

## Bundled component (SBOM)

| Component | Version | Licence | URL | sha256 |
|---|---|---|---|---|
| draw.io web app (`draw.war`) | 32.5.5 | Apache-2.0 | https://github.com/jgraph/drawio/releases/download/v32.5.5/draw.war | `cde0ebd72da197da37d100353e226d5344b08f0fcf7e1b18d1e000a77f9c5f52` |

The pin lives only in `src/cartographer/drawio_pin.json`; update this table to match when it changes. The release must be
at least 7 days old (the age gate). The `drawio-bump` workflow checks for a newer release on the 1st and 15th of each month
and opens a PR (`scripts/bump_drawio.py`, or run it by hand with `--dry-run` to preview).

## Install the plugin

In Claude Code:

```
/plugin marketplace add git@github.com:rguha-sbp/cartographer.git
/plugin install cartographer@cartographer
```

Then run `/cartographer` in the repo you want to document.

## First run

### Terraform mode

Say: "Draw the architecture of the Terraform in `infra/`." Claude then:

1. Asks for a diagram name (`<system>-<view>`, for example `shop-l7`) and the Terraform folder.
2. Extracts the facts (the Terraform is parsed, not planned, so no cloud credentials are needed).
3. Curates: decides what is worth drawing, grouping and flows, reading the application code for evidence.
4. Builds: unproven claims and anything that looks like a secret are dropped and reported.
5. Reviews: takes screenshots of the result, checks them against a checklist, fixes the curation and rebuilds, at most
   three rounds.

### Describe mode

Say: "Help me design a diagram for a new solution." Use it when there is no Terraform yet. Claude then:

1. Interviews you, one question per message, until the gaps (entry points, data stores, integrations, who calls whom)
   are closed.
2. Draws an early rough version, opens it in the bundled draw.io editor and alternates questions and redraws.
3. Runs the same review loop as Terraform mode.
4. Ends by listing every assumption it made in chat so you can correct them. Assumptions are never shown on the
   diagram.

## Where files land

Everything goes to `docs/architecture/diagrams/` in your repo:

| File | What it is |
|---|---|
| `<name>.drawio` | the diagram, the source of truth |
| `<name>.svg` | image rendered from exactly that `.drawio`, for GitHub |
| `<name>.curated.json` | the curation: what was drawn and the evidence for it |
| `README.md` | generated index of the diagrams in the folder |

Commit all four. Intermediates (facts, schema, screenshots) live in the plugin data folder (`~/.cache/cartographer/<name>/` for the
standalone CLI) and are not committed. Claude never commits or pushes for you.

## Nesting on the diagram

An L7 diagram nests AWS Cloud, region, account, VPC, subnet tier and workload:

- A VPC frame carries its address ranges in the title, for example `shop-vpc (10.0.0.0/16)`, but only when the
  Terraform or you gave them. A CIDR is never guessed.
- Subnet frames group the services of one tier: public, private or isolated. Availability Zones are not drawn.
- Workload frames hold the services of one application, so separate workloads read as separate, inside a subnet frame
  or directly under the account for regional services such as S3.

`cartographer view` opens the diagram in the bundled draw.io editor. To change a diagram, edit it there as below.

## Nesting on the diagram

An L7 diagram nests AWS Cloud, region, account, VPC, subnet tier and workload:

- A VPC frame carries its address ranges in the title, for example `shop-vpc (10.0.0.0/16)`, but only when the
  Terraform or you gave them. A CIDR is never guessed.
- Subnet frames group the services of one tier: public, private or isolated. Availability Zones are not drawn.
- Workload frames hold the services of one application, so separate workloads read as separate, inside a subnet frame
  or directly under the account for regional services such as S3.

`cartographer view` opens the diagram in the bundled draw.io editor. To change a diagram, edit it there as below.

## Editing a diagram by hand

1. `cartographer view docs/architecture/diagrams/<name>.drawio` opens the editor in your browser. It keeps running
   until you close the tab (or press Ctrl-C).
2. Edit, then Save. Save writes the `.drawio` and regenerates its image next to it, so `cartographer check` stays
   green.

The next time the skill runs it notices the hand edit and asks you whether to keep it, replace it with a fresh
generation, or write a side file to compare. These map to doing nothing, `build --replace` and `build --side-file`
(which writes `<name>.generated.drawio` and its image, not to be committed).

## Pre-commit hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: git@github.com:rguha-sbp/cartographer
    rev: v0.3.0
    hooks:
      - id: cartographer-check
```

It runs offline on `docs/architecture/diagrams/` and blocks the commit when a `.drawio` has no image or its image was
rendered from a different `.drawio`, for example after a hand edit without `cartographer image`.

## Running the CLI directly

Without the plugin, prefix each command with
`uvx --from git+ssh://git@github.com/rguha-sbp/cartographer@v0.3.0 cartographer`:

| Command | What it does |
|---|---|
| `extract INFRA_DIR --name NAME` | cache the Terraform facts and print the inputs key |
| `prompt --name NAME [--describe]` | print the curation prompt, or the describe prompt for a new solution |
| `build --name NAME [--replace \| --side-file]` | verify, then write `.drawio`, `.svg` and the folder index |
| `image FILE.drawio` | regenerate the `.svg` next to a `.drawio` |
| `check FOLDER` | offline: fail when a `.drawio` has no image or a stale one |
| `snapshot FILE.drawio -o DIR` | PNG and tiles from the bundled draw.io, for the visual review |
| `view FILE.drawio` | edit in the bundled draw.io until the tab is closed |
| `docs interview\|review\|rules` | print the path of a packaged document |

## Troubleshooting

`build` exit codes:

| Exit | Meaning | What to do |
|---|---|---|
| 1 | verify dropped something or left a node without a line | read the report, fix the curated file, rebuild |
| 2 | no facts for a Terraform diagram | run `extract` first |
| 3 | stale or missing curated file: Terraform changed since curation | curate again |
| 4 | the `.drawio` was edited by hand, nothing written | keep it, or rerun with `--replace` or `--side-file` |
| 5 | the bundled draw.io could not be downloaded or the render failed, nothing written | read the message (download blocked, sha256 mismatch, Chrome missing), fix it, rerun |

`build`, `image` and `snapshot` accept `--drawio-url` to use your own local draw.io instead.

`check` exits 1 when a `.drawio` has no image or a stale one: run `cartographer image <file.drawio>`.

## Developing

```
uv sync
uv run --locked ruff check
uv run --locked pytest -q
```

To try the plugin from a working tree, run `claude --plugin-dir /path/to/checkout`: the plugin launcher
(`scripts/cartographer`) runs the checkout itself, so no tag or git access is involved. Bump the version in
`pyproject.toml`, `.claude-plugin/plugin.json` and the `@vX.Y.Z` pins in this README together; a test checks that
they agree. Design docs: [DESIGN.md](DESIGN.md), `docs/superpowers/specs/`, and
[src/cartographer/RULES.md](src/cartographer/RULES.md) for the drawing rules.
