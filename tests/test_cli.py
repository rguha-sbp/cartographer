import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from cartographer import cli, files, snapshot, svg_export, tfdiagram

FIXTURES = Path(__file__).parent / "fixtures"
STALE = "Terraform changed since curation: rerun the curation"


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path / "cache" / "cartographer" / "mini"


def _extract(capsys) -> list[str]:
    assert cli.main(["extract", "mini", "--repo", str(FIXTURES), "--name", "mini"]) == 0
    return capsys.readouterr().out.splitlines()


def _curated(facts: dict, key: str) -> dict:
    fact = next(e["id"] for e in facts["edges"] if e["kind"] == "iam")
    node = {"group": None, "service": "other", "multi": False}
    return {
        "source": "terraform",
        "inputs_sha256": key,
        "system": "Mini",
        "view": "l7",
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
    assert cli.main(["prompt", "--name", "mini", "--repo", str(tmp_path)]) == 0
    prompt = capsys.readouterr().out
    assert (cache / "curated.schema.json").read_text() == tfdiagram.schema_text()
    for needle in (str(cache / "facts.json"), str(tmp_path.resolve()), str(cache / "curated.schema.json"), key,
                   str(tmp_path.resolve() / "docs/architecture/diagrams/mini.curated.json")):
        assert needle in prompt
    assert "{" + "facts_path}" not in prompt


def test_prompt_without_facts_says_to_extract(tmp_path: Path, capsys) -> None:
    assert cli.main(["prompt", "--name", "mini", "--repo", str(tmp_path)]) == 2
    assert "cartographer extract" in capsys.readouterr().err


def _build(tmp_path: Path, curated: Path, *extra: str) -> int:
    out = tmp_path / "out"
    return cli.main(["build", "--name", "mini", "--repo", str(FIXTURES), "--out", str(out), "--curated", str(curated),
                     *extra])


@pytest.fixture
def renderer(monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(svg_export, "export_svg", lambda mxfile, url: f"<svg>{files.sha256_text(mxfile)}</svg>")


def test_build_writes_drawio_svg_fingerprint_and_index(cache: Path, tmp_path: Path, capsys, renderer) -> None:
    curated = _setup_build(tmp_path, capsys)
    assert _build(tmp_path, curated) == 0
    out = tmp_path / "out"
    drawio = out / "mini.drawio"
    root = ElementTree.parse(drawio).getroot()
    assert root.tag == "mxfile" and root[0].get("name") == "Layer 7 diagram for Mini"
    assert (out / "mini.svg").read_text() == f"<svg>{files.sha256_file(drawio)}</svg>"
    assert json.loads(curated.read_text())["drawio_sha256"] == files.sha256_file(drawio)
    assert (cache / "verify.txt").exists() and (cache / "verified.json").exists()
    assert not list(out.glob("*.json"))


def test_build_defaults_to_the_diagrams_folder(tmp_path: Path, capsys, renderer) -> None:
    repo = tmp_path / "repo"
    folder = repo / "docs" / "architecture" / "diagrams"
    folder.mkdir(parents=True)
    (folder / "mini.curated.json").write_text(_setup_build(tmp_path, capsys).read_text())
    assert cli.main(["build", "--name", "mini", "--repo", str(repo)]) == 0
    assert (folder / "mini.drawio").exists() and (folder / "mini.svg").exists()
    assert "[mini.drawio](mini.drawio)" in (folder / "README.md").read_text()


def test_build_fails_before_writing_when_draw_io_is_down(tmp_path: Path, capsys, monkeypatch) -> None:
    curated = _setup_build(tmp_path, capsys)
    before = curated.read_text()
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: False)
    assert _build(tmp_path, curated) == 5
    assert "start the local draw.io" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
    assert curated.read_text() == before


def _built(tmp_path: Path, capsys) -> Path:
    curated = _setup_build(tmp_path, capsys)
    assert _build(tmp_path, curated) == 0
    return curated


def test_build_refuses_a_hand_edited_drawio_and_writes_nothing(tmp_path: Path, capsys, renderer) -> None:
    curated = _built(tmp_path, capsys)
    out = tmp_path / "out"
    (out / "mini.drawio").write_text("<mxfile>hand</mxfile>")
    svg, record = (out / "mini.svg").read_text(), curated.read_text()
    assert _build(tmp_path, curated) == 4
    assert "the .drawio was edited by hand" in capsys.readouterr().err
    assert (out / "mini.drawio").read_text() == "<mxfile>hand</mxfile>"
    assert (out / "mini.svg").read_text() == svg and curated.read_text() == record


def test_build_refuses_an_existing_drawio_the_curated_file_does_not_vouch_for(tmp_path: Path, capsys, renderer) -> None:
    curated = _setup_build(tmp_path, capsys)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "mini.drawio").write_text("<mxfile/>")
    assert _build(tmp_path, curated) == 4


