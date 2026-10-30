"""Screenshot a .drawio file in the local draw.io viewer so it can be reviewed visually (see REVIEW.md)."""

import argparse
import base64
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

MARGIN = 120
SCALE = 2
TILE_OVERLAP = 0.10
DRAWIO_TIMEOUT_S = 3
VIRTUAL_TIME_MS = 15000
CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_HINT = "install Google Chrome or Chromium, or put google-chrome / chromium on PATH"
DRAWIO_URL = "http://localhost:8080"
DRAWIO_DOWN = "start the local draw.io (localhost:8080) first"


class SnapshotError(Exception):
    pass


@dataclass(frozen=True)
class Tile:
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int


def viewer_url(drawio_url: str, xml: str) -> str:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = comp.compress(urllib.parse.quote(xml, safe="~()*!.'").encode()) + comp.flush()
    payload = urllib.parse.quote(base64.b64encode(raw).decode(), safe="")
    return f"{drawio_url}/?lightbox=1&nav=0&toolbar=0#R{payload}"


def window_size(xml: str) -> tuple[int, int]:
    """Bounding box of all vertices (parent offsets resolved) plus MARGIN on each side."""
    cells = {c.get("id"): c for c in ElementTree.fromstring(xml).iter("mxCell")}

    def origin(cell: ElementTree.Element | None) -> tuple[float, float]:
        x = y = 0.0
        while cell is not None:
            geo = cell.find("mxGeometry")
            if geo is not None:
                x += float(geo.get("x", 0))
                y += float(geo.get("y", 0))
            cell = cells.get(cell.get("parent"))
        return x, y

    boxes = []
    for cell in cells.values():
        geo = cell.find("mxGeometry")
        if cell.get("vertex") == "1" and geo is not None:
            x, y = origin(cell)
            boxes.append((x, y, x + float(geo.get("width", 0)), y + float(geo.get("height", 0))))
    if not boxes:
        raise SnapshotError("no vertices in the diagram")
    width = max(b[2] for b in boxes) - min(b[0] for b in boxes)
    height = max(b[3] for b in boxes) - min(b[1] for b in boxes)
    return round(width + 2 * MARGIN), round(height + 2 * MARGIN)


def parse_tiles(spec: str) -> tuple[int, int]:
    """'COLSxROWS' -> (rows, cols)."""
    try:
        cols, rows = (int(n) for n in spec.lower().split("x"))
    except ValueError:
        raise ValueError(f"--tiles must look like 2x2, got {spec!r}") from None
    return rows, cols


def _spans(total: int, parts: int) -> list[tuple[int, int]]:
    if parts == 1:
        return [(0, total)]
    size = round(total / parts * (1 + TILE_OVERLAP))
    step = (total - size) / (parts - 1)
    return [(round(i * step), size) for i in range(parts)]


def tile_rects(width: int, height: int, rows: int, cols: int) -> list[Tile]:
    return [
        Tile(r, c, x, y, w, h)
        for r, (y, h) in enumerate(_spans(height, rows))
        for c, (x, w) in enumerate(_spans(width, cols))
    ]


def find_chrome() -> str:
    if Path(CHROME_MAC).exists():
        return CHROME_MAC
    for name in ("google-chrome", "chromium"):
        if found := shutil.which(name):
            return found
    raise SnapshotError(f"Chrome not found: {CHROME_HINT}")


def drawio_up(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=DRAWIO_TIMEOUT_S).close()
    except (urllib.error.URLError, OSError):
        return False
    return True


def headless_cmd(chrome: str, size: tuple[int, int], *tail: str) -> list[str]:
    return [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={SCALE}",
        f"--virtual-time-budget={VIRTUAL_TIME_MS}", f"--window-size={size[0]},{size[1]}", *tail,
    ]


def _shoot(chrome: str, url: str, size: tuple[int, int], png: Path) -> None:
    cmd = headless_cmd(chrome, size, f"--screenshot={png}", url)
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0 or not png.exists():
        raise SnapshotError(f"Chrome failed for {png.name}: {(result.stderr or '').strip()[-300:]}")


def _tile_html(png: Path, size: tuple[int, int], tile: Tile) -> str:
    return (
        f'<html><body style="margin:0;overflow:hidden"><img src="{png.name}" width="{size[0]}" height="{size[1]}" '
        f'style="position:absolute;left:{-tile.x}px;top:{-tile.y}px"></body></html>'
    )


def snapshot(drawio: Path, out_dir: Path, drawio_url: str, tiles: str) -> list[Path]:
    rows, cols = parse_tiles(tiles)
    xml = drawio.read_text()
    size = window_size(xml)
    if not drawio_up(drawio_url):
        raise SnapshotError(DRAWIO_DOWN)
    chrome = find_chrome()
    out_dir.mkdir(parents=True, exist_ok=True)
    full = out_dir / f"{drawio.stem}.png"
    _shoot(chrome, viewer_url(drawio_url, xml), size, full)
    written = [full]
    if rows * cols == 1:
        return written
    for tile in tile_rects(*size, rows, cols):
        stem = f"{drawio.stem}.tile-r{tile.row}c{tile.col}"
        html = out_dir / f"{stem}.html"
        html.write_text(_tile_html(full, size, tile))
        try:
            _shoot(chrome, html.resolve().as_uri(), (tile.w, tile.h), out_dir / f"{stem}.png")
        finally:
            html.unlink(missing_ok=True)
        written.append(out_dir / f"{stem}.png")
    return written


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("drawio", type=Path)
    ap.add_argument("-o", "--out-dir", type=Path, required=True)
    ap.add_argument("--drawio-url", default=DRAWIO_URL, help="local draw.io; never a public host")
    ap.add_argument("--tiles", default="2x2", help="COLSxROWS, 1x1 for the full image only (default 2x2)")


def run(args: argparse.Namespace) -> int:
    try:
        paths = snapshot(args.drawio, args.out_dir, args.drawio_url.rstrip("/"), args.tiles)
    except SnapshotError as err:
        print(err, file=sys.stderr)
        return 2 if str(err) == DRAWIO_DOWN else 1
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print("\n".join(str(p) for p in paths))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_arguments(ap)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
