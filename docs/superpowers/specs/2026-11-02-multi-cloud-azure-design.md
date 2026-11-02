# Multi-cloud: a per-cloud catalog, deterministic icons and Azure

Date: 2026-11-02. Status: draft for the owner's approval.

## Intent

cartographer is a focused AWS tool. The owner wants it to grow into a generic cloud diagram generator, starting with
Azure, and a single diagram may show more than one cloud (an AWS stack calling an Azure service, or one repo with
both). GCP is dropped for now.

A review of how cartographer knows which service a Terraform resource is found that it does not: extraction reads
every resource generically, then Claude picks each node's icon from the full list of 331 draw.io AWS icon names
injected into the schema, and verification only checks that the name exists. `aws_sqs_queue` drawn with the `sns`
icon passes. That works for common AWS services but does not scale: Azure adds 666 icons and 1,107 resource types,
obscure services get a guess nobody checks, and the whole icon list goes into Claude's context on every run.

So this change does two things, in this order:

1. Makes icons deterministic and organises the code per cloud. Each cloud ships a reviewed catalog that maps
   Terraform resource types to icons; extraction writes the icon on every resource; Claude reviews the rendered
   result and corrects the catalog through a repo override file when it is wrong.
2. Adds Azure on that structure, following the same principles as AWS with Azure's own terms, including the edge
   cases (load balancers, private endpoints, VNet integration, delegated subnets).

## Measured baseline (2026-11-02)

Sources: Terraform Registry provider docs index (`registry.terraform.io/v2/provider-docs`), draw.io 32.5.5 sidebar
files (`Sidebar-AWS4.js`, `Sidebar-Azure2.js`, `img/lib/azure2/`), Microsoft's samples repo `github.com/Azure/terraform`
(commit 57313b5).

| | AWS (`hashicorp/aws` 6.71.0) | Azure (`hashicorp/azurerm` 5.12.0) |
|---|---|---|
| Resource types | 1,740 | 1,107 |
| Registry service groups (subcategory) | 258 | 111 |
| Type families (first token after the provider) | about 267 | about 144 |
| draw.io icons | 329 `resIcon` with titles | 666 distinct names (704 SVGs, 31 categories) |

- AWS, matching registry service names to draw.io icon titles: 146 match exactly, 69 belong to a parent service with
  an icon (CloudWatch Logs -> CloudWatch, S3 Tables -> S3), 43 have no automatic candidate, of which at least 10 have
  an icon under another name (AppConfig -> `app_config`, Managed Prometheus -> `managed_service_for_prometheus`,
  QuickSight -> `quick_suite`, ELB Classic -> `elastic_load_balancing`). The rest are mostly billing, account and
  admin services.
- Azure: name matching is unusable. 48 of 111 service groups matched and several were wrong (Database -> a SAP icon,
  Compute -> `compute_fleet`). Azure's groups are coarse: "Messaging" spans Service Bus, Event Hubs, Event Grid,
  SignalR and Relay; "Network" holds 108 types. Azure must map at type-family level.
- Extraction on all 152 Azure quickstart samples: every one parsed (1,562 resources, 2,382 edges), but network,
  placement and permission facts were empty (they only read AWS), and about 20% of resources were `random_*`,
  `tls_*` or `time_*`. 35 were `azapi_resource`, whose service is only in its `type` string.

Conclusion: automatic matching only drafts a catalog. The reliable source is a reviewed table.

## Goals

1. **Per-cloud structure.** A cloud-neutral core (parse Terraform, layout, routing, render, verify, view) and one
   package per cloud under `src/cartographer/clouds/`. The core never branches on which cloud it is.
2. **Deterministic icons.** A reviewed catalog per cloud maps every resource type of the pinned provider version to
   an icon, to "fold into owner", to "drop", or to a deliberate generic icon. Extraction writes the result on each
   resource. Same Terraform, same icons.
