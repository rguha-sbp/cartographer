# Describe mode playbook

How Claude gets an AWS engineer from "I have a design" to a complete, reviewed Layer 7 diagram when there is no
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

- Elements: each has a name, an AWS service (sets the icon) or a named external system, and a purpose.
- Arrows: each has a direction, a label stating its intent, sync or async (solid or dashed), and the protocol where it
  matters.
- Entry points: who or what calls into the system, and through what.
- Where data lives: every store and what it holds.
- Outside AWS: third-party and on-premises systems, and the account and VPC boundaries.
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
