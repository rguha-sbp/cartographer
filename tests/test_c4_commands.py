import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from cartographer import c4_model, cli, files, snapshot
from cartographer.workdir import cache_dir

FIXTURES = Path(__file__).parent / "fixtures"
NAME = "shop-c4"
STATED = [{"stated": "the engineer said so"}]
VIEW_FILES = ["shop-c4-1-context.drawio", "shop-c4-2-container.drawio", "shop-c4-3-component-api.drawio",
              "shop-c4-6-dynamic-buy.drawio"]


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path / "cache" / "cartographer" / NAME


def el(eid: str, kind: str, parent: str | None = None, **extra) -> dict:
    base = {"id": eid, "type": kind, "name": eid.capitalize(), "description": "Does things", "evidence": STATED}
    return base | ({"parent": parent} if parent else {}) | extra


def rel(rid: str, src: str, dst: str, label: str, **extra) -> dict:
    return {"id": rid, "src": src, "dst": dst, "label": label, "dashed": False, "evidence": STATED} | extra


def _shop() -> dict:
    return {
        "source": "description",
        "elements": [
            el("user", "person"),
            el("psp", "system", external=True),
            el("shop", "system"),
            el("api", "container", "shop", technology="Python"),
            el("db", "container", "shop", technology="Postgres", shape="store"),
            el("auth", "component", "api", technology="Python"),
            el("cart", "component", "api", technology="Python"),
        ],
        "relationships": [
            rel("r1", "user", "auth", "logs in", technology="HTTPS"),
            rel("r2", "cart", "db", "stores carts", technology="SQL"),
            rel("r3", "cart", "psp", "charges", technology="HTTPS"),
            rel("r4", "cart", "auth", "checks", technology="Python call"),
        ],
        "scenarios": [{"id": "buy", "name": "Buy", "steps": ["r1", "r3", "r2"]}],
    }


def _model(model: dict) -> None:
    (cache_dir(NAME) / "model.json").write_text(json.dumps(model))


def _build(tmp_path: Path, *extra: str) -> int:
    return cli.main(["build", "--c4", "--name", NAME, "--repo", str(tmp_path), "--out", "out", *extra])


def test_prompt_c4_describe_needs_no_facts(cache: Path, tmp_path: Path, capsys) -> None:
    assert cli.main(["prompt", "--name", NAME, "--c4", "--describe", "--repo", str(tmp_path)]) == 0
    prompt = capsys.readouterr().out
    assert (cache / "c4.schema.json").read_text() == c4_model.SCHEMA.read_text()
    for needle in (str(cache / "c4.schema.json"), str(cache / "model.json"), str(tmp_path.resolve()),
                   str(cli.DOCS["interview"]), "Facts file: none",
                   "For the Component diagram of the `api` container I need its main internal parts"):
        assert needle in prompt
    assert "{" not in prompt.replace('{"', "")
    assert prompt.isascii()


def test_prompt_c4_without_facts_exits_2(tmp_path: Path, capsys) -> None:
    assert cli.main(["prompt", "--name", NAME, "--c4", "--repo", str(tmp_path)]) == 2
    assert "cartographer extract" in capsys.readouterr().err


def test_prompt_c4_names_the_cached_facts(cache: Path, tmp_path: Path, capsys) -> None:
    assert cli.main(["extract", "mini", "--repo", str(FIXTURES), "--name", NAME]) == 0
    assert cli.main(["prompt", "--name", NAME, "--c4", "--repo", str(tmp_path)]) == 0
    assert f"Facts file: {cache / 'facts.json'}" in capsys.readouterr().out


def test_build_c4_writes_one_file_pair_per_view(tmp_path: Path, capsys, renderer) -> None:
    _model(_shop())
    assert _build(tmp_path) == 0
    out = tmp_path / "out"
    assert sorted(p.name for p in out.glob("*.drawio")) == VIEW_FILES
    assert ElementTree.parse(out / "shop-c4-2-container.drawio").getroot()[0].get("name") == "Container diagram for Shop"
    for name in VIEW_FILES:
        drawio = out / name
        assert files.image_path(drawio).read_text() == f"<svg>{files.sha256_file(drawio)}</svg>"
    readme = (out / "README.md").read_text()
    assert "| Container diagram for Shop | [shop-c4-2-container.drawio]" in readme


def test_build_c4_prints_every_written_path(tmp_path: Path, capsys, renderer) -> None:
    _model(_shop())
    assert _build(tmp_path) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "C4 model: ok"
    out = tmp_path / "out"
    for name in VIEW_FILES:
        assert str(out / name) in lines and str(files.image_path(out / name)) in lines