3. **Attribute rules** for the types whose icon or placement depends on one attribute (AWS `aws_lb`, Azure
   `azurerm_lb`, `azurerm_cognitive_account`, `azapi_resource`, ...). An unresolvable attribute (a variable with no
   default) falls back to the type's base icon and is marked, never guessed.
4. **Completeness tests.** Every resource type in the vendored provider type list has a catalog row; every icon a
   catalog names exists in the pinned draw.io. A provider or draw.io bump with an unmapped type fails CI.
5. **Repo override file and fix step.** When Claude's review finds a wrong or marked icon, Claude writes an override
   to the repo's override file and rebuilds, inside the existing review loop (at most three rounds). Overrides are
   listed in the build report so the catalog can be fixed upstream.
6. **Multi-cloud diagrams.** Each resource is resolved by the cloud that owns its provider. Each cloud present gets
   its own top-level frame with its regions, accounts or subscriptions and networks inside; arrows between clouds
   route between frames with the existing rules.
7. **Azure, same principles as AWS.** Boxes, subnet tiers, permissions, triggers, routes, fold rules, managed
   services and describe mode, in Azure's terms (sections below).
8. **AWS output unchanged in appearance**, apart from icons the catalog corrects. A single-cloud AWS diagram keeps
   its frames, labels and layout; every icon that changes is listed in the build report.
9. **Bounded context.** Claude never sees a full icon list. Curation sees the resolved icon on each resource; the fix
   step sees only the icons of the clouds present, and only when it needs to choose one.

## Non-goals

- GCP. draw.io's GCP set is old (about 149 titles, no Vertex AI, Gemini, Secret Manager, AlloyDB, Looker, Workflows
  or Eventarc); a usable GCP needs Google's own icon pack, a new download with its own licence and pin. The structure
  must make GCP a new package later, nothing more.
- Other providers' resources as first-class services (Kubernetes, Datadog, GitHub). They keep today's treatment:
  generic or brand icons chosen in curation, or dropped.
- An L3 (network) view, Availability Zones, subnet CIDRs, route tables drawn as shapes.
- Running `terraform plan`, reading state or `.tfvars`, or calling any cloud API. Parsing stays the only input.

## Anti-goals (failure even if it works)

- The icon decision stays a model guess anywhere in the default path.
- A full icon list (any cloud) is injected into the prompt or schema.
- Cloud checks (`if cloud == "azure"`) scattered through the core instead of living behind the cloud contract.
- An AWS diagram that changes appearance because Azure was added.
- Azure placement that is plausible but wrong: drawing an App Service inside a subnet because it has VNet
  integration, or calling a subnet public by name alone when the evidence says otherwise.
- Any download at runtime beyond the existing pinned draw.io. Provider type lists and icon tables are vendored and
  committed.

## Constraints

- Everything else in `DESIGN.md` stays: the tool never calls a model; stages 1, 3, 4, 5 are deterministic; diagrams
  never leave the machine; the review loop decides "ready".
- No file over 1,000 lines. `tf_extract.py` (373) and `tf_network.py` (180) lose their AWS parts to `clouds/aws/`.
- Python 3.13, the existing dependency set (`python-hcl2` only at runtime). No new runtime dependency.
- The plugin data folder layout, launcher and draw.io pin are unchanged.
- The public repo contains no client or company names; fixtures are synthetic.

## Decisions

The owner decided:

- Icons are resolved in code from a reviewed per-cloud catalog; Claude reviews and fixes.
- Claude's fix step updates the listing and regenerates the diagram.
- Organise per cloud: AWS, Azure; GCP dropped for now.
- Diagrams may show more than one cloud at a time.
- Azure boxes follow the same principles as AWS with Azure's terms, accurate, covering edge cases like the AWS load
  balancer.
- The reviewing Claude knows exactly which kind of diagram (L7 now, L3 later) and which resource each icon stands
  for, so it judges icons correctly (review sheet below).

The designer's calls (the owner can override):

- The override file lives in the user's repo, `docs/architecture/diagrams/icons.json`, committed with the diagrams,
  because the plugin's own files are replaced on every update.
