from pathlib import Path

from cartographer import drawio_app, workdir


def test_cache_root_defaults_to_xdg_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CARTOGRAPHER_HOME", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert workdir.cache_root() == tmp_path / "xdg" / "cartographer"


def test_cartographer_home_wins_over_xdg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CARTOGRAPHER_HOME", str(tmp_path / "data"))
    assert workdir.cache_root() == tmp_path / "data"
    assert workdir.cache_dir("shop-l7") == tmp_path / "data" / "shop-l7"
    assert drawio_app.app_dir() == tmp_path / "data" / "drawio" / drawio_app.VERSION
