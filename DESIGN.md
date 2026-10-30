# cartographer: Terraform folder -> Lucid-compatible draw.io

Python package in `src/cartographer/` (the stage files below live there). Subcommands of `cartographer`:

```
cartographer extract INFRA_DIR --name NAME       facts to $XDG_CACHE_HOME/cartographer/NAME/facts.json
cartographer prompt --name NAME [--describe]     schema to the cache folder, curation or describe prompt on stdout
cartographer build --name NAME                   verify, then docs/architecture/diagrams/NAME.drawio and .svg
cartographer image FILE.drawio                   regenerate the .svg next to a .drawio
cartographer check FOLDER                        fail when a .drawio has no image or a stale one (offline)
cartographer snapshot FILE -o DIR                PNG and tiles from the local draw.io
cartographer view FILE                           open in the local draw.io
cartographer docs interview|review|rules         path of a packaged document
```

The curation (stage 2) runs in the user's own Claude session, driven by the plugin skill; the tool never calls a model.
The committed files are `<name>.curated.json`, `<name>.drawio`, `<name>.svg` and the folder `README.md` index; facts and verify output stay
in the cache folder. `build` writes the svg by rendering the diagram in the local draw.io with headless Chrome
(`svg_export.py`), inlining local images as data URIs and embedding the mxfile in the `content` attribute.
Output is XML (draw.io), never an image. Coordinates come from a deterministic column grid (pure Python).

## Pipeline

| Stage | File | AI? | Input -> output |
|---|---|---|---|
| 1 extract | `tf_extract.py` | no | infra dir -> facts.json |
| 2 curate | `curate_prompt.md`, followed by Claude in the user's session (`cartographer prompt`) | yes | facts.json + repo code -> curated.json |
| 3 verify | `tf_verify.py` | no | facts + curated + repo -> verified curated + report |
| 4 layout | `tf_layout.py` | no | verified curated -> `Diagram` (absolute coords) |
| 5 render | `gen_drawio.py render(diagram, page_id=, page_name=)` | no | Diagram -> .drawio XML |

Reproducibility: curated.json is cached under `inputs_sha256`, a hash of the facts.json bytes, the prompt template
(`curate_prompt.md` with its placeholders unsubstituted, so no path enters the key) and the schema text the curation
must satisfy (with the icon enums injected). There is no model in the key. `build` refuses (exit 3) when the curated file's
`inputs_sha256` differs from the current key, so the curation is only redone when one of those changes. Stages 1, 3, 4, 5
are deterministic (sorted iteration everywhere, fixed grid constants), so the same curated.json always yields
a byte-identical .drawio.

## Shared types (`diagram_model.py`)

`diagram_model.py` holds the dataclasses `Group`, `Icon`, `Box`, `Edge`, `Title`, `Legend`, `LegendEntry`,
`Diagram`, plus the colour and port constants. `tests/test_drawio_format.py` renders a small synthetic diagram and
checks the file format (no `version` attribute, id first and `as` last, 2-space indent, `&#39;`, ports and points on
every edge, unique vertex ids).
`gen_drawio.render(diagram)` takes the draw.io page `id` and `name` as required keyword arguments: `build.py`
passes `<name>-architecture` and the curated title, `tf_layout.__main__` derives the name from the input file name.
Nothing in the generic modules is specific to one stack.

## Icons (`aws_icons.json`)

The tool works for any AWS Terraform stack. Icons are draw.io's own 329 AWS resource icons, keyed by draw.io
`resIcon` name (`lambda`, `s3`, `key_management_service`, `systems_manager`, `eventbridge`, `cloudwatch_2`, ...).
`aws_icons.json` maps each name to its category fill colour (`{"lambda": "#ED7100"}`). It is vendored by
`vendor_aws_icons.py` from `Sidebar-AWS4.js` of the pinned image `jgraph/drawio:32.5.5`:

```
docker cp drawio:/usr/local/tomcat/webapps/draw/js/diagramly/sidebar/Sidebar-AWS4.js <dir>/
python -m cartographer.vendor_aws_icons <dir>/Sidebar-AWS4.js
```

`generic_icons.json` (same script, same source file) holds the General Resources shapes drawn as
`shape=mxgraph.aws4.<name>` (`users`, `user`, `client`, `mobile_client`, `internet`, `generic_application`,
`corporate_data_center`, `generic_database`, ...) with their fill colour; names that are also `resIcon` names
(`marketplace`, `all_products`) stay AWS icons. `diagram_model.AWS_ICONS` and `GENERIC_ICONS` load the two files, in
that one place, and `has_icon` accepts either. `gen_drawio` styles AWS icons from `AWS_ICONS` and generic ones from
`GENERIC_ICONS` (shape with the label below, split on its line breaks and never wrapped, like an AWS icon).
Any other `Icon.service` renders as a plain box.

