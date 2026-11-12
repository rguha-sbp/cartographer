# External networks: design for the PR #19 rework

Status: draft for approval. Local only (excluded through `.git/info/exclude`), not committed.

## Intent

Cartographer diagrams are review and audit evidence: engineers produce them, tech leads review them, auditors audit
on that basis. For networks, the question a reader asks is **"which network does this component run in?"**

- Every component that runs in a network (a Lambda with `vpc_config`, an ECS service, an RDS instance, an Azure
  resource in a subnet) sits inside the box of the network it actually runs in.
- A network this stack creates is a plain network box, as today.
- A network this stack does not create (another stack or account shares it, or the stack looks it up) shows the
  network's own name and the marker `External`, for example `shared-vpc (External)`.

The user decided the title names the network itself, not the stack, workspace or account it comes from.

## Why a rework

PR #19 drew the title as `shared from <stack>` and guessed the stack name from remote state settings (seven config
fields, path rules, environment word lists, word stems) and warned when an account frame was named after that stack.
That guessing has no bounded input space: 36 review rounds each found a new input that broke it, and several fixes
caused the next finding. This design removes the guessing and keeps only what the reader needs.

## Goals

1. **Correct box.** A node drawn inside a network group runs in that network, as the Terraform shows it. Verify
   enforces this for every network group, local and external, both directions.
2. **External marker.** A network group whose nodes run only in external networks is titled `<name> (External)`.
3. **One box per network, never one box for two networks.** Modules that read the same remote output of the same
   state share one network fact. Two different states give two network facts.
4. **AWS and Azure alike.** VPCs and VNets follow the same rules.
5. **Reviewable against this document.** Each review round reads this document; it defines what counts as a finding.

## Non-goals

- Naming the stack, workspace or account a network comes from.
- Deciding which account owns an external network. Terraform does not say.
- Checking which account frame a network group sits in. The curation prompt and review rule 17 still tell the
  curator to keep an external network in the stack's own account frame; nothing in verify checks it.
- Following a lookup whose id comes from a remote output (`data "aws_vpc"` with `id = data.terraform_remote_state...`,
  as in GIP and MCI). That is a follow-up.

## Anti-goals (a failure even if everything else works)

- A component drawn inside a network box it does not run in, with no note in the build report.
- Two real networks merged into one box.
- A network marked `external` that this stack creates.
- Extract or verify crashing on any Terraform input.

When the tool cannot tell, it prefers the visible, harmless error: two boxes for one network, or a plain box without
the marker.

## Design

### 1. Network facts

A network fact keeps `id`, `cloud`, `address`, `name`, `cidrs`, `remote`, `file`, `line`. PR #19's `stack` field on
network and placement facts goes away. `remote` keeps its current meaning: true for a remote output (`tfe_outputs`,
`terraform_remote_state`) and for a data lookup (`data.aws_vpc`, `data.azurerm_virtual_network`, `data.aws_subnet(s)`).
`remote: true` is exactly "external". A lookup that picks a resource of its own type that this stack creates is
that local resource, not a lookup. Only the arguments that pick one resource count: `id` or a `vpc-id` / `subnet-id`
filter for AWS, `name` for Azure. Each must be one reference and nothing else, all must read the same one resource,
that resource must use the same provider, and for Azure the `resource_group_name` (and a subnet's
`virtual_network_name`) must agree. A tag, a name filter, `"${aws_vpc.main.tags.Name}-peer"`, a `depends_on` or another
provider keeps the lookup external: a peer or DR network is often found by the tags of a local one.

`name` is the network's own name, as today: the output name less its id suffix (`shared_vpc_id` → `shared-vpc`), or
the data source name for a lookup.

### 2. Identity of a remote network (which outputs are the same network)

Cartographer never opens a state file, never contacts a backend and never runs Terraform. It reads only the `.tf`
source. "State" below means the text of the data block that points at a state, as written in the `.tf` files.

A remote output's network is identified by **the state its data block names plus the network name derived from the output**
(`hub_vnet_id` and `hub_vnet_name` of one state are one VNet; builder check, my call). The state is a typed value,
built once per data source reference and kept on the reference (not encoded in a string key that is parsed back):

