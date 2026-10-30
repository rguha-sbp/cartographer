import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

from cartographer import snapshot, svg_export

XML = '<mxfile><diagram name="a &amp; b"><mxGraphModel/></diagram></mxfile>'
DOM = (
    '<html><head></head><body><div class="geDiagramContainer" style="x"><svg style="left: 0px; width: 100%; '
    'min-width: 900px; min-height: 700px; background-color: light-dark(rgb(255, 255, 255), rgb(18, 18, 18));">'
    '<g><rect x="1" fill="none" style="stop-color: light-dark(rgb(223, 222, 222), var(--c, #121212)); a: b"></rect>'
    '<image xlink:href="http://localhost:8080/img/lib/atlassian/Jira_Logo.svg" x="1" width="60" height="60"></image>'
    '<foreignObject width="10" height="10"><div style="display: flex;"><div>a&nbsp;b<br>c</div></div></foreignObject>'
    "</g></svg><div>viewer chrome</div></div></body></html>"
)
LOGO = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="1"/></svg>'


def _fetch(url: str) -> tuple[bytes, str]:
    assert url == "http://localhost:8080/img/lib/atlassian/Jira_Logo.svg"
    return LOGO, "image/svg+xml"


def _svg() -> str:
    return svg_export.svg_from_dom(DOM, XML, (800, 600), "http://localhost:8080", _fetch)


def test_result_is_well_formed_and_standalone() -> None:
    svg = _svg()
    root = ElementTree.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "localhost" not in svg
    assert "light-dark" not in svg
    assert "viewer chrome" not in svg
    assert root.get("viewBox") == "0 0 900 700"


def test_content_attribute_round_trips_the_mxfile() -> None:
    assert ElementTree.fromstring(_svg()).get("content") == XML


def test_images_become_data_uris() -> None:
    svg = _svg()
    assert 'href="data:image/svg+xml;base64,' in svg


def test_light_variant_is_kept() -> None:
    assert "rgb(223, 222, 222)" in _svg()


def test_missing_diagram_container_is_an_error() -> None:
    with pytest.raises(svg_export.SvgError):
        svg_export.svg_from_dom("<html></html>", XML, (1, 1), "http://localhost:8080", _fetch)


def test_export_runs_headless_chrome_with_dump_dom(tmp_path: Path, monkeypatch) -> None:
    drawio = tmp_path / "a.drawio"
    drawio.write_text("<mxfile><diagram><mxGraphModel><root>"
                      '<mxCell id="0"/><mxCell id="1" parent="0"/>'
                      '<mxCell id="g" parent="1" vertex="1"><mxGeometry width="10" height="10"/></mxCell>'
                      "</root></mxGraphModel></diagram></mxfile>")
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=DOM, stderr="")

    monkeypatch.setattr(snapshot, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(svg_export.subprocess, "run", fake_run)
    out = svg_export.export_svg(drawio, "http://localhost:8080", _fetch)
    assert "--dump-dom" in seen[0]
    ElementTree.fromstring(out)
