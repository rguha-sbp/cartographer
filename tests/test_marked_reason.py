import json
from pathlib import Path

from cartographer import build, review_sheet, tf_layout, tf_verify
from cartographer.verify_shared import declared_icon

LB = {"icon": "azure:load_balancers", "marked": True, "decided_by": "rule azurerm_lb frontend_ip_configuration absent",
      "reason": "frontend_ip_configuration absent"}


def test_a_marked_fact_resolution_keeps_its_reason() -> None:
    node = {"id": "lb", "tf": ["azurerm_lb.lb"]}
    tf_verify._facts_icon(node, {"azurerm_lb.lb": LB})
    assert node["reason"] == "frontend_ip_configuration absent"


def test_an_unmarked_fact_resolution_carries_no_reason() -> None:
    node = {"id": "lb", "tf": ["azurerm_lb.lb"]}
    tf_verify._facts_icon(node, {"azurerm_lb.lb": {"icon": "azure:load_balancers", "marked": False}})
    assert "reason" not in node


def test_a_marked_declared_resolution_keeps_its_reason() -> None:
    item = {"id": "fn", "tf_type": "azurerm_kubernetes_cluster_brand_new"}
    declared_icon(item)
    assert item["reason"] == "type newer than provider list"


def test_the_marked_report_line_includes_the_reason() -> None:
    verified = {"nodes": [{"id": "lb", "icon": "azure:load_balancers", "decided_by": "rule", "marked": True,
                           "reason": "frontend_ip_configuration absent"}], "externals": []}
    assert build._marked(verified) == ["lb: azure:load_balancers (rule) frontend_ip_configuration absent"]


def test_review_json_entries_include_the_reason(tmp_path: Path) -> None:
    verified = {
        "format": 2, "title": "t", "view": "l7", "groups": [],
        "nodes": [{"id": "a", "label": "Bucket", "icon": "aws:s3", "group": None, "tf": [], "multi": False, "marked": True,
                   "reason": "engine is not a literal"}],
        "externals": [], "edges": [],
    }
    sheet = json.loads(review_sheet.write(tmp_path, verified, None, tf_layout.layout(verified)).read_text())
    assert sheet["icons"][0]["reason"] == "engine is not a literal"
