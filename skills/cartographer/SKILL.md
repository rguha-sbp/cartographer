---
name: cartographer
description: Build a verified AWS architecture diagram (draw.io and svg) either from the Terraform in this repo or from an engineer's description of a new solution, then review the rendered result visually and fix curation findings until it is clean. Use when asked to generate, refresh, design or check an architecture diagram.
---

# Cartographer diagram loop

A diagram is not ready because the build passed. It is ready when you have looked at it. You do the curation yourself
in this session: the cartographer tool reads Terraform when there is some, verifies your curation against the Terraform and
the code (or, for a described solution, checks its structure and evidence), and draws. It never calls a model.

Every command below runs from the repo root. Shell state does not carry between Bash calls, so each command is spelled
out in full.

## 0. Choose the mode

- The repo has a Terraform folder (`infra/`, `terraform/`, or one the user names): ask whether to draw from it
  (Terraform flow, steps 3 to 5) or describe a new solution (describe flow below).
- No Terraform folder: describe mode, go straight to the describe flow.

Both flows end in the same review loop (step 6) and the same checks.

## 1. Name and folders

Ask the user, or derive from the repo, the diagram name (lowercase kebab-case `<system>-<view>`, for example
`shop-l7`) and, for the Terraform flow, the Terraform folder (default `infra`). The outputs go to `docs/architecture/diagrams/<name>.*`.

## 2. Prerequisites

- `uv` is installed (`uv --version`). Nothing else is needed: no git, no SSH key, no Python. The launcher keeps
  every download and cache in the plugin data folder, which Claude Code deletes on uninstall.
- Nothing else runs: cartographer serves its own pinned draw.io on 127.0.0.1 while a command needs it. The first
  command downloads it once (about 49 MB, checked against a pinned sha256). If that download is blocked, tell the
  user and stop. Never use a public draw.io host: the diagram must not leave the machine.
- Chrome or Chromium is installed.

## 3. Extract

```
"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" extract INFRA_DIR --name NAME
```

It prints the facts path (in the cache folder, nothing is written into the repo) and the `inputs key`.

## 4. Curate (only when needed)

If `docs/architecture/diagrams/<name>.curated.json` exists and its `inputs_sha256` equals the inputs key, skip this step.
Otherwise:

```
"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" prompt --name NAME
```

Follow the printed prompt: read the facts and the application code, then write
`docs/architecture/diagrams/<name>.curated.json`. Read only files inside this repo. Start from the existing curated file when
there is one, so the diff stays small. Every edge and external needs evidence you have actually read; never invent
evidence.

## 5. Build

```
"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" build --name NAME
```

- Exit 0: `docs/architecture/diagrams/<name>.drawio` and `<name>.svg` are written, the `drawio_sha256` of the new
  .drawio is stored in the curated file, and the folder `README.md` index is regenerated.
- Exit 1: verify dropped something or left a node without a line. The report is printed. Fix the curated file and
  rebuild. A drop with the reason "looks like a secret" means the curation quoted a credential: remove that text.
- Exit 3: Terraform changed since curation (Terraform flow only). Go back to step 4.
- Exit 2: no facts for a Terraform diagram. Run step 3. A described diagram never needs facts.
- Exit 4: the .drawio was edited by hand and nothing was written. Ask the user which to do: keep it (do nothing, skip
  regeneration), replace it (rerun build with `--replace`), or write a side file to compare (rerun build with
  `--side-file`, which writes `<name>.generated.drawio` and `<name>.generated.svg`, not to be committed). Never choose
  for the user.
- Exit 5: the bundled draw.io could not be downloaded or the render failed, and nothing was written. Show the user
  the message (download blocked, sha256 mismatch or Chrome missing) and stop.

If the user kept a hand-edited .drawio, regenerate its image with
`"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" image docs/architecture/diagrams/<name>.drawio`
(exit 5 means the bundled draw.io or Chrome is unavailable).

## Describe flow (instead of steps 3 to 5)

1. Get the prompt: `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" prompt --name NAME --describe`. It writes the schema to the cache folder and prints the
   describe prompt: schema path, output path `docs/architecture/diagrams/<name>.curated.json`, the evidence rules for
   described diagrams and the path of the interview playbook.
2. Get the playbook path with `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" docs interview`, Read that file and follow it: the opening, one question per
   message, the gap checklist, no visible assumptions.
3. Write each draft straight to the curated path, with `"source": "description"`. Every draft must pass `build`.
4. Build (step 5, no extract and no facts), then open it in the background (`view` blocks until the editor tab is closed): `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" view docs/architecture/diagrams/<name>.drawio`.
5. Alternate questions and redraws as the playbook says, then run the review loop (step 6). Fix [curation] findings
   from the engineer's answers or by asking them; never invent evidence.
6. At the end, list every entry of `assumptions` in chat so the engineer can correct them. Never mark an assumption on
   the diagram itself.

## 6. Review loop (at most 3 rounds)

1. Snapshot: `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" snapshot docs/architecture/diagrams/<name>.drawio -o SNAP_DIR`, with `SNAP_DIR` set to `${CLAUDE_PLUGIN_DATA}/<name>/snap`. It prints the full PNG and four tiles, one path per line. Exit 2 means the bundled draw.io could not be downloaded or Chrome is missing.
2. Look: Read the full PNG, then every tile. Do not skip tiles: small defects show only there.
3. Get the checklist path with `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" docs review`, Read that file, and list findings against it. Each finding names the rule, the tile (for example `r0c1`) and the element (node, caption or line). `docs rules` (same launcher) prints the drawing rules the tool already enforces.
4. Fix every [curation] finding in `docs/architecture/diagrams/<name>.curated.json`. The evidence rules in the `prompt` output still apply: add an edge or change an icon only when the Terraform or code supports it. If a fix needs evidence you cannot find, leave the finding open and report it.
5. Rebuild (step 5) and snapshot again. Review the new images from scratch.

## 7. Show it

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" view docs/architecture/diagrams/<name>.drawio` in the background (it blocks until the editor tab is closed) to open the result in the bundled draw.io editor. Saving in the editor writes the file and its image. Then tell the user: "To reopen later: /cartographer:view NAME in Claude Code, or `cartographer view NAME` from the repo root."

## Stopping

- Stop when a round has zero findings, or after 3 rounds.
- Never say the diagram is ready while a finding remains.
- Do not patch [tool] findings by hand and do not edit the .drawio or the .svg by hand. Report each one to the user as a tool defect, with the rule, the tile it appears in and the element.
- Before finishing, run `"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" check docs/architecture/diagrams`. It is offline and must print nothing and exit 0: every .drawio has an image rendered from exactly that .drawio.
- Never commit or push. Tell the user exactly which files to review and commit:
  `docs/architecture/diagrams/<name>.drawio`, `docs/architecture/diagrams/<name>.svg`,
  `docs/architecture/diagrams/<name>.curated.json` and the regenerated `docs/architecture/diagrams/README.md`.
- For a described diagram the final message also lists every assumption, one line each.
- The final message lists: rounds run, curation fixes made, remaining findings (tool defects and any unfixed curation
  findings), and the files.
