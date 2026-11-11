# cartographer: Terraform folder (AWS, Azure or both) -> Lucid-compatible draw.io

The Python package is in `src/cartographer/`. The stage files below are in that folder. The subcommands of `cartographer` are:

```
cartographer extract INFRA_DIR --name NAME       facts to $XDG_CACHE_HOME/cartographer/NAME/facts.json
cartographer prompt --name NAME [--describe]     schema to the cache folder, curation or describe prompt on stdout
cartographer prompt --name NAME --c4 [--describe]  C4 curation prompt (model.json), schema c4.schema.json
cartographer build --name NAME                   verify, then docs/architecture/diagrams/NAME.drawio and .svg
cartographer build --name NAME --c4              verify model.json, then NAME-c4.drawio, a page and .svg per view
cartographer image FILE.drawio                   regenerate the .svg next to a .drawio, one per page
cartographer check FOLDER                        fail when a .drawio has no image or a stale one (offline)
cartographer snapshot FILE -o DIR                per page: `view: <name>`, then PNG and tiles from the local draw.io
cartographer view FILE                           open in the local draw.io
cartographer icons --cloud C --search WORDS        icon names of a namespace (aws, azure, generic, brand), at most 20
cartographer docs interview|review|rules         path of a packaged document
```

The user's own Claude session runs the curation (stage 2), and the plugin skill drives it. The tool never calls a model.
The committed files are `<name>.curated.json`, `<name>.drawio`, `<name>.svg` and the `README.md` index of the folder. Facts and verify output stay
in the cache folder. `build` also applies the overrides in `<out>/icons.json` and writes `review.json` to the cache folder. `snapshot` writes
`tiles.json` beside the PNGs.
`build` writes the svg in this way: it renders the diagram in the local draw.io with headless Chrome (`svg_export.py`), inlines local images as data URIs and embeds the mxfile in the `content` attribute.
The output is XML (draw.io), never an image. The coordinates come from a deterministic column grid (pure Python).

## Pipeline

| Stage | File | AI? | Input -> output |
|---|---|---|---|
| 1 extract | `tf_extract.py` | no | infra dir -> facts.json |
| 2 curate | `curate_prompt.md`, which Claude follows in the user's session (`cartographer prompt`) | yes | facts.json + repo code -> curated.json |
| 3 verify | `tf_verify.py` | no | facts + curated + repo -> verified curated + report |
| 4 layout | `tf_layout.py` | no | verified curated -> `Diagram` (absolute coords) |
| 5 render | `gen_drawio.py render(diagram, page_id=, page_name=, notation=LAYER7)` | no | Diagram -> .drawio XML |

Reproducibility: the tool caches curated.json under `inputs_sha256`. This key is a hash of three inputs: the bytes of facts.json, the prompt template and the schema text that the curation must satisfy.
The prompt template is `curate_prompt.md` with its placeholders unsubstituted, so no path enters the key. The schema is the static `curated.schema.json`, and it lists no icons. There is no model in the key.

`build` refuses (exit 3) when `inputs_sha256` in the curated file differs from the current key. So the tool does the curation again only when one of those inputs changes.
Stages 1, 3, 4, 5 are deterministic (sorted iteration everywhere, fixed grid constants). Therefore the same curated.json always gives a byte-identical .drawio.

## Shared types (`diagram_model.py`)

`diagram_model.py` holds the dataclasses `Group`, `Icon`, `Box`, `Edge`, `Title`, `Legend`, `LegendEntry`, `Diagram`, and the colour and port constants.
`tests/test_drawio_format.py` renders a small synthetic diagram and checks the file format. The checks are: no `version` attribute, id first and `as` last, 2-space indent, `&#39;`, ports and points on
every edge, unique vertex ids.

`gen_drawio.render(diagram)` takes the draw.io page `id` and `name` as required keyword arguments. `build.py`
passes `<name>-architecture` and the curated title. `tf_layout.__main__` derives the name from the input file name.

