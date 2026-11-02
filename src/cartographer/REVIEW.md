# Visual review checklist

What Claude checks on the `cartographer snapshot` PNGs (full image and every tile) before calling a diagram ready.
One line per rule. A finding names the view, the rule, the tile and the element. The tag says how a finding is fixed:

- [curation]: edit `docs/architecture/diagrams/<name>.curated.json` (a C4 set: the `model.json` in the cache folder), then rebuild. The evidence rules in the `cartographer prompt` output still apply; never invent evidence. For a Terraform diagram the Terraform and code decide the fix. For a described diagram (`source` is `description`) change the curated file from the engineer's answers, or ask the engineer.
- [tool]: a cartographer defect. Report it with the tile it appears in; do not patch the .drawio or the curated file by hand.

Drawing rules the tool already enforces are in `RULES.md` (`cartographer docs rules` prints its path); this list is what a human eye still has to confirm on the rendered result.

## How to pick the rules

`cartographer snapshot` prints `view: <page name>` as its first line. The page name starts with the view type:

- `System Context diagram for ...`, `Container diagram for ...`, `Component diagram for ...`, `Code diagram for ...`, `Deployment diagram for ...`, `Dynamic diagram for ...`: a C4 view. Apply "Every diagram", "C4: every view" and the section named like the page.
- Anything else: an AWS Layer 7 diagram. Apply "Every diagram" and "Layer 7".

The numbers of the Layer 7 rules did not change when the list was split, so a finding can still be quoted as "rule 10".

## Every diagram

1. [curation] Every node and external has at least one visible line. Fix: add an evidenced edge, or drop the node (described diagram: ask what the node talks to). Deployment infrastructure nodes (frames that only hold other nodes) are exempt.
3. [tool] Captions are legible (RULES.md: text at least 12 px) and sit next to their own line, not on another line, icon or label. [curation] if the fix is a shorter caption (schema `maxLength` 28).
4. [tool] Labels of neighbouring icons do not collide or overlap (RULES.md: caption and label clearance).
6. [tool] No line ends at a frame border or in empty space; every line starts and ends at an icon or box.
8. [tool] Nothing is clipped at the page edge; no line, label or icon is cut off.
10. [tool] No arrow passes through an icon, caption, box or a group it does not start or end in (RULES.md routing rules).
15. [tool] No two lines overlap along a shared segment, and no two icons or boxes overlap.
16. [tool] Nothing flashy or animated: no animation, shadow, glow or gradient, and no decoration that carries no meaning.

## Layer 7

2. [curation] Every icon is a real icon: no empty box, and not the generic four-squares icon when a brand or AWS icon fits (`brand_icons.json`, `aws_icons.json`).
5. [tool] Lines in a bundle are distinguishable by colour (RULES.md: an arrow takes the colour of its destination).
7. [curation] AWS services sit inside the AWS Cloud frame; third parties (brands, SaaS, users) sit outside it (RULES.md: AWS managed services are externals with `service` set).
9. [tool] The legend matches what is drawn: colour meaning and solid versus dashed (RULES.md: line style is explained in words).
11. [curation] Every VPC-attached node (load balancer, compute, database, endpoint) sits in a subnet frame inside its VPC; regional services (S3, DynamoDB, SQS) sit outside the VPC. Fix: add the `subnet` group and move the node.
12. [curation] Workloads are visually separate: each application or service boundary has its own frame, and unrelated services do not share one. Fix: split or merge role groups.
13. [curation] No frame holds a single node only because nesting allows it. Fix: drop the frame and put the node in its parent.
14. [curation] No Availability Zone is drawn on L7: one icon per service, never one per AZ or subnet.

## C4: every view

From the c4model.com notation page and review checklist. Fix [curation] findings in `model.json`.

- C4.1 [tool] The title states the diagram type and its scope, for example "Container diagram for Shop".
- C4.2 [tool] The key explains every shape, colour, line style and arrowhead that is drawn, and nothing that is not.
- C4.3 [curation] Every element shows its name, its type and a short description.
- C4.4 [curation] Containers and components also show their technology.
- C4.5 [curation] Every arrow is one-directional and has a label. An arrow between containers also shows the technology or protocol.
- C4.6 [tool] Plain shapes only: no AWS icons, no clip art, no decoration. Sync is solid, async is dashed.
- C4.7 [curation] Abstraction levels are not mixed: nothing from another level appears on the view.

## System Context

- Context.1 [curation] Only the system, the people and the external systems appear: no containers, no components.
- Context.2 [curation] Every person and every external system has a line to the system.
- Context.3 [curation] The system is one box with a one-line description of what it is for.

## Container

- Container.1 [curation] The containers sit inside one system boundary that carries the system name.
- Container.2 [curation] The people and external systems the containers use sit outside the boundary.
- Container.3 [curation] No component appears. Every container shows its technology.

## Component

- Component.1 [curation] The components of one container sit inside a boundary that names that container.
- Component.2 [curation] Everything outside the container (other containers, people, external systems) is drawn outside the boundary.
- Component.3 [curation] Every component shows its technology and a short description of its responsibility.

## Code

- Code.1 [curation] The view exists only because the engineer agreed to Code-level diagrams. It holds the main types of one component.
- Code.2 [curation] Each type shows its name and stereotype only: no fields, no methods.
- Code.3 [tool] Association, inheritance and implementation arrows are told apart in the key.

## Deployment

- Deployment.1 [curation] Deployment nodes are nested, outermost first, and each shows its name, type and technology.
- Deployment.2 [curation] Container instances sit inside the node that runs them, and each names the container it instantiates.
- Deployment.3 [curation] The view shows one environment, named in the title.

## Dynamic

- Dynamic.1 [curation] The view shows one scenario, named in the title, with only the elements that take part.
- Dynamic.2 [tool] Every arrow label starts with its step number, and the numbers run 1, 2, 3 in order without gaps.
- Dynamic.3 [curation] Each step is one interaction between two elements with its own label.
