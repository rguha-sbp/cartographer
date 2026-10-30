import argparse
from contextlib import nullcontext
from pathlib import Path

import pytest

from cartographer import cli, snapshot, view, view_browser, view_target


def _diagrams(root: Path, *names: str) -> Path:
    folder = root / view_target.DIAGRAMS
    folder.mkdir(parents=True)
    for name in names:
        (folder / name).write_text("<mxfile/>")
    return folder


def test_bare_name_resolves_into_the_diagrams_folder(tmp_path: Path) -> None:
    folder = _diagrams(tmp_path, "shop-l7.drawio")
    assert view_target.resolve("shop-l7", tmp_path) == folder / "shop-l7.drawio"


def test_a_path_is_kept_as_given(tmp_path: Path) -> None:
    assert view_target.resolve("x/a.drawio", tmp_path) == Path("x/a.drawio")
    assert view_target.resolve("a.svg", tmp_path) == Path("a.svg")


def test_a_missing_bare_name_is_an_error(tmp_path: Path) -> None:
    _diagrams(tmp_path, "shop-l7.drawio")
    with pytest.raises(view_target.TargetError, match="no diagram named nope"):
        view_target.resolve("nope", tmp_path)


def test_no_argument_opens_the_only_diagram_and_ignores_generated(tmp_path: Path) -> None:
    folder = _diagrams(tmp_path, "shop-l7.drawio", "shop-l7.generated.drawio", "shop-l7.svg")
    assert view_target.resolve(None, tmp_path) == folder / "shop-l7.drawio"


def test_no_argument_with_several_lists_them_one_per_line(tmp_path: Path) -> None:
    _diagrams(tmp_path, "b-l7.drawio", "a-l7.drawio")
    with pytest.raises(view_target.TargetError) as err:
        view_target.resolve(None, tmp_path)
    assert str(err.value).splitlines()[-2:] == ["a-l7", "b-l7"]


def test_no_argument_with_none_says_so(tmp_path: Path) -> None:
    with pytest.raises(view_target.TargetError, match="no .drawio files"):
        view_target.resolve(None, tmp_path)


def test_cli_view_without_argument_and_none_exits_2(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["view"]) == 2
    assert "no .drawio files" in capsys.readouterr().err


class _ExitedChrome:
    def wait(self) -> int:
        return 0

    def poll(self) -> int:
        return 0

    def terminate(self) -> None:
        pass


def test_view_flushes_every_status_line_and_stops_when_chrome_exits(tmp_path: Path, monkeypatch) -> None:
    drawio = tmp_path / "a.drawio"
    drawio.write_text("<mxfile/>")
    flushed = []
    real_print = print

    def spy(*args, **kwargs):
        flushed.append(kwargs.get("flush"))
        real_print(*args, **kwargs)

    monkeypatch.setattr(view, "print", spy, raising=False)
    monkeypatch.setattr(view_browser, "launch", lambda url: view_browser.Launch(_ExitedChrome(), None, "note"))
    monkeypatch.setattr(view.drawio_app, "ensure", lambda: tmp_path)
    monkeypatch.setattr(view.drawio_app, "serve", lambda handler: nullcontext("http://127.0.0.1:1"))
    assert view.run(argparse.Namespace(file=str(drawio), drawio_url=None)) == 0
    assert len(flushed) >= 3 and all(flushed)


def test_chrome_argv_is_its_own_locked_down_instance() -> None:
    argv = view_browser.chrome_argv("/c/chrome", Path("/tmp/p"), "http://127.0.0.1:9/_cartographer/")
    assert argv[0] == "/c/chrome"
    assert "--user-data-dir=/tmp/p" in argv
    assert f"--host-resolver-rules={snapshot.OFFLINE_RULES}" in argv
    assert "--no-first-run" in argv and "--no-default-browser-check" in argv
    assert argv[-1] == "--app=http://127.0.0.1:9/_cartographer/"
    assert not any("headless" in a for a in argv)


def test_launch_without_chrome_falls_back_and_says_lockdown_is_off(monkeypatch) -> None:
    opened = []

    def no_chrome() -> str:
        raise snapshot.SnapshotError("none")

    monkeypatch.setattr(view_browser.snapshot, "find_chrome", no_chrome)
    monkeypatch.setattr(view_browser.webbrowser, "open", opened.append)
    result = view_browser.launch("http://x/")
    assert opened == ["http://x/"]
    assert result.process is None and result.profile is None
    assert "network lockdown is not applied" in result.note