`gen_drawio` draws icons, lines, title and legend. The `notation.Notation` that it receives draws every box and group (value HTML and style).
`notation.LAYER7` is the Layer 7 look: grey boxes, frames by `Group.kind` in the styles of their `Group.cloud`,
and plain groups in their purpose colour. A `Box` carries the `shape` of its node (its `icon`) and no colours.
Nothing in the generic modules is specific to one stack.

## Clouds and icons

A member of a `Cloud` object (`clouds/base.py`) holds every cloud difference. The core never tests a cloud name.
`clouds/__init__.py` registers `AWS` and `AZURE`. Each cloud is in `clouds/<cloud>/`:

| File | Holds |
|---|---|
| `icons.json` | draw.io icon name -> fill colour and title. `vendor.py` vendors it from the sidebar of the pinned, sha256-checked draw.io web app (`drawio_pin.json`). Refresh it after a bump with `uv run python -m cartographer.clouds.<cloud>.vendor` |
| `catalog.json` | reviewed Terraform type -> icon row: `icon`, `fold` (merged into its owner), `drop` (never in the facts), `global` |
| `provider_types.json` | the resource types of the provider, so the tool marks a type that is newer than the list and does not fail |
| `rules.py` | attribute rules that choose one of the icons of a type (for example `load_balancer_type`, `kind`) |
| `modules.json` | remote module source prefix -> icon |
| `network.py`, `permissions.py` | networks and placements; permission edges (IAM, Azure role assignments) |

The catalog is the single place where the icon, fold or drop of a type lives. If an attribute is not a literal (a `var.x` with no
default, a `local`, a reference), the tool never guesses. It uses the base icon and marks the resource as `marked` with a reason.

`icons.py` is the one lookup of icon names. A name is qualified: `aws:lambda`, `azure:key_vault`, `generic:users`
(General Resources shapes, `generic_icons.json`), `brand:github` (`brand_icons.json`, complete draw.io styles).
The notation draws any other name as a box of icon size.
`cartographer icons --cloud X --search Y` searches one namespace by name and title and returns at most 20 matches.
No full icon list is in the schema, the prompts or the skill.

`overrides.py` reads `<out>/icons.json` (`{"overrides": [{"cloud", "type", "icon", "reason", "address"?}]}`) and applies
it to the verified diagram at build time. An address beats a type. The tool refuses a malformed file, an unknown icon or an address that
is not a resource of that type, with one report line. It skips an override for a type that is not in this diagram, with
one report line. In both cases the rest of the build continues.

`review_sheet.py` writes `review.json`. It holds the `view`, its `view_name`, the `clouds`, and for each icon: label, qualified icon and
title, `tf` addresses, `decided_by`, `marked`, `override`, `frame`, `tiles`. `snapshot` writes `tiles.json` (the icon ids
per tile) and fills the `tiles` of each sheet entry. The reviewer reads the sheet for a Layer 7 diagram (`REVIEW.md`).

## facts.json (stage 1)

```json
{
  "infra_dir": "infra",
  "resources": [
    {"address": "aws_lambda_function.orders_api", "type": "aws_lambda_function", "module": "", "cloud": "aws",
     "icon": "aws:lambda", "marked": false, "decided_by": "catalog aws_lambda_function",
     "multi": false, "file": "infra/orders_api.tf", "line": 12}
  ],
  "networks": [{"id": "n1", "cloud": "aws", "name": "main", "cidrs": ["10.0.0.0/16"], "remote": false,
                "address": "aws_vpc.main"}],
  "placements": [{"id": "p1", "resource": "aws_lambda_function.orders_api", "network": "n1", "tier": "private",
                  "cloud": "aws"}],
  "edges": [
    {"id": "f12", "src": "aws_lambda_function.orders_api", "dst": "aws_dynamodb_table.orders",
     "kind": "iam", "detail": "dynamodb:Query,dynamodb:GetItem", "file": "infra/orders_api.tf", "line": 40}
  ],
  "services": [{"service": "bedrock", "actions": ["bedrock:InvokeModel"], "principals": ["module.agent.aws_iam_role.exec"]}]
}
```

