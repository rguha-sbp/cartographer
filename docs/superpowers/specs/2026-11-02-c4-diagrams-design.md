# C4 diagrams: design

Date: 2026-11-02. Status: draft for the owner's approval.

## Intent

The owner's team builds one of its stacks with AI assistance. An internal audit framework (a mix of EU AI Act style
technical documentation, ISO and DNB/EBA style rules, plus internal rules; the exact framework does not change this
design) requires that the stack be described technically so auditors can understand it. The agreed vehicle is a set of
C4 diagrams drawn to the C4 standard. Engineers produce them, tech leads review them, auditors audit on that basis.

What matters to the owner is that a C4 diagram is present and that it follows the C4 notation rules. An auditor should
be able to check it against c4model.com and find nothing missing. The existing cartographer promise carries over and is
what makes the diagrams worth trusting as audit evidence: every box and line traces back to Terraform, application
code, or a named engineer's statement.

C4 is usually delivered as diagrams, either drawn by hand in a tool such as draw.io or Lucid, or generated from a single
model as Structurizr does. Hand drawing lets the levels drift apart. Generating from one model keeps names and
relationships consistent across levels. This design takes the second approach and keeps draw.io as the output.

## Goals

1. **All C4 levels for one software system, drawn from one model.**
   - Core: System Context, Container, Component (one per container that has components), and Code only when the
     engineer agrees to it (see Code level).
   - Supplementary: Deployment (from the Terraform) and Dynamic (main runtime scenarios).
   - System Landscape is out: one model holds exactly one in-scope software system (builder's call, see below).
2. **Strict C4 notation, enforced by the tool, not left to taste** (c4model.com/diagrams/notation and
   /diagrams/checklist):
   - every diagram has a title stating its type and scope ("Container diagram for GIP");
   - every diagram has a key (legend) explaining shapes, colours, border and line styles actually used;
   - every element shows its name, its element type, and a short description; containers and components also show
     their technology (`[Container: Python, AWS Lambda]`);
   - every relationship is a one-way arrow with a label stating intent and, between containers, the technology or
     protocol;
   - boundaries (software system, container, deployment nodes) are drawn and labelled;
   - abstraction levels are never mixed on one diagram (a Context diagram shows no containers, a Component diagram
     stays inside one container).
3. **Facts from the repo first, questions second.** Claude reads the Terraform and the application code in the same
   repo and proposes the whole model. Anything the repo cannot prove (people and roles, external systems not named in
   code, the system's purpose and boundary, the code for a level that is not in the repo) is asked of the engineer. Each
   question says which level it serves, what is needed and why: "For the Component diagram of the `api` container I
   need its main internal parts, because a C4 Component view shows what is inside one container." Answers are recorded
   as `stated` evidence, like describe mode today.
4. **Review knows what it is reviewing.** The visual review step is told the view type of each diagram and checks the
   common drawing rules plus the rules for that view type.
5. **Same drawing quality bar as today.** Every rule in `RULES.md` and `REVIEW.md` applies: no overlapping lines,
   icons or captions, arrows around boxes, A4 fit, the 3-round visual review loop.

## Non-goals

- Other diagram kinds (data flow with trust boundaries, CI/CD pipeline, IAM access view, network topology, BPMN). They
  come later as further views over the same pipeline; this design only has to leave room for them.
- PlantUML or Mermaid output. draw.io is the deliverable. A Structurizr DSL workspace is written beside it, so the
  same model can be explored with drill-down (see "Structurizr workspace" below); it is not a second rendering of the
  views.
- Rendering from a running cloud account. No credentials, as today.

## Anti-goals

Any of these makes the result a failure even if it builds:

- A diagram that an auditor checking c4model.com would flag: missing title, key, element type, technology on a
  container or component, or a relationship without a label.
- Levels that disagree: a container named differently on two views, or a relationship on the Context view with nothing
  behind it on the Container view.
- A box or line that neither the repo nor an engineer's statement supports.
- Overlapping lines, icons or captions; flashy, animated, 3D or decorative shapes. C4 is plain boxes and arrows.
- Visible "assumed", "draft" or "TBD" marks on the diagram (as in describe mode, guesses go to `assumptions`).

## Constraints

As in the earlier designs: no new runtime dependency, the tool never calls an LLM (curation runs in the user's Claude
session through the skill), modules under 300 lines, TDD, plain ASCII in user-facing text, `main` changes only through
a PR. Built in its own worktree on branch `feat/c4-diagrams`, because other agents work in this repo at the same time.

## Decided by the owner

- C4 only for now; other diagram kinds later.
- All levels, because the deliverable is "standard C4".
- Output is draw.io, since the end product is a diagram.
- Claude reads the code (expected in the same repo) and proposes the views, Context included. When something is not
  in the repo, Claude asks, saying which C4 level needs it and why.
- Review is told which kind of diagram it is reviewing.
- Code level: the skill asks the engineer first. If they agree, it draws class names and their associations only
  (no fields or methods) for 1 to 3 components the engineer picks.
- cartographer is a generator, not an artifact manager. Each run reads the repo afresh and writes the diagrams to the
  default place, overwriting older ones. It keeps no memory between runs and marks nothing as stale or hand edited.
- The existing drawing rules are the quality bar.

## Builder's calls (open to correction)

### One model, many views

The core simplification is that Claude curates one C4 model per system, and the tool derives every view from it
deterministically. Claude never draws a view.

- File: `<cache>/<system>-c4/model.json` in the cache folder, validated by a new `c4.schema.json`. It is a working
  file of one run, not committed and not reused: every run curates the model afresh from the repo (owner's
  generator rule). One model holds
  exactly one in-scope software system; every other system in it is `external`. `--name` is `<system>-c4`. A
  Landscape view therefore never arises and is not built.
- Elements, each with `id`, `name`, `description`, `evidence`:
  - `person` (optional `external: true`);
  - `system` (`external: true` for systems outside the scope);
  - `container` (parent a system, `technology` required, `kind`: `app | store | queue | other` for the shape);
  - `component` (parent a container, `technology` required);
  - `code` element (parent a component, Code level only, see below).
- Relationships `{src, dst, label, technology, dashed, evidence}` are stated at the **lowest level known**
  (component or container). Higher views get **implied relationships**: an arrow between two elements shown on a view
  exists when any relationship exists between them or their descendants. Labels of rolled-up arrows come from an
  optional `summary` on the relationship, else the label of the single underlying relationship, else the curation must
  supply a `summary`. Consistency across levels then holds by construction, which is the anti-goal above.
- Deployment: one Deployment view per model, for the Terraform folder given to `extract` (one root, one
  environment). The environment's name comes from the engineer (`stated`) or the folder name. Other environments are
  drawn only when they are separate Terraform roots, each extracted under its own `--name`; tfvars and workspaces are
  not modelled. `deployment_nodes` (nestable: AWS cloud, region, account, VPC, subnet tier, and infrastructure such as
  a Lambda function or ECS service) with `tf` addresses as evidence, and `instances` mapping containers onto them.
- Dynamic: `scenarios`, each an ordered list of existing relationship ids, at most 3 by default (the main request
  path first).
- `assumptions` as in describe mode, never rendered.

### Evidence and verify

Same three evidence arms as today (`fact`, `file/line/contains`, `stated`), checked by the existing shared verify code
(`verify_shared.py`). New checks are a C4-specific verifier module:

- every container and component has a `technology`; every relationship a label; every non-root element a parent of the
  right type;
- a relationship's ends exist and are not the same element or ancestor and descendant;
- every rolled-up arrow on a view resolves to a label (else the build fails and names the relationship);
- which evidence each element needs: anything the repo can prove (containers, stores, queues, components,
  deployment nodes, relationships) needs a `fact` or `file` citation; `stated` is accepted only for persons, external
  systems, the system's purpose, and parts whose code is not in the repo (the engineer was asked, see Goal 3).
- completeness against the Terraform: every compute, store and queue resource in the facts (Lambda, ECS service, EC2
  or ASG, RDS or Aurora, DynamoDB, S3, SQS, SNS, Kinesis, ElastiCache) must back a container or a deployment instance,
  or be listed in `omitted` with a reason. Otherwise the build fails and names the resource. This reuses the "unshown"
  idea of `tf_verify` and turns the "auditor finds nothing missing" anti-goal into a check.

No staleness key, no `inputs_sha256`, no `drawio_sha256`: a run extracts, curates, verifies and writes; that is all.


### Projection, then the existing layout

The code-judo move: each view is a pure function from the model to the shape the layout already consumes (groups,
nodes, externals, edges). Persons and external systems become externals in the side lanes, the system and container
boundaries become groups, and elements become boxes. `tf_layout`, routing, captions, checks and `gen_drawio` stay the
engine. New module `c4_views.py` holds the projections, one small function per view type.

What the engine needs, kept out of the AWS paths by a notation object rather than `if c4` branches:

- **Notation** (`aws` today, `c4` new) supplies node and group styles, the legend entries and the title format.
  `gen_drawio` and the legend code ask the notation instead of reading AWS constants directly.
- **Sized boxes**: C4 boxes hold three text blocks (name bold, `[Type: technology]`, description), so a box's size is
  measured from its text with the existing `tf_geom` text metrics. The layout already places `Box` with `w` and `h`;
  the grid cell grows to the largest box in its block.
- **C4 shapes and colours**: draw.io's built-in C4 library (`mxgraph.c4.person2`, rounded rectangles, cylinder for
  stores, pipe for queues) in the standard C4 palette (person `#08427B`, system `#1168BD`, container `#438DD5`,
  component `#85BBF0`, external `#999999`, boundaries dashed and unfilled). No AWS icons on Context, Container,
  Component or Code views. The Deployment view keeps the AWS frames for deployment nodes and draws container instances
  as C4 container boxes inside them, which C4 allows.
- **Arrows**: one neutral colour, solid for synchronous, dashed for asynchronous, explained in the key. The
  "arrow takes its destination's colour" rule stays for the AWS notation only.
- **Dynamic**: the Container view layout of the involved elements, with each arrow's label prefixed by its step
  number.

### Code level (owner's decision)

Claude asks the engineer whether they want Code-level diagrams, saying C4 treats the level as optional. Only if they
agree: Claude proposes the 1 to 3 most important components and the engineer picks. Each gets a Code view of its main
types as UML class boxes holding the type name and stereotype only (no fields, no methods), with association,
inheritance and implementation arrows, every type and arrow citing `file/line/contains`. Without agreement no Code view
is built and the model has no `code` elements.

### Files

- One `<name>-c4.drawio` in `docs/architecture/diagrams/` with one page (a draw.io tab) per view, in slug order
  (`1-context`, `2-container`, `3-component-<container>`, `4-code-<component>`, `5-deployment`,
  `6-dynamic-<scenario>`). Each page has the id `<name>-<slug>` and the view title as its name.
- One `<name>-c4-<slug>.svg` per view, drawn from that page alone and stamped with the sha256 of the whole .drawio,
  for the README index, diffs and readers without draw.io. A .drawio of several pages has an image per page;
  `check`, `image`, `view` and `snapshot` handle every page, and a one-page L7 diagram keeps its sibling `.svg`.
- Everything is overwritten on every run. There is no hand-edit guard for C4 views. The image of a view the new
  model no longer produces (a container that was removed) is deleted on the same run, as are the per-view
  `<name>-<slug>.drawio` and `.svg` files of earlier builds, so the folder always matches the repo. The folder index
  (`index.py`) has one row per C4 view, linking the .drawio and that view's image.
- The draw.io page name and the diagram title carry the view type and scope.
- The folder `README.md` index groups the C4 views of one system in level order.

### CLI and skill

- `cartographer prompt --name NAME --c4 [--describe]` prints the C4 curation prompt (from the facts when Terraform
  is used, interview-led otherwise) and writes `c4.schema.json` to the cache folder.
- `cartographer build --name NAME` sees a model file and builds every view.
- `skills/cartographer/SKILL.md` gains the choice "AWS architecture diagram or C4 set" at step 0 and points to a
  C4 section of the playbook.
- `INTERVIEW.md` gains a C4 gap checklist per level (Context: users, roles, external systems, purpose; Container:
  deployable units and stores the code does not reveal; Component: internal parts when the code is missing; Deployment:
  environments). Every question names the level, what is needed and why.

### Review

- `REVIEW.md` splits into common rules (today's list, minus AWS-only ones) and per-view sections: L7 (today's AWS
  rules), and C4 Context, Container, Component, Code, Deployment, Dynamic, each from the c4model.com checklist.
- `cartographer snapshot` prints the view type of the diagram (read from the page name) on its first line, and the
  skill tells the reviewer to apply the common rules plus that view's section. A finding names the view, the rule, the
  tile and the element.

- `tf_extract.py` is already over 300 lines: any new fact (for example the compute and store list for the
  completeness check, if facts do not already carry it) goes in a new module.

- The existing AWS (L7) diagram keeps its current cache key and hand-edit guard in this change. Aligning it with the
  generator rule is a separate change, so this one does not collide with work other agents have open on L7.

## Left to the builder

- Exact JSON field names and the schema layout.
- How `Box` sizing grows the grid cells, within the existing A4 fit rule.
- The C4 legend wording, as long as it explains every shape, colour and line style used.
- Order of work, as long as each step ships with tests and keeps the existing L7 output byte-identical
  (the current `test_layout` and `test_drawio_format` fixtures must not change).

## Sources

- C4 notation: https://c4model.com/diagrams/notation
- C4 review checklist: https://c4model.com/diagrams/checklist
- Models as code (Structurizr): https://docs.structurizr.com/as-code

## Structurizr workspace

Added after the first release. C4's main strength is moving between levels, and static draw.io pages cannot be drilled
into. `build --c4` therefore also writes `<name>-c4.dsl`, a Structurizr DSL workspace of the same model
(`c4_structurizr.py`), from which `structurizr export -f static` makes a static site with drill-down, Dynamic view
playback and evidence tooltips.

- Structurizr's implied relationships are turned off. Its default labels a rolled-up arrow with the first relationship's
  text, which would contradict the shared `summary` the draw.io pages show. Each rolled-up edge of a core view is
  written as an explicit relationship instead, with the text and technologies `c4_model.edge_parts` gives the page.
- Views keep the slugs and titles of the draw.io pages. Code views and code elements are left out: Structurizr has no
  level below components.
- Evidence travels as element and relationship properties; deployment nodes keep their Terraform addresses.
- The workspace is computed before anything is written, like the images, so a failed build leaves the folder as it was.
