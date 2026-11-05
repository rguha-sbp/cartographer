You are curating a cloud architecture diagram (AWS, Azure or both) from Terraform facts and application code.

Inputs
- Facts file: {facts_path} (JSON: resources, edges with ids like f12, networks, placements, services). Read it fully first.
- Repo root: {repo_root}. Terraform paths in the facts are relative to it.
- Schema file: {schema_path}. Read it: it lists every allowed field. It has no list of icons: find names with `cartographer icons`.
- Output file: {output_path}. Write one JSON object there that validates against the schema and includes
  "inputs_sha256": "{inputs_sha256}" exactly. If the file already exists, start from it and change only what the facts
  or code no longer support, so the diff stays small. Write nothing else and run no commands except `cartographer icons`.
- `format` is 2. `system` is the display name of the system (for example "GIP") and `view` is "l7". Never write a title: the tool
  derives "Layer 7 diagram for <system>". Leave `drawio_sha256` as it is when the file has one: the tool writes it.

Step 1: understand the facts
- Read {facts_path}. List resources by type and module. Note edge kinds: iam, trigger, route, network, uses. Each resource carries `cloud` and, when the catalog
  resolved it, `icon` (qualified, for example aws:lambda or azure:key_vault) or `fold`; `marked` resources have a `reason`
  and `decided_by` says what chose the icon; `global` marks a service that sits outside any region.
- Read only files inside the repo root. Never guess a file path; search for it.

Step 2: read the application code
- For every compute resource (Lambda, ECS service or task, AgentCore runtime, Step Functions, Batch), find the code it runs.
  Lambda: the `filename`, `source_dir`, `s3_key` or `handler` attribute in its .tf file; follow it to the source folder.
  Agent runtimes and containers: the build context, Dockerfile, or entrypoint named in the .tf file or module.
- Read the entrypoints and the modules they call. Note which cloud services, databases, queues, buckets, secrets and
  external HTTP APIs the code calls, and from which line.

Step 3: produce the curated JSON
- Nodes: aim for 40 to 90. Each node cites at least one real `tf` address copied exactly from facts.json resources.
  Never invent or alter an address. If no address exists, it is not a node (see externals).
- Collapse support resources into their owner: IAM policies and attachments, log groups, versions, aliases,
  encryption configs, public access blocks, lifecycle rules. Put all their addresses in the owner's `tf` list
  only when they truly belong to it.
- One node per module instance family when the resources are `multi` (count or for_each); set `multi` true.
- Icons come from the facts: a node whose `tf` resources have an `icon` gets it from the tool, so leave the node's
  `icon` unset. Set a node's `icon` (qualified, for example `generic:internet` or `brand:github`) only when none of its
  resources has one (a non-cloud provider such as Datadog). Find names with `cartographer icons --cloud <aws|azure|generic|brand> --search <words>`
  (at most 20 results); never guess a name. A `marked` resource keeps its icon, and a wrong one is fixed later by an override, not here.
- `fold` resources (associations, policies, diagnostic settings, NICs and the like) are merged into their owner node:
  put their addresses in the owner's `tf`. They never become nodes of their own.
- Externals: systems outside the cloud or outside the Terraform (Okta, Slack, GitHub, Jira, browsers, users). Cite evidence
  (a code line or a facts edge) that proves the system is used. Externals have no `tf` and no group: they always
  sit in lanes beside the cloud frames, so never create a group just for them.
- Hints: facts.json has a `hints` array (kind host, param or module: external hostnames, SSM or Secrets Manager names
  and integration folders such as integrations/okta, found in the code Terraform deploys), with `hints_cut`
  counting what was dropped per kind. Every distinct external system a hint suggests must be drawn as an external whose
  evidence is a code citation (file, line, contains) naming the hint value, or be listed in `omitted` as
  {"hint": <hint id or value>, "reason": <at most 80 characters>}. Several hints for one system (its host, its
  parameter and its folder) need one external. A cloud's own hosts (amazonaws.com, azure.com, windows.net, azure.net) are not externals and are never hinted. Read the hinted file
  and line before deciding; verify reports every hint that is neither cited nor omitted.
- A cloud managed service the stack calls but Terraform does not create (Bedrock foundation models, Azure OpenAI in
  another subscription, a shared service in another account) is an external with `tf_type` set to the
  Terraform type that stands for it, plus `attributes` when the type needs them to choose its icon (for example
  `{"kind": "OpenAI"}`). The tool resolves the icon and draws it in that cloud's managed services block (an
  external whose `icon` is a qualified cloud icon such as `aws:bedrock` lands there too). Third-party systems set `icon`
  to a `brand:` or `generic:` name.
- External `icon`: when the external is that product use its brand icon (`brand:github`, `brand:okta`, `brand:jira`,
  `brand:confluence`, `brand:atlassian`, `brand:statuspage`). People get `generic:users` (or `generic:user` for one person),
  browsers and apps `generic:client` (`generic:mobile_client` for phones), SaaS and remote APIs `generic:internet` or
  `generic:generic_application`, on-prem systems `generic:corporate_data_center`, anything else `none` (a plain box).