- Each resource has `cloud` (from the provider of its type) and `icon` (qualified) or `fold: "owner"`. `random_*`, `tls_*`, `time_*`, `null_*` and other non-cloud
  providers never reach the facts. A resource also has `marked` (with `reason`) when the
  catalog could not decide, `decided_by`, and `global: true` for a service outside any region. Folded resources stay in
  the facts so evidence can cite them. The curator merges them into their owner.
- The tool parses every `*.tf` in the infra dir and, recursively, every LOCAL module (`source` starting `./` or `../`).
  Addresses inside a module instance get the prefix `module.<name>.`, and nested modules chain the prefix. The tool records remote
  modules (registry, git, TFC private) as a single resource of type `module` and does not enter them. They carry
  `source` (any `?ref=` query and credentials stripped) and `version` when given. `module.<remote>.<output>` references
  from other resources become `uses` edges to that module resource.
- Module families: two or more calls in one parent module with the same local `source` collapse into one instance.
  Its address is `module.<basename of the source dir>.` (`<basename>-family` if a different call already has that name).
  Every resource in it has `multi: true` and `instances`, the sorted call names. `var.x` resolves to the union of the
  arguments of the calls. The tool rewrites edges to family addresses, removes duplicates (it keeps the lowest file and line) and drops self-edges.
  A source that one call uses keeps `module.<name>.` addressing. This applies at every nesting level.
- `multi`: true when the block has `count` or `for_each`, or sits in a module call that has them.
- `file`/`line`: the repo-relative path and the start line of the block (python-hcl2 `with_meta=True`).
- References: the tool scans every attribute value (strings after hcl2 parsing, recursively through lists/dicts) for
  `<type>.<name>`, where the type matches a resource type in the parsed set. It also scans for `module.<name>.<output>`
  and, inside modules, `var.<name>`. It resolves `var.x` inside a module instance to the references in the
  argument `x` of the module call. It resolves `module.m.out` to the references in the value of `output "out"` of module m.
  It resolves `data.` sources to nothing. It drops self references.
- Edge `kind` comes from a single table keyed on (source resource type, top-level attribute), with a `ref`
  fallback:
  - `iam`: from `aws_iam_role_policy` / `aws_iam_policy` documents. The tool parses `jsonencode` / heredoc JSON.
    Every Statement with Effect Allow yields edges from each PRINCIPAL to each resource
    referenced in `Resource`, with `detail` = sorted actions. The PRINCIPALs are the compute resources that use the role:
    any resource whose `role`/`execution_role_arn`/`role_arn` references that `aws_iam_role`. `Resource = "*"` or a constructed ARN that
    references no resource adds the actions to `services` (service = action prefix, e.g. `bedrock`).
    The policy can also be `templatefile("${path.module}/x.json.tpl", {k = ref})`, `file(...)`, `local.x`, `var.x`
    or a policy-document data source. The tool resolves `var.x` through the module call; a var that no call passes means no policy. In a
    template, `${k}` for a vars-map key maps to the references of that key. Other `${...}` and `%{...}` directives become
    placeholders or vanish. If a policy is still not JSON (for example statements passed in at runtime), the tool counts it
    as unparsed and it yields no edges.
  - `trigger`: `aws_cloudwatch_event_target` (rule -> target arn), `aws_lambda_event_source_mapping`
    (event source -> function), `aws_s3_bucket_notification`, `aws_scheduler_schedule` target,
    `aws_lambda_permission` (principal source_arn -> function).
  - `route`: `aws_cloudfront_distribution` origins (distribution -> origin resource), `aws_lambda_function_url`.
  - `network`: `vpc_config` / `network_configuration` / `subnet_ids` / `security_group_ids` references.
  - `uses`: everything else (e.g. `kms_key_arn`, `role`). The curator decides if these matter. The tool drops a `uses` edge when
    either end is a support type that the curator folds into its owner (IAM roles/policies/attachments, log groups, KMS
    aliases, Lambda aliases/layer versions/invoke configs, S3 bucket policy/versioning/encryption/lifecycle/public
    access block/ownership/logging). Such an edge only restates the wiring of the owner, and it was most of the size
    (on a large real stack the edge count fell by about half). An LLM reads the facts in full, so the facts must stay well under about 400 KB.
