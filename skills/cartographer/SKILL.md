---
name: cartographer
description: Build a verified AWS architecture diagram (draw.io and .drawio.svg) from the Terraform in this repo, curate it in this session, then review the rendered result visually and fix curation findings until it is clean. Use when asked to generate, refresh or check an architecture diagram.
---

# Cartographer diagram loop

A diagram is not ready because the build passed. It is ready when you have looked at it. You do the curation yourself
in this session: the cartographer tool only reads Terraform, verifies your curation against the Terraform and the code,
and draws. It never calls a model.

Every command below runs from the repo root. Shell state does not carry between Bash calls, so each command is spelled
out in full. `CARTOGRAPHER_FROM` lets a developer point at a local checkout; leave it unset otherwise.

## 1. Stack and folders

Ask the user, or derive from the repo, the stack name (a short word such as `shop`) and the Terraform folder
(default `infra`). The outputs go to `docs/architecture/<stack>.*`.

## 2. Prerequisites

- `uv` is installed (`uvx --version`).
- The local draw.io runs on `http://localhost:8080` (`curl -sI http://localhost:8080`). If not, tell the user and stop.
  Never use a public draw.io host: the diagram must not leave the machine.
- Chrome or Chromium is installed.

## 3. Extract

```
uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0}" cartographer extract INFRA_DIR --stack STACK
```

It prints the facts path (in the cache folder, nothing is written into the repo) and the `inputs key`.

## 4. Curate (only when needed)

If `docs/architecture/<stack>.curated.json` exists and its `inputs_sha256` equals the inputs key, skip this step.
Otherwise:

```
uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0}" cartographer prompt --stack STACK
```

Follow the printed prompt: read the facts and the application code, then write
`docs/architecture/<stack>.curated.json`. Read only files inside this repo. Start from the existing curated file when
there is one, so the diff stays small. Every edge and external needs evidence you have actually read; never invent
evidence.

## 5. Build

```
uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0}" cartographer build --stack STACK
```

- Exit 0: `docs/architecture/<stack>.drawio` and `<stack>.drawio.svg` are written. If it prints "svg skipped", the local
  draw.io was down: say so and rerun after it is up.
- Exit 1: verify dropped something or left a node without a line. The report is printed. Fix the curated file and
  rebuild. A drop with the reason "looks like a secret" means the curation quoted a credential: remove that text.
- Exit 3: Terraform changed since curation. Go back to step 4.

## 6. Review loop (at most 3 rounds)

1. Snapshot: `uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0}" cartographer snapshot docs/architecture/<stack>.drawio -o SNAP_DIR`, with `SNAP_DIR` under `${XDG_CACHE_HOME:-$HOME/.cache}/cartographer/<stack>/snap`. It prints the full PNG and four tiles, one path per line. Exit 2 means the local draw.io is down.
2. Look: Read the full PNG, then every tile. Do not skip tiles: small defects show only there.
3. Get the checklist path with `uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0}" cartographer docs review`, Read that file, and list findings against it. Each finding names the rule, the tile (for example `r0c1`) and the element (node, caption or line). `cartographer docs rules` prints the drawing rules the tool already enforces.
4. Fix every [curation] finding in `docs/architecture/<stack>.curated.json`. The evidence rules in the `prompt` output still apply: add an edge or change an icon only when the Terraform or code supports it. If a fix needs evidence you cannot find, leave the finding open and report it.
5. Rebuild (step 5) and snapshot again. Review the new images from scratch.

## 7. Show it

Run `uvx --from "${CARTOGRAPHER_FROM:-git+ssh://git@github.com/rguha-sbp/cartographer@v0.1.0}" cartographer view docs/architecture/<stack>.drawio.svg` to open the result in the local draw.io.

## Stopping

- Stop when a round has zero findings, or after 3 rounds.
- Never say the diagram is ready while a finding remains.
- Do not patch [tool] findings by hand and do not edit the .drawio or .drawio.svg. Report each one to the user as a tool defect, with the rule, the tile it appears in and the element.
- Never commit or push. Tell the user exactly which three files to review and commit:
  `docs/architecture/<stack>.drawio`, `docs/architecture/<stack>.drawio.svg` and `docs/architecture/<stack>.curated.json`.
- The final message lists: rounds run, curation fixes made, remaining findings (tool defects and any unfixed curation
  findings), and the three files.