- Groups: organise by architectural role, for example edge, identity, APIs, triggers, data, AI services, network.
  Nest them inside frames. Every frame group (kind `cloud`, `region`, `account`, `network`, `subnet`) carries `cloud`
  (`aws` or `azure`). Draw one top-level `cloud` frame per cloud present, each with its own `region` inside it and
  `account` inside that (an Azure subscription is the `account`). The role groups have `parent` set to the account (or to
  a `network` group when they sit in the network). Use kind `network` for the VPC or virtual network frame and kind
  `subnet` for a subnet tier frame. Role groups use kind null and no `cloud`. Every group id is unique; parents must exist.
  Resource groups are never drawn. Global services (resources with `global` true: CloudFront, Front Door, Traffic
  Manager, public DNS) sit outside the region frame, directly in their cloud frame. Never put a node in a frame of another cloud.
  Every group has an integer `column` (0 to 3) that places role groups left to right in request order, for example
  0 = entry (DNS, CDN, WAF, load balancers, identity, event sources), 1 = APIs and front compute (Lambda, containers,
  agent runtimes such as AgentCore), 2 = data stores, queues and pipelines, 3 = back-end services, ML or analytics,
  and shared platform services. Use up to 4 columns (0 to 3). Balance the columns so none is much taller than the others,
  and order groups top to bottom within a column in list order. Frames (cloud, region, account) set column 0, and
  it is ignored. A group nested in another role group or in a network group gets its parent's column.
- Network nesting: facts.json has `networks` (id like n1, `cloud`, name, cidrs, remote, stack) and `placements` (id like p1, a
  resource, its network fact id and tier public, private or isolated). Put each network-attached node in a `subnet`
  group with that `tier`, whose parent is its `network` group (one subnet group per tier that holds a node, label "Public
  subnets", "Private subnets" or "Isolated subnets"). The subnet group cites a placement fact of that tier in `evidence`,
  and a node stays in it only when a placement fact of that tier exists for one of its `tf` addresses. Give a `network`
  group `cidrs` only copied from a `networks` fact (the same list), and cite that fact in the group's `evidence`; with no
  cidrs in the fact, leave `cidrs` out. A network group that comes from a remote fact is named after it, without cidrs.
- Shared networks: a `networks` fact with `remote` true is a VPC this stack does not create. Often another account
  owns it and shares it (AWS VPC sharing), but it can also be a VPC of the same account that another stack creates.
  The stack's resources in its subnets still belong to the stack's account. Put its `network` group inside the
  stack's account frame, never in an account frame of its own. Cite the remote fact in
  the group's `evidence`. The tool adds the stack it comes from to the frame title (for example `shared-vpc (shared
  from networking)`). Never name the owning account or stack in any group label.
- Azure placement: a Function or Web App with VNet integration (`virtual_network_subnet_id`) stays outside the subnets
  and draws an outbound arrow to the integration subnet. A private endpoint sits in its subnet with an arrow to the
  service it exposes, and that service stays in the region outside the subnets. PaaS services without a subnet fact
  (Storage, Key Vault, Cosmos DB, Service Bus) sit in the region, never in a subnet.
- Workloads: propose role groups (kind null) from the Terraform module or root a resource lives in, named for what
  the workload does ("Order processing", not the module name). A workload that has network-attached nodes sits inside
  the subnet group of their tier. Regional services (S3, DynamoDB, SQS, Bedrock, Azure Storage, Key Vault) have no subnet: put them in a
  workload group directly under the account. A workload spanning both gets one group per place with the same label.
- Labels: short name, then a newline, then a 2 to 4 word role, for example "sessions API\nchat history".
  Plain ASCII only. No em dashes, en dashes, or smart quotes. Use a comma or colon instead.

Step 4: edges
- Each edge is a real runtime or deployment relationship between two shown nodes or externals (use node/external ids).
- Every edge needs at least one evidence item. Two forms only:
  {"fact": "f12"}: an edge id from facts.json whose src and dst are tf addresses of the two nodes.
  {"file": "src/x/y.py", "line": 88, "contains": ".query("}: the call site in the repo. `file` is relative to the
  repo root, `line` is 1-based, `contains` is a short literal substring copied from that exact line (or within 3
  lines of it). Check by reading the file; never cite a line you have not seen.
- Data-flow arrows (a Lambda reading a table, an agent calling a model, a handler posting to Slack) come from the
  application code and must cite the call site. Permissions-only facts (iam) are weaker: include them when the
  code confirms the call or the fact is the only evidence for a structural link (trigger, route).
- Direction follows the request or data, never the Terraform reference: a Terraform attribute on A that
  names B does not mean A calls B. Traffic passes WAF before CloudFront (waf -> cloudfront); an event source
  feeds its rule (bucket -> rule -> queue); a caller points at what it calls.
- Prefer fewer, true edges over many guessed ones. If you cannot cite it, leave it out.
- Aim for at most about 45 edges. Keep the primary request and data paths. Leave out plumbing that every compute node
  has: logging, a shared KMS key, config and parameter reads. Mention those once in a group label (for example
  "Platform APIs\nall log to CloudWatch") or in a single representative edge, never one edge per node.
- Every node and external has at least one edge. Plumbing every compute uses (log groups, a shared KMS key) gets one
  edge from the most important caller with a short label, or is left out of the diagram. Never draw an unconnected node.
- Every group must hold at least one node (directly or in a child group); the layout drops empty groups.
- `flow`: web = user or browser traffic and API requests; trigger = events, schedules, queues;
  runtime = agent or service calls at run time (models, tools, sub-agents); credential = identity, tokens, secrets,
  keys; data = storage reads and writes.
- `label`: a specific verb plus the protocol where the code or Terraform shows it, at most 28 characters, for example
  "invokes, HTTPS" or "reads, SQL". Never "uses", "calls" or "connects" alone. Captions share the canvas, so keep
  them short. `dashed` true only for secondary, optional, control, asynchronous or fallback paths; the solid line is
  the primary request path.
- `omitted` is required; use an empty array when every hint is drawn.
- Do not output fields outside the schema.

Before finishing, re-check: every `tf` address exists in facts.json, every edge endpoint is a node or external id,
every group parent exists, every citation was read by you, no dash punctuation in labels.