- The output is sorted (resources by address, edges by (src, dst, kind)). The tool assigns edge ids after the sort.

## curated.json (stage 2, AI)

```json
{
  "inputs_sha256": "...",
  "format": 2,
  "system": "Shop",
  "view": "l7",
  "groups": [{"id": "g_api", "label": "Shop APIs", "kind": null, "parent": "acct", "column": 1},
             {"id": "acct", "label": "Account", "kind": "account", "cloud": "aws", "parent": "region", "column": 0}],
  "nodes": [{"id": "api_orders", "label": "Orders API\norder handling", "group": "g_api",
             "tf": ["aws_lambda_function.orders_api"], "multi": false}],
  "externals": [{"id": "stripe", "label": "Stripe\n(payments)", "icon": "generic:internet",
                 "evidence": [{"file": "infra/orders_api.tf", "line": 30, "contains": "stripe"}]}],
  "edges": [{"src": "api_orders", "dst": "ddb_orders", "label": "reads orders", "flow": "web",
             "dashed": false,
             "evidence": [{"fact": "f12"}, {"file": "src/shop/orders.py", "line": 88, "contains": ".query("}]}]
}
```

- `format` is 2. A file without it is legacy (`vpc` groups, node and external `service`, bare icons), and `curated_format.py` converts it on
  load. A described solution still builds from it. A Terraform one was keyed to the older
  prompt, schema and facts, so build refuses it as stale and it needs a new curation.
- `kind` in groups: `cloud | region | account | network | subnet | null`. Frame kinds carry `cloud`. A null kind is a role group:
  a solid outline and a faint tint in its colour. There is one top-level `cloud` frame per cloud present, side by side. The tool never draws resource groups.
- `column` in groups: integer 0 to 3, required. It places the role groups that are directly in the account from left to right.
  The tool ignores it for frames and for groups nested in another group, which follow their parent.
- Node `icon`: a qualified name. Set it only when no resource of the node resolves to one (a non-cloud provider) or for a
  described node with no fitting `tf_type`. Otherwise the icon comes from the facts. A described node or a managed-service
  external names `tf_type` (and `attributes`), and the catalog resolves its icon (`clouds.resolve_declared`).
- Externals: `icon` is a qualified `brand:` or `generic:` name, an `aws:` or `azure:` name (drawn in the managed
  services block of that cloud), or `none` (plain box). Externals have no `group`. They sit in the side lanes. The schema is static
  (`curated.schema.json`) and lists no icon names. The prompt guidance is:
  - people: `generic:users`/`generic:user`
  - browsers and apps: `generic:client`
  - SaaS and remote APIs: `generic:internet` or `generic:generic_application`
  - on-prem: `generic:corporate_data_center`
- `label` on edges: a specific verb plus the protocol where known ("invokes, HTTPS"), schema `maxLength` 28. The prompt asks for at most about 45 edges: primary request
  and data paths only. It asks to mention the per-node plumbing (logs, shared KMS key, config reads) once in a group label.
- Groups with no nodes (directly or in a child group) are legal, but the layout drops them. Verify warns about them.
- `flow`: `web | trigger | runtime | credential | data`. The tool maps it to the legend colours
  (blue, green, purple, red, grey).
- Every node must cite at least one existing TF address (`tf`) unless it is in `externals`. Every edge must cite
  at least one evidence item. An evidence item is a fact id, or a `file`/`line`/`contains` code citation (1-based line).
  `contains` is a literal substring that must appear within +-3 lines of `line`.
- Curation rules for the prompt:
  - Use 40 to 90 nodes.
  - Collapse support resources (policies, attachments, log groups, versions, encryption configs, public access blocks, aliases) into their owner.
  - Use one node per module instance family when `multi`.
  - Data-flow arrows come from the application code that runs in each compute node (Lambda handler `filename`/`source_dir`, agent runtime code). Each arrow must cite the call site.

