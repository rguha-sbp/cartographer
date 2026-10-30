import hashlib
import urllib.request
import zipfile
from pathlib import Path

import pytest

from cartographer import drawio_app


def _war(tmp_path: Path, members: dict[str, str]) -> Path:
    war = tmp_path / "src" / "draw.war"
    war.parent.mkdir()
    with zipfile.ZipFile(war, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return war


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def pin(war: Path, sha: str | None = None) -> None:
        monkeypatch.setattr(drawio_app, "URL", war.as_uri())
        monkeypatch.setattr(drawio_app, "SHA256", sha or hashlib.sha256(war.read_bytes()).hexdigest())

    return pin


def test_ensure_downloads_checks_and_unpacks(tmp_path: Path, pinned) -> None:
    pinned(_war(tmp_path, {"index.html": "<html>hi</html>", "js/app.js": "x"}))
    web = drawio_app.ensure()
    assert web == drawio_app.app_dir() / "web"
    assert (web / "index.html").read_text() == "<html>hi</html>" and (web / "js" / "app.js").is_file()
    assert not (drawio_app.app_dir() / "draw.war").exists()


def test_ensure_is_idempotent(tmp_path: Path, pinned, monkeypatch) -> None:
    pinned(_war(tmp_path, {"index.html": "a"}))
    drawio_app.ensure()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not download twice"))
    assert drawio_app.ensure() == drawio_app.app_dir() / "web"


def test_ensure_rejects_a_sha_mismatch_and_deletes_the_download(tmp_path: Path, pinned) -> None:
    pinned(_war(tmp_path, {"index.html": "a"}), sha="0" * 64)
    with pytest.raises(drawio_app.DrawioError, match="pinned sha256"):
        drawio_app.ensure()
    assert not list(drawio_app.app_dir().rglob("*.war"))
    assert not (drawio_app.app_dir() / drawio_app.MARKER).exists()


@pytest.mark.parametrize("name", ["../evil.txt", "/abs/evil.txt", "a/../../evil.txt"])
def test_ensure_rejects_unsafe_paths(tmp_path: Path, pinned, name: str) -> None:
    pinned(_war(tmp_path, {"index.html": "a", name: "x"}))
    with pytest.raises(drawio_app.DrawioError, match="unsafe path"):
        drawio_app.ensure()
    assert not (drawio_app.app_dir() / drawio_app.MARKER).exists()
    assert not (tmp_path / "cache" / "evil.txt").exists() and not (tmp_path / "evil.txt").exists()


def test_ensure_reports_a_blocked_download(tmp_path: Path, pinned, monkeypatch) -> None:
    pinned(_war(tmp_path, {"index.html": "a"}))
    monkeypatch.setattr(drawio_app, "URL", (tmp_path / "missing.war").as_uri())
    with pytest.raises(drawio_app.DrawioError, match="could not download"):
        drawio_app.ensure()


def test_serve_serves_files_then_stops(tmp_path: Path, pinned) -> None:
    pinned(_war(tmp_path, {"index.html": "<html>hi</html>"}))
    with drawio_app.serve() as base:
        assert base.startswith("http://127.0.0.1:")
        assert urllib.request.urlopen(f"{base}/index.html").read() == b"<html>hi</html>"
    with pytest.raises(OSError):
        urllib.request.urlopen(f"{base}/index.html", timeout=2)


def test_drawio_at_uses_a_given_url_and_does_not_serve(monkeypatch) -> None:
    monkeypatch.setattr(drawio_app, "serve", lambda: pytest.fail("must not serve"))
    with drawio_app.drawio_at("http://localhost:8080/") as url:
        assert url == "http://localhost:8080"
