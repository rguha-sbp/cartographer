# Drawing rules

Each rule, where it is enforced, and where it comes from.

| Rule | Enforced by | Source |
|---|---|---|
| An arrow never passes through an icon, its caption or a box | `tf_check` edge through node; `tf_route` walls | libavoid/ELK routing principles |
| An arrow never passes through a group it does not start or end in | `tf_check` edge through group; `tf_route` group walls | AWS networking best-practices conventions |
| An arrow never crosses a group title | `tf_check` edge through title; `tf_route` title walls (`tf_geom` title_rect) | AWS networking best-practices conventions |
| An arrow running beside a group or frame border keeps LINE_GAP (12 px) from it; crossing it at a right angle is fine | `tf_check` line on frame; `tf_grid` border strips | libavoid/ELK routing principles |
| Arrows are never angled: every segment, stubs at the ports included, is horizontal or vertical | `tf_check` angled segments; `tf_route` explicit points on every edge; ports on whole pixels with `exitPerimeter=0;entryPerimeter=0` (`gen_drawio`) | libavoid/ELK routing principles |
| Parallel segments of different arrows are at least LINE_GAP (12 px) apart | `tf_check` lines too close; `tf_grid` tracks at LINE_GAP, near-parallel segments blocked | libavoid/ELK routing principles |
| Ports on one side are at least PORT_GAP (12 px) apart and PORT_EDGE (8 px) from the corners; a side holds at most floor((side - 16) / 12) + 1 ports, the overflow moves to another side | `tf_check` ports too close; `tf_ports` | Purchase graph readability studies |
| Ports use all four sides: default is the side facing the other end, then balanced; an icon and its label are one unit (bottom ports sit under the label); ports of one colour sit together | `tf_ports` | Purchase graph readability studies |
| An arrow keeps NODE_CLEAR (10 px) from every icon, label zone or box it does not end at (the final stub is exempt) | `tf_check` line near node; `tf_route` obstacles inflated by NODE_CLEAR | libavoid/ELK routing principles |
| A caption keeps CAPTION_CLEAR (6 px) from icons, label zones, other captions, other arrows and group borders, and its centre lies within half its height + CAPTION_NEAR (6 px) of its own line | `tf_check` caption crowding, caption far; `tf_labels`, `tf_space` | Purchase graph readability studies |
| Label sizes are true: icon label = longest line x 7.5 + 8 wide, lines x 16 + 6 high; caption = longest line x 7.5 + 8 wide, 20 per line | `tf_geom` label_size, caption_size | AWS Architecture Icons guidance |
| Where a gap is too short for its lines, the diagram is widened by tracks x 12 + 2 x NODE_CLEAR (at most 3 rounds) | `tf_space` | Purchase graph readability studies |
| A caption's position is draw.io's `mxGraphView.getPoint` of `at`, plus a small perpendicular nudge; one function for placing and checking | `tf_geom` point_at | draw.io |
| An arrow takes the colour of its destination group (or external); the group border has the same colour | `tf_colors`; legend `tf_layout` | C4 model notation |
| AWS managed services Terraform does not create are externals with `service` set, drawn in "AWS managed services" inside the region | `tf_aws_externals` | AWS Architecture Icons |
| Brand logos (GitHub, Okta, Atlassian family) come from draw.io's own libraries | `brand_icons.json`, `gen_drawio` | draw.io |
| Fewest crossings, then fewest bends, then shortest | `tf_check` crossings and bends; `tf_grid` cost order | Purchase graph readability studies |
| Nodes, blocks and externals are ordered so their lines cross least; a block with an open column (AWS managed services) sits by its callers | `tf_place`; `tf_layout` picks the placement with the fewest routed defects | Purchase graph readability studies |
| A caption never overlaps an icon, box, group title, group border, other caption or other arrow | `tf_check` caption overlaps, on node, on line; `tf_labels` | Purchase graph readability studies |
| Arrows are drawn exactly as routed (no connector re-routing) | renderer style (`Edge.exact`); `tf_check` reads the file | libavoid/ELK routing principles |
| Text is at least 12 px, strokes at least 1 pt | renderer style (`gen_drawio`) | AWS Architecture Icons guidance |
| Arrowheads are open | renderer style (`gen_drawio`) | C4 model notation |
| Line style is explained in words (solid primary, dashed secondary) | legend (`tf_layout`) | C4 model notation |
| Captions are a specific verb plus protocol where known, never "uses" | curation prompt (`curate_prompt.md`, schema `maxLength` 28) | C4 model notation |
| Official AWS icons and group frames (cloud, region, account, VPC) | renderer (`gen_drawio`, `aws_icons.json`) | AWS Architecture Icons |
| Layout fits A4 landscape | `tf_layout` grid choice | AWS networking best-practices conventions |