- Resource groups are not drawn as boxes, matching AWS, which has no box for that kind of logical grouping. The
  resource group stays available as evidence and in labels.
- Group kinds become cloud-neutral: `cloud`, `region`, `account`, `network`, `subnet`. Each cloud labels them
  (AWS: AWS Cloud, Region, Account, VPC; Azure: Azure, Region, Subscription, Virtual network).
- Existing curated files are converted automatically (`vpc` -> `network`) on read; see Migration.
- Synthetic test fixtures, not copied samples. The Azure quickstarts are a local smoke run only.
- Overrides are applied at build time, after verify, and are not part of the curation cache key: an icon fix is a
  plain rebuild, never a re-curation.
- Remote modules resolve through a module-source table (below); an unknown remote module is chosen by Claude and
  marked, the same treatment as an unresolvable attribute.
- Fold stays what it is today (edge suppression plus the curator merging); the tool enforces only `drop`.
- Existing diagrams are not pinned to their old icons: corrections are the point of the change, and each one is
  listed in the build report.
- Claude never chooses from a list: describe-mode nodes and externals name a Terraform resource type that the
  catalog resolves, and the fix step finds icons with a search command.
- Frame groups carry a `cloud` field; Claude keeps writing their labels as today.

## Architecture

```
src/cartographer/
  core modules (cloud-neutral): tf_extract (blocks, modules, references), tf_layout, tf_route, tf_place, ...,
                                gen_drawio, verify, view, build
  clouds/
    __init__.py      registry: provider prefix -> Cloud; resolve(resource) -> Cloud
    base.py          the Cloud contract (below) and shared helpers (catalog loading, longest-prefix match)
    aws/
      __init__.py    the AWS Cloud
      catalog.json   type family -> row (reviewed)
      icons.json     vendored draw.io icon table (today's aws_icons.json)
      provider_types.json  vendored resource type list of the pinned hashicorp/aws version
      rules.py       attribute rules, fold and drop lists, trigger and route specs (moved from tf_extract)
      network.py     VPC, subnet, tier facts (moved from tf_network)
      permissions.py IAM policy reading (moved from tf_policies)
      vendor.py      refresh icons.json and provider_types.json; draft catalog candidates
    azure/
      same files; plus arm_types.json (ARM resource type -> icon, for azapi_resource)
```

### The Cloud contract

Each cloud is one object implementing a small protocol. The core only calls these:

