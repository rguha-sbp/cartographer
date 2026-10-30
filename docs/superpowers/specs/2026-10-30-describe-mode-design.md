# Describe mode, diagram files and drift: design

Date: 2026-10-30. Status: approved in conversation by the repo owner; built from this document.

## Intent

cartographer today turns a Terraform folder into a verified Layer 7 (L7) AWS diagram. The people who use it are AWS
engineers on the owner's team. They also need L7 diagrams for solutions that have no Terraform yet, usually a design
they are proposing to their team or a customer. The diagram ends up in official documents, so it must be correct,
clean and look finished. The drawing basics (real icons, no overlaps, captions on their own line, arrows around icons)
are table stakes: the skill must always get them right, in every mode.

The engineer may arrive with a description, a prompt, a file (an ADR, an OpenSpec `design.md`, notes) or nothing. In
every case Claude must get them to a complete diagram by asking good questions, finding the gaps that would break or
mislead the diagram, and reviewing the rendered result before calling it ready.

## Goals

1. **Two entry paths, chosen at the start.** When the repo has a Terraform folder (`infra/`, `terraform/`, or one the
   engineer names), Claude asks whether to draw from it (the existing Terraform path) or describe a new solution.
   Without Terraform, describe mode starts directly.
2. **An interview in describe mode** modelled on the superpowers brainstorming skill and the "grill me" skill:
   - one question per message, a single sentence, no list of example answers attached;
   - open questions first, in the engineer's own words ("Walk me through what happens when a user does the main thing");
   - then targeted questions, one open design decision at a time, each carrying Claude's recommended answer the
     engineer can accept ("I'd put API Gateway in front of the Lambda; does that match?");
   - if the repo or a supplied file answers it, Claude reads instead of asking;
   - no leading questions; vary the wording of "why" questions instead of repeating "why?";
   - a first rough diagram after one or two open answers, opened in the local draw.io, because a drawing surfaces
     "no, that's wrong" faster than a question. After that, questions alternate with redraws.
3. **Gap detection** before any question is asked, against a checklist adapted from the C4 diagram review checklist
   (c4model.com/diagrams/checklist) for L7:
   - every element: a name, an AWS service (which sets the icon) or a named external system, and what it does;
   - every arrow: a direction, a label stating its intent, sync or async (solid or dashed), and the protocol where it
     matters;
   - entry points: who or what calls into the system, and through what;
   - where data lives;
   - what sits outside AWS, and the account and VPC boundaries;
   - how identity and auth flow.
   Gaps are ranked by how badly they would mislead the diagram (changes to boxes or arrows first). At most about
   8 targeted questions; everything still open after that is settled by Claude's best guess.
4. **No visible assumptions.** The diagram never marks anything as assumed, draft, or unverified: no styling, no
   block, no footer. Where the engineer did not say, Claude uses its best guess and draws it normally. The guesses are
   recorded in the curated file (`assumptions`, not rendered) and listed in chat at the end so the engineer can
   correct them before the diagram goes into official documents.
5. **The .drawio is the source, the image is generated from it.**
   - Committed per diagram: `<name>.drawio` (source), `<name>.svg` (image rendered from that exact .drawio) and
     `<name>.curated.json` (the curation).
   - The image is never edited or copied over by hand. `cartographer image <name>.drawio` regenerates it anywhere a
     local draw.io runs. The image carries a fingerprint (sha256) of the .drawio bytes it was rendered from.
   - `cartographer check <dir>` fails when any .drawio has no image, or its image fingerprint does not match the
     current .drawio. It is published as a pre-commit hook so consuming repos can block a commit where someone edited
     the .drawio without regenerating the image.
6. **Folder and naming standard.** All outputs live in `docs/architecture/diagrams/` at the repo root:
   - file names are lowercase kebab-case `<system>-<view>`, for example `gip-l7.drawio`, `gip-l7.svg`,
     `gip-l7.curated.json`; later views use `l3`, `c4-context`, `c4-container`;
   - the diagram title follows C4 wording: "Layer 7 diagram for <System>";
   - every diagram has a legend;
   - a generated `README.md` in the folder lists one line per diagram: view, what it shows, source file, image file.
7. **Hand edits: the user decides, never the tool.** Every generated .drawio's fingerprint is recorded in its curated
   file (`drawio_sha256`). When the skill runs again and the .drawio no longer matches, someone edited it by hand.
   Claude stops and asks the user, offering: keep the hand-edited diagram and skip regeneration; regenerate and
   replace it; or regenerate to a side file (`<name>.generated.drawio`, not committed) to compare. Whatever .drawio
   ends up in the folder, its image is regenerated and checked before the skill finishes.
8. **A README that gets someone working**, written for an AWS engineer who has never seen the tool: what it does, what
   they need (Claude Code, `uv`, SSH access to the GitHub repo, Chrome, the local draw.io and how to start it), plugin
   install, a first run in each mode, where the files land and which to commit, how to edit a diagram at localhost and
   regenerate the image, the pre-commit hook, and troubleshooting for the common exits.

## Non-goals

- Layer 3 and C4 views (later; the naming standard leaves room for them).
- Mixing Terraform and a described change in one diagram (a later "change overlay").
- CI in consuming repos.
- Lucid compatibility.

## Anti-goals (failure even if it technically works)

- Any "assumed", "draft" or "unverified" marking in a diagram meant for official documents.
- An image that does not match its .drawio.
- The tool silently overwriting a hand-edited diagram.
- Broken drawing basics in describe mode because it skips the review loop.
- Sending the diagram to a public draw.io host.