## tf_verify.py (stage 3)

- The tool drops nodes whose `tf` addresses do not all exist in facts. It drops edges that touch dropped nodes.
- An edge survives if at least one evidence item checks out. An evidence item checks out in one of two cases:
  - It is a fact id that exists AND whose src/dst are among the tf addresses of the src/dst nodes of the edge (either direction).
  - It is a code citation whose `contains` is found within +-3 lines of `line` in `<repo-root>/<file>`.
- The report (text, sorted) lists:
  - dropped nodes
  - dropped edges with reason
  - `unshown` facts of kind iam/trigger/route between two shown nodes that no curated edge covers (recall hints)
  - IAM-only vs code-only mismatches for code-cited edges
- The exit code is always 0, and the report is the artefact. `--strict` exits 1 when the tool dropped anything or a node has no edge.

## tf_layout.py (stage 4)

This stage is pure Python, with no external process. It has five modules:

- `tf_layout.py` (orchestration, edges, legend)
- `tf_blocks.py` (frames and block grids)
- `tf_lanes.py` (externals)
- `tf_order.py` (barycentric ordering)
- `tf_place.py` (crossing-aware placement)

Every number is a module constant
(icon pitch 150x150, group padding 30 sides and 50 top, frame padding 20 sides and 40 top, gap 40).
Blocks side by side or stacked in a frame are BLOCK_GAP apart. The gap is a channel of CHANNEL_TRACKS (6) lines at LINE_GAP. Each line keeps at least GROUP_CLEAR from both blocks.
So routes between distant blocks run through the gaps and not round the whole drawing.

- Frames are groups of kind cloud, region or account. Every other group (kind null, network or subnet) is a block. Several frame trees (one per cloud, or two regions of one cloud) sit side by side.
  The layout drops a block with no nodes and no non-empty child block (`tf_blocks.empty_blocks`; verify reports it as a warning).
- Block size: the child blocks are stacked vertically at the top. Then the nodes of the block itself go in a grid of `min(n, GRID_COLS)`
  columns in curated order. The width is the maximum of the grid, the children and a label estimate (7 px per char + 40).
- Innermost frame: its direct child blocks go into columns by `column`, stacked in list order, with the tops aligned. Each
  column is as wide as its widest block. Outer frames wrap the single child with frame padding. If there are no frames, the
  column grid sits at the top level. Nodes placed directly in a frame form an extra grid row under the columns.
- A4 proportions: `GRID_COLS` is chosen from {2, 3, 4}. The tool lays out all three. The one whose bounding box (frames,
  lanes and legend, not the title) has a width/height ratio closest to sqrt(2) (compared on a log scale) wins. Ties go
  to the smaller value.
- Placement (`tf_place.py`): 4 deterministic barycentric passes give a start (`tf_order.py`: nodes inside a block by the mean x of
  their neighbours, sibling blocks inside a column and externals by the mean y of theirs). The tool keeps the best of
  them by the objective. The objective is the number of proper crossings between the edges drawn as straight
  lines between node centres, plus their total length at a given number of pixels per crossing. Then a greedy local search
  tries these moves:
  - every swap of two nodes in one block
  - every swap of two blocks in one column slot
  - every swap of two externals in one lane
  - every move of an external to the other lane
  - every slot (column and position) for a block whose `column` is open

  The search keeps each change that lowers the objective, until a sweep finds none (at most 30 sweeps). Every candidate is a
  full placement, so the objective sees the real grid. Each cloud's managed-services block (`tf_externals`) has an open column, so it
  lands by its callers.
- Straight lines only approximate the routes. So for the chosen `GRID_COLS`, the tool makes the placement once for each length
  weight in `tf_layout.SPREADS` (none, and 1000, 500 and 250 px per crossing). It routes and fits each one. The one with the fewest
  crossings plus checker violations wins, then the one with the fewest bends.