def test_build_c4_lists_what_rests_only_on_stated(tmp_path: Path, capsys, renderer) -> None:
    _model(_shop())
    assert _build(tmp_path) == 0
    out = capsys.readouterr().out
    assert out.startswith("C4 model: ok\n")
    assert "Stated by the engineer, not found in the repo (8)\n  api\n  auth\n  cart\n  db\n  r1\n" in out


def test_build_c4_overwrites_without_asking(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "shop-c4-1-context.drawio").write_text("edited by hand")
    _model(_shop())
    assert _build(tmp_path) == 0
    assert "System Context diagram for Shop" in (out / "shop-c4-1-context.drawio").read_text()


def test_build_deletes_stale_views_only_of_this_model(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    keep = ["gip.drawio", "shop-c4.drawio", "shop-c4-old.generated.drawio", "shop-c5-1-context.drawio",
            "shop-c4-legacy.drawio", "shop-l7.drawio"]
    for name in keep:
        (out / name).write_text("y")
    (out / "shop-c4-3-component-old.drawio").write_text("x")
    (out / "shop-c4-3-component-old.svg").write_text("x")
    _model(_shop())
    assert _build(tmp_path) == 0
    assert not (out / "shop-c4-3-component-old.drawio").exists()
    assert not (out / "shop-c4-3-component-old.svg").exists()
    assert all((out / name).read_text() == "y" for name in keep)
    assert "[gip.drawio](gip.drawio)" in (out / "README.md").read_text()


def test_build_c4_of_model_shop_keeps_its_l7_diagram(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "shop-l7.drawio").write_text("y")
    (cache_dir("shop") / "model.json").write_text(json.dumps(_shop()))
    assert cli.main(["build", "--c4", "--name", "shop", "--repo", str(tmp_path), "--out", "out"]) == 0
    assert (out / "shop-l7.drawio").read_text() == "y" and (out / "shop-1-context.drawio").is_file()


@pytest.mark.parametrize("flag", [["--side-file"], ["--replace"], ["--curated", "x.json"]])
def test_build_c4_refuses_l7_only_flags(tmp_path: Path, capsys, flag: list[str]) -> None:
    _model(_shop())
    assert _build(tmp_path, *flag) == 2
    assert capsys.readouterr().err.strip() == "--side-file/--curated/--replace do not apply to --c4"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("key", ["source", "elements", "relationships"])
def test_build_c4_model_without_a_required_key_fails_verify(tmp_path: Path, capsys, key: str) -> None:
    model = _shop()
    del model[key]
    _model(model)
    assert _build(tmp_path) == 1
    out = capsys.readouterr().out
    assert out.startswith("C4 model: 1 problem") and f"model: {key} is required" in out


def test_build_c4_without_model_exits_3(tmp_path: Path, cache: Path, capsys) -> None:
    assert _build(tmp_path) == 3
    assert capsys.readouterr().err.strip() == (
        f"no C4 model at {cache / 'model.json'}: run the curation (cartographer prompt --c4)")


def test_build_c4_terraform_model_needs_facts(tmp_path: Path, capsys) -> None:
    _model({**_shop(), "source": "terraform"})
    assert _build(tmp_path) == 2
    assert "cartographer extract" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_build_c4_fails_on_verify_errors(tmp_path: Path, capsys) -> None:
    model = _shop()
    del model["elements"][3]["technology"]
    _model(model)
    assert _build(tmp_path) == 1
    out = capsys.readouterr().out
    assert out.startswith("C4 model: 1 problem") and "api: container needs a technology" in out
    assert not (tmp_path / "out").exists()


def test_build_c4_rollup_conflict_exits_1(tmp_path: Path, capsys) -> None:
    model = _shop()
    model["relationships"].append(rel("r5", "auth", "db", "reads", technology="SQL"))
    _model(model)
    assert _build(tmp_path) == 1
    assert "api->db: relationships r2, r5 need a shared summary" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_build_c4_writes_nothing_when_draw_io_is_down(tmp_path: Path, capsys, monkeypatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "shop-c4-3-component-old.drawio").write_text("x")
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: False)
    _model(_shop())
    assert _build(tmp_path, "--drawio-url", "http://localhost:8080") == 5
    assert "no draw.io answers" in capsys.readouterr().err
    assert [p.name for p in out.iterdir()] == ["shop-c4-3-component-old.drawio"]
