from pathlib import Path

from cartographer import tf_extract

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_finds_resources_and_iam_edge() -> None:
    facts = tf_extract.extract(Path("mini"), FIXTURES)
    addresses = {r["address"] for r in facts["resources"]}
    assert {"aws_lambda_function.fn", "aws_s3_bucket.data"} <= addresses
    edges = [(e["src"], e["dst"], e["kind"]) for e in facts["edges"]]
    assert ("aws_lambda_function.fn", "aws_s3_bucket.data", "iam") in edges