## facts.json (stage 1)

```json
{
  "infra_dir": "infra",
  "resources": [
    {"address": "aws_lambda_function.orders_api", "type": "aws_lambda_function", "module": "",
     "multi": false, "file": "infra/orders_api.tf", "line": 12}
  ],
  "edges": [
    {"id": "f12", "src": "aws_lambda_function.orders_api", "dst": "aws_dynamodb_table.orders",
     "kind": "iam", "detail": "dynamodb:Query,dynamodb:GetItem", "file": "infra/orders_api.tf", "line": 40}
  ],
  "services": [{"service": "bedrock", "actions": ["bedrock:InvokeModel"], "principals": ["module.agent.aws_iam_role.exec"]}]
}
```

- Parse every `*.tf` in the infra dir and, recursively, every LOCAL module (`source` starting `./` or `../`).
  Addresses inside a module instance are prefixed `module.<name>.`; nested modules chain the prefix. Remote
  modules (registry, git, TFC private) are recorded as a single resource of type `module` and not entered; they carry
  `source` (any `?ref=` query and credentials stripped) and `version` when given. `module.<remote>.<output>` references
  from other resources become `uses` edges to that module resource.
- Module families: two or more calls in one parent module with the same local `source` collapse into one instance
  addressed `module.<basename of the source dir>.` (`<basename>-family` if a different call already has that name).
  Every resource in it has `multi: true` and `instances`, the sorted call names; `var.x` resolves to the union of the
  calls' arguments, and edges are rewritten to family addresses, deduped (lowest file and line kept), self-edges dropped.
  A source used by one call keeps `module.<name>.` addressing. Applies at every nesting level.
- `multi`: true when the block has `count` or `for_each`, or sits in a module call with them.
- `file`/`line`: repo-relative path and start line of the block (python-hcl2 `with_meta=True`).
- References: scan every attribute value (strings after hcl2 parsing, recursively through lists/dicts) for
  `<type>.<name>` where type matches a resource type present in the parsed set, plus `module.<name>.<output>`
  and `var.<name>` inside modules. Resolve `var.x` inside a module instance to the references in the module
  call's argument `x`; resolve `module.m.out` to the references in module m's `output "out"` value. Resolve
  `data.` sources to nothing. Self references dropped.
- Edge `kind`, decided by a single table keyed on (source resource type, top-level attribute) with a `ref`
  fallback:
  - `iam`: from `aws_iam_role_policy` / `aws_iam_policy` documents. Parse `jsonencode` / heredoc JSON;
    every Statement with Effect Allow yields edges from each PRINCIPAL (the compute resources that use the role:
    any resource whose `role`/`execution_role_arn`/`role_arn` references that `aws_iam_role`) to each resource
    referenced in `Resource`, with `detail` = sorted actions. `Resource = "*"` or a constructed ARN that
    references no resource adds the actions to `services` (service = action prefix, e.g. `bedrock`).
    The policy may also be `templatefile("${path.module}/x.json.tpl", {k = ref})`, `file(...)`, `local.x`, `var.x`
    (resolved through the module call; a var no call passes means no policy) or a policy-document data source. In a
    template `${k}` for a vars-map key maps to that key's references, other `${...}` and `%{...}` directives become
    placeholders or vanish. A policy that still is not JSON (for example statements passed in at runtime) is counted
    as unparsed and yields no edges.
  - `trigger`: `aws_cloudwatch_event_target` (rule -> target arn), `aws_lambda_event_source_mapping`
    (event source -> function), `aws_s3_bucket_notification`, `aws_scheduler_schedule` target,
    `aws_lambda_permission` (principal source_arn -> function).
  - `route`: `aws_cloudfront_distribution` origins (distribution -> origin resource), `aws_lambda_function_url`.
  - `network`: `vpc_config` / `network_configuration` / `subnet_ids` / `security_group_ids` references.
  - `uses`: everything else (e.g. `kms_key_arn`, `role`). The curator decides whether these matter. Dropped when
    either end is a support type the curator folds into its owner (IAM roles/policies/attachments, log groups, KMS
    aliases, Lambda aliases/layer versions/invoke configs, S3 bucket policy/versioning/encryption/lifecycle/public
    access block/ownership/logging): such an edge only restates the owner's wiring and dominated the size
    (on a large real stack this roughly halved the edge count). Facts are read in full by an LLM, so keep them well under about 400 KB.
- Output is sorted (resources by address, edges by (src, dst, kind)); edge ids assigned after sorting.

## curated.json (stage 2, AI)

