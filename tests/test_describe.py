import copy
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from cartographer import cli, files, snapshot, svg_export, tf_verify, tfdiagram, verify_description

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "password = hunter2hunter2"
ASSUMPTION = "payments go through a queue nobody mentioned"


def _node(node_id: str, label: str, service: str) -> dict:
    return {"id": node_id, "label": label, "service": service, "group": None, "tf": [], "multi": False}


def _edge(src: str, dst: str, label: str, *, flow: str = "web", dashed: bool = False) -> dict:
    return {"src": src, "dst": dst, "label": label, "flow": flow, "dashed": dashed,
            "evidence": [{"stated": "the engineer described this call"}]}


def _shop() -> dict:
    return {
        "source": "description",
        "system": "Shop",
        "view": "l7",
        "groups": [],
        "nodes": [
            _node("cdn", "CloudFront\nweb delivery", "cloudfront"),
            _node("api", "API Gateway\nshop API", "api_gateway"),
            _node("fn", "Lambda\norder logic", "lambda"),
            _node("tbl", "DynamoDB\norders", "dynamodb"),
        ],
        "externals": [
            {"id": "user", "label": "Customer\nbrowser", "icon": "user", "evidence": [{"stated": "customers buy online"}]},
            {"id": "psp", "label": "Payment provider\nSaaS", "icon": "generic_application",
             "evidence": [{"stated": "payments use an external provider"}]},
        ],
        "edges": [
            _edge("user", "cdn", "browses, HTTPS"),
            _edge("cdn", "api", "forwards, HTTPS"),
            _edge("api", "fn", "invokes, HTTPS", flow="runtime"),
            _edge("fn", "tbl", "reads, writes", flow="data"),
            _edge("fn", "psp", "charges, HTTPS", flow="runtime", dashed=True),
        ],
        "assumptions": [{"about": "fn->psp", "guess": ASSUMPTION}],
    }


def _verify(curated: dict, repo: Path = Path(".")) -> tuple[dict, str]:
    return verify_description.verify(curated, repo)


def test_a_valid_description_verifies_clean() -> None:
    verified, report = _verify(_shop())
    assert report.splitlines()[0].startswith("verify: nodes 4/4, externals 2/2, edges 5/5, dropped 0")
    assert not tf_verify.needs_attention(_shop(), verified)


def test_fact_evidence_is_rejected_in_a_description() -> None:
    curated = _shop()
    curated["edges"][0]["evidence"] = [{"fact": "f1"}]
    verified, report = _verify(curated)
    assert len(verified["edges"]) == 4
    assert "fact evidence is for Terraform diagrams" in report


def test_file_evidence_is_checked_against_the_repo(tmp_path: Path) -> None:
    (tmp_path / "design.md").write_text("# Design\nThe API Gateway invokes the Lambda\n")
    curated = _shop()
    curated["edges"][2]["evidence"] = [{"file": "design.md", "line": 2, "contains": "invokes the Lambda"}]
    assert len(_verify(curated, tmp_path)[0]["edges"]) == 5
    curated["edges"][2]["evidence"] = [{"file": "design.md", "line": 2, "contains": "queue"}]
    assert len(_verify(curated, tmp_path)[0]["edges"]) == 4


def test_stated_evidence_over_200_characters_is_rejected() -> None:
    curated = _shop()
    curated["edges"][0]["evidence"] = [{"stated": "x" * 201}]
    assert len(_verify(curated)[0]["edges"]) == 4


def test_a_node_with_tf_addresses_is_dropped_in_a_description() -> None:
    curated = _shop()
    curated["nodes"][0]["tf"] = ["aws_cloudfront_distribution.cdn"]
    verified, report = _verify(curated)
    assert [n["id"] for n in verified["nodes"]] == ["api", "fn", "tbl"]
    assert "cdn: tf addresses are for Terraform diagrams" in report


