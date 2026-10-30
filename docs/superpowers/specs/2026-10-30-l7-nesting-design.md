# L7 nesting: VPC details, subnet tiers and workload frames

Date: 2026-10-30. Status: draft for the owner's approval.

## Intent

An L7 diagram today nests AWS Cloud > region > account > VPC, then flat role groups ("Edge", "Data stores"). Readers
cannot see the VPC's address range, which services run in public or private subnets, or which services belong to
which workload. A network (L3) diagram the owner showed as a reference for clarity gets this right by strict
nesting with the CIDR in every frame label. L7 should borrow that nesting, cut at a coarser level, so separate
workloads read as separate even inside one account or VPC.

## Goals

1. **VPC frame labels carry name and CIDR(s)**, for example `shared-vpc (10.22.0.0/16, 10.97.16.0/20)`.
   - Terraform flow: only when the VPC and its CIDRs are in the Terraform being drawn (`aws_vpc.cidr_block`,
     `aws_vpc_ipv4_cidr_block_association`, literal or resolvable through locals and variable defaults). A VPC that
     comes from another stack (remote state, `tfe_outputs`, a data source) gets its name from the reference
     (`shared_vpc_id` -> `shared-vpc`) and no CIDR.
   - Describe mode: a CIDR only when the engineer stated one. Never guessed: an invented address plan in an official
     document is worse than none.
2. **Subnet tier frames inside a VPC**: `public`, `private`, `isolated`, one frame per tier that holds a node, label
   "Public subnets", "Private subnets", "Isolated subnets". Availability Zones are not drawn on L7.
   - Terraform flow: a node's tier comes from the subnets it is attached to (`subnet_ids`, `subnet_id`,
     `vpc_config.subnet_ids`, `network_configuration.subnets`, also through module variables): the subnet's
     `map_public_ip_on_launch`, its route to an internet gateway, or its name or tags, or for a remote reference the
     output name (`shared_vpc_private_subnet_ids` -> private). The extract records this as a fact; curation cites it.
   - Describe mode: from what the engineer said, else the usual default (load balancers public, compute and data
     private), recorded in `assumptions`.
3. **Workload frames**: a workload is an application or service boundary. Its frame sits inside the tier frame where
   its VPC-attached services run, and directly under the account for its regional services (S3, DynamoDB, Bedrock,
   SQS). A workload that spans a tier and regional services gets one frame per place, with the same label and
   colour, so ownership stays readable. Workloads in separate VPCs or accounts nest under those frames the same way:
   no special case.
   - Terraform flow: proposed from the Terraform module or root a resource lives in; curation names, merges or splits
     them.
   - Describe mode: the interview asks how the solution splits into workloads (one targeted question in the gap
     checklist).
4. **Drawing rules unchanged**: captions, arrows around icons, group boxes passed over or under, A4 fit, and the
   review loop all apply to the new frames. Nesting depth is bounded: cloud > region > account > VPC > tier > workload.

## Non-goals

- Availability Zones, subnet CIDRs, route tables, transit gateway and RAM shares: those belong to the separate L3
  view, designed after this one.
- The on-demand draw.io editor: parked for more thought. The desktop app is ruled out (security review) and Docker is
  too heavy. `view` keeps the read-only lightbox.

## Anti-goals

- A CIDR, tier or workload on the diagram that neither the Terraform nor the engineer supports (tier defaults in
  describe mode are the exception, recorded as assumptions and never marked on the diagram).
- Empty frames, or a frame holding a single node only because the model allows it.
- An L7 that turns into an L3: one icon per service, never one per AZ or subnet.

## Constraints

As in the describe-mode design: no new dependency, the tool never calls an LLM, modules under 300 lines, TDD, no em
dashes in user-facing text, `main` changes through a PR.

## Decided by the owner

- VPC details on L7 now; L3 as its own view afterwards.
- Separate nesting on L7 for separate workloads.
- No on-demand editor in this change; lightbox stays (`view` also prints that it is read-only).

## Builder's calls (open to correction)

- **Schema**: group `kind` gains `subnet`, with `tier` (`public` | `private` | `isolated`); its `parent` is a `vpc`.
  A `vpc` group gains optional `cidrs` (list). Both carry `evidence` (same arms as edges). Workload frames are the
  existing role groups (`kind: null`): no new kind, a workload is simply a role group whose parent is a `subnet` group
  or the `account`.
- **Extract** gains two fact lists: `vpcs` (address or remote reference, name, cidrs, remote flag) and `placements`
  (resource, vpc, tier, what the tier came from). No subnet ids or AZs are recorded.
- **Verify** (Terraform flow) checks a `vpc` group's `cidrs` against the `vpcs` fact it cites, and that every node
  inside a `subnet` group has a `placements` fact with that tier. Describe mode requires `stated` or `file` evidence
  for `cidrs` and for a subnet tier.
- **Colour**: the palette goes to the outermost role groups (workloads); `vpc` and `subnet` frames use the AWS
  frame colours and pass no colour down.
- **Layout**: subnet and workload frames reuse the existing block packing (`tf_blocks`), which already nests blocks.
- **`view`** prints "Read-only view. To edit, open the .drawio in your local draw.io (never a public host) and run `cartographer image` after." until
  the editor question is settled.
- Version 0.3.0, plugin pin and SKILL.md updated, tag after merge.

## Left to the builder

Module boundaries, how module variables are followed to find a node's subnets, test fixtures.
