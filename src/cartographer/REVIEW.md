# Visual review checklist

What Claude checks on the `cartographer snapshot` PNGs (full image and every tile) before calling a diagram ready.
One line per rule. The tag says how a finding is fixed:

- [curation]: edit `docs/architecture/<stack>.curated.json`, then rebuild. The evidence rules in the `cartographer prompt` output still apply; never invent evidence.
- [tool]: a cartographer defect. Report it with the tile it appears in; do not patch the .drawio or the curated file by hand.

Drawing rules the tool already enforces are in `RULES.md` (`cartographer docs rules` prints its path); this list is what a human eye still has to confirm on the rendered result.

1. [curation] Every node and external has at least one visible line. Fix: add an evidenced edge, or drop the node.
2. [curation] Every icon is a real icon: no empty box, and not the generic four-squares icon when a brand or AWS icon fits (`brand_icons.json`, `aws_icons.json`).
3. [tool] Captions are legible (RULES.md: text at least 12 px) and sit next to their own line, not on another line, icon or label. [curation] if the fix is a shorter caption (schema `maxLength` 28).
4. [tool] Labels of neighbouring icons do not collide or overlap (RULES.md: caption and label clearance).
5. [tool] Lines in a bundle are distinguishable by colour (RULES.md: an arrow takes the colour of its destination).
6. [tool] No line ends at a frame border or in empty space; every line starts and ends at an icon or box.
7. [curation] AWS services sit inside the AWS Cloud frame; third parties (brands, SaaS, users) sit outside it (RULES.md: AWS managed services are externals with `service` set).
8. [tool] Nothing is clipped at the page edge; no line, label or icon is cut off.
9. [tool] The legend matches what is drawn: colour meaning and solid versus dashed (RULES.md: line style is explained in words).
10. [tool] No arrow passes through an icon, caption, box or a group it does not start or end in (RULES.md routing rules).
