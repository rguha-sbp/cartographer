from contextlib import contextmanager

import pytest

from cartographer import drawio_app, snapshot, svg_export

BUNDLED_URL = "http://127.0.0.1:9"


@pytest.fixture
def bundled_app(monkeypatch) -> str:
    """Commands that default to the bundled draw.io get a stand-in URL instead of a download."""

    @contextmanager
    def fake_serve(handler=None):
        yield BUNDLED_URL

    monkeypatch.setattr(drawio_app, "serve", fake_serve)
    return BUNDLED_URL


@pytest.fixture
def renderer(monkeypatch, bundled_app) -> None:
    """svg export without Chrome: the image is the sha256 of the .drawio it came from."""
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(svg_export, "export_svg", lambda mxfile, source_sha256, url: f"<svg>{source_sha256}</svg>")