def test_duplicate_ids_are_dropped() -> None:
    curated = _shop()
    curated["externals"][0]["id"] = "fn"
    verified, report = _verify(curated)
    assert [x["id"] for x in verified["externals"]] == ["psp"]
    assert "fn: duplicate id" in report


def test_an_edge_to_an_unknown_endpoint_is_dropped() -> None:
    curated = _shop()
    curated["edges"].append(_edge("fn", "ghost", "calls, HTTPS"))
    assert "endpoint dropped or unknown (ghost)" in _verify(curated)[1]


def test_an_isolated_node_needs_attention() -> None:
    curated = _shop()
    curated["nodes"].append(_node("orphan", "SQS\nqueue", "sqs"))
    verified, report = _verify(curated)
    assert "orphan: " in report.split("Isolated nodes")[1]
    assert tf_verify.needs_attention(curated, verified)


@pytest.mark.parametrize("where", ["stated", "guess", "label"])
def test_the_secret_guard_covers_stated_text_and_assumptions(where: str) -> None:
    curated = _shop()
    if where == "stated":
        curated["edges"][0]["evidence"] = [{"stated": SECRET}]
    elif where == "guess":
        curated["assumptions"][0]["guess"] = SECRET
    else:
        curated["nodes"][0]["label"] = SECRET
    verified, report = _verify(curated)
    assert "looks like a secret" in report
    assert SECRET not in json.dumps(verified)
    assert tf_verify.needs_attention(curated, verified)


def test_assumptions_name_a_node_an_external_or_an_edge() -> None:
    curated = _shop()
    curated["assumptions"] = [
        {"about": "fn", "guess": "a"},
        {"about": "psp", "guess": "b"},
        {"about": "api->fn", "guess": "c"},
        {"about": "fn->nowhere", "guess": "d"},
    ]
    verified, report = _verify(curated)
    assert [a["about"] for a in verified["assumptions"]] == ["fn", "psp", "api->fn"]
    assert "fn->nowhere: unknown node, external or edge" in report
    assert tf_verify.needs_attention(curated, verified)


def _terraform() -> dict:
    return {
        "source": "terraform", "system": "T", "view": "l7", "groups": [], "externals": [], "edges": [], "omitted": [],
        "nodes": [{**_node("fn", "fn", "other"), "tf": ["aws_lambda_function.fn"]}],
    }


FACTS = {"resources": [{"address": "aws_lambda_function.fn"}], "edges": [], "hints": []}


def test_terraform_rejects_stated_evidence_and_empty_tf_and_duplicate_ids() -> None:
    curated = _terraform()
    curated["nodes"] += [{**curated["nodes"][0]}, {**_node("b", "b", "other"), "tf": []}]
    curated["externals"] = [{"id": "x", "label": "x", "icon": "none", "evidence": [{"stated": "said so"}]}]
    verified, report = tf_verify.verify(FACTS, curated, Path("."))
    assert [n["id"] for n in verified["nodes"]] == ["fn"]
    assert verified["externals"] == []
    for needle in ("fn: duplicate id", "b: needs at least one tf address", "stated evidence is for described diagrams"):
        assert needle in report


def test_terraform_also_checks_assumption_targets() -> None:
    curated = _terraform()
    curated["assumptions"] = [{"about": "nope", "guess": "g"}]
    assert tf_verify.verify(FACTS, curated, Path("."))[0]["assumptions"] == []


