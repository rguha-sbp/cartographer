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
| Managed services Terraform does not create are externals with a cloud `tf_type`, drawn in "<Cloud> managed services" inside that cloud's region | `tf_externals` | AWS and Azure Architecture Icons |
| Brand logos (GitHub, Okta, Atlassian family) come from draw.io's own libraries | `brand_icons.json`, `gen_drawio` | draw.io |
| Fewest crossings, then fewest bends, then shortest | `tf_check` crossings and bends; `tf_grid` cost order | Purchase graph readability studies |
| Nodes, blocks and externals are ordered so their lines cross least; a block with an open column (managed services) sits by its callers | `tf_place`; `tf_layout` picks the placement with the fewest routed defects | Purchase graph readability studies |
| A caption never overlaps an icon, box, group title, group border, other caption or other arrow | `tf_check` caption overlaps, on node, on line; `tf_labels` | Purchase graph readability studies |
| Arrows are drawn exactly as routed (no connector re-routing) | renderer style (`Edge.exact`); `tf_check` reads the file | libavoid/ELK routing principles |
| Text is at least 12 px, strokes at least 1 pt | renderer style (`gen_drawio`) | AWS Architecture Icons guidance |
| Arrowheads are open | renderer style (`gen_drawio`) | C4 model notation |
| Line style is explained in words (solid primary, dashed secondary) | legend (`tf_layout`) | C4 model notation |
| Captions are a specific verb plus protocol where known, never "uses" | curation prompt (`curate_prompt.md`, schema `maxLength` 28) | C4 model notation |
| Official icons and group frames (cloud, region, account or subscription, VPC or virtual network, subnet tier), one top-level frame per cloud | renderer (`gen_drawio`, `clouds/<cloud>/icons.json`) | AWS and Azure Architecture Icons |
| An icon comes from the catalog, never from the curation, unless no resource of the node resolves to one; a reviewed fix is an override in `icons.json` | `clouds/<cloud>/catalog.json`, `overrides.py` | Cartographer design |
| Layout fits A4 landscape | `tf_layout` grid choice | AWS networking best-practices conventions |
| C4: the page name and the title state the view type and scope ("Container diagram for S") | `c4_views` | C4 model notation |
| C4: the key explains every shape, colour, line style and arrowhead drawn | `c4_views` legend, `c4_styles` | C4 model notation |
| C4: every element shows name, type and description; containers and components show technology | `c4_verify` required fields; `c4_boxes` text blocks | C4 model notation |
| C4: every relationship is one arrow with a label; between containers it names the technology or protocol | `c4_verify` | C4 model notation |
| C4: Context holds the system, people and external systems only; levels are never mixed | `c4_verify`, `c4_views` | C4 model notation |
| C4: containers sit in a system boundary; a Component view draws everything outside its container outside the boundary | `c4_views` | C4 model notation |
| C4: plain shapes in the standard palette, no cloud icons (Deployment keeps cloud frames and icons for its infrastructure), solid sync and dashed async | `c4_styles`, `c4_deploy` | C4 model notation |
| C4: Code views hold type name and stereotype only, and exist only with the engineer's consent | `c4_verify` (no `code` elements without consent), `c4_views` | C4 model notation |
| C4: Dynamic arrows carry their step number | `c4_views` | C4 model notation |
| C4: every C4 view obeys the line, icon and caption rules above; nothing flashy or animated | `tf_check`, `tf_route`, `c4_styles` | libavoid/ELK routing principles |
