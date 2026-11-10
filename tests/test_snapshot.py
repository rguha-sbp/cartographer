import base64
import json
import subprocess
import urllib.parse
import zlib
from pathlib import Path

import pytest

from cartographer import snapshot

XML = """<mxfile><diagram><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="g" parent="1" vertex="1"><mxGeometry x="100" y="50" width="400" height="300" as="geometry"/></mxCell>
<mxCell id="n" parent="g" vertex="1"><mxGeometry x="20" y="30" width="60" height="60" as="geometry"/></mxCell>
<mxCell id="e" parent="1" edge="1" source="g" target="n"><mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def test_viewer_url_round_trips():
    url = snapshot.viewer_url("http://localhost:8080", XML)
    prefix = "http://localhost:8080/?lightbox=1&nav=0&toolbar=0#R"
    assert url.startswith(prefix)
    raw = base64.b64decode(urllib.parse.unquote(url[len(prefix):]))
    inflated = zlib.decompress(raw, -15).decode()
    assert urllib.parse.unquote(inflated) == XML


def test_extent_resolves_parents_and_adds_margin():
    # vertices span x 100..500, y 50..350; margin 120 on each side
    assert snapshot.window_size(XML) == (400 + 240, 300 + 240)


def test_extent_child_outside_parent_counts():
    xml = XML.replace('x="20" y="30"', 'x="600" y="500"')
    # child absolute 700..760, 550..610 -> bbox x 100..760, y 50..610
    assert snapshot.window_size(xml) == (660 + 240, 560 + 240)


def test_tile_rects_2x2_overlap():
    rects = snapshot.tile_rects(1000, 500, 2, 2)
    assert len(rects) == 4
    r0c0, r0c1, r1c0, r1c1 = rects
    assert (r0c0.x, r0c0.y) == (0, 0)
    assert r0c0.w == 550 and r0c0.h == 275
    assert r0c1.x + r0c1.w == 1000 and r1c1.y + r1c1.h == 500
    assert r0c1.x == 450 and r1c0.y == 225
    assert (r1c1.row, r1c1.col) == (1, 1)


def test_parse_tiles():
    assert snapshot.parse_tiles("3x2") == (2, 3)
    with pytest.raises(ValueError):
        snapshot.parse_tiles("two")


def test_drawio_not_running_exits_2(tmp_path, monkeypatch, capsys):
    d = tmp_path / "a.drawio"
    d.write_text(XML)
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: False)
    monkeypatch.setattr(snapshot.subprocess, "run", lambda *a, **k: pytest.fail("chrome must not run"))
    assert snapshot.main([str(d), "-o", str(tmp_path / "out"), "--drawio-url", "http://localhost:8080"]) == 2
    assert "no draw.io answers" in capsys.readouterr().err


def test_main_writes_full_and_tiles(tmp_path, monkeypatch, capsys, bundled_app):
    d = tmp_path / "a.drawio"
    d.write_text(XML.replace("<diagram>", '<diagram name="Container diagram for Shop">'))
    out = tmp_path / "out"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        shot = next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]
        Path(shot).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(snapshot, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    assert snapshot.main([str(d), "-o", str(out)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "view: Container diagram for Shop"
    assert lines[1] == str(out / "a.png")
    assert [Path(p).name for p in lines[2:]] == [
        "a.tile-r0c0.png", "a.tile-r0c1.png", "a.tile-r1c0.png", "a.tile-r1c1.png"]
    assert len(calls) == 5
    assert "--window-size=640,540" in calls[0]
    assert "--force-device-scale-factor=2" in calls[0]
    assert f"--host-resolver-rules={snapshot.OFFLINE_RULES}" in calls[0]
    assert calls[0][-1].startswith(bundled_app)


def test_main_shoots_every_page_of_a_book_alone(tmp_path, monkeypatch, capsys, bundled_app):
    model = XML[XML.index("<mxGraphModel>"):XML.index("</diagram>")]
    wide = model.replace('width="400"', 'width="900"')
    d = tmp_path / "shop-c4.drawio"
    d.write_text(f'<mxfile><diagram id="1-context" name="Context">{model}</diagram>'
                 f'<diagram id="2-container" name="Container">{wide}</diagram></mxfile>')
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        Path(next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(snapshot, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    assert snapshot.main([str(d), "-o", str(tmp_path), "--tiles", "1x1"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "view: Context", str(tmp_path / "shop-c4-1-context.png"),
        "view: Container", str(tmp_path / "shop-c4-2-container.png")]
    assert ["--window-size=640,540" in calls[0], "--window-size=1140,540" in calls[1]] == [True, True]


def test_find_chrome_missing(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent-playwright")
    monkeypatch.setattr(snapshot.Path, "exists", lambda self: False)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)
    with pytest.raises(snapshot.SnapshotError, match="Chrome"):
        snapshot.find_chrome()


def _no_chrome_anywhere(monkeypatch):
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent-playwright")
    monkeypatch.setattr(snapshot.Path, "exists", lambda self: False)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)


def test_find_chrome_windows_install_dirs(monkeypatch, tmp_path):
    _no_chrome_anywhere(monkeypatch)
    exe = tmp_path / "local" / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "unused"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(snapshot.Path, "exists", lambda self: self == exe)
    assert snapshot.find_chrome() == str(exe)


def test_chrome_candidates_skip_unset_env_vars(monkeypatch):
    _no_chrome_anywhere(monkeypatch)
    assert snapshot.chrome_candidates() == [Path(snapshot.CHROME_MAC)]


def test_find_chrome_program_files_x86(monkeypatch, tmp_path):
    _no_chrome_anywhere(monkeypatch)
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
    exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    monkeypatch.setattr(snapshot.Path, "exists", lambda self: self == exe)
    assert snapshot.find_chrome() == str(exe)


@pytest.mark.parametrize("name", ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"])
def test_find_chrome_path_names(monkeypatch, name):
    _no_chrome_anywhere(monkeypatch)
    monkeypatch.setattr(snapshot.shutil, "which", lambda n: f"/usr/bin/{n}" if n == name else None)
    assert snapshot.find_chrome() == f"/usr/bin/{name}"


def test_find_chrome_prefers_install_path_over_path(monkeypatch):
    _no_chrome_anywhere(monkeypatch)
    mac = Path(snapshot.CHROME_MAC)
    monkeypatch.setattr(snapshot.Path, "exists", lambda self: self == mac)
    monkeypatch.setattr(snapshot.shutil, "which", lambda n: "/usr/bin/chromium")
    assert snapshot.find_chrome() == str(mac)


def _playwright_chromium(root: Path, revision: int, rel: str) -> Path:
    exe = root / f"chromium-{revision}" / rel
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return exe


def test_find_chrome_falls_back_to_playwright_newest_revision(monkeypatch, tmp_path):
    _no_chrome_anywhere(monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    _playwright_chromium(tmp_path, 1200, "chrome-linux/chrome")
    newest = _playwright_chromium(tmp_path, 1248, "chrome-linux-arm64/chrome")
    _playwright_chromium(tmp_path, 999, "chrome-win/chrome.exe")
    assert snapshot.find_chrome() == str(newest)


@pytest.mark.parametrize("rel", [
    "chrome-linux64/chrome",
    "chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chrome-win64/chrome.exe",
])
def test_find_chrome_knows_every_playwright_layout(monkeypatch, tmp_path, rel):
    _no_chrome_anywhere(monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    exe = _playwright_chromium(tmp_path, 1248, rel)
    assert snapshot.find_chrome() == str(exe)


def test_find_chrome_ignores_playwrights_headless_shell(monkeypatch, tmp_path):
    """The headless shell has no window, so the editor could not open in it."""
    _no_chrome_anywhere(monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    shell = tmp_path / "chromium_headless_shell-1248" / "chrome-headless-shell-linux64" / "chrome-headless-shell"
    shell.parent.mkdir(parents=True)
    shell.write_text("")
    with pytest.raises(snapshot.SnapshotError, match="Chrome not found"):
        snapshot.find_chrome()


def test_find_chrome_prefers_a_system_install_over_playwright(monkeypatch, tmp_path):
    _no_chrome_anywhere(monkeypatch)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    _playwright_chromium(tmp_path, 1248, "chrome-linux/chrome")
    monkeypatch.setattr(snapshot.shutil, "which", lambda n: "/usr/bin/chromium" if n == "chromium" else None)
    assert snapshot.find_chrome() == "/usr/bin/chromium"


@pytest.mark.parametrize(("platform", "env", "expected"), [
    ("linux", {}, Path.home() / ".cache" / "ms-playwright"),
    ("linux", {"XDG_CACHE_HOME": "/xdg"}, Path("/xdg") / "ms-playwright"),
    ("darwin", {}, Path.home() / "Library" / "Caches" / "ms-playwright"),
    ("win32", {"LOCALAPPDATA": "C:/Users/me/AppData/Local"}, Path("C:/Users/me/AppData/Local") / "ms-playwright"),
])
def test_playwright_root_follows_playwrights_defaults(monkeypatch, platform, env, expected):
    for var in ("PLAYWRIGHT_BROWSERS_PATH", "XDG_CACHE_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    monkeypatch.setattr(snapshot.sys, "platform", platform)
    assert snapshot.playwright_root() == expected


def test_chrome_not_found_names_playwright():
    assert "playwright install chromium" in snapshot.CHROME_HINT


def test_a_chrome_without_its_system_libraries_says_so(tmp_path, monkeypatch):
    stderr = "chrome: error while loading shared libraries: libnss3.so: cannot open shared object file"
    monkeypatch.setattr(snapshot.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 127, stdout="", stderr=stderr))
    with pytest.raises(snapshot.SnapshotError) as err:
        snapshot._shoot("/bin/chrome", "http://x", (100, 100), tmp_path / "x.png")
    assert "libnss3.so" in str(err.value)
    assert snapshot.MISSING_LIBRARIES in str(err.value)


@pytest.mark.parametrize(("value", "flagged"), [(None, False), ("0", False), ("", False), ("1", True)])
def test_headless_chrome_keeps_the_sandbox_unless_turned_off(monkeypatch, value, flagged):
    monkeypatch.delenv(snapshot.NO_SANDBOX_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(snapshot.NO_SANDBOX_ENV, value)
    assert ("--no-sandbox" in snapshot.headless_cmd("/bin/chrome", (10, 10))) is flagged


def test_a_chrome_without_a_usable_sandbox_says_how_to_run_it():
    stderr = (
        "[1:1:FATAL:zygote_host_impl_linux.cc:130] No usable sandbox! If you are running on Ubuntu 23.10+ ...\n"
        + "\n".join(f"#{n} 0xaaaa (chrome+0x{n})" for n in range(40))
    )
    message = snapshot.chrome_failure(stderr)
    assert message.startswith("No usable sandbox!")
    assert snapshot.NO_SANDBOX_ENV in message
    assert "#39" not in message, "the stack trace is noise once the cause is known"


def test_other_chrome_failures_carry_no_library_hint():
    assert snapshot.chrome_failure("Trace/breakpoint trap") == "Trace/breakpoint trap"


def test_tiles_json_maps_icons_to_tiles() -> None:
    xml = """<mxfile><diagram><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="left" parent="1" vertex="1"><mxGeometry x="0" y="0" width="60" height="60" as="geometry"/></mxCell>