@pytest.fixture(autouse=True)
def cache(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path / "cache" / "cartographer" / "shop-l7"


@pytest.fixture
def renderer(monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "drawio_up", lambda url: True)
    monkeypatch.setattr(svg_export, "export_svg", lambda mxfile, url: f"<svg>{files.sha256_text(mxfile)}</svg>")


def _write(repo: Path, curated: dict) -> Path:
    folder = repo / "docs" / "architecture" / "diagrams"
    folder.mkdir(parents=True)
    path = folder / "shop-l7.curated.json"
    path.write_text(json.dumps(curated))
    return path


def test_build_a_description_needs_no_facts(cache: Path, tmp_path: Path, renderer) -> None:
    curated = _write(tmp_path, _shop())
    assert not (cache / "facts.json").exists()
    assert cli.main(["build", "--name", "shop-l7", "--repo", str(tmp_path)]) == 0
    folder = curated.parent
    drawio = folder / "shop-l7.drawio"
    root = ElementTree.parse(drawio).getroot()
    assert root[0].get("name") == "Layer 7 diagram for Shop"
    assert (folder / "shop-l7.svg").read_text() == f"<svg>{files.sha256_file(drawio)}</svg>"
    assert json.loads(curated.read_text())["drawio_sha256"] == files.sha256_file(drawio)
    assert "[shop-l7.drawio](shop-l7.drawio)" in (folder / "README.md").read_text()
    assert ASSUMPTION not in drawio.read_text() and "assum" not in drawio.read_text().lower()
    assert not (cache / "facts.json").exists()


def test_build_a_description_rebuilds_without_a_staleness_key(tmp_path: Path, renderer) -> None:
    _write(tmp_path, _shop())
    assert cli.main(["build", "--name", "shop-l7", "--repo", str(tmp_path)]) == 0
    assert cli.main(["build", "--name", "shop-l7", "--repo", str(tmp_path)]) == 0


def test_build_a_description_fails_on_a_verify_drop(tmp_path: Path, capsys) -> None:
    broken = copy.deepcopy(_shop())
    broken["edges"][0]["evidence"] = [{"fact": "f1"}]
    _write(tmp_path, broken)
    assert cli.main(["build", "--name", "shop-l7", "--repo", str(tmp_path)]) == 1
    assert "fact evidence is for Terraform diagrams" in capsys.readouterr().out


def test_build_refuses_a_curated_file_without_a_valid_source(tmp_path: Path, capsys) -> None:
    curated = _shop()
    del curated["source"]
    _write(tmp_path, curated)
    assert cli.main(["build", "--name", "shop-l7", "--repo", str(tmp_path)]) == 1
    assert "source" in capsys.readouterr().err


def test_terraform_build_still_needs_facts(tmp_path: Path, capsys) -> None:
    _write(tmp_path, _terraform())
    assert cli.main(["build", "--name", "shop-l7", "--repo", str(tmp_path)]) == 2
    assert "cartographer extract" in capsys.readouterr().err


def test_describe_prompt_needs_no_facts(cache: Path, tmp_path: Path, capsys) -> None:
    assert cli.main(["prompt", "--name", "shop-l7", "--describe", "--repo", str(tmp_path)]) == 0
    prompt = capsys.readouterr().out
    assert (cache / "curated.schema.json").read_text() == tfdiagram.schema_text()
    folder = tmp_path.resolve() / "docs/architecture/diagrams"
    for needle in (str(cache / "curated.schema.json"), str(folder / "shop-l7.curated.json"),
                   str(cli.DOCS["interview"]), '"source": "description"', "assumptions", "stated"):
        assert needle in prompt
    assert "{" + "output_path}" not in prompt


def test_docs_interview_prints_the_playbook_path(capsys) -> None:
    assert cli.main(["docs", "interview"]) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.name == "INTERVIEW.md" and path.read_text().count("\n") < 130


def test_the_schema_describes_sources_stated_evidence_and_assumptions() -> None:
    schema = json.loads(tfdiagram.schema_text())
    assert schema["properties"]["source"]["enum"] == ["terraform", "description"]
    assert "source" in schema["required"]
    arms = schema["$defs"]["evidence"]["oneOf"]
    stated = next(a for a in arms if "stated" in a["properties"])
    assert stated["properties"]["stated"]["maxLength"] == 200 and stated["additionalProperties"] is False
    assert "minItems" not in schema["properties"]["nodes"]["items"]["properties"]["tf"]
    item = schema["properties"]["assumptions"]["items"]
    assert item["required"] == ["about", "guess"] and item["additionalProperties"] is False
    assert "src->dst" in schema["properties"]["assumptions"]["description"]
