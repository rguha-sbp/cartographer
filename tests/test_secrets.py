from pathlib import Path

import pytest

from cartographer import secret_patterns, tf_verify

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
SAMPLES = [
    AWS_KEY,
    "ASIA" + "ABCDEFGHIJKLMNOP",
    "-----BEGIN RSA PRIVATE KEY-----",
    "ghp_" + "a" * 20,
    "gho_" + "a" * 20,
    "github_pat_" + "a" * 20,
    "xoxb-" + "1234-abcd",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.sig",
    'password = "hunter2hunter2"',
    "api_key: abcdefgh1234",
]


@pytest.mark.parametrize("text", SAMPLES)
def test_patterns_match(text: str) -> None:
    assert secret_patterns.looks_like_secret(text)


@pytest.mark.parametrize("text", ["reads, SQL", "token_endpoint = var.x", "password = x", "AKIA short"])
def test_patterns_ignore_normal_text(text: str) -> None:
    assert not secret_patterns.looks_like_secret(text)


FACTS = {
    "resources": [{"address": a} for a in ("aws_lambda_function.fn", "aws_dynamodb_table.tbl")],
    "edges": [],
    "hints": [],
}


def _node(node_id: str, tf: str, label: str) -> dict:
    return {"id": node_id, "tf": [tf], "service": "other", "group": None, "label": label}


def _curated(node_label: str = "fn", edge_label: str = "reads, SQL", contains: str = "x = 1") -> dict:
    return {
        "title": "t",
        "groups": [],
        "nodes": [
            _node("n_fn", "aws_lambda_function.fn", node_label),
            _node("n_tbl", "aws_dynamodb_table.tbl", "tbl"),
        ],
        "externals": [],
        "edges": [
            {
                "src": "n_fn", "dst": "n_tbl", "flow": "data", "label": edge_label, "dashed": False,
                "evidence": [{"file": "a.py", "line": 1, "contains": contains}],
            }
        ],
        "omitted": [],
    }


def _repo(tmp_path: Path, line: str) -> Path:
    (tmp_path / "a.py").write_text(line + "\n")
    return tmp_path


def test_clean_curation_drops_nothing(tmp_path: Path) -> None:
    _, report = tf_verify.verify(FACTS, _curated(), _repo(tmp_path, "x = 1"))
    assert "dropped 0" in report.splitlines()[0]


def test_secret_in_evidence_drops_edge_and_hides_value(tmp_path: Path) -> None:
    repo = _repo(tmp_path, f"key = '{AWS_KEY}'")
    out, report = tf_verify.verify(FACTS, _curated(contains=AWS_KEY), repo)
    assert out["edges"] == []
    assert "looks like a secret" in report
    assert AWS_KEY not in report


def test_secret_in_edge_label_drops_edge(tmp_path: Path) -> None:
    out, report = tf_verify.verify(FACTS, _curated(edge_label="token: abcdefgh1234"), _repo(tmp_path, "x = 1"))
    assert out["edges"] == []
    assert "abcdefgh1234" not in report


def test_secret_in_node_label_drops_node(tmp_path: Path) -> None:
    out, report = tf_verify.verify(FACTS, _curated(node_label=AWS_KEY), _repo(tmp_path, "x = 1"))
    assert [n["id"] for n in out["nodes"]] == ["n_tbl"]
    assert AWS_KEY not in report
    assert "dropped 2" in report.splitlines()[0]