```
State(kind, settings, index)
  kind      "tfe_outputs" | "terraform_remote_state"
  settings  every attribute of the data block that selects the state, resolved to literals:
            backend, workspace (dropped when "default"), organization, and every key of config
            (bucket, key, prefix, path, workspaces.name, workspaces.prefix, storage_account_name,
            container_name, ...), as a sorted tuple of (path, value); for tfe_outputs also the
            hostname of the tfe provider it uses (default app.terraform.io), so two hosts never merge, and
            that provider's organization when the block has none. A terraform_remote_state with the
            `remote` backend of one named workspace gets the identity of the tfe_outputs of that workspace
  index     the literal index of a count / for_each reference (`net["prod"]`, `net[0]`), else none
```

Rules:

- Settings are compared **exactly as written** after resolving `var.` and `local.` to literals. No path cleanup,
  no stemming, no environment words. `networking/terraform.tfstate` and `./networking/terraform.tfstate` are two
  states; that is an accepted duplicate box.
- A `config` given as one `local.` resolves to that local's object, as today. A `config` given any other way that is
  not an object literal (`var.x`, `local.x.y`, `merge(...)`) is not comparable: the address rule below applies.
- If **any** selecting setting does not resolve to a literal, the state is not comparable: its identity is the data
  source's full address including the module path and index. Modules then get separate boxes (duplicate, never merged).
- Values resolve through module calls with the strict rule: when the calls one module instance stands for pass
  different values, or one passes a value and another uses the default, the value does not resolve. This strict rule
  applies **only to state identity**. Every other caller (icons, CIDRs, Azure location and subscription, getters)
  keeps main's behaviour (the first passed value). The two behaviours are two named functions, not one function with
  a mode flag.
- An attribute path reads only its part of an object or list literal (quoted keys match unquoted; `["k"]` and `.k`
  are one key; `[0]` is a list index); a key or index the literal does not have reads nothing; an index that is no
  literal (`[each.key]`) reads the rest of the path from every element. A local or variable that reads itself gives nothing and no crash.
  A path after a value that is no single reference (`merge(local.a, local.b).vpc_id`) reads from each reference in
  it. A resource's `vpc_id` or `virtual_network_name` (`aws_subnet.a.vpc_id`) reads what that argument reads.
- An index or attribute after a remote output is part of its name, so `vpcs["blue"]` and `vpcs["green"]` of one
  state are two networks (`vpcs.blue`, `vpcs.green`: attributes and keys join with `.`). A list index stays in brackets (`vpc_ids[0]` is `vpc[0]`);
  an index that is no literal becomes `[*]`, so all keys of `vpcs[each.key]` merge into one network `vpcs[*]`
  (accepted, listed under Out of scope). A last attribute that only identifies the network (`network.vpc_id`) is no part of the name;
  `network.app_vpc_id` is `network.app-vpc`. Every cloud strips the same suffixes: `_id`, `_ids`, `_name`, `_arn`.
- The index of a module call (`module.net[0].vpc_id`, `module.net["k"].vpc_id`) is skipped: every instance of the
  module has the same outputs.
- A lookup (`data.aws_vpc.x`) is identified by its full address including the module path, as in PR #19, and a
  literal index: `data.aws_vpc.x[0]` and `data.aws_vpc.x[1]` are two networks, `x[0]` and `x[1]`. A subnet lookup whose `vpc_id`,
  `vpc-id` filter or `virtual_network_name` reads one network (of this stack, through a subnet of it, counted or not,
  a lookup or a remote output) is in that network; that network is a network fact even when no other resource names
  it. When they name no network this stack knows, the subnet is ranked by its name like a remote subnet. Its other
  selectors (`id`, tags) name no network. An attribute of a subnet lookup
  (`data.aws_subnet.x.vpc_id`) is no network.

### 3. Placing a node in a remote subnet

