from pathlib import Path

from cartographer import tf_extract, tf_verify

REPO = Path(__file__).parent / "fixtures" / "hints"


def _hints() -> dict[tuple[str, str], dict]:
    facts = tf_extract.extract(Path("infra"), REPO)
    return {(h["kind"], h["value"]): h for h in facts["hints"]}


def _curated(externals: list[dict], omitted: list[dict]) -> dict:
    return {"source": "terraform", "title": "t", "groups": [], "nodes": [], "externals": externals, "edges": [], "omitted": omitted}


def _unaccounted(curated: dict) -> str:
    facts = tf_extract.extract(Path("infra"), REPO)
    report = tf_verify.verify(facts, curated, REPO)[1]
    return report.split("Unaccounted integration hints")[1]


def test_code_hints_from_archive_file_source_dir() -> None:
    hints = _hints()
    host = hints[("host", "example.okta.com")]
    assert host["file"] == "src/app/event_processors/okta/client.py"
    assert host["line"] == 3
    assert host["owner"] == "aws_lambda_function.app"
    assert hints[("param", "/app/okta/token")]["count"] == 2
    assert ("module", "okta") in hints


def test_code_hints_from_manifest_source_tree() -> None:
    hints = _hints()
    assert hints[("module", "servicenow")]["owner"] == "module.acme_publisher"
    assert ("host", "api.servicenow.example.com") in hints


def test_terraform_hints() -> None:
    hints = _hints()
    assert hints[("host", "billing.vendor.example.org")]["file"] == "infra/main.tf"
    assert hints[("param", "/app/stripe/key")]["owner"] == "aws_ssm_parameter.stripe_key"


def test_skips_tests_vendored_aws_and_schema_hosts() -> None:
    hosts = {v for k, v in _hints() if k == "host"}
    assert not {h for h in hosts if "invalid" in h or "amazonaws" in h or "json-schema" in h}


def test_hint_cap_records_cut(monkeypatch) -> None:
    monkeypatch.setattr("cartographer.tf_hints.HINT_CAP", 1)
    facts = tf_extract.extract(Path("infra"), REPO)
    assert sum(h["kind"] == "host" for h in facts["hints"]) == 1
    assert facts["hints_cut"]["host"] >= 2


def test_verify_reports_ignored_hint() -> None:
    assert "example.okta.com" in _unaccounted(_curated([], []))


def test_verify_accepts_omitted_and_cited() -> None:
    facts = tf_extract.extract(Path("infra"), REPO)
    omitted = [{"hint": h["value"], "reason": "not an external"} for h in facts["hints"]]
    assert "(0)" in _unaccounted(_curated([], omitted)).splitlines()[0]
    cited = [{"id": "okta", "label": "Okta", "icon": "none", "evidence": [
        {"file": "src/app/event_processors/okta/client.py", "line": 3, "contains": "https://example.okta.com/api/v1"}]}]
    report = _unaccounted(_curated(cited, []))
    assert "host example.okta.com" not in report
    assert "module okta" not in report
    assert "param /app/okta/token" in report