- Externals sit outside the frames in two lanes. If an external has a `lane` (set by placement), the `lane` decides. Without one, the externals
  that are only ever an edge `src` go left, and all others (including edgeless ones) go right. An external with an `icon` takes a 150x150 icon cell (shape plus label below).
  One without an `icon` takes a 200x100 box cell. A lane taller than the frames wraps into two sub-columns, filled row-major.
- Nodes without an icon become boxes, centred in an icon cell.
- The output is a `Diagram`: frames, then groups parent-before-child, then leaves. Edges are sorted by (src, dst, label). A
  generated legend that lists only the flows used goes under everything. The title comes from curated.json.
- Routing (`tf_route.py`, after the tool chooses the arrangement):
  - `tf_ports.py` picks a side for each edge end. It picks sideways when the
    other end is 90 px or more away horizontally and the gap fits the caption. Otherwise it picks top/bottom. The bottom of an icon holds its
    caption, so the icon uses a flank. `tf_ports.py` spreads the edges on one side evenly, ordered by the position of the other end.
  - A first routing with these ports shows where each route comes from and which way it turns off its stub. Then every end takes the side that faces
    where its route comes from. The tool reorders the ports on every side so that no two routes cross beside the node
    (`tf_ports.untangle`). It routes the diagram again and keeps the one with fewer defects.
  - The tool never chooses a side whose stubs would
    run into a group title. So lines that converge on a node under a title do not wrap round it.
  - The stub out of a port is closed to every other edge. The line across its end is also closed, LINE_GAP either side. So
    no route boxes a stub in or jogs beside it.
  - The router is
    an orthogonal A* over a sparse grid (obstacle borders, ports, evenly spaced tracks in each gap). These are walls:
    - every leaf plus the caption under an icon (`tf_geom.py`)
    - every group title band (`title_rect`: every line of the title at its rendered left spacing)
    - every group that holds neither end of the edge (a group is an ancestor when its box contains an endpoint)
  - A segment parallel to a group or frame border, within LINE_GAP of it, is closed too. The router relaxes that strip last,
    when an edge has no other route. The grid itself is in `tf_grid.py`.
  - Cost: length, a bend penalty, a heavy flat+per-px penalty for sharing a segment with an earlier edge, and a crossing penalty (300) that is worth a short detour round the line.
    The router also charges the crossing penalty on every grid segment through the
    zone of a caption that it placed earlier.
  - Edges go shortest first, ties by id. Each `Edge` gets `out`, `into`, `points` and `exact=True`. The renderer then
    draws the polyline as given (no `edgeStyle`). So draw.io cannot re-route it, and the captions stay where the tool measured them.
    Hand-made models leave `exact` off, and their points stay connector hints.
- Captions (`tf_labels.py`): each caption (about 7 px per character at 12 px, 20 px tall) goes on its own route. If possible, it goes on a horizontal
  segment that is long enough for it, nearest the source. The first spot that is clear of nodes, group titles, other
  captions, other edges and group borders wins. If there is none, the spot that overlaps the fewest nodes, titles, captions and lines wins. If two spots tie, the one with the fewest things in its clearance wins. After the tool routes every edge, it places again each caption that a later route now crowds.
- The tool stores a caption as `Edge.at` (relative position along the polyline) plus `Edge.shift`
  (draw.io `offset` point, emitted only when non-zero). `--edge-labels off` blanks the captions, and routing still runs.
- `tf_check.measure` takes the draw.io text, not the model. `tf_read.read` parses it back (absolute boxes through
  parents, ports from exit/entry, points, caption at relative x plus offset), and the counters run on that. So they can
  never disagree with the file. They count:
  - bends
  - crossings
  - caption overlaps
  - captions on nodes
  - captions on lines (other edges, group borders, group titles)
  - edges through nodes
  - edges through foreign groups
  - edges through group titles
  - segments that run within LINE_GAP beside a group border (line on frame)
  - edge pairs that share a collinear segment

  The command line of `tf_layout` prints the result.
- Legend: colours plus the words "Solid line: primary request path" and "Dashed line: secondary, control or async".
  All text is at least 12 px. Arrowheads are open.

