# cartographer

cartographer draws Layer 7 AWS architecture diagrams as draw.io files, either from the Terraform in your repo or from
a solution you describe to Claude. Claude does the curation and, in describe mode, an interview. The tool does layout,
routing and verification and never calls a model. A diagram is only called ready after a visual review loop in which
Claude looks at the rendered image, fixes what is wrong and looks again.

## What you need

- Claude Code.
- `uv` (`uvx --version` should work).
- SSH access to `github.com/rguha-sbp/cartographer`.
- Google Chrome, used headless for images and screenshots.
- A local draw.io at `http://localhost:8080`. Start it once with the official image:

  ```
  docker run -d --name drawio -p 8080:8080 jgraph/drawio
  ```

  After a reboot, `docker start drawio`. Diagrams are rendered only by this local instance and are never sent to a
  public draw.io host.

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
2. Draws an early rough version, opens it in your local draw.io and alternates questions and redraws.
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

Commit all four. Intermediates (facts, schema, screenshots) live in `~/.cache/cartographer/<name>/` and are not
committed. Claude never commits or pushes for you.

## Nesting on the diagram

An L7 diagram nests AWS Cloud, region, account, VPC, subnet tier and workload:

- A VPC frame carries its address ranges in the title, for example `shop-vpc (10.0.0.0/16)`, but only when the
  Terraform or you gave them. A CIDR is never guessed.
- Subnet frames group the services of one tier: public, private or isolated. Availability Zones are not drawn.
- Workload frames hold the services of one application, so separate workloads read as separate, inside a subnet frame
  or directly under the account for regional services such as S3.

`cartographer view` is read-only: it opens the diagram in the local draw.io for looking. To change a diagram, edit
the `.drawio` as below and run `cartographer image` after.

## Nesting on the diagram

An L7 diagram nests AWS Cloud, region, account, VPC, subnet tier and workload:

- A VPC frame carries its address ranges in the title, for example `shop-vpc (10.0.0.0/16)`, but only when the
  Terraform or you gave them. A CIDR is never guessed.
- Subnet frames group the services of one tier: public, private or isolated. Availability Zones are not drawn.
- Workload frames hold the services of one application, so separate workloads read as separate, inside a subnet frame
  or directly under the account for regional services such as S3.

`cartographer view` is read-only: it opens the diagram in the local draw.io for looking. To change a diagram, edit
the `.drawio` as below and run `cartographer image` after.

## Editing a diagram by hand

1. Open the `.drawio` in the local draw.io (File > Open from > Device).
2. Edit, then save it back over the file (or export as `.drawio` and overwrite it).
3. Regenerate the image: `cartographer image docs/architecture/diagrams/<name>.drawio`.

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
| `snapshot FILE.drawio -o DIR` | PNG and tiles from the local draw.io, for the visual review |
| `view FILE.drawio` | open read-only in the local draw.io |
| `docs interview\|review\|rules` | print the path of a packaged document |

## Troubleshooting

`build` exit codes:

| Exit | Meaning | What to do |
|---|---|---|
| 1 | verify dropped something or left a node without a line | read the report, fix the curated file, rebuild |
| 2 | no facts for a Terraform diagram | run `extract` first |
| 3 | stale or missing curated file: Terraform changed since curation | curate again |
| 4 | the `.drawio` was edited by hand, nothing written | keep it, or rerun with `--replace` or `--side-file` |
| 5 | local draw.io is down or the render failed, nothing written | start draw.io on `localhost:8080`, rerun |

`check` exits 1 when a `.drawio` has no image or a stale one: run `cartographer image <file.drawio>`.

## Developing

```
uv sync
uv run --locked ruff check
uv run --locked pytest -q
```

Set `CARTOGRAPHER_FROM=/path/to/checkout` to make the skill run your working tree instead of the pinned tag. Bump the
version in `pyproject.toml`, `.claude-plugin/plugin.json` and the `@vX.Y.Z` pin in `skills/cartographer/SKILL.md`
together; a test checks that they agree. Design docs: [DESIGN.md](DESIGN.md), `docs/superpowers/specs/`, and
[src/cartographer/RULES.md](src/cartographer/RULES.md) for the drawing rules.
