"""Render a .drawio to an svg image in the local draw.io, stamped with the sha256 of the .drawio it came from."""

import base64
import html
import re
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

from cartographer import files, index, snapshot

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XHTML_NS = "http://www.w3.org/1999/xhtml"
SOURCE_SHA_ATTR = "data-cartographer-source-sha256"
BACKGROUND = "#ffffff"
FETCH_TIMEOUT_S = 10

Fetch = Callable[[str], tuple[bytes, str]]


class SvgError(Exception):
    pass


def fetch_url(url: str) -> tuple[bytes, str]:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read(), resp.headers.get_content_type()


def _first_light_dark_arg(text: str, start: int) -> tuple[str, int]:
    """For `light-dark(A, B)` whose arguments start at `start`: (A, index after the closing paren)."""
    depth, first_end = 1, None
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == "," and depth == 1 and first_end is None:
            first_end = i
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:first_end if first_end is not None else i].strip(), i + 1
    raise SvgError("unbalanced light-dark() in the rendered svg")


def light_theme(text: str) -> str:
    """Replace every `light-dark(A, B)` with A so the file looks the same whatever the viewer's colour scheme."""
    marker = "light-dark("
    out, pos = [], 0
    while (hit := text.find(marker, pos)) != -1:
        out.append(text[pos:hit])
        light, pos = _first_light_dark_arg(text, hit + len(marker))
        out.append(light)
    out.append(text[pos:])
    return "".join(out)


def _inline_images(svg: str, drawio_url: str, fetch: Fetch) -> str:
    def data_uri(match: re.Match[str]) -> str:
        url = html.unescape(match["url"])
        body, mime = fetch(url)
        return f'{match["name"]}="data:{mime};base64,{base64.b64encode(body).decode()}"'

    return re.sub(rf'(?P<name>xlink:href|href)="(?P<url>{re.escape(drawio_url)}/[^"]*)"', data_uri, svg)


def _xml_safe(svg: str) -> str:
    """Chrome serialises HTML void tags and &nbsp; the HTML way; make the fragment XML."""
    svg = re.sub(r"<(br|hr|wbr)\b([^>]*?)/?>", r"<\1\2/>", svg).replace("&nbsp;", "&#160;")
    return re.sub(r"(<foreignObject[^>]*>\s*<div)\b", rf'\1 xmlns="{XHTML_NS}"', svg)


def _viewer_svg(dom: str) -> tuple[str, str]:
    """(attributes of the viewer's root svg, its inner markup)."""
    box = dom.find('class="geDiagramContainer"')
    start = dom.find("<svg", box) if box != -1 else -1
    end = dom.find("</svg>", start)
    if start == -1 or end == -1:
        raise SvgError("no rendered diagram found in draw.io")
    open_end = dom.index(">", start)
    return dom[start + 4:open_end], dom[open_end + 1:end]


def _px(attrs: str, prop: str) -> int:
    hit = re.search(rf"{prop}:\s*(\d+)px", attrs)
    return int(hit[1]) if hit else 0


def svg_from_dom(dom: str, source_sha256: str, size: tuple[int, int], drawio_url: str, fetch: Fetch) -> str:
    attrs, inner = _viewer_svg(dom)
    width, height = max(size[0], _px(attrs, "min-width")), max(size[1], _px(attrs, "min-height"))
    root = (
        f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}" width="{width}px" height="{height}px" '
        f'viewBox="0 0 {width} {height}" style="background: {BACKGROUND};" {SOURCE_SHA_ATTR}="{source_sha256}">'
    )
    svg = _xml_safe(_inline_images(light_theme(root + inner + "</svg>"), drawio_url, fetch))
    try:
        ElementTree.fromstring(svg)
    except ElementTree.ParseError as err:
        raise SvgError(f"rendered svg is not well-formed: {err}") from err
    return svg


def export_svg(mxfile: str, drawio_url: str, fetch: Fetch = fetch_url) -> str:
    if not snapshot.drawio_up(drawio_url):
        raise SvgError(snapshot.DRAWIO_DOWN)
    size = snapshot.window_size(mxfile)
    cmd = snapshot.headless_cmd(snapshot.find_chrome(), size, "--dump-dom", snapshot.viewer_url(drawio_url, mxfile))
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SvgError(f"Chrome failed: {proc.stderr.strip()[-300:]}")
    return svg_from_dom(proc.stdout, files.sha256_text(mxfile), size, drawio_url, fetch)


def write_image(drawio: Path, drawio_url: str, mxfile: str) -> Path:
    """Render `mxfile` (the content of `drawio`) to the svg next to it and refresh the folder index."""
    image = files.image_path(drawio)
    image.write_text(export_svg(mxfile, drawio_url))
    index.write_index(drawio.parent)
    return image
