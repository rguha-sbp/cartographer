from pathlib import Path

from cartographer import tfdiagram


def _key(tmp_path: Path, facts_dir: str, facts: bytes) -> str:
    path = tmp_path / facts_dir / "facts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(facts)
    return tfdiagram.inputs_sha256(path)


def test_key_ignores_paths(tmp_path: Path) -> None:
    assert _key(tmp_path, "a", b"{}") == _key(tmp_path, "b/deeper", b"{}")


def test_key_changes_with_facts(tmp_path: Path) -> None:
    assert _key(tmp_path, "a", b'{"x": 1}') != _key(tmp_path, "a", b"{}")
