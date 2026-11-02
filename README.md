# cartographer

cartographer draws Layer 7 AWS and Azure architecture diagrams and C4 diagram sets (System Context, Container, Component,
Code, Deployment and Dynamic views, to the C4 model standard) as draw.io files, either from the code and Terraform in
your repo or from a solution you describe to Claude. Claude does the curation and, in describe mode, an interview. The tool does layout,
routing and verification and never calls a model. A diagram is only called ready after a visual review loop in which
Claude looks at the rendered image, fixes what is wrong and looks again.

## View and edit a diagram

- In Claude Code: `/cartographer:view` (the only diagram) or `/cartographer:view shop-l7`.
- With the standalone CLI (see "Running the CLI directly"): `view` or `view shop-l7` from the repo root (a path to a
  .drawio works too).

This serves a pinned draw.io on `127.0.0.1` only while the window is open. Save writes the .drawio and regenerates the
image. Closing the window stops the server.

## What you need

- Claude Code, and `git`, which Claude Code uses to add the marketplace. No SSH key is needed: it clones over HTTPS
  when none is set up.
- `uv` (`uv --version` should work). No Python install is needed: `uv` fetches one if the machine has none.
- Google Chrome or Chromium on macOS, Linux or Windows. It opens the editor window and renders images and screenshots
  headless.

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

