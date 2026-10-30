import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from cartographer import cli, snapshot, svg_export, tfdiagram

FIXTURES = Path(__file__).parent / "fixtures"
STALE = "Terraform changed since curation: rerun the curation"


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path / "cache" / "cartographer" / "mini"


def _extract(capsys) -> list[str]:
    assert cli.main(["extract", "mini", "--repo", str(FIXTURES), "--stack", "mini"]) == 0
    return capsys.readouterr().out.splitlines()


def _curated(facts: dict, key: str) -> dict:
    fact = next(e["id"] for e in facts["edges"] if e["kind"] == "iam")
    node = {"group": None, "service": "other", "multi": False}
    return {
        "inputs_sha256": key,
        "title": "Mini architecture",
        "groups": [],
        "nodes": [
            {**node, "id": "fn", "label": "fn", "tf": ["aws_lambda_function.fn"]},
            {**node, "id": "data", "label": "data", "tf": ["aws_s3_bucket.data"]},
        ],
        "externals": [],
        "edges": [{"src": "fn", "dst": "data", "label": "reads", "flow": "data", "dashed": False,
                   "evidence": [{"fact": fact}]}],
        "omitted": [],
    }


def _setup_build(tmp_path: Path, capsys, key_override: str | None = None) -> Path:
    lines = _extract(capsys)
    facts = json.loads(Path(lines[0].split(": ", 1)[1]).read_text())
    key = key_override or lines[1].split(": ", 1)[1]
    curated = tmp_path / "mini.curated.json"
    curated.write_text(json.dumps(_curated(facts, key)))
    return curated


def test_extract_writes_facts_to_the_cache_and_prints_path_and_key(cache: Path, capsys) -> None:
    lines = _extract(capsys)
    assert lines[0] == f"facts: {cache / 'facts.json'}"
    assert lines[1] == f"inputs key: {tfdiagram.inputs_sha256(cache / 'facts.json')}"
    assert "aws_lambda_function.fn" in (cache / "facts.json").read_text()


def test_prompt_writes_schema_and_fills_the_template(cache: Path, tmp_path: Path, capsys) -> None:
    lines = _extract(capsys)
    key = lines[1].split(": ", 1)[1]
    assert cli.main(["prompt", "--stack", "mini", "--repo", str(tmp_path)]) == 0
    prompt = capsys.readouterr().out
    assert (cache / "curated.schema.json").read_text() == tfdiagram.schema_text()
    for needle in (str(cache / "facts.json"), str(tmp_path.resolve()), str(cache / "curated.schema.json"), key,
                   str(tmp_path.resolve() / "docs/architecture/mini.curated.json")):
        assert needle in prompt
    assert "{" + "facts_path}" not in prompt


def test_prompt_without_facts_says_to_extract(tmp_path: Path, capsys) -> None:
    assert cli.main(["prompt", "--stack", "mini", "--repo", str(tmp_path)]) == 2
    assert "cartographer extract" in capsys.readouterr().err


def test_build_writes_drawio_and_svg(cache: Path, tmp_path: Path, capsys, monkeypatch) -> None:
    curated = _setup_build(tmp_path, capsys)
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(svg_export, "export_svg", lambda path, url: "<svg/>")
    out = tmp_path / "out"
    code = cli.main(["build", "--stack", "mini", "--repo", str(FIXTURES), "--out", str(out), "--curated", str(curated)])
    assert code == 0
    assert ElementTree.parse(out / "mini.drawio").getroot().tag == "mxfile"
    assert (out / "mini.drawio.svg").read_text() == "<svg/>"
    assert (cache / "verify.txt").exists() and (cache / "verified.json").exists()
    assert not list(out.glob("*.json"))


def test_build_skips_svg_when_draw_io_is_down(tmp_path: Path, capsys, monkeypatch) -> None:
    curated = _setup_build(tmp_path, capsys)
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: False)
    out = tmp_path / "out"
    assert cli.main(["build", "--stack", "mini", "--repo", str(FIXTURES), "--out", str(out),
                     "--curated", str(curated)]) == 0
    assert (out / "mini.drawio").exists() and not (out / "mini.drawio.svg").exists()
    assert "svg skipped" in capsys.readouterr().out


def test_build_refuses_a_stale_key(tmp_path: Path, capsys) -> None:
    curated = _setup_build(tmp_path, capsys, key_override="0" * 64)
    out = tmp_path / "out"
    code = cli.main(["build", "--stack", "mini", "--repo", str(FIXTURES), "--out", str(out), "--curated", str(curated)])
    assert code == 3
    assert STALE in capsys.readouterr().err
    assert not out.exists()


def test_build_fails_when_verify_drops_something(tmp_path: Path, capsys) -> None:
    curated = _setup_build(tmp_path, capsys)
    data = json.loads(curated.read_text())
    data["nodes"][0]["tf"] = ["aws_lambda_function.nope"]
    curated.write_text(json.dumps(data))
    out = tmp_path / "out"
    code = cli.main(["build", "--stack", "mini", "--repo", str(FIXTURES), "--out", str(out), "--curated", str(curated)])
    assert code == 1
    assert "unknown tf address" in capsys.readouterr().out
    assert not (out / "mini.drawio").exists()


def test_build_defaults_curated_to_the_out_folder(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "mini.curated.json").write_text(_setup_build(tmp_path, capsys).read_text())
    assert cli.main(["build", "--stack", "mini", "--repo", str(FIXTURES), "--out", str(out)]) == 0


def test_view_opens_the_local_viewer(tmp_path: Path, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    drawio = tmp_path / "a.drawio"
    drawio.write_text("<mxfile/>")
    assert cli.main(["view", str(drawio)]) == 0
    assert opened[0].startswith("http://localhost:8080/?") and "#R" in opened[0]


def test_view_reads_the_mxfile_out_of_a_drawio_svg(tmp_path: Path, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    svg = tmp_path / "a.drawio.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" content="&lt;mxfile/&gt;"/>')
    assert cli.main(["view", str(svg)]) == 0
    assert opened[0] == snapshot.viewer_url("http://localhost:8080", "<mxfile/>")


def test_docs_print_packaged_paths(capsys) -> None:
    assert cli.main(["docs", "review"]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.name == "REVIEW.md" and path.is_file()
    assert cli.main(["docs", "rules"]) == 0
    assert Path(capsys.readouterr().out.strip()).name == "RULES.md"


def test_snapshot_subcommand_delegates(tmp_path: Path, monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(snapshot, "snapshot", lambda *a: seen.append(a) or [])
    assert cli.main(["snapshot", str(tmp_path / "a.drawio"), "-o", str(tmp_path / "s")]) == 0
    assert seen[0][3] == "2x2"
