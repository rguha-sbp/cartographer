# Bundled draw.io: render and edit without anything left running

Date: 2026-10-30. Status: approved in conversation by the repo owner (serve our own copy).

## Intent

`build`, `image`, `snapshot` and `view` need a draw.io on `localhost:8080`, which today means a Docker container
running all the time. Nobody without that container can generate a diagram. The owner ruled out the desktop app
(security review) and Docker (too heavy, extra dependencies). cartographer serves its own pinned copy of the draw.io
web app, only while a command needs it.

## What was checked (2026-10-30, jgraph/drawio, Apache-2.0)

- Releases ship one asset, `draw.war` (about 49 MB, about 118 MB unpacked), weekly. A war is a zip of the web app.
- The web app runs as static files: the repo README offers GitHub Pages as a way to run the editor. Served with
  Python's `http.server`, v32.5.5 rendered the shop test diagram to a PNG byte-identical to the Docker container's.
- Embed mode (`index.html?embed=1&proto=json`) works from the static copy: `init`, then `load` with our XML, then
  `export` returns the XML. The same protocol sends `save` when the user presses Save.
- The README calls the repository a "test version" with a paid production version; the code licence is Apache-2.0.
  The Docker image used today is the same build. Whether that is acceptable is the owner's call.

## Goals

1. **Pinned artifact.** cartographer pins a draw.io version and the sha256 of its `draw.war`. On first use it
   downloads the war from the jgraph/drawio GitHub release into `~/.cache/cartographer/drawio/<version>/`, checks the
   sha256, and unpacks it. A mismatch deletes the download and stops with a clear message. The pin lives in one place
   and is listed for SBOM purposes (name, version, licence, URL, sha256).
2. **Render on demand.** `build`, `image` and `snapshot` start a stdlib HTTP server on 127.0.0.1 with a free port for
   the duration of the command and stop it after. `--drawio-url` keeps working for anyone who points at their own
   instance.
3. **Edit on demand.** `cartographer view x.drawio` serves the web app plus a small host page, opens Chrome on it, and
   embeds the full editor with the file loaded. Save posts the XML back to the host page, which posts it to the local
   server, which writes the file in place. The server stops when the tab is closed or on Ctrl-C. Nothing keeps running.
   After a save, the next skill run sees the hand edit and asks the user, as it does now.
4. **Offline.** The diagram never leaves the machine: the embed URL sets `offline=1` and `stealth=1`, and the local
   server sends a Content Security Policy on every reply that limits the page to 127.0.0.1, so a request to any other
   host is refused instead of leaking. Headless renders also keep a Chrome host-resolver rule, because they may point at
   the user's own draw.io, which the policy does not cover.
5. **Fallback.** If the download is blocked or fails, `view` prints the lightbox note and render commands exit 5 with
   the reason.

## Non-goals

- The desktop app, Docker, a long-running service.
- Bumping the draw.io version automatically. A bump is a PR that changes the pin (7-day age gate applies).

## Constraints

No new Python dependency (stdlib `http.server`, `zipfile`, `hashlib`, `urllib`). Chrome is already required.

## Builder's calls (open to correction)

- Pin v32.5.5 (sha256 `cde0ebd72da197da37d100353e226d5344b08f0fcf7e1b18d1e000a77f9c5f52`), the version the
  render comparison used and older than 7 days.
- The save endpoint accepts only POSTs from the host page's own origin to the one file `view` was started with.
- After a save, `view` regenerates the image from the saved file with the same local server, so `check` stays green;
  the curated `drawio_sha256` is not updated, so the next skill run still asks the user about the hand edit.
- `view` stops its server when the page sends a close beacon on `pagehide`, or on Ctrl-C. No keepalive polling.
- README prerequisites drop Docker.
