# cartographer

cartographer draws Layer 7 AWS and Azure architecture diagrams as draw.io files. It also draws C4 diagram sets (System
Context, Container, Component, Code, Deployment and Dynamic views, to the C4 model standard). It uses the code and
Terraform in your repo, or a solution that you describe to Claude.

Claude does the curation and, in describe mode, an interview. The tool does the layout, the routing and the
verification. The tool never calls a model. A diagram is ready only after a visual review loop. In the loop, Claude
looks at the rendered image, fixes what is wrong and looks again.

## View and edit a diagram

- In Claude Code: `/cartographer:view` (the only diagram) or `/cartographer:view shop-l7`.
- With the standalone CLI (see "Running the CLI directly"): run `view` or `view shop-l7` from the repo root. A path to a
  .drawio also works.

The command serves a pinned draw.io on `127.0.0.1` only while the window is open. Save writes the .drawio and
regenerates the image. When you close the window, the server stops.

## What you need

- Claude Code, and `git`. Claude Code uses `git` to add the marketplace. You do not need an SSH key: if none is set up,
  `git` clones over HTTPS.
- `uv` (`uv --version` must work). You do not need a Python install: if the machine has none, `uv` gets one.
- Google Chrome or Chromium on macOS, Linux or Windows. Chrome opens the editor window. Chrome also renders images and
  screenshots in headless mode.

## What gets installed

A pinned draw.io web app, run with `offline=1`, renders and edits the diagrams. A local server on `127.0.0.1` serves the
app only while a command runs. The Content Security Policy of the server limits the page to `127.0.0.1`. Diagrams are
never sent to a public draw.io host. There is no Docker.

### With the plugin

On the first command, cartographer downloads these items:

- Its Python dependencies from PyPI, through `uv` (about 11 MB of uv cache).
- A Python interpreter, only if `uv` finds none on the machine.
- The pinned draw.io build (version in the SBOM below). The download is about 49 MB. The tool checks it against its
  sha256 and unpacks it to about 118 MB on disk.

All of these items stay in the plugin data folder, `~/.claude/plugins/data/<id>/` (`cartographer-cartographer` for this
marketplace), under `drawio/`, `uv/` and `python/`. The intermediates (facts, schema, screenshots) also stay there, in
`<name>/`. The tool writes nothing to `~/.cache` or to the global directories of uv. The folder stays when you update
the plugin. `claude plugin uninstall cartographer` deletes the folder, unless you use `--keep-data`.

### Without the plugin (standalone CLI)

`uvx --from git+https://...` keeps its environment in the cache of uv (`uv cache dir`, `~/.cache/uv` on Linux and
macOS). cartographer keeps draw.io and the intermediates in `${XDG_CACHE_HOME:-~/.cache}/cartographer/`. To remove them,
run these commands:

```
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/cartographer"
uv cache clean cartographer
```

To move the cartographer folder to a different place, set `CARTOGRAPHER_HOME=/some/dir`.

## Bundled component (SBOM)

| Component | Version | Licence | URL | sha256 |
|---|---|---|---|---|
| draw.io web app (`draw.war`) | 32.5.5 | Apache-2.0 | https://github.com/jgraph/drawio/releases/download/v32.5.5/draw.war | `cde0ebd72da197da37d100353e226d5344b08f0fcf7e1b18d1e000a77f9c5f52` |

The pin is only in `src/cartographer/drawio_pin.json`. When the pin changes, change this table to match.

