from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "cartographer"
PATTERNS = ('"aws_', "'aws_", '"azurerm', '"azapi', '== "aws"', '== "azure"')
ALLOWED = {"curated_format.py"}  # format 1 is AWS by definition


def test_core_has_no_cloud_checks() -> None:
    hits = [f"{path.name}: {pattern}" for path in sorted(SRC.glob("*.py")) if path.name not in ALLOWED
            for pattern in PATTERNS if pattern in path.read_text(encoding="utf-8")]
    assert hits == []
