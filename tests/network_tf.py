"""Terraform snippets and helpers the network tests share."""
from pathlib import Path

import pytest

from cartographer import tf_extract


def two_modules(tmp_path: Path, a: str, b: str | None = None, root: str = 'module "a" { source = "./a" }\nmodule "b" { source = "./b" }\n') -> dict:
    """Facts of a root that calls modules `a` and `b`, with bodies `a` and `b` (`a` for both by default)."""
    for name, body in (("a", a), ("b", a if b is None else b)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "main.tf").write_text(body)
    (tmp_path / "main.tf").write_text(root)
    return tf_extract.extract(Path("."), tmp_path)


def tfe_state(workspace: str, organization: str = "acme", name: str = "net") -> str:
    return (f'data "tfe_outputs" "{name}" {{\n  organization = "{organization}"\n  workspace = "{workspace}"\n}}\n'
            f'resource "aws_security_group" "sg" {{ vpc_id = data.tfe_outputs.{name}.values.shared_vpc_id }}\n')


def placed_in(facts: dict, field: str = "address") -> dict[str, str]:
    network = {n["id"]: n[field] for n in facts["networks"]}
    return {p["resource"]: network[p["network"]] for p in facts["placements"]}


def vpc_networks(tmp_path: Path, tf: str) -> list[tuple[str, bool]]:
    (tmp_path / "main.tf").write_text(tf)
    return [(n["address"], n["remote"]) for n in tf_extract.extract(Path("."), tmp_path)["networks"]]


def extract_tf(tmp_path: Path, tf: str) -> dict:
    (tmp_path / "main.tf").write_text(tf)
    return tf_extract.extract(Path("."), tmp_path)


S3_STATE = ('data "terraform_remote_state" "net" {\n  backend = "s3"\n'
            '  config = {\n    bucket = "tf"\n    key = "network.tfstate"\n  }\n}\n')


def mark_reason(facts: dict, address: str) -> str | None:
    return next(r.get("reason") for r in facts["resources"] if r["address"] == address)


def count_calls(monkeypatch: pytest.MonkeyPatch, owner: object, name: str, limit: int) -> None:
    """Fail the test when `owner.name` runs more than `limit` times, so an exponential walk fails fast."""
    calls = 0
    real = getattr(owner, name)

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert calls <= limit, f"{name} ran more than {limit} times"
        return real(*args, **kwargs)
    monkeypatch.setattr(owner, name, counted)


TRS = 'data "terraform_remote_state" "{0}" {{\n  backend = "s3"\n  config = {{ bucket = "b", key = "{0}.tfstate" }}\n}}\n'