A subnet output (`shared_vpc_private_subnet_ids[0]`) belongs to the remote network whose name parts without indexes
start the subnet's, and whose indexes are the subnet's or none. The last network part equals the subnet's part, or
is its first words when the other words are about subnets: `vpcs.blue` never fits `vpcs.blue-east.private-subnet`.
A remote output's subnet only goes to a network of its own `State` or to a lookup network, never to a
network of another state. When several networks match, prefer, in order: a network of the subnet's own state; then
one with the subnet's indexes; then the longest name; then for a lookup, one in the same module. Two networks that
fit equally well give no placement; the resource is marked with why. A subnet name that names no network
(`private_subnet_ids`) fits every network of its own state with fitting indexes. A remote subnet with no matching
network, or whose name gives no tier, gives no placement; the resource is marked with why. Every reason is kept,
also when another subnet of the resource is placed or the resource is already marked.

### 4. Verify: the correct-box check

Replaces PR #19's `_mark_shared` and its stack logic.

- A network group **stands for** the network facts its evidence cites. It cites more than one only when they are one
  network that extract keys twice (see Out of scope); verify notes every such group so the reader can check. A network group that cites no network fact
  stands for nothing that can be checked: its nodes are not checked against it and it gets no marker. (Described
  diagrams have no facts and skip this check entirely.)
- A network group keeps only evidence that cites a network fact or code; any other item is dropped.
- `cidrs` stay a separate claim: kept only when they equal the cidrs of a cited network fact, as today. Dropping
  `cidrs` never removes the network citation. One reading of the evidence, no snapshot taken before `check_claims`.
- In a Terraform diagram, every network group must cite its network fact. Verify adds a note for one that does not
  (`group <id>: cites no network fact, its nodes cannot be checked`). The curation prompt and review rules say so
  (user decision).
- **Every node with a placement fact** inside a network group that stands for networks must have a placement fact in
  one of those networks (any tier). Nodes without any placement fact (security groups, internet gateways, gateway
  endpoints, route tables: attached to the network but to no subnet) are not checked and stay where the curator put
  them (user decision). A placed node that does not match moves to the one network group that stands for a network it
  runs in (note `...; moved to network group <home>`); when there is not exactly one, it moves out of the network group, to the nearest ancestor that is not a network
  or subnet group, with the note `<node>: placed in <network name(s)>, not in network group <group>; moved out`.
  This is the same treatment the subnet tier check already gives, and it covers both directions: a local node in an
  external box and an external node in a local box.
- The existing subnet tier check stays, in the same pass. A node it takes out of a subnet group, or one just moved to
  another network group, goes to a subnet group of a tier it runs in under that network group, else to the network
  group itself; a node without placements leaves the network.
- Network groups do not nest. A network group inside another network group moves beside it (to the parent of the
  outermost network group around it), with the note `group <id>: network inside network group <outer>, moved beside it`; it keeps its nodes.
- A node with a placement fact that sits outside every network group gets a note only (`<node>: placed in
  <network name>, drawn outside any network group`); verify does not move it in, because it cannot pick the box
  (builder check, my call).
- After the moves, a network group gets `external: true` when it stands for at least one network, every network it
  stands for is remote, and it still holds at least one node. A curated `external` is dropped with a
  note, in both modes.

### 5. Title

`group_label`: a network group with `external` gets the marker after its cidrs:
`shared-vpc (External)`, `hub (10.0.0.0/16, External)`.

### 6. What gets deleted

- `stack_names.py` and its tests (`named_after`, `names_a_stack`, stems, environment and region lists).
- `stack()`, `_state()`, `_local_stack()`, `store()` and the `Ref.stack` / `Ref.store` / `Ref.key` / `Ref.state`
  string encoding in `clouds/refs.py`, replaced by the `State` value.
- `stack` on network and placement facts; the `(via, res, stack)` third field at each placement call site.
- The account-frame warning and the "evidence cites a network of …" warnings.
- `shared_from` in the schema, verify, `group_label`, prompts, RULES.md, REVIEW.md, README and DESIGN.md, replaced by
  `external`.
- Most of the Decisions section of the PR description.

### 7. Kept from PR #19

- `Inst.value` living on `Inst` (moved from `Extractor`), with the first-value behaviour; the strict variant beside it.
- Hyphenated and indexed remote state names in the reference pattern.
- `ancestors` / `enclosing` helpers in `verify_shared.py`.
- Curation prompt guidance that an external network stays in the stack's account frame (wording updated to
  `external`), review rule 17 and the RULES.md row (updated).

## Supported inputs (what a reviewer may test)