```json
{
  "inputs_sha256": "...",
  "title": "Shop: AWS architecture",
  "groups": [{"id": "g_api", "label": "Shop APIs", "kind": null, "parent": "acct", "column": 1}],
  "nodes": [{"id": "api_orders", "label": "orders API\norder handling", "service": "lambda", "group": "g_api",
             "tf": ["aws_lambda_function.orders_api"], "multi": false}],
  "externals": [{"id": "stripe", "label": "Stripe\n(payments)", "icon": "internet",
                 "evidence": [{"file": "infra/orders_api.tf", "line": 30, "contains": "stripe"}]}],
  "edges": [{"src": "api_orders", "dst": "ddb_orders", "label": "reads orders", "flow": "web",
             "dashed": false,
             "evidence": [{"fact": "f12"}, {"file": "src/shop/orders.py", "line": 88, "contains": ".query("}]}]
}
```

- `kind` in groups: `cloud | region | account | vpc | null` (the AWS frames; null = plain dashed group).
- `column` in groups: integer 0 to 3, required. Role groups directly in the account are placed left to right by it
  (ignored for frames and for groups nested in another group, which follow their parent).
- `service`: a draw.io icon name from `aws_icons.json` (`AWS_ICONS`) or `other` (SaaS, non-AWS), which becomes a
  plain box. The static `curated.schema.json` keeps `"type": "string"`; `tfdiagram.schema_text()` injects the enum
  (`sorted(AWS_ICONS) + ["other"]`) when it builds the schema the curation validates against, and that injected text
  feeds `inputs_sha256`. The prompt has no service list: the schema enum is the list.
- `icon` in nodes: optional, the same enum as the external `icon`. A non-AWS node (`service` `other`, a Datadog
  monitor) with an icon is drawn as that icon instead of a plain box.
- `icon` in externals: required, a name from `generic_icons.json` or `none` (plain box). Externals have no `group`;
  they always sit in the side lanes. `tfdiagram.schema_text()` injects the enum (`sorted(GENERIC_ICONS) + ["none"]`) like the
  service enum. Prompt guidance: people `users`/`user`, browsers and apps `client`, SaaS and remote APIs `internet` or
  `generic_application`, on-prem `corporate_data_center`.
- `label` on edges: a specific verb plus protocol where known ("invokes, HTTPS"), schema `maxLength` 28. The prompt asks for at most about 45 edges: primary request
  and data paths only, with per-node plumbing (logs, shared KMS key, config reads) mentioned once in a group label.
- Groups with no nodes (directly or in a child group) are legal but dropped by the layout; verify warns about them.
- `flow`: `web | trigger | runtime | credential | data`, mapped to the legend colours
  (blue, green, purple, red, grey).
- Every node must cite at least one existing TF address (`tf`) unless it is in `externals`. Every edge must cite
  at least one evidence item: a fact id, or a `file`/`line`/`contains` code citation (1-based line; `contains`
  is a literal substring that must appear within +-3 lines of `line`).
- Curation rules for the prompt: 40 to 90 nodes; collapse support resources (policies, attachments, log groups,
  versions, encryption configs, public access blocks, aliases) into their owner; one node per module instance
  family when `multi`; data-flow arrows come from reading the application code that runs in each compute node
  (Lambda handler `filename`/`source_dir`, agent runtime code) and must cite the call site.

## tf_verify.py (stage 3)

- Drop nodes whose `tf` addresses do not all exist in facts; drop edges touching dropped nodes.
- An edge survives if at least one evidence item checks out: a fact id that exists AND whose src/dst are among
  the tf addresses of the edge's src/dst nodes (either direction), or a code citation whose `contains` is found
  within +-3 lines of `line` in `<repo-root>/<file>`.
- Report (text, sorted): dropped nodes, dropped edges with reason, and `unshown` facts of kind
  iam/trigger/route between two shown nodes that no curated edge covers (recall hints), and IAM-only vs
  code-only mismatches for code-cited edges.
- Exit 0 always; the report is the artefact. `--strict` exits 1 when anything was dropped.

## tf_layout.py (stage 4)

Pure Python, no external process, five modules: `tf_layout.py` (orchestration, edges, legend), `tf_blocks.py` (frames
and block grids), `tf_lanes.py` (externals), `tf_order.py` (barycentric ordering), `tf_place.py` (crossing-aware
placement). Every number is a module constant
(icon pitch 150x150, group padding 30 sides and 50 top, frame padding 20 sides and 40 top, gap 40).

- Frames are groups of kind cloud, region or account. Every other group (kind null or vpc) is a block. A block with no
  nodes and no non-empty child block is dropped (`tf_blocks.empty_blocks`; verify reports it as a warning).
- Block size: child blocks stacked vertically at the top, then the block's own nodes in a grid of `min(n, GRID_COLS)`
  columns in curated order. Width is the max of the grid, the children and a label estimate (7 px per char + 40).
- Innermost frame: its direct child blocks go into columns by `column`, stacked in list order, tops aligned, each
  column as wide as its widest block. Outer frames wrap the single child with frame padding. No frames: the
  column grid sits at the top level. Nodes placed directly in a frame form an extra grid row under the columns.
