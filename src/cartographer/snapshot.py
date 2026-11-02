"""Screenshot every page of a .drawio file in the local draw.io viewer so it can be reviewed visually (see REVIEW.md)."""

import argparse
import base64
import json
import os
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

from cartographer import drawio_app, files
from cartographer.diagram_model import ICON
from cartographer.workdir import cache_root, write_json

MARGIN = 120
SCALE = 2
TILE_OVERLAP = 0.10
DRAWIO_TIMEOUT_S = 3
VIRTUAL_TIME_MS = 15000
CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_WINDOWS = Path("Google") / "Chrome" / "Application" / "chrome.exe"
CHROME_WINDOWS_ROOTS = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
CHROME_PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
CHROME_HINT = (
    "install Google Chrome or Chromium (macOS app bundle, or the Windows per-machine or per-user install), "
    "or put google-chrome / chromium on PATH"
)
DRAWIO_DOWN = "no draw.io answers at the given --drawio-url: start it, or omit the flag to use the bundled one"
OFFLINE_RULES = "MAP * ~NOTFOUND , EXCLUDE 127.0.0.1 , EXCLUDE localhost"


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


def _vertex_boxes(xml: str) -> dict[str, tuple[float, float, float, float]]:
    """Id -> absolute (left, top, right, bottom) of every vertex, parent offsets resolved."""
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

    boxes = {}
    for cid, cell in cells.items():
        geo = cell.find("mxGeometry")
        if cell.get("vertex") == "1" and geo is not None:
            x, y = origin(cell)
            boxes[cid] = (x, y, x + float(geo.get("width", 0)), y + float(geo.get("height", 0)))
    return boxes


def window_size(xml: str) -> tuple[int, int]:
    """Bounding box of all vertices (parent offsets resolved) plus MARGIN on each side."""
    boxes = list(_vertex_boxes(xml).values())
    if not boxes:
        raise SnapshotError("no vertices in the diagram")
    width = max(b[2] for b in boxes) - min(b[0] for b in boxes)
    height = max(b[3] for b in boxes) - min(b[1] for b in boxes)
    return round(width + 2 * MARGIN), round(height + 2 * MARGIN)


def tile_map(xml: str, stem: str, size: tuple[int, int], rows: int, cols: int) -> dict[str, list[str]]:
    """Tile png name -> ids of the icon cells (ICON x ICON vertices) whose rectangle intersects that tile."""
    boxes = _vertex_boxes(xml)
    left = min(b[0] for b in boxes.values()) - MARGIN
    top = min(b[1] for b in boxes.values()) - MARGIN
    icons = {cid: b for cid, b in boxes.items() if (b[2] - b[0], b[3] - b[1]) == (ICON, ICON)}
    tiles = {}
    for tile in tile_rects(*size, rows, cols):
        hit = [cid for cid, b in icons.items()
               if b[0] < left + tile.x + tile.w and b[2] > left + tile.x
               and b[1] < top + tile.y + tile.h and b[3] > top + tile.y]
        if hit:
            tiles[f"{stem}.tile-r{tile.row}c{tile.col}.png"] = sorted(hit)
    return tiles


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


def chrome_candidates() -> list[Path]:
    roots = [os.environ[var] for var in CHROME_WINDOWS_ROOTS if os.environ.get(var)]
    return [Path(CHROME_MAC), *(Path(root) / CHROME_WINDOWS for root in roots)]


def find_chrome() -> str:
    for path in chrome_candidates():
        if path.exists():
            return str(path)
    for name in CHROME_PATH_NAMES:
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
        f"--virtual-time-budget={VIRTUAL_TIME_MS}", f"--host-resolver-rules={OFFLINE_RULES}", f"--window-size={size[0]},{size[1]}", *tail,
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


def _write_tiles(tiles: dict[str, list[str]], diagram: str, out_dir: Path) -> None:
    """`tiles.json` beside the PNGs; also fills the `tiles` of each icon in the review sheet of `diagram`."""
    write_json(out_dir / "tiles.json", tiles)
    sheet_path = cache_root() / diagram / "review.json"
    if sheet_path.is_file():
        sheet = json.loads(sheet_path.read_text())
        for entry in sheet["icons"]:
            entry["tiles"] = [name for name, ids in tiles.items() if entry["id"] in ids]
        write_json(sheet_path, sheet)


def _shots(chrome: str, page: files.Page, size: tuple[int, int], out_dir: Path, drawio_url: str,
           rows: int, cols: int) -> list[Path]:
    """The full PNG of the page, named for its image, then its tiles when there are several."""
    full = out_dir / f"{page.image.stem}.png"
    _shoot(chrome, viewer_url(drawio_url, page.mxfile), size, full)
    written = [full]
    _write_tiles(xml, drawio.stem, size, rows, cols, out_dir)
    if rows * cols == 1:
        return written
    for tile in tile_rects(*size, rows, cols):
        stem = f"{page.image.stem}.tile-r{tile.row}c{tile.col}"
        html = out_dir / f"{stem}.html"
        html.write_text(_tile_html(full, size, tile))
        try:
            _shoot(chrome, html.resolve().as_uri(), (tile.w, tile.h), out_dir / f"{stem}.png")
        finally:
            html.unlink(missing_ok=True)
        written.append(out_dir / f"{stem}.png")
    return written


def snapshot(drawio: Path, out_dir: Path, drawio_url: str, tiles: str) -> list[tuple[files.Page, list[Path]]]:
    """The PNGs of every page of the .drawio, each page shot alone."""
    rows, cols = parse_tiles(tiles)
    pages = files.pages(drawio, drawio.read_text())
    sizes = [window_size(page.mxfile) for page in pages]
    if not drawio_up(drawio_url):
        raise SnapshotError(DRAWIO_DOWN)
    chrome = find_chrome()
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = [(page, _shots(chrome, page, size, out_dir, drawio_url, rows, cols))
            for page, size in zip(pages, sizes, strict=True)]
    if rows * cols != 1:
        _write_tiles({tile: ids for page, size in zip(pages, sizes, strict=True)
                      for tile, ids in tile_map(page.mxfile, page.image.stem, size, rows, cols).items()},
                     drawio.stem, out_dir)
    return shot


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("drawio", type=Path)
    ap.add_argument("-o", "--out-dir", type=Path, required=True)
    ap.add_argument("--drawio-url", default=None, help="your own local draw.io (never a public host); default: the bundled one")
    ap.add_argument("--tiles", default="2x2", help="COLSxROWS, 1x1 for the full image only (default 2x2)")


def run(args: argparse.Namespace) -> int:
    try:
        with drawio_app.drawio_at(args.drawio_url) as url:
            shot = snapshot(args.drawio, args.out_dir, url, args.tiles)
    except drawio_app.DrawioError as err:
        print(err, file=sys.stderr)
        return 2
    except SnapshotError as err:
        print(err, file=sys.stderr)
        return 2 if str(err) == DRAWIO_DOWN else 1
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print("\n".join(line for page, paths in shot for line in (f"view: {page.name}", *map(str, paths))))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    add_arguments(ap)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
