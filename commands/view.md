---
description: Reopen an architecture diagram in the local draw.io editor
argument-hint: [diagram-name]
allowed-tools: Bash
---

Reopen a diagram in the bundled draw.io editor. Run this from the repo root, in the background (it blocks until the
editor window is closed):

```
"${CLAUDE_PLUGIN_ROOT}/scripts/cartographer" "${CLAUDE_PLUGIN_DATA}" view $ARGUMENTS
```

With no argument it opens the only diagram in `docs/architecture/diagrams`. If it exits with code 2 and lists names,
ask the user which one and run it again with that name.

Tell the user the URL it prints. Saving in the editor writes the .drawio and regenerates the image; closing the window
stops the local server.
