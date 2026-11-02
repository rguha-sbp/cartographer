import shutil
from pathlib import Path

import pytest

from cartographer import cli, tf_check
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
    drawios = sorted((tmp_path / "out").glob("*.drawio"))
    assert [p.name.removeprefix(f"{NAME}-") for p in drawios] == [
        "1-context.drawio", "2-container.drawio", "3-component-fn.drawio", "5-deployment.drawio",
        "6-dynamic-read.drawio"]
    for drawio in drawios:
        routed = tf_check.measure(drawio.read_text())
        assert (routed.edge_through_node, routed.caption_overlaps, routed.edge_through_title) == (0, 0, 0), (
            drawio.name, routed.summary())
