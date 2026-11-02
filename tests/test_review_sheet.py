import json
from pathlib import Path

from cartographer import review_sheet, tf_layout
from cartographer.diagram_model import Icon

FACTS = {"resources": [{"address": "aws_s3_bucket.a", "type": "aws_s3_bucket", "file": "s3.tf", "line": 3}]}
VERIFIED = {
    "format": 2, "title": "Layer 7 diagram for Shop", "view": "l7",
    "groups": [{"id": "cloud", "label": "AWS Cloud", "kind": "cloud", "cloud": "aws", "parent": None, "column": 0},
               {"id": "region", "label": "eu-west-1", "kind": "region", "cloud": "aws", "parent": "cloud", "column": 0},
               {"id": "app", "label": "App", "kind": None, "parent": "region", "column": 0}],
    "nodes": [{"id": "a", "label": "Bucket", "icon": "aws:s3", "group": "app", "tf": ["aws_s3_bucket.a"],
               "multi": False, "decided_by": "catalog aws_s3_bucket", "marked": False}],
    "externals": [{"id": "user", "label": "Shopper", "icon": "generic:user", "evidence": []}],
    "edges": [{"src": "user", "dst": "a", "label": "browse", "flow": "web", "dashed": False, "evidence": []}],
}


def test_review_sheet_has_one_entry_per_drawn_icon(tmp_path: Path) -> None:
    diagram = tf_layout.layout(VERIFIED)
    path = review_sheet.write(tmp_path, VERIFIED, FACTS, diagram)
    sheet = json.loads(path.read_text())
    ids = [i["id"] for i in sheet["icons"]]
    assert path == tmp_path / "review.json"
    assert sorted(ids) == sorted(n.id for n in diagram.nodes if isinstance(n, Icon))
    assert len(ids) == len(set(ids))
    bucket = next(i for i in sheet["icons"] if i["id"] == "a")
    assert bucket["frame"] == "AWS Cloud > eu-west-1 > App"
    assert bucket["tf"] == [{"address": "aws_s3_bucket.a", "type": "aws_s3_bucket", "file": "s3.tf", "line": 3}]
    assert bucket["icon_title"] and bucket["tiles"] == []
    assert sheet["view"] == "l7" and sheet["view_name"].startswith("Layer 7: ") and sheet["clouds"] == ["aws"]