`uvx --from git+https://...` keeps its environment in uv's cache (`uv cache dir`, `~/.cache/uv` on Linux and macOS)
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
at least 7 days old (the age gate) and not named by any open
[draw.io security advisory](https://github.com/jgraph/drawio/security/advisories). When an advisory names the pinned
version, a release that fixes it skips the age gate; if no fix exists yet the run fails so it is noticed. The
`drawio-bump` workflow checks daily and opens a PR (`scripts/bump_drawio.py`, or run it by hand with `--dry-run` to
preview).

## Install the plugin

In Claude Code:

```
/plugin marketplace add rguha-sbp/cartographer
/plugin install cartographer@cartographer
```

Then, in the repo you want to document, start a prompt with `/cartographer:cartographer` (see First run).

### Update

To update to the latest release:

```
claude plugin update cartographer@cartographer
```

then start a new session or run `/reload-plugins`. Updates keep the plugin data folder, so draw.io is not downloaded
again unless its pin changed.

## First run

### Terraform mode

In the repo root:

```
/cartographer:cartographer draw the architecture diagram of the Terraform in infra/
```

Claude then:

1. Asks for a diagram name (`<system>-<view>`, for example `shop-l7`) and the Terraform folder.
2. Extracts the facts (the Terraform is parsed, not planned, so no cloud credentials are needed).
3. Curates: decides what is worth drawing, grouping and flows, reading the application code for evidence.
4. Builds: unproven claims and anything that looks like a secret are dropped and reported.
5. Reviews: takes screenshots of the result, checks them against a checklist, fixes the curation and rebuilds, at most
   three rounds.

### Describe mode

Use it when there is no Terraform yet:

```
/cartographer:cartographer help me design an architecture diagram for a new solution
```

Claude then:

1. Interviews you, one question per message, until the gaps (entry points, data stores, integrations, who calls whom)
   are closed.
2. Draws an early rough version, opens it in the bundled draw.io editor and alternates questions and redraws.
3. Runs the same review loop as Terraform mode.
4. Ends by listing every assumption it made in chat so you can correct them. Assumptions are never shown on the
   diagram.

### C4 mode

Use it for a C4 set instead of a Layer 7 diagram:

```
/cartographer:cartographer draw the C4 diagrams of this system
```

Claude asks "Layer 7 architecture diagram or C4 set?" and then:

1. Reads the Terraform if there is some, or interviews you if not. Each question names the C4 level, what is needed
   and why.
2. Asks whether you want Code-level diagrams. C4 makes them optional, so they are built only if you say yes.
3. Curates the model, builds one diagram per view (Context, Container, Component, Deployment, Dynamic) and reviews each
   one against the checklist, with the rules for its view type.

C4 runs overwrite the diagrams every time and delete the view files the model no longer produces. No curated file is
kept in the repo.

## Where files land

Everything goes to `docs/architecture/diagrams/` in your repo:

| File | What it is |
|---|---|
| `<name>.drawio` | the diagram, the source of truth |
| `<name>.svg` | image rendered from exactly that `.drawio`, for GitHub |
| `<name>.curated.json` | the curation: what was drawn and the evidence for it |
| `icons.json` | optional icon overrides for the diagrams in the folder |
| `README.md` | generated index of the diagrams in the folder |

Commit all four (and `icons.json` when it exists). A C4 set instead writes one `<name>-c4.drawio` with a page (a tab in draw.io) per view, an `.svg` per view (for example `shop-c4-1-context.svg`, `shop-c4-2-container.svg`, `shop-c4-3-component-api.svg`, `shop-c4-5-deployment.svg`) and the index `README.md`, with one row per view. There is no curated file to commit. Intermediates (facts, schema, screenshots) live in the plugin data folder (`~/.cache/cartographer/<name>/` for the
standalone CLI) and are not committed. Claude never commits or pushes for you.

## Nesting on the diagram

An L7 diagram nests cloud, region, account (an Azure subscription), network (a VPC or an Azure virtual network), subnet tier
and workload. A diagram that uses both clouds has one top-level frame per cloud, side by side:

- A network frame carries its address ranges in the title, for example `shop-vpc (10.0.0.0/16)`, but only when the
  Terraform or you gave them. A CIDR is never guessed.
- Subnet frames group the services of one tier: public, private or isolated. Availability Zones are not drawn.
- Workload frames hold the services of one application, so separate workloads read as separate, inside a subnet frame
  or directly under the account for regional services such as S3 or Azure Storage.
- On Azure, a private endpoint sits in its subnet, an app with VNet integration stays outside it, and resource groups are
  not drawn.

The view command opens the diagram in the bundled draw.io editor. A C4 set opens with `view <name>-c4`, one tab per
view. To change a diagram, edit it there as below.

## Azure support

Azure Terraform (`azurerm` and `azapi`) is read like AWS: resources, role assignments, event subscriptions and virtual
networks become facts, and the subnet tier is decided from what sits in the subnet. Only literal values are read; a
variable without a default marks the icon for review instead of guessing.

## Icons and overrides

Each resource gets its icon from a per-cloud catalog, so the same Terraform always draws the same icon. A resource the
catalog is unsure of is marked, and the build report lists it under `Marked icons`. To change an icon, find its name,
then add an override to `docs/architecture/diagrams/icons.json`:

```
cartographer icons --cloud azure --search "key vault"
```

```json
{"overrides": [{"cloud": "azure", "type": "azurerm_key_vault", "icon": "key_vault", "reason": "why this icon",
                "address": "optional: one resource instead of the whole type"}]}
```

Run `build` again. The report shows `Overrides` (a refused one names its reason; a skipped one targets something this diagram does not have) and `Icon changes` since the last build.
`icons` prints at most 20 matches, as `cloud:name` and the title; `--cloud` is `aws`, `azure`, `generic` or `brand`.
Commit `icons.json` with the diagram.

The visual review starts from `review.json` (written by `build` to the cache folder: the view being reviewed and, for
every icon, the resource it stands for) and `tiles.json` (written by `snapshot`: which icons fall in which tile).

## Editing a diagram by hand

1. `/cartographer:view <name>` in Claude Code (or `view docs/architecture/diagrams/<name>.drawio` with the
   standalone CLI) opens the editor in its own Chrome window. It keeps running until you close the window (or press
   Ctrl-C).
2. Edit, then Save. Save writes the `.drawio` and regenerates its image next to it, so `check` stays green.

The next time the skill runs it notices the hand edit and asks you whether to keep it, replace it with a fresh
generation, or write a side file to compare. These map to doing nothing, `build --replace` and `build --side-file`
(which writes `<name>.generated.drawio` and its image, not to be committed).

## Pre-commit hook

Add to `.pre-commit-config.yaml`, then run `pre-commit autoupdate --repo https://github.com/rguha-sbp/cartographer`,
which sets `rev` to the latest release tag:

```yaml
repos:
  - repo: https://github.com/rguha-sbp/cartographer
    rev: LATEST_TAG
    hooks:
      - id: cartographer-check
```

It runs offline on `docs/architecture/diagrams/` and blocks the commit when a `.drawio` has no image or its image was
rendered from a different `.drawio`, for example after a hand edit without `cartographer image`.

## Running the CLI directly

Without the plugin, prefix each command with
`uvx --from git+https://github.com/rguha-sbp/cartographer@LATEST_TAG cartographer`, where `LATEST_TAG` is the tag of
the latest release at https://github.com/rguha-sbp/cartographer/releases/latest:

| Command | What it does |
|---|---|
| `extract INFRA_DIR --name NAME` | cache the Terraform facts and print the inputs key |
| `prompt --name NAME [--describe]` | print the curation prompt, or the describe prompt for a new solution |
| `prompt --name NAME --c4 [--describe]` | print the C4 curation prompt, or the interview-led one |
| `build --name NAME [--replace \| --side-file]` | verify, then write `.drawio`, `.svg` and the folder index |
| `build --name NAME --c4` | verify `model.json`, then write `NAME-c4.drawio` with a page and an `.svg` per C4 view; overwrites, deletes stale view images |
| `image FILE.drawio` | regenerate the `.svg` next to a `.drawio`, one per page of a file of several |
| `check FOLDER` | offline: fail when a page of a `.drawio` has no image or a stale one |
| `snapshot FILE.drawio -o DIR` | per page: print `view: <page name>`, then its PNG and tiles from the bundled draw.io, for the visual review |
| `view FILE.drawio` | edit in the bundled draw.io until the tab is closed |
| `icons --cloud CLOUD --search WORDS` | find icon names (at most 20 results) |
| `docs interview\|review\|rules` | print the path of a packaged document |

## Troubleshooting

`build` exit codes:

| Exit | Meaning | What to do |
|---|---|---|
| 1 | verify dropped something or left a node without a line | read the report, fix the curated file, rebuild |
| 2 | no facts for a Terraform diagram | run `extract` first |
| 3 | stale or missing curated file (or no `model.json` for C4): Terraform changed since curation | curate again |
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
`pyproject.toml` and `.claude-plugin/plugin.json` together; a test checks that they agree. The README names no
release tag, so it needs no change for a release. Design docs: [DESIGN.md](DESIGN.md), `docs/superpowers/specs/`, and
[src/cartographer/RULES.md](src/cartographer/RULES.md) for the drawing rules.
