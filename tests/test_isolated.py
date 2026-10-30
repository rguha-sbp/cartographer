from pathlib import Path

import pytest

from cartographer import tf_verify

FACTS = {
    "resources": [{"address": a} for a in ("aws_lambda_function.fn", "aws_dynamodb_table.tbl", "aws_kms_key.key")],
    "edges": [{"id": "f1", "src": "aws_lambda_function.fn", "dst": "aws_dynamodb_table.tbl", "kind": "iam", "detail": "rw"}],
    "hints": [],
}


def _node(node_id: str, tf: str) -> dict:
    return {"id": node_id, "tf": [tf], "service": "other", "group": None, "label": node_id}


def _curated() -> dict:
    return {
        "source": "terraform",
        "title": "t",
        "groups": [],
        "nodes": [
            _node("n_fn", "aws_lambda_function.fn"),
            _node("n_tbl", "aws_dynamodb_table.tbl"),
            _node("n_key", "aws_kms_key.key"),
        ],
        "externals": [],
        "edges": [],
        "omitted": [],
    }


def _isolated(report: str) -> str:
    return report.split("Isolated nodes")[1].split("\n\n")[0]


def test_isolated_node_lists_backing_fact_or_none() -> None:
    _, report = tf_verify.verify(FACTS, _curated(), Path("."))
    section = _isolated(report)
    assert "isolated 3" in report.splitlines()[0]
    assert "n_tbl: n_fn -> n_tbl [iam] f1 rw" in section
    assert "n_key: no fact connects it" in section


def test_connected_nodes_are_not_isolated() -> None:
    curated = _curated()
    curated["nodes"].pop()
    curated["edges"] = [
        {"src": "n_fn", "dst": "n_tbl", "label": "x", "flow": "runtime", "evidence": [{"fact": "f1"}]}
    ]
    _, report = tf_verify.verify(FACTS, curated, Path("."))
    assert "isolated 0" in report.splitlines()[0]
    assert "Isolated nodes (0)" in report


def test_isolated_external_has_no_fact(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("call()\n")
    curated = _curated()
    ev = [{"file": "a.py", "line": 1, "contains": "call"}]
    curated["externals"] = [{"id": "x_user", "label": "u", "icon": "none", "group": None, "evidence": ev}]
    _, report = tf_verify.verify(FACTS, curated, tmp_path)
    assert "x_user: no fact connects it" in _isolated(report)


@pytest.mark.parametrize("strict,code", [(True, 1), (False, 0)])
def test_strict_exits_one_on_isolated(tmp_path: Path, monkeypatch, strict: bool, code: int) -> None:
    import json

    (tmp_path / "f.json").write_text(json.dumps(FACTS))
    (tmp_path / "c.json").write_text(json.dumps(_curated()))
    argv = ["v", str(tmp_path), str(tmp_path / "f.json"), str(tmp_path / "c.json"), "-o", str(tmp_path / "o.json")]
    monkeypatch.setattr("sys.argv", argv + (["--strict"] if strict else []))
    assert tf_verify.main() == code


def test_uses_fact_connects_isolated_node_but_not_unshown_section() -> None:
    facts = {
        "resources": [{"address": a} for a in ("aws_lambda_function.fn", "module.monitors")],
        "edges": [{"id": "f9", "src": "module.monitors", "dst": "aws_lambda_function.fn", "kind": "uses", "detail": "m"}],
        "hints": [],
    }
    curated = _curated()
    curated["nodes"] = [_node("n_fn", "aws_lambda_function.fn"), _node("n_mon", "module.monitors")]
    _, report = tf_verify.verify(facts, curated, Path("."))
    assert "n_mon: n_mon -> n_fn [uses] f9 m" in _isolated(report)
    assert "unshown 0" in report.splitlines()[0]