## C4 diagrams

This is a second notation next to the Layer 7 one. The curation writes `model.json` (schema `c4.schema.json`) in the cache folder.
The repo keeps no curated file. The curated data of a view uses the Layer 7 keys (format 2): the C4 kind of an element
(`person`, `container_store`, ...) is its `icon`, and `c4_styles.C4` draws it. The modules are:

| File | Role |
|---|---|
| `c4_model.py` | the model: people, systems, containers, components, code, deployment, scenarios |
| `c4_verify.py` | structure and evidence checks; no `code` elements without the engineer's consent |
| `c4_styles.py` | the C4 `Notation`: element boxes by shape, boundaries and deployment nodes, key, neutral lines |
| `c4_views.py`, `c4_boxes.py` | one `Diagram` per view, boxes sized from the three text blocks of each |
| `c4_deploy.py` | the Deployment view: nested nodes and container instances. Frames carry their `cloud` and use the frame styles of that cloud. Infrastructure keeps its qualified `icon` |

The views are pages of `docs/architecture/diagrams/<name>-c4.drawio` (the page id is the slug, in slug order).
The tool draws them into `<name>-c4-<slug>.svg`:

| Slug | Page title |
|---|---|
| `1-context` | System Context diagram for S |
| `2-container` | Container diagram for S |
| `3-component-<id>` | Component diagram for S: C |
| `4-code-<id>` | Code diagram for S: X (only with consent) |
| `5-deployment` | Deployment diagram for S: env |
| `6-dynamic-<id>` | Dynamic diagram for S: scenario |

`build --c4` overwrites the file and every view image on each run. It deletes the images of views that the model no longer
produces. It also deletes the per-view `<name>-<slug>.drawio` and `.svg` files of earlier builds (exact slugs only, so
`<name>-3-tier.drawio` survives). It writes a README index with one row per view. There is no hand-edit guard for C4
views.

Pages (`files.pages`): the tool draws a one-page .drawio whole into its sibling `.svg`, as it always did for an L7 diagram. It draws each
page of a file of several alone, as a one-page mxfile, into `<stem>-<page id>.svg`: page `1-context` of
`shop-c4.drawio` becomes `shop-c4-1-context.svg`. Every image has a stamp of the sha256 of the whole file. Because of this, `check` wants a
fresh image for each page, and `image` and `view` regenerate them all. The index lists one row per page, and `snapshot` captures
each page alone. Layer 7 and C4 share the layout, router and checker.

The model states relationships at the lowest level known, and `c4_model.rollup` lifts them to the elements that a view shows. Each
lifted edge names the relationships behind it. Context and Container views draw every lifted edge, including those
between people and external systems. A Component view draws only those that touch its components. `c4_verify` projects
the core views (Context, Container, Component, Code) last. It fails on a rolled-up arrow without a shared label and on
a relationship that no core view draws.

A lifted edge over several relationships shows their shared `summary` (else their shared label). The line under it lists every
`technology` behind them, joined with commas, so the tool drops no protocol. Parts with different texts cause a verify error. Every
relationship needs a label. It also needs a technology when both ends are containers, components or code (except code
`inherits` and `implements`).

Evidence: the `fact` of a deployment node needs only to exist. The `fact` of an element must have an end on a node that hosts its
container. The `fact` of a relationship must run between the hosts of its two ends. A successful build prints the whole
report. It shows "C4 model: ok", then every container, component, code element, relationship and deployment node that rests
only on `stated`.

Review: `snapshot` prints `view: <page name>` before the PNGs of each page (the `<diagram name=...>`; the README index uses it too).
`REVIEW.md` picks the rules from it: "Every diagram" plus "Layer 7" or "C4: every view" plus the section with the same name as the page.

## Non-goals

The tool does no HCL evaluation (no `terraform plan`, no credentials). It does not expand the internals of remote modules.
The layout will be machine-made, not hand-tuned.

[RULES.md](src/cartographer/RULES.md) lists the drawing rules, where each is enforced and its source.