## Constraints

- No new runtime dependency; `uv.lock` changes only if unavoidable, and the 7-day age gate holds.
- The tool never calls an LLM; all curation and interviewing happens in the user's Claude session via the skill.
- The local draw.io at `http://localhost:8080` is the only renderer (snapshot, image). Never a public host.
- Python 3.13, ruff at 120, each module under 300 lines, TDD.
- User-facing text (SKILL.md, README, CLI output, diagram text) has no em dashes, en dashes or smart quotes.
- `main` is protected: changes land through a PR with CI green.

## Decided how (by the owner in conversation)

- Interview style as in goal 2; no visible assumptions (goal 4); .drawio is the source and the image is regenerated
  from it with drift caught (goal 5); output folder `docs/architecture/diagrams/` with generally accepted naming
  (goal 6); hand-edit drift always goes to the user as a question (goal 7); a getting-started README (goal 8).

## Builder's calls (made by Claude, open to the owner's correction)

- **Describe mode reuses the existing pipeline.** The curated file gains `source: "terraform" | "description"`. For
  `description`, nodes carry no Terraform addresses and edges and externals carry `stated` evidence (a short
  paraphrase of what the engineer said, or `{"file", "line", "contains"}` when it came from a supplied document).
  `build` skips the facts and staleness check for described diagrams, and verify still enforces structure: unique
  ids, edge endpoints exist, icons in the draw.io vocabulary, no isolated node, the secret guard. Layout, routing,
  rendering and the visual review loop are unchanged.
- **Best guesses** are kept in the curated file as `assumptions: [{"about": <node or edge id>, "guess": <text>}]` and
  never rendered.
- **`--stack` becomes `--name`** with the `<system>-<view>` convention; the cache folder uses the same name.
- **Image format is SVG** rendered via headless Chrome against the local draw.io (the existing svg_export, without the
  embedded `content` attribute); the fingerprint is a `data-cartographer-source-sha256` attribute on the root `<svg>`.
- **The folder README index** is regenerated by `build` and `image` from the curated files present.
- **The interview playbook and gap checklist** ship inside the package as `INTERVIEW.md`, reachable with
  `cartographer docs interview`, so the skill reads the installed version.
- Editing at localhost: open the .drawio from disk in the local draw.io in Chrome and save it back in place; if that
  build cannot save in place, export the .drawio and overwrite the file. The README documents whichever works.

## Settled after the builder check (Claude's calls)

1. **The CLI enforces the hand-edit guard, not only the skill.** `build` exits 4 ("the .drawio was edited by hand")
   without writing anything when the existing .drawio's sha256 differs from the curated `drawio_sha256`, or when a
   .drawio exists and the curated file has no `drawio_sha256`. `--replace` overwrites it; `--side-file` writes
   `<name>.generated.drawio` and its image next to it instead. The skill maps the user's three choices onto: do
   nothing, `--replace`, `--side-file`. `build` writes the new `drawio_sha256` into the curated file after a write.
2. **Clean break, no migration.** v0.1.0 has no consumers. `--stack` becomes `--name`, outputs move to
   `docs/architecture/diagrams/`, `.drawio.svg` becomes `.svg`, and `view` accepts a `.drawio` only. The version
   becomes 0.2.0 in pyproject, plugin.json and the SKILL.md pin; tag `v0.2.0` after the PR merges.
3. **Local draw.io down means `build` fails before writing anything** (exit 5, "start the local draw.io
   (localhost:8080) first"), so a .drawio is never written without its image. `image` fails the same way.
4. **`check` is offline and fast**: no Chrome, no draw.io, stdlib only. For every `*.drawio` under the given folder
   (side files `*.generated.drawio` ignored) it requires a sibling `.svg` that parses as XML and whose
   `data-cartographer-source-sha256` equals the .drawio's sha256. It does not look at curated files: a hand edit
   followed by a regenerated image is a legitimate state, and a hand-drawn .drawio with no curated file is allowed.
   `.pre-commit-hooks.yaml` declares hook `cartographer-check`, `language: python`, `entry: cartographer check
   docs/architecture/diagrams`, `files: ^docs/architecture/diagrams/`, `pass_filenames: false`.
5. **Schema**: `source` (`terraform` | `description`) is required. A third evidence arm `{"stated": <text>}`
   (maxLength 200) joins `fact` and `file`; verify accepts `stated` only when `source` is `description` and rejects
   `fact` there. `tf` allows an empty array in the schema; verify requires at least one address for `terraform`
   and requires it empty for `description`. `flow` stays required and Claude picks it in both modes; the 28 character
   label cap stays; the legend is unchanged (it already explains colour, solid and dashed).
   New fields: `system` (display name, e.g. "GIP"), `view` (`l7`), `assumptions` (described above),
   `drawio_sha256` (written by build). `title` is removed from the schema: build derives
   "Layer 7 diagram for <system>".
6. **Describe-mode CLI**: `cartographer prompt --name N --describe` writes the schema to the cache folder and prints
   the describe prompt (schema path, output path `docs/architecture/diagrams/<name>.curated.json`, evidence rules,
   and the path of `INTERVIEW.md`); it needs no facts. Drafts are written straight to that output path and built
   with the normal `build`, which is equally strict for drafts: Claude keeps every draft structurally valid.
7. **Title** is derived by build from `system` and `view` and is not free text.

## Left to the builder

Module boundaries, exact CLI flag names beyond those above, test layout, and the README's structure.