def test_build_rebuilds_an_untouched_drawio(tmp_path: Path, capsys, renderer) -> None:
    curated = _built(tmp_path, capsys)
    assert _build(tmp_path, curated) == 0


def test_replace_overwrites_a_hand_edited_drawio(tmp_path: Path, capsys, renderer) -> None:
    curated = _built(tmp_path, capsys)
    out = tmp_path / "out"
    (out / "mini.drawio").write_text("<mxfile>hand</mxfile>")
    assert _build(tmp_path, curated, "--replace") == 0
    drawio = out / "mini.drawio"
    assert drawio.read_text() != "<mxfile>hand</mxfile>"
    assert json.loads(curated.read_text())["drawio_sha256"] == files.sha256_file(drawio)


def test_side_file_leaves_the_hand_edit_and_the_record_alone(tmp_path: Path, capsys, renderer) -> None:
    curated = _built(tmp_path, capsys)
    out = tmp_path / "out"
    (out / "mini.drawio").write_text("<mxfile>hand</mxfile>")
    record = curated.read_text()
    assert _build(tmp_path, curated, "--side-file") == 0
    assert (out / "mini.drawio").read_text() == "<mxfile>hand</mxfile>"
    assert ElementTree.parse(out / "mini.generated.drawio").getroot().tag == "mxfile"
    assert (out / "mini.generated.svg").exists()
    assert curated.read_text() == record


def test_build_refuses_a_stale_key(tmp_path: Path, capsys) -> None:
    curated = _setup_build(tmp_path, capsys, key_override="0" * 64)
    out = tmp_path / "out"
    code = cli.main(["build", "--name", "mini", "--repo", str(FIXTURES), "--out", str(out), "--curated", str(curated)])
    assert code == 3
    assert STALE in capsys.readouterr().err
    assert not out.exists()


def test_build_fails_when_verify_drops_something(tmp_path: Path, capsys) -> None:
    curated = _setup_build(tmp_path, capsys)
    data = json.loads(curated.read_text())
    data["nodes"][0]["tf"] = ["aws_lambda_function.nope"]
    curated.write_text(json.dumps(data))
    out = tmp_path / "out"
    code = cli.main(["build", "--name", "mini", "--repo", str(FIXTURES), "--out", str(out), "--curated", str(curated)])
    assert code == 1
    assert "unknown tf address" in capsys.readouterr().out
    assert not (out / "mini.drawio").exists()


def test_build_defaults_curated_to_the_out_folder(tmp_path: Path, capsys, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "mini.curated.json").write_text(_setup_build(tmp_path, capsys).read_text())
    assert cli.main(["build", "--name", "mini", "--repo", str(FIXTURES), "--out", str(out)]) == 0


def test_view_opens_the_local_viewer(tmp_path: Path, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    drawio = tmp_path / "a.drawio"
    drawio.write_text("<mxfile/>")
    assert cli.main(["view", str(drawio)]) == 0
    assert opened[0].startswith("http://localhost:8080/?") and "#R" in opened[0]


def test_view_refuses_anything_but_a_drawio(tmp_path: Path, capsys) -> None:
    assert cli.main(["view", str(tmp_path / "a.svg")]) == 2
    assert "takes a .drawio" in capsys.readouterr().err


def test_image_regenerates_the_sibling_svg_and_the_index(tmp_path: Path, renderer) -> None:
    drawio = tmp_path / "a-l7.drawio"
    drawio.write_text("<mxfile/>")
    (tmp_path / "a-l7.curated.json").write_text(json.dumps({"system": "A", "view": "l7"}))
    assert cli.main(["image", str(drawio)]) == 0
    assert (tmp_path / "a-l7.svg").read_text() == f"<svg>{files.sha256_file(drawio)}</svg>"
    assert "Layer 7 diagram for A" in (tmp_path / "README.md").read_text()


def test_image_fails_with_exit_5_when_draw_io_is_down(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: False)
    drawio = tmp_path / "a.drawio"
    drawio.write_text("<mxfile/>")
    assert cli.main(["image", str(drawio)]) == 5
    assert "start the local draw.io" in capsys.readouterr().err
    assert not (tmp_path / "a.svg").exists()


def test_check_reports_problems_with_exit_1(tmp_path: Path, capsys) -> None:
    assert cli.main(["check", str(tmp_path)]) == 0
    (tmp_path / "a.drawio").write_text("<mxfile/>")
    assert cli.main(["check", str(tmp_path)]) == 1
    assert "a.drawio: no image" in capsys.readouterr().out


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
