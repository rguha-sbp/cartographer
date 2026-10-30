You are curating an AWS architecture diagram from Terraform facts and application code.

Inputs
- Facts file: {facts_path} (JSON: resources, edges with ids like f12, services). Read it fully first.
- Repo root: {repo_root}. Terraform paths in the facts are relative to it.
- Schema file: {schema_path}. Read it: it lists every allowed field and enum value.
- Output file: {output_path}. Write one JSON object there that validates against the schema and includes
  "inputs_sha256": "{inputs_sha256}" exactly. If the file already exists, start from it and change only what the facts
  or code no longer support, so the diff stays small. Write nothing else and run no commands.
- `system` is the display name of the system (for example "GIP") and `view` is "l7". Never write a title: the tool
  derives "Layer 7 diagram for <system>". Leave `drawio_sha256` as it is when the file has one: the tool writes it.

Step 1: understand the facts
- Read {facts_path}. List resources by type and module. Note edge kinds: iam, trigger, route, network, uses.
- Read only files inside the repo root. Never guess a file path; search for it.

Step 2: read the application code
- For every compute resource (Lambda, ECS service or task, AgentCore runtime, Step Functions, Batch), find the code it runs.
  Lambda: the `filename`, `source_dir`, `s3_key` or `handler` attribute in its .tf file; follow it to the source folder.
  Agent runtimes and containers: the build context, Dockerfile, or entrypoint named in the .tf file or module.
- Read the entrypoints and the modules they call. Note which AWS services, databases, queues, buckets, secrets and
  external HTTP APIs the code calls, and from which line.

Step 3: produce the curated JSON
- Nodes: aim for 40 to 90. Each node cites at least one real `tf` address copied exactly from facts.json resources.
  Never invent or alter an address. If no address exists, it is not a node (see externals).
- Collapse support resources into their owner: IAM policies and attachments, log groups, versions, aliases,
  encryption configs, public access blocks, lifecycle rules. Put all their addresses in the owner's `tf` list
  only when they truly belong to it.
- One node per module instance family when the resources are `multi` (count or for_each); set `multi` true.
- `service`: the draw.io AWS icon name for the resource (the schema lists them), for example lambda, dynamodb, s3, sqs,
  key_management_service, or `other` for a SaaS or non-AWS system, which renders as a plain box.
  A node with `service` `other` (a Datadog monitor, a SaaS resource) sets `icon` to the generic or brand shape that fits it, from the same list as external icons, so it is drawn as that icon instead of a box.
- Externals: systems outside AWS or outside the Terraform (Okta, Slack, GitHub, Jira, browsers, users). Cite evidence
  (a code line or a facts edge) that proves the system is used. Externals have no `tf` and no group: they always
  sit in lanes beside the AWS frames, so never create a group just for them.
- Hints: facts.json has a `hints` array (kind host, param or module: external hostnames, SSM or Secrets Manager names
  and integration folders such as integrations/okta, found in the code Terraform deploys), with `hints_cut`
  counting what was dropped per kind. Every distinct external system a hint suggests must be drawn as an external whose
  evidence is a code citation (file, line, contains) naming the hint value, or be listed in `omitted` as
  {"hint": <hint id or value>, "reason": <at most 80 characters>}. Several hints for one system (its host, its
  parameter and its folder) need one external. AWS's own hosts (amazonaws.com) are not externals. Read the hinted file
  and line before deciding; verify reports every hint that is neither cited nor omitted.
- An AWS managed service the stack calls but Terraform does not create (Bedrock foundation models, a shared
  service in another account) is an external with `service` set to its draw.io AWS icon name; third-party systems
  leave `service` unset.
- External `icon`: a generic or brand draw.io shape from the schema enum. When the external is that product, use its
  brand icon (github, okta, jira, confluence, atlassian, statuspage) instead of a generic one. People get `users` (or `user` for one person),
  browsers and apps `client` (`mobile_client` for phones), SaaS and remote APIs `internet` or `generic_application`,
  on-prem systems `corporate_data_center`, anything else `none` (a plain box).
- Groups: organise by architectural role, for example edge, identity, APIs, triggers, data, AI services, VPC.
  Nest them inside frames: one group of kind `cloud` (AWS Cloud), inside it `region`, inside it
  `account`; the role groups have `parent` set to the account (or to a `vpc` group when they sit in the VPC).
  Use kind `vpc` for the VPC frame and kind `subnet` for a subnet tier frame. Role groups use kind null. Every group id is unique; parents must exist.
  Every group has an integer `column` (0 to 3) that places role groups left to right in request order, for example
  0 = entry (DNS, CDN, WAF, load balancers, identity, event sources), 1 = APIs and front compute (Lambda, containers,
  agent runtimes such as AgentCore), 2 = data stores, queues and pipelines, 3 = back-end services, ML or analytics,
  and shared platform services. Use up to 4 columns (0 to 3). Balance the columns so none is much taller than the others,
  and order groups top to bottom within a column in list order. Frames (cloud, region, account) set column 0, and
  it is ignored. A group nested in another role group or in a vpc group gets its parent's column.
- Network nesting: facts.json has `vpcs` (id like v1, name, cidrs, remote) and `placements` (id like p1, a resource,
  its vpc fact id and tier public, private or isolated). Put each VPC-attached node in a `subnet` group with that
  `tier`, whose parent is its `vpc` group (one subnet group per tier that holds a node, label "Public subnets",
  "Private subnets" or "Isolated subnets"). The subnet group cites a placement fact of that tier in `evidence`, and
  a node stays in it only when a placement fact of that tier exists for one of its `tf` addresses. Give a `vpc` group
  `cidrs` only copied from a `vpcs` fact (the same list), and cite that fact in the group's `evidence`; with no
  cidrs in the fact, leave `cidrs` out. A vpc group that comes from a remote fact is named after it, without cidrs.
- Workloads: propose role groups (kind null) from the Terraform module or root a resource lives in, named for what
  the workload does ("Order processing", not the module name). A workload that has VPC-attached nodes sits inside
  the subnet group of their tier. Regional services (S3, DynamoDB, SQS, Bedrock) have no subnet: put them in a
  workload group directly under the account. A workload spanning both gets one group per place with the same label.
- Labels: short name, then a newline, then a 2 to 4 word role, for example "sessions API\nchat history".
  Plain ASCII only. No em dashes, en dashes, or smart quotes. Use a comma or colon instead.
- Title: one line naming the system and "AWS architecture".

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