| Input | Expected |
|---|---|
| `aws_vpc` / `azurerm_virtual_network` resource in this stack | local network, plain box |
| `data.tfe_outputs.X.values.<vpc>_id` (and `nonsensitive_values`), literal `workspace`, `organization` | external network |
| `data.terraform_remote_state.X.outputs.<vpc>_id`, any backend, literal `config` and `workspace` | external network |
| Same as above with `count` / `for_each` and a literal index | one network per index |
| `config` given inline or as one `local.` | as written |
| Settings passed through `var.` / `local.` across module calls that agree | resolved, merged across modules |
| `data.aws_vpc`, `data.azurerm_virtual_network` lookups | external network, one per module |
| Subnets from a local `aws_subnet` / `azurerm_subnet` or a remote subnet output | placement by tier as today; a remote path's tier comes only from its last name |
| A literal key or index after a local, variable or module output (`local.nets["blue"].vpc`, `local.list[0].vpc`) | that part only |
| A literal key or index after a remote output (`values.vpcs["blue"]`) | one network per key or index |

## Out of scope (not findings; must not crash)

- Settings built by interpolation (`"${var.env}/net.tfstate"`), functions or `terraform.workspace`: identity falls
  back to the data source address, module prefix included. The same holds when calls of one module instance pass
  different `tfe` providers.
- Partial backend configuration supplied outside Terraform (`-backend-config`).
- Two spellings of one state (`./a.tfstate` and `a.tfstate`): two boxes.
- A non-literal index (`net[each.key]`): identity falls back to the data source address. After a remote output
  (`vpcs[each.key]`) or on a lookup (`data.aws_vpc.x[count.index]`), all keys merge into one network.
- Several calls of one module collapsed into one instance whose identity settings differ: falls back to the address
  of that one instance. The instance stands for all its calls, its nodes are drawn once, and so is its network: one
  box for the networks of all the calls, exactly as one box for their nodes. This is not a merge of two drawn
  instances; separate instances never share a network fact.
- The lookup indirection named under Non-goals.
- A lookup that selects a network this stack creates by a literal tag or filter value
  (`values = ["main"]` matching `tags = { Name = "main" }`): it stays external. Only a reference selects.
- A lookup whose selector is one reference to a local or variable that builds a value from a network this stack
  creates (`id = local.peer_id`): only the selector text itself is checked for being one whole reference.
- A function with a literal key or index (`lookup(values.vpc_ids, "blue")`, `element(values.vpc_ids, 0)`): the
  function reads the whole output, so all keys give one network, as on `main`.

## Review against this document

Each review round gets this document's path. A finding is one of:

- a crash on any input;
- a supported input that gives a result other than the table above;
- a node left inside a network group it is not placed in, or a network wrongly marked `external`;
- two different states merged into one network fact;
- a gap or contradiction in this document.

An out-of-scope input that gives a duplicate box or no marker is not a finding. Code-quality remarks are welcome but
do not block the loop on their own.

## Delivery

New commits on PR #19 (branch `fix/shared-vpc-account`), keeping its link. The PR description is rewritten for the
new design in ASD-STE100. Cached curations go stale (facts change shape) and need one fresh curation, as the PR
already states.

## Left to the builder

- Where `State` lives (`clouds/refs.py` is the natural home) and its exact Python shape (frozen dataclass or
  NamedTuple).
- How placements carry the network for the correct-box check (the existing `placed` map is enough).
- Test layout: table-driven tests for identity and for the correct-box check replace the stack-name tests.

## Builder calls made during the build

- A remote data block that is missing from the module, or that has no selecting settings, gives the data source's full
  address as identity (separate boxes, never merged).
- `workspace = "default"` is dropped only for `terraform_remote_state`, where it is the backend default. On
  `tfe_outputs` the workspace is the state's name and stays.
- The describe prompt names a shared network after the network itself; it never names the owner.

## User decisions after the samples

- The marker is `External` with a capital letter: `Ingress VPC (External)`, `Hub VNet (10.0.0.0/16, External)`.
- A network group is named after its fact's `name` in words with a capital letter, plus `VPC` (AWS) or `VNet` (Azure).
  The curate prompt and review rule 17 say so; the tool does not rewrite the curated label.
