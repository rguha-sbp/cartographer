# Describe mode playbook

How Claude gets a cloud engineer from "I have a design" to a complete, reviewed Layer 7 diagram when there is no
Terraform to read. The diagram ends up in official documents, so it must be correct and look finished.

## 1. Opening

- If the repo has `infra/`, `terraform/` or another Terraform folder, ask once: draw from it, or describe a new
  solution? Terraform means the Terraform flow in SKILL.md; stop using this playbook.
- Otherwise start describing. Accept a description, a prompt or a file (ADR, `design.md`, notes). Read any file or
  pasted text fully before asking anything. Never ask what a supplied document already answers.

## 2. Interview rules

- One question per message, one sentence, no list of example answers.
- Open questions first, in the engineer's own words: "Walk me through what happens when a user does the main thing."
- Then targeted questions, one open decision at a time. Each carries your recommended answer:
  "I'd put API Gateway in front of the Lambda; does that match?"
- Read the repo or the supplied file instead of asking when it can answer.
- No leading questions. Vary the wording of "why": "What made you pick X?", "What would break without X?", "What
  does X buy you over Y?"

## 3. First drawing early

After one or two open answers, write a rough draft to the curated path (the prompt output names it), run
`cartographer build`, then `cartographer view` to open it in the local draw.io. A drawing brings out "no, that is
wrong" faster than a question. From then on alternate: one question, redraw, one question, redraw. Every draft must
pass `build` (structurally valid, every node connected), so keep drafts small and complete rather than half-written.

## 4. Gap checklist (Layer 7)

Adapted from the C4 diagram review checklist (c4model.com/diagrams/checklist). Before each question, check the
current diagram against it:

- Cloud: which cloud or clouds the solution runs on (AWS, Azure or both). Ask it first when the engineer has not said.
- Elements: each has a name, a cloud service (sets the icon) or a named external system, and a purpose.
- Arrows: each has a direction, a label stating its intent, sync or async (solid or dashed), and the protocol where it
  matters.
- Entry points: who or what calls into the system, and through what.
- Where data lives: every store and what it holds.
- Workloads: how the solution splits into applications or services (one targeted question, with your recommended
  split). Each workload becomes its own frame, so separate workloads read as separate.
- Network placement: which services run in a VPC or virtual network and in which subnet tier (public, private, isolated). When the
  engineer does not say, default to gateways and public load balancers public, compute and data private, and record each default in
  `assumptions`. Ask for a CIDR only if the engineer brings one up; draw a CIDR only when stated, never guess one.
- Outside the cloud: third-party and on-premises systems, and the account or subscription and network boundaries.
- Identity and auth: how callers and services prove who they are.

Rank the gaps by how badly each would mislead the diagram: wrong or missing boxes and arrows first, labels and
protocols last. Ask at most about 8 targeted questions in total. Settle everything still open with your best guess.

## 5. No visible assumptions

- Never mark anything as assumed, draft, TBD or unverified on the diagram: no label text, styling, block or footer.
- Draw each best guess like any other fact. Record it in the curated file under `assumptions`
  (`{"about": <id or src->dst>, "guess": <what you chose>}`). Assumptions are never rendered.
- Evidence still applies: `stated` is a short paraphrase of what the engineer said, `file` is
  `{file, line, contains}` from a supplied document. Never invent evidence; a guess hangs on the nearest thing the
  engineer actually said.

## 6. Finishing

1. Run the visual review loop: `cartographer snapshot`, read the full image and every tile, check against
   `cartographer docs review` (REVIEW.md), fix [curation] findings in the curated file from the engineer's answers or
   by asking them, rebuild. Repeat until a round has no findings, at most 3 rounds.
2. Run `cartographer check docs/architecture/diagrams`.
3. Tell the engineer which files to commit, and list every entry of `assumptions` in chat, one line each
   ("Payments go through a queue: I guessed this"), so they can correct anything before the diagram is published.
4. Never say the diagram is ready while a review finding is open.

## 7. C4 set

Use this section when the engineer chose a C4 set at step 0 of SKILL.md. Sections 1 to 3 and 5 to 6 apply as written,
with `model.json` instead of the curated file and `cartographer build --c4` instead of `build`. The diagrams end up in
official documents, so the same care applies. Where section 4 or 5 says to settle a gap with a best guess, in a C4
set you ask first and guess only when the engineer cannot answer.

### Question rule

Every question names the level, what you need and why you need it. For example: "For the Container diagram I need to
know what runs the nightly import and where it stores its result, so the diagram does not hide a deployable unit. Which
service does that?" One question per message. Read the repo first and ask only what it cannot answer.

### C4 gap checklist

Before each question, check the model against the level it feeds. When the repo does not answer something C4 needs,
ask the engineer first, as the question rule says. Record an assumption only when the engineer cannot answer, and
never mark it on the diagram.

- Context: the people and their roles; every external system the system talks to; one sentence on what the system is
  for.
- Container: every deployable unit and every data store, including the ones the code does not reveal (queues, caches,
  scheduled jobs); the technology of each; who calls whom and over which protocol.
- Component: the internal parts of one container when the code is missing or unclear; each part's responsibility and
  technology. Ask which containers to open up, offering the main application container first even when its code is
  not in the repo; never pick only the containers whose code is easy to read.
- Deployment: the environments (production, staging); the nesting of the deployment nodes (account, region, cluster,
  host); which container runs on which node and how many instances.
- Dynamic: the scenarios worth showing, and the order of the calls in each.

### Code level needs consent

C4 treats the Code level as optional. Ask once, before any Code work: "C4 makes Code diagrams optional. They show the
main types of one component and go stale fast. Do you want them?" Only on a yes: propose the 1 to 3 most important
components and let the engineer pick. A Code view shows type names and stereotypes only, and every type and arrow cites
`file`, `line` and `contains`. On a no, the model has no `code` elements and no Code view is built.