- A4 proportions: `GRID_COLS` is chosen from {2, 3, 4}. All three are laid out; the one whose bounding box (frames,
  lanes and legend, not the title) has a width/height ratio closest to sqrt(2) (compared on a log scale) wins; ties go
  to the smaller value.
- Placement (`tf_place.py`): 4 deterministic barycentric passes (`tf_order.py`: nodes inside a block by the mean x of
  their neighbours, sibling blocks inside a column and externals by the mean y of theirs) give a start, and the best of
  them by the objective is kept. The objective is the number of proper crossings between the edges drawn as straight
  lines between node centres, plus their total length at a given number of pixels per crossing. A greedy local search
  then tries every swap of two nodes in one block, two blocks in one column slot and two externals in one lane, every
  move of an external to the other lane, and every slot (column and position) for a block whose `column` is open,
  keeping each change that lowers the objective, until a sweep finds none (at most 30 sweeps). Every candidate is a
  full placement, so the objective sees the real grid. The "AWS managed services" block has an open column, so it
  lands by its callers.
- Straight lines only approximate the routes, so for the chosen `GRID_COLS` the placement is made once per length
  weight in `tf_layout.SPREADS` (none, and 500 px per crossing), each is routed and fitted, and the one with the fewest
  crossings plus checker violations wins, then fewest bends.
- Externals sit outside the frames in two lanes: an external's `lane` (set by placement) decides; without one, those
  that are only ever an edge `src` go left and all others (including edgeless ones) go right. An external with an `icon` takes a 150x150 icon cell (shape plus label below),
  one without a 200x100 box cell. A lane taller than the frames wraps into two sub-columns, filled row-major.
- Nodes whose service has no icon (`has_icon`) become boxes, centred in an icon cell.
- Output is a `Diagram`: frames, then groups parent-before-child, then leaves, edges sorted by (src, dst, label), a
  generated legend listing only the flows used under everything, title from curated.json.
- Routing (`tf_route.py`, after the arrangement is chosen): `tf_ports.py` picks a side per edge end (sideways when the
  other end is 90 px or more away horizontally and the gap fits the caption, else top/bottom; an icon's bottom holds its
  caption so it uses a flank) and spreads the edges on one side evenly, ordered by the other end's position. The router is
  an orthogonal A* over a sparse grid (obstacle borders, ports, evenly spaced tracks in each gap); every leaf plus the
  caption under an icon is a wall (`tf_geom.py`), so is every group title band (`title_rect`: every line of the
  title at its rendered left spacing), and so is every group that holds neither end of the edge (a group is an
  ancestor when its box contains an endpoint). A segment parallel to a group or frame border within LINE_GAP of it is
  closed too; that strip is the last constraint relaxed when an edge has no other route. The grid itself lives in `tf_grid.py`. Cost: length, a bend penalty,
  a heavy flat+per-px penalty for sharing a segment with an earlier edge, and a crossing penalty above the bend one.
  Edges go shortest first, ties by id. Each `Edge` gets `out`, `into`, `points` and `exact=True`: the renderer then
  draws the polyline as given (no `edgeStyle`), so draw.io cannot re-route it and the captions stay where they were
  measured. Hand-made models leave `exact` off and their points stay connector hints.
- Captions (`tf_labels.py`): each caption (about 7 px per character at 12 px, 20 px tall) goes on its own route, on a horizontal
  segment long enough for it if possible, nearest the source; the first spot clear of nodes, group titles, other
  captions, other edges and group borders wins, else the spot overlapping the fewest nodes, titles and captions, then
  with the fewest things in its clearance. Once every edge is routed, a caption that a later route now crowds is placed
  again. Stored as `Edge.at` (relative position along the polyline) plus `Edge.shift`
  (draw.io `offset` point, emitted only when non-zero). `--edge-labels off` blanks the captions; routing still runs.
- `tf_check.measure` takes the draw.io text, not the model: `tf_read.read` parses it back (absolute boxes through
  parents, ports from exit/entry, points, caption at relative x plus offset) and the counters run on that, so they can
  never disagree with the file. It counts bends, crossings, caption overlaps, captions on nodes, captions on lines
  (other edges, group borders, group titles), edges through nodes, edges through foreign groups, edges through group
  titles, segments running within LINE_GAP beside a group border (line on frame) and edge pairs sharing a collinear
  segment; `tf_layout`'s command line prints it.
- Legend: colours plus the words "Solid line: primary request path" and "Dashed line: secondary, control or async".
  All text is at least 12 px; arrowheads are open.

## Non-goals

No HCL evaluation (no `terraform plan`, no credentials). Remote module internals are not expanded.
Layout will be machine-made, not hand-tuned.

The drawing rules, where each is enforced and its source are listed in [RULES.md](src/cartographer/RULES.md).