| Member | Meaning |
|---|---|
| `name`, `label` | `aws` / "AWS", `azure` / "Azure" |
| `providers` | Terraform provider prefixes it owns: AWS `aws`; Azure `azurerm`, `azapi` |
| `resolve(resource) -> Resolution` | icon, or fold-into-owner, or drop, plus `marked` and the rule that decided |
| `network_facts(module_set) -> NetworkFacts` | networks, subnets, tiers and resource placements |
| `permission_edges(module_set) -> list[Edge]` | IAM (AWS) or role assignments (Azure) as edges |
| `edge_specs` | trigger and route specs keyed by resource type (today's `SPECS`) |
| `labels` | frame labels per neutral group kind, managed-services box label |
| `frame_styles` | draw.io styles of its frames (today's `GROUP_STYLES` for AWS) |
| `icon_style(icon) -> str` | the draw.io style of one icon |

Providers no cloud owns (`random`, `tls`, `time`, `null`, `local`, `archive`) are dropped by the core. Other providers
(`kubernetes`, `datadog`, `github`, `azuread`) stay resources with no resolved icon: curation chooses a generic or
brand icon as today. `azuread` is owned by Azure only for permissions (service principals and groups are principals),
not for icons.

### The catalog

`catalog.json` rows are keyed by type family, matched by longest prefix of the type name, so
`azurerm_virtual_machine` and `azurerm_virtual_network` resolve to different rows.

```json
{
  "aws_cloudwatch_log": {"fold": "owner"},
  "aws_lb": {"icon": "elastic_load_balancing", "rule": "aws_lb_type"},
  "aws_s3_bucket": {"icon": "simple_storage_service"},
  "aws_s3_bucket_policy": {"fold": "owner"},
  "aws_billing": {"generic": "generic_application", "why": "no draw.io icon"}
}
```

Row kinds: `icon` (optionally with a `rule`), `fold` (into the resource it references, as `SUPPORT` does today), `drop`
(never drawn: `random_*`), `generic` (a deliberate generic icon, with `why`). Every row is reviewed by a person in a
PR. `vendor.py` drafts candidates for new types by matching registry service names against draw.io icon titles and
search tags; drafts are never committed without review.

### Attribute rules

A rule reads one attribute of the resource after hcl2 parsing and variable-default resolution, as extraction already
resolves `var.x`. Required rules (minimum; the builder adds others found while writing the catalog):

| Type | Attribute | Outcome |
|---|---|---|
| `aws_lb` / `aws_alb` | `load_balancer_type` | application (default), network, gateway icon |
| `aws_ecs_service` | `launch_type`, `capacity_provider_strategy` | Fargate or ECS icon |
| `aws_db_instance`, `aws_rds_cluster` | `engine` | Aurora icon for `aurora*`, else RDS |
| `azurerm_lb` | frontend `public_ip_address_id` vs `subnet_id`, `sku` | public LB, internal LB, Gateway LB |
| `azurerm_application_gateway` | `sku.tier` | App Gateway, with WAF marker for `WAF_v2` |
| `azurerm_cognitive_account` | `kind` | OpenAI, AIServices, Speech, Form Recognizer, ... |
| `azurerm_storage_account` | `is_hns_enabled`, `account_kind` | Data Lake Gen2, Blob, File, Storage account |
| `azurerm_cosmosdb_account` | `kind`, `capabilities` | NoSQL, MongoDB, Cassandra, Table, Gremlin |
| `azapi_resource` | `type` (`Microsoft.X/y@version`, version stripped) | `arm_types.json` lookup |

When the attribute is a reference or a variable without a default, the outcome is the row's base icon with
`marked: true` and the reason. Marked resources are listed in the build report and are what the review looks at
first.

### Remote modules

Extraction does not open remote modules; each is one resource of type `module` with `source` and `version`. They
resolve through `clouds/<cloud>/modules.json`, keyed by source prefix:

- `terraform-aws-modules/<name>/aws` -> a row per module name (`eks` -> `elastic_kubernetes_service`, `rds` -> RDS).
- Azure Verified Modules `Azure/avm-res-<provider>-<resource>/azurerm` -> the ARM type they deploy
  (`avm-res-network-virtualnetwork` -> `Microsoft.Network/virtualNetworks`), then `arm_types.json`. AVM pattern modules
  (`avm-ptn-*`) have no single resource and are treated as unknown.
- Any other source: the curator picks the icon with `cartographer icons` (below), recorded as an override with its
  reason, and the review sheet shows `decided_by: "curator, unknown module"` with `marked: true`.

A test checks that every `modules.json` icon exists in the cloud's icon table.

### Facts

Each resource in `facts.json` gains `cloud` and `icon` (or `fold`), plus `marked` and `rule` when they apply. Folded
resources stay in the facts so evidence can cite them; dropped resources are omitted.

`fold` keeps today's meaning: a `uses` edge touching a folded type is not emitted, and the curator merges the
resource into its owner. The tool does not compute owners, because many folds reference two resources (role
assignments, associations) or are referenced by their owner (a VM references its NIC). Verify warns when a node is
built only from folded resources. `drop` is enforced: dropped resources never reach the facts. `vpcs`/`placements` become
`networks`/`placements` carrying `cloud`. Facts stay well under the existing 400 KB guidance.

### Curation, verification and the fix step

- The schema no longer injects icon enums. A node's icon comes from its `tf` addresses (the first resolved one,
  in the order listed); `service` disappears from nodes created from Terraform.
- Externals that are cloud managed services, and describe-mode nodes, name `tf_type` (a resource type such as
  `azurerm_cognitive_account`) and optional `attributes` (`{"kind": "OpenAI"}`); the catalog and its rules resolve
  the icon exactly as for Terraform resources. Only when no type fits do they name `icon`, found with the search
  command, and that entry is marked.
- `cartographer icons --cloud azure --search openai` prints the matching icon names with their draw.io titles
  (at most 20). It is the only way Claude looks up an icon by name.
- Verification rejects an override or external icon that does not exist in its cloud's table, and an override for a
  resource or type not in the facts.
- Override file `docs/architecture/diagrams/icons.json`:

  ```json
  {"overrides": [
    {"cloud": "azure", "type": "azurerm_cognitive_account", "address": "azurerm_cognitive_account.chat",
     "icon": "azure_openai", "reason": "kind = var.kind, set to OpenAI in env/prod.tfvars"}
  ]}
  ```

  `address` is optional (type-wide override when absent). `reason` is required. Overrides are applied by `build`
  after verify, when icons are attached to nodes; they are not in `facts.json` and not in the curation cache key.
- Fix step (in the skill's review loop): when a rendered icon is wrong or marked, Claude finds the right icon with
  `cartographer icons`, edits the override file with a reason, runs `build` again (no re-curation) and looks again. The build report lists every override so the owner can move it into the
  catalog.

### Review sheet: what the reviewer is looking at

The owner requires that the reviewing Claude knows exactly which kind of diagram it is reviewing and which resource
each icon stands for, so it judges icons against the right resource and the right view.

- `build` writes `review.json` to the cache folder next to the screenshots, and the skill's review step reads it
  before looking at any image:

  ```json
  {"view": "l7", "view_name": "Layer 7: services and how they call each other", "clouds": ["aws", "azure"],
   "nodes": [
     {"id": "chat_ai", "label": "chat model", "cloud": "azure", "icon": "azure_openai", "icon_title": "Azure OpenAI",
      "tf": [{"address": "azurerm_cognitive_account.chat", "type": "azurerm_cognitive_account",
              "file": "infra/ai.tf", "line": 12}],
      "decided_by": "rule azurerm_cognitive_account kind = \"OpenAI\"", "marked": false, "override": null,
      "frame": "Azure > West Europe > Subscription > Virtual network > Private subnets"}
   ]}
  ```

- Every icon on the rendered page maps to exactly one entry by node id. Tiles do not record what they show today:
  `snapshot` gains a `tiles.json` listing, per tile file, the node ids whose icon falls in it (from the `.drawio`
  coordinates), and each sheet entry gets its tile names, so the reviewer ties what it sees to an entry. Each icon
  also shows its label, which the sheet repeats.
- `view` is the diagram kind. Today it is always `l7`; the review checklist (`REVIEW.md`) gets a section per view, and
  the reviewer applies only the section for the sheet's `view`. An L3 view, when designed, adds its own section and
  its own icon expectations (subnets, route tables, gateways drawn as shapes) without touching L7's.
- `icon_title` is draw.io's display title for the icon, so the reviewer checks "is `azurerm_cognitive_account.chat`
  an Azure OpenAI resource" in words, not by internal icon names.
- `decided_by`, `marked` and `override` tell the reviewer why the icon is what it is; marked entries are reviewed
  first, and a fix writes an override with the evidence that settles it.
- The sheet lists only the nodes on this diagram, so its size is bounded by the diagram, not by any catalog.

### Multi-cloud frames

- Frame groups (`cloud`, `region`, `account`, `network`, `subnet`) carry `cloud`; verify rejects a frame without it
  and a node whose resolved cloud differs from its frame's. Claude writes frame labels as today.
- Layout today follows one frame chain (`tf_blocks._frame_chain` takes the single deepest frame). It must handle
  several frame trees: two clouds side by side, two regions in one cloud. This is new layout work in the core, and
  the routing rules and `tf_check` apply unchanged across trees.
- One top-level frame per cloud present, side by side, each with its own region/account/network nesting. A
  single-cloud diagram is the same as today.
- The managed-services block (`tf_aws_externals.py` today) becomes per cloud: an external with `cloud` and `icon` is
  moved into "<Cloud> managed services" inside that cloud's region frame. An external of a cloud with no region frame
  in the diagram gets that cloud's frame with only the managed-services block.
- Arrow colours keep today's rule (colour of the destination group).
- Legend: unchanged entries; a cloud frame needs no legend entry.

## Azure model

### Boxes

| AWS | Azure | Read from Terraform |
|---|---|---|
| AWS Cloud frame | Azure frame | resource provider `azurerm` or `azapi` |
| Account | Subscription | `subscription_id` on the provider block, including aliases (`provider = azurerm.hub`). A variable with no default gives the label "Subscription" without an id, never a guess |
| Region | Region | each resource's `location`, usually `azurerm_resource_group.x.location`; a different location is a second region frame |
| VPC | Virtual network | `azurerm_virtual_network`; remote VNets via `data.azurerm_virtual_network`, peering (`azurerm_virtual_network_peering.remote_virtual_network_id`) or other stacks' outputs, named from the reference without address space |
| VPC label with CIDR | VNet label with `address_space` | literal or resolvable values only, as for AWS |
| Subnet tier frames | the same three tiers | rules below |
| AWS managed services | Azure managed services | externals with `cloud: azure` |

Resource groups are not boxes.

### Subnet tiers

Azure has no internet-gateway route, so a tier comes from what is in the subnet and how it leaves:

- **Public**: the subnet holds an internet-facing endpoint: a NIC with `public_ip_address_id`, an Application Gateway
  or Load Balancer whose frontend has a public IP, Bastion (`AzureBastionSubnet`), a VPN or ExpressRoute gateway
  (`GatewaySubnet`), or Azure Firewall (`AzureFirewallSubnet`).
- **Private**: no internet-facing endpoint, and outbound internet only through an explicit path: a NAT gateway
  association, a Standard Load Balancer outbound rule, or a route table with `0.0.0.0/0` to a firewall or virtual
  appliance.
- **Isolated**: `default_outbound_access_enabled = false` and no explicit outbound path.
- No evidence either way: fall back to the subnet's name or tags (as AWS does), else private, and record what decided
  it. Since the ARM API versions released after 31 March 2026, new subnets default to no default outbound access;
  older API versions keep the old default. The code reads the flag and never assumes the default.

### Placement edge cases

- **VMs** reach their subnet through the NIC: `network_interface_ids` -> `azurerm_network_interface.ip_configuration.subnet_id`.
  Scale sets carry `subnet_id` in their `network_interface.ip_configuration`.
- **Subnets** may be inline (`azurerm_virtual_network.subnet {}`) or separate `azurerm_subnet`; both count.
- **Private endpoints**: the PaaS service (SQL, Storage, Key Vault, App Service) stays in the region's regional area;
  the private endpoint is drawn in its subnet with an arrow to the service. Inbound only.
- **VNet integration** (`virtual_network_subnet_id` on Web or Function Apps): outbound only. The app stays in the
  regional area with an outbound arrow into the delegated subnet; it is never drawn inside the subnet.
- **Subnet-injected services** are drawn inside the subnet: PostgreSQL and MySQL Flexible Server
  (`delegated_subnet_id`), AKS node pools (`vnet_subnet_id`), Container Instances, Container Apps environments
  (`infrastructure_subnet_id`), SQL Managed Instance, API Management in internal or external VNet mode,
  App Service Environment.
- **Global services** sit outside any region frame, like CloudFront: Front Door, Traffic Manager, public DNS zones.
- **Peering and hubs**: a peered VNet is a second network frame; hub-spoke is two frames with a peering arrow.

### Permissions (the Azure counterpart of IAM edges)

`azurerm_role_assignment` with `principal_id` referencing a resource's managed identity
(`<resource>.identity[0].principal_id`, or `azurerm_user_assigned_identity.x.principal_id` attached to resources
through `identity.identity_ids`) and `scope` referencing a resource yields an edge principal -> scope resource with
`detail` = `role_definition_name`. A scope that is a subscription or resource group adds the role to the cloud-wide
`services` list, as `Resource = "*"` does for AWS. Key Vault access policies (`azurerm_key_vault_access_policy`)
yield the same kind of edge. Role assignments are folded after their edge is made.

### Triggers and routes

Minimum specs (the builder adds others found while writing the catalog):

- Trigger: `azurerm_eventgrid_event_subscription` / `azurerm_eventgrid_system_topic_event_subscription` (source ->
  endpoint: function, queue, Event Hub, webhook), `azurerm_monitor_action_group` receivers,
  `azurerm_stream_analytics_*_input`/`_output`.
- Route: `azurerm_cdn_frontdoor_origin` (Front Door -> origin host resource), `azurerm_application_gateway` backend
  pools, `azurerm_api_management_backend`, `azurerm_lb_backend_address_pool` members.
- Function triggers live in the application code, not Terraform; curation reads them as it reads Lambda handlers.

### Fold and drop

Fold: `*_association`, `azurerm_role_assignment` (after its edge), `azurerm_monitor_diagnostic_setting`,
`azurerm_private_dns_zone_virtual_network_link`, `azurerm_subnet_*` associations, NSG rules into their NSG, NICs
into their VM. Drop: `random_*`, `tls_*`, `time_*`, `null_*`. The catalog is the single place these live.

### Describe mode

The interview asks which cloud or clouds; externals and nodes then name `cloud` and `icon`. Defaults for Azure tiers:
gateways and public load balancers public, compute and data private, recorded in `assumptions`.

## Migration

- `aws_icons.json` and `vendor_aws_icons.py` move into `clouds/aws/`. `generic_icons.json` and `brand_icons.json`
  stay in the core.
- Existing `curated.json` files: the schema change alters the cache key, so `build` reports them stale and they are
  re-curated on their next run, as any schema change does today. Old icons are not kept: each icon that differs
  from the previous `.drawio` is listed in the build report so the user sees every correction. Re-curation writes
  `network` and frame `cloud` fields.
- `DESIGN.md`, `RULES.md`, `curate_prompt.md`, `describe_prompt.md`, `INTERVIEW.md`, `REVIEW.md`, the skill and the
  README are updated to cloud-neutral wording with per-cloud sections where needed.

## Testing

- Completeness: every type in each `provider_types.json` resolves to a row; every catalog icon exists in its
  `icons.json`; every `arm_types.json` icon exists.
- Rules: one test per attribute rule, including the unresolvable-variable fallback that marks.
- Azure network: synthetic fixtures for each tier rule, inline and separate subnets, NIC indirection, private
  endpoint, VNet integration, delegated subnet, reserved subnet names, peering.
- Review sheet: every node on a built fixture has exactly one sheet entry with its `tf` types, `icon_title`,
  `decided_by` and tiles; `view` matches the curated view.
- Multi-cloud: a fixture with AWS and Azure resources and a cross-cloud edge renders two frames with no rule
  violations (`tf_check`).
- AWS parity: today's AWS fixtures, converted to the new schema by hand in the test data, render byte-identical
  `.drawio` except where the catalog corrects an icon (listed in the PR).
- Remote modules: a `terraform-aws-modules` call, an AVM resource module and an unknown module each resolve as above.
- Search: `cartographer icons` returns at most 20 matches with titles.
- Smoke (local, not committed): extract over the 152 Azure quickstarts with no errors and non-empty network facts
  where the sample has a VNet.

## Left to the builder

- The exact module split and names inside `clouds/`, as long as no file passes 1,000 lines and the core has no cloud
  checks.
- Catalog row content for each type family (reviewed in the PR), and any extra attribute rules, triggers or routes
  found while writing it.
- Azure frame colours and draw.io styles, within draw.io's Azure group styles where they exist.
- How `vendor.py` fetches the registry list (it runs by hand, never at runtime).