<mxCell id="right" parent="1" vertex="1"><mxGeometry x="940" y="440" width="60" height="60" as="geometry"/></mxCell>
<mxCell id="frame" parent="1" vertex="1"><mxGeometry x="0" y="0" width="1000" height="500" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""
    size = snapshot.window_size(xml)
    assert snapshot.tile_map(xml, "a", size, 2, 2) == {"a.tile-r0c0.png": ["left"], "a.tile-r1c1.png": ["right"]}


def test_a_1x1_snapshot_names_the_full_image_in_tiles_json(tmp_path, monkeypatch, bundled_app):
    d = tmp_path / "a.drawio"
    d.write_text(XML)
    out = tmp_path / "out"

    def fake_run(cmd, **kw):
        Path(next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(snapshot, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    [(_, shots)] = snapshot.snapshot(d, out, "http://localhost:8080", "1x1")
    assert shots == [out / "a.png"]
    assert set(json.loads((out / "tiles.json").read_text())) == {"a.png"}


def test_a_side_file_snapshot_fills_the_sheet_of_the_diagram_it_was_built_from(tmp_path, monkeypatch, bundled_app):
    monkeypatch.setenv("CARTOGRAPHER_HOME", str(tmp_path / "home"))
    sheet = tmp_path / "home" / "a" / "review.json"
    sheet.parent.mkdir(parents=True)
    sheet.write_text(json.dumps({"icons": [{"id": "n", "tiles": []}]}))
    d = tmp_path / "a.generated.drawio"
    d.write_text(XML)

    def fake_run(cmd, **kw):
        Path(next(a for a in cmd if a.startswith("--screenshot=")).split("=", 1)[1]).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(snapshot, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    snapshot.snapshot(d, tmp_path / "out", "http://localhost:8080", "1x1")
    assert json.loads(sheet.read_text())["icons"][0]["tiles"] == ["a.generated.png"]