The release must be at least 7 days old (the age gate). No open
[draw.io security advisory](https://github.com/jgraph/drawio/security/advisories) can name the release. If an advisory
names the pinned version, a release that fixes it skips the age gate. If no fix exists yet, the run fails so that
someone sees it. The `drawio-bump` workflow checks daily and opens a PR (`scripts/bump_drawio.py`). To preview, run the
script by hand with `--dry-run`.

## Install the plugin

In Claude Code:

```
/plugin marketplace add rguha-sbp/cartographer
/plugin install cartographer@cartographer
```

Then, in the repo that you want to document, start a prompt with `/cartographer:cartographer` (see First run).

### Update

To update to the latest release, run this command:

```
claude plugin update cartographer@cartographer
```

Then start a new session or run `/reload-plugins`. An update keeps the plugin data folder. Because of this, the tool does not download draw.io again unless its pin changed.

## First run

### Terraform mode

In the repo root:

```
/cartographer:cartographer draw the architecture diagram of the Terraform in infra/
```

Claude then does these steps:

1. Asks for a diagram name (`<system>-<view>`, for example `shop-l7`) and the Terraform folder.
2. Extracts the facts. The tool parses the Terraform and does not plan it, so you do not need cloud credentials.
3. Curates: decides what is worth drawing, the grouping and the flows. Claude reads the application code for evidence.
4. Builds: the tool drops and reports unproven claims and anything that looks like a secret.
5. Reviews: takes screenshots of the result, checks them against a checklist, fixes the curation and builds again. It
   does this at most three times.

### Describe mode

Use this mode when there is no Terraform yet:

```
/cartographer:cartographer help me design an architecture diagram for a new solution
```

Claude then does these steps:

1. Interviews you, one question for each message, until the gaps are closed (entry points, data stores, integrations,
   who calls whom).
2. Draws an early rough version and opens it in the bundled draw.io editor. Then Claude asks questions and draws again,
   in turn.
3. Runs the same review loop as Terraform mode.
4. Ends with a list in the chat of every assumption that it made, so that you can correct them. The diagram never shows assumptions.

### C4 mode

Use this mode for a C4 set instead of a Layer 7 diagram:

```
/cartographer:cartographer draw the C4 diagrams of this system
```

Claude asks "Layer 7 architecture diagram or C4 set?" and then does these steps:

1. Reads the Terraform if there is some. If there is none, Claude interviews you. Each question names the C4 level,
   what Claude needs and why.
2. Asks if you want Code-level diagrams. C4 makes them optional, so Claude builds them only if you say yes.
3. Curates the model and builds one diagram for each view (Context, Container, Component, Deployment, Dynamic).
   Then it reviews each diagram against the checklist, with the rules for the type of the view.

Each C4 run overwrites the diagrams. It also deletes the view files that the model no longer makes. The repo keeps no
curated file.

## Where files land

All files go to `docs/architecture/diagrams/` in your repo:

| File | What it is |
|---|---|
| `<name>.drawio` | the diagram (the source of truth) |
| `<name>.svg` | image that the tool renders from exactly that `.drawio`, for GitHub |
| `<name>.curated.json` | the curation: what the tool drew and the evidence for it |
| `icons.json` | optional icon overrides for the diagrams in the folder |
| `README.md` | generated index of the diagrams in the folder |

Commit the four files that always exist: the `.drawio`, the `.svg`, the curated file and `README.md`. Also commit `icons.json` if it exists.

A C4 set writes different files. It writes one `<name>-c4.drawio` with a page (a tab in draw.io) for each view. It
writes an `.svg` for each view (for example `shop-c4-1-context.svg`, `shop-c4-2-container.svg`,
`shop-c4-3-component-api.svg`, `shop-c4-5-deployment.svg`). It also writes the index `README.md`, with one row for each
view. There is no curated file to commit.

The intermediates (facts, schema, screenshots) stay in the plugin data folder (`~/.cache/cartographer/<name>/` for the
standalone CLI). Do not commit them. Claude never commits or pushes for you.

## Nesting on the diagram

An L7 diagram nests these levels: cloud, region, account (an Azure subscription), network (a VPC or an Azure virtual
network), subnet tier and workload. A diagram that uses both clouds has one top-level frame for each cloud, side by
side:

- A network frame shows its address ranges in the title, for example `shop-vpc (10.0.0.0/16)`. It does this only when
  the Terraform or you gave the ranges. The tool never guesses a CIDR.
- A network frame for a VPC that another account shares in names that account in the title, for example
  `shared-vpc (in Networking account)`. The frame stays in your workload account, because the services in it belong to
  that account. Verify moves a shared VPC out of an account frame of its own, and keeps the owner only on a VPC the
  Terraform does not create, and only when a cited code line names the owner.
- Subnet frames group the services of one tier: public, private or isolated. The tool does not draw Availability
  Zones.
- Workload frames hold the services of one application, so that separate workloads look separate. A workload frame is inside a subnet frame, or directly under the account for regional services such as S3 or Azure Storage.
- On Azure, a private endpoint is in its subnet. An app with VNet integration stays outside the subnet. The tool does
  not draw resource groups.

The view command opens the diagram in the bundled draw.io editor. A C4 set opens with `view <name>-c4`, with one tab for
each view. To change a diagram, edit it there as the section below describes.

## Azure support

The tool reads Azure Terraform (`azurerm` and `azapi`) in the same way as AWS. Resources, role assignments, event
subscriptions and virtual networks become facts. The tool decides the subnet tier from what is in the subnet. It reads
only literal values. If a variable has no default, the tool marks the icon for review and does not guess.

## Icons and overrides

Each resource gets its icon from a catalog for each cloud, so the same Terraform always draws the same icon. If the
catalog is not sure about a resource, the tool marks it. The build report lists it under `Marked icons`. To change an
icon, find its name. Then add an override to `docs/architecture/diagrams/icons.json`:

```
cartographer icons --cloud azure --search "key vault"
```

```json
{"overrides": [{"cloud": "azure", "type": "azurerm_key_vault", "icon": "key_vault", "reason": "why this icon",
                "address": "optional: one resource instead of the whole type"}]}
```

Run `build` again. The report shows `Overrides` and `Icon changes` since the last build. A refused override names its
reason. A skipped override targets something that this diagram does not have.

`icons` prints at most 20 matches, as `cloud:name` and the title. `--cloud` is `aws`, `azure`, `generic` or `brand`.
Commit `icons.json` with the diagram.

The visual review starts from two files. `review.json` shows the view under review and, for every icon, the resource
that it stands for. `build` writes it to the cache folder. `tiles.json` shows which icons are in which tile.
`snapshot` writes it.

## Editing a diagram by hand

1. Run `/cartographer:view <name>` in Claude Code (or `view docs/architecture/diagrams/<name>.drawio` with the
   standalone CLI). The editor opens in its own Chrome window. It runs until you close the window (or press Ctrl-C).
2. Edit, then Save. Save writes the `.drawio` and regenerates its image next to it, so `check` stays green.

The next time the skill runs, it finds the hand edit. It asks you if you want to keep the edit, replace it with a fresh
generation, or write a side file to compare. These choices map to these actions: do nothing, `build --replace` and
`build --side-file`. The option `--side-file` writes `<name>.generated.drawio` and its image. Do not commit the side file or its image.

## Pre-commit hook

Add this to `.pre-commit-config.yaml`. Then run `pre-commit autoupdate --repo https://github.com/rguha-sbp/cartographer`.
This command sets `rev` to the latest release tag:

```yaml
repos:
  - repo: https://github.com/rguha-sbp/cartographer
    rev: LATEST_TAG
    hooks:
      - id: cartographer-check
```

The hook runs offline on `docs/architecture/diagrams/`. It blocks the commit when a `.drawio` has no image or its image
came from a different `.drawio`. This can occur after a hand edit without `cartographer image`.

## Running the CLI directly

Without the plugin, put this before each command:
`uvx --from git+https://github.com/rguha-sbp/cartographer@LATEST_TAG cartographer`. `LATEST_TAG` is the tag of the
latest release at https://github.com/rguha-sbp/cartographer/releases/latest.

| Command | What it does |
|---|---|
| `extract INFRA_DIR --name NAME` | save the Terraform facts in the cache and print the inputs key |
| `prompt --name NAME [--describe]` | print the curation prompt, or the describe prompt for a new solution |
| `prompt --name NAME --c4 [--describe]` | print the C4 curation prompt, or the C4 prompt that starts with an interview |
| `build --name NAME [--replace \| --side-file]` | verify, then write the `.drawio`, the `.svg` and the folder index |
| `build --name NAME --c4` | verify `model.json`, then write `NAME-c4.drawio` with a page and an `.svg` for each C4 view. It overwrites files and deletes stale view images |
| `image FILE.drawio` | regenerate the `.svg` next to a `.drawio`, one for each page of a file with several pages |
| `check FOLDER` | offline: fail when a page of a `.drawio` has no image or has a stale image |
| `snapshot FILE.drawio -o DIR` | for each page: print `view: <page name>`, then its PNG and tiles from the bundled draw.io, for the visual review |
| `view FILE.drawio` | edit in the bundled draw.io until you close the tab |
| `icons --cloud CLOUD --search WORDS` | find icon names (at most 20 results) |
| `docs interview\|review\|rules` | print the path of a packaged document |

## Troubleshooting

These are the `build` exit codes:

| Exit | Meaning | What to do |
|---|---|---|
| 1 | verify dropped something or left a node without a line | read the report, fix the curated file, build again |
| 2 | no facts for a Terraform diagram | run `extract` first |
| 3 | stale or missing curated file (or no `model.json` for C4): the Terraform changed after the curation | curate again |
| 4 | a person edited the `.drawio` by hand, the tool wrote nothing | keep it, or run again with `--replace` or `--side-file` |
| 5 | the tool could not download the bundled draw.io, or the render failed, and wrote nothing | read the message (download blocked, sha256 mismatch, Chrome missing), fix the cause, run again |

`build`, `image` and `snapshot` accept `--drawio-url`. Add this option to run your own local draw.io instead.

`check` exits 1 when a `.drawio` has no image or has a stale image. Run `cartographer image <file.drawio>`.

## Developing

```
uv sync
uv run --locked ruff check
uv run --locked pytest -q
```

To try the plugin from a working tree, run `claude --plugin-dir /path/to/checkout`. The plugin launcher
(`scripts/cartographer`) runs the checkout itself, so the plugin uses no tag and no git access. Change the version in
`pyproject.toml` and `.claude-plugin/plugin.json` together. A test checks that they agree. The README names no release tag, so you do not need to change it for a release. These are the design documents: [DESIGN.md](DESIGN.md),
`docs/superpowers/specs/`, and [src/cartographer/RULES.md](src/cartographer/RULES.md) for the drawing rules.
