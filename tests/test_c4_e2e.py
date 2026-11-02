import shutil
from pathlib import Path

import pytest

from cartographer import cli, files, tf_check
from cartographer.workdir import cache_dir

FIXTURES = Path(__file__).parent / "fixtures"
NAME = "mini-c4"


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def test_mini_c4_builds_clean(tmp_path: Path, capsys, renderer) -> None:
    assert cli.main(["extract", "mini", "--repo", str(FIXTURES), "--name", NAME]) == 0
    shutil.copy(FIXTURES / "c4" / "model.json", cache_dir(NAME) / "model.json")
    assert cli.main(["build", "--c4", "--name", NAME, "--repo", str(FIXTURES), "--out", str(tmp_path / "out")]) == 0
    assert "C4 model: ok" in capsys.readouterr().out.splitlines()
    drawio = tmp_path / "out" / f"{NAME}-c4.drawio"
    pages = files.pages(drawio, drawio.read_text())
    assert [p.image.name.removeprefix(f"{NAME}-c4-") for p in pages] == [
        "1-context.svg", "2-container.svg", "3-component-fn.svg", "5-deployment.svg", "6-dynamic-read.svg"]
    for page in pages:
        routed = tf_check.measure(page.mxfile)
        assert (routed.edge_through_node, routed.caption_overlaps, routed.edge_through_title) == (0, 0, 0), (
            page.name, routed.summary())
