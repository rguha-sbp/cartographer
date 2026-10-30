from contextlib import contextmanager

import pytest

from cartographer import drawio_app

BUNDLED_URL = "http://127.0.0.1:9"


@pytest.fixture
def bundled_app(monkeypatch) -> str:
    """Commands that default to the bundled draw.io get a stand-in URL instead of a download."""

    @contextmanager
    def fake_serve(handler=None):
        yield BUNDLED_URL

    monkeypatch.setattr(drawio_app, "serve", fake_serve)
    return BUNDLED_URL
