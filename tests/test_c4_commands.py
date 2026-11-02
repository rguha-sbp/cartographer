import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from cartographer import c4_model, cli, files, snapshot, svg_export
from cartographer.workdir import cache_dir

FIXTURES = Path(__file__).parent / "fixtures"
NAME = "shop-c4"
STATED = [{"stated": "the engineer said so"}]
SLUGS = ["1-context", "2-container", "3-component-api", "6-dynamic-buy"]
DRAWIO = "shop-c4-c4.drawio"
IMAGES = [f"shop-c4-c4-{slug}.svg" for slug in SLUGS]


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


def test_build_c4_writes_one_file_with_a_page_and_an_image_per_view(tmp_path: Path, capsys, renderer) -> None:
    _model(_shop())
    assert _build(tmp_path) == 0
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == sorted(["README.md", DRAWIO, *IMAGES])
    drawio = out / DRAWIO
    pages = ElementTree.parse(drawio).getroot().findall("diagram")
    assert [p.get("id") for p in pages] == [f"{NAME}-{slug}" for slug in SLUGS]
    assert pages[1].get("name") == "Container diagram for Shop"
    for image in IMAGES:
        assert (out / image).read_text() == f"<svg>{files.sha256_file(drawio)}</svg>"
    readme = (out / "README.md").read_text()
    assert f"| Container diagram for Shop | [{DRAWIO}]({DRAWIO}) | [{IMAGES[1]}]({IMAGES[1]}) |" in readme


def test_build_c4_draws_each_image_from_its_view_alone(tmp_path: Path, monkeypatch, renderer) -> None:
    drawn = []
    monkeypatch.setattr(svg_export, "export_svg", lambda mxfile, sha, url: drawn.append(mxfile) or "<svg/>")
    _model(_shop())
    assert _build(tmp_path) == 0
    assert [ElementTree.fromstring(m).find("diagram").get("id") for m in drawn] == [f"{NAME}-{s}" for s in SLUGS]
    assert all(len(ElementTree.fromstring(m).findall("diagram")) == 1 for m in drawn)


def test_build_c4_prints_every_written_path(tmp_path: Path, capsys, renderer) -> None:
    _model(_shop())
    assert _build(tmp_path) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "C4 model: ok"
    out = tmp_path / "out"
    assert lines[-5:] == [str(out / name) for name in (DRAWIO, *IMAGES)]


def test_build_c4_lists_what_rests_only_on_stated(tmp_path: Path, capsys, renderer) -> None:
    _model(_shop())
    assert _build(tmp_path) == 0
    out = capsys.readouterr().out
    assert out.startswith("C4 model: ok\n")
    assert "Stated by the engineer, not found in the repo (8)\n  api\n  auth\n  cart\n  db\n  r1\n" in out


def test_build_c4_overwrites_without_asking(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / DRAWIO).write_text("edited by hand")
    _model(_shop())
    assert _build(tmp_path) == 0
    assert "System Context diagram for Shop" in (out / DRAWIO).read_text()


def test_build_deletes_stale_views_only_of_this_model(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    keep = ["gip.drawio", "shop-c4.drawio", "shop-c4-old.generated.drawio", "shop-c5-1-context.drawio",
            "shop-c4-legacy.drawio", "shop-l7.drawio", "shop-c4-c4-3-component-old.drawio", "shop-c4-c4-notes.svg"]
    stale = ["shop-c4-3-component-old.drawio", "shop-c4-3-component-old.svg", "shop-c4-1-context.drawio",
             "shop-c4-1-context.svg", "shop-c4-c4-3-component-old.svg"]
    for name in keep + stale:
        (out / name).write_text("y")
    _model(_shop())
    assert _build(tmp_path) == 0
    assert not any((out / name).exists() for name in stale)
    assert all((out / name).read_text() == "y" for name in keep)
    assert "[gip.drawio](gip.drawio)" in (out / "README.md").read_text()


def test_build_c4_of_model_shop_keeps_its_l7_diagram(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "shop-l7.drawio").write_text("y")
    (cache_dir("shop") / "model.json").write_text(json.dumps(_shop()))
    assert cli.main(["build", "--c4", "--name", "shop", "--repo", str(tmp_path), "--out", "out"]) == 0
    assert (out / "shop-l7.drawio").read_text() == "y" and (out / "shop-c4.drawio").is_file()


def test_build_c4_deletes_only_names_a_view_can_have(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    keep = ["shop-3-tier.drawio", "shop-1-contexts.drawio", "shop-3-component-.drawio", "shop-4-code-A.drawio",
            "shop-6-dynamic-x.generated.drawio", "shop-2-container-v2.drawio"]
    stale = ["shop-5-deployment.drawio", "shop-4-code-old_k.drawio", "shop-6-dynamic-pay.drawio",
             "shop-c4-6-dynamic-pay.svg"]
    keep += ["shop-c4-1-context.drawio", "shop-c4-3-tier.svg", "shop-c4-1-contexts.svg"]
    for name in keep + stale:
        (out / name).write_text("y")
    (cache_dir("shop") / "model.json").write_text(json.dumps(_shop()))
    assert cli.main(["build", "--c4", "--name", "shop", "--repo", str(tmp_path), "--out", "out"]) == 0
    assert all((out / name).read_text() == "y" for name in keep)
    assert not any((out / name).exists() for name in stale)


def test_build_c4_escapes_the_name(tmp_path: Path, renderer) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "shopx-1-context.drawio").write_text("y")
    (out / "shopx-c4-1-context.svg").write_text("y")
    (cache_dir("shop[x]") / "model.json").write_text(json.dumps(_shop()))
    assert cli.main(["build", "--c4", "--name", "shop[x]", "--repo", str(tmp_path), "--out", "out"]) == 0
    assert (out / "shopx-1-context.drawio").read_text() == "y" and (out / "shopx-c4-1-context.svg").read_text() == "y"


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
    assert out.startswith("C4 model: 1 problem") and f"model: missing '{key}'" in out


def test_build_c4_does_not_list_empty_evidence_as_stated(tmp_path: Path, capsys) -> None:
    model = _shop()
    model["elements"][3]["evidence"] = []
    _model(model)
    assert _build(tmp_path) == 1
    out = capsys.readouterr().out
    assert out == "C4 model: 1 problem\nelements[3].evidence: needs at least 1 item\n"


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
