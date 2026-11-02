import copy

from cartographer import c4_views
from cartographer.c4_verify import report, stated_only, verify

FACT = [{"fact": "f1"}]
STATED = [{"stated": "the engineer said so"}]


def el(eid, kind, parent=None, **extra):
    base = {"id": eid, "type": kind, "name": eid, "description": "d", "evidence": FACT}
    return base | ({"parent": parent} if parent else {}) | extra


def rel(rid, src, dst, label, **extra):
    return {"id": rid, "src": src, "dst": dst, "label": label, "dashed": False, "technology": "SQL",
            "evidence": STATED} | extra


def _valid():
    return {
        "source": "description",
        "elements": [
            el("u", "person", evidence=STATED),
            el("s", "system", evidence=STATED),
            el("api", "container", "s", technology="Python", evidence=STATED),
            el("db", "container", "s", technology="Postgres", evidence=STATED),
        ],
        "relationships": [rel("r1", "api", "db", "reads")],
    }


def _tf():
    m = _valid()
    m["source"] = "terraform"
    m["relationships"] = [rel("r1", "api", "db", "reads", evidence=[{"fact": "f1"}])]
    m["deployment"] = {
        "environment": "prod",
        "nodes": [
            {"id": "n1", "name": "fn", "technology": "Lambda", "evidence": FACT, "tf": ["aws_lambda_function.fn"]},
            {"id": "n2", "name": "db", "technology": "RDS", "evidence": FACT, "tf": ["aws_db_instance.db"]},
        ],
        "instances": [{"container": "api", "node": "n1"}, {"container": "db", "node": "n2"}],
    }
    return m


def _facts(*resources, edges=()):
    return {"resources": [{"address": a, "type": a.split(".")[0]} for a in resources], "edges": list(edges)}


def _edge(src, dst):
    return {"id": "f1", "src": src, "dst": dst, "kind": "uses"}


def test_valid_model_passes(tmp_path):
    assert verify(_valid(), None, tmp_path) == []


def test_container_without_technology_fails(tmp_path):
    m = _valid()
    del m["elements"][2]["technology"]
    assert "api: container needs a technology" in verify(m, None, tmp_path)


def test_structure_errors_do_not_crash(tmp_path):
    m = _valid()
    m["elements"].append({**m["elements"][0]})
    m["relationships"].append(rel("r9", "api", "s", "x"))
    errs = verify(m, None, tmp_path)
    assert any("duplicate id" in e for e in errs)
    assert any("r9: ends are ancestor and descendant" in e for e in errs)


def test_parent_cycle_is_an_error_not_a_hang(tmp_path):
    m = _valid()
    m["elements"] += [el("c1", "component", "c2", evidence=STATED), el("c2", "component", "c1", evidence=STATED)]
    assert any(e.startswith("c1: parent cycle") for e in verify(m, None, tmp_path))


def test_missing_parent_and_wrong_parent_type(tmp_path):
    m = _valid()
    m["elements"] += [el("x", "container", "nope", technology="t"), el("y", "component", "s", technology="t")]
    errs = verify(m, None, tmp_path)
    assert "x: parent nope does not exist" in errs
    assert "y: component needs a container as parent" in errs


def test_in_scope_system_must_be_unique(tmp_path):
    m = _valid()
    m["elements"].append(el("s2", "system", evidence=STATED))
    assert any("exactly one in-scope system" in e for e in verify(m, None, tmp_path))


def test_relationship_rules(tmp_path):
    m = _valid()
    m["relationships"] += [
        rel("r2", "api", "api", "self"),
        rel("r3", "api", "ghost", "x"),
        rel("r4", "api", "db", "x", kind="inherits"),
        {**rel("r5", "api", "db", "x"), "id": "r1"},
    ]
    m["scenarios"] = [{"id": "sc", "name": "n", "steps": ["r1", "nope"]}]
    errs = verify(m, None, tmp_path)
    assert "r2: ends are the same element" in errs
    assert "r3: unknown end ghost" in errs
    assert "r4: kind inherits is only for code elements" in errs
    assert "r1: duplicate id" in errs
    assert "sc: step nope is not a relationship" in errs


def test_instance_and_node_parent_must_exist(tmp_path):
    m = _tf()
    m["deployment"]["instances"].append({"container": "ghost", "node": "n9"})
    m["deployment"]["nodes"][0]["parent"] = "nowhere"
    errs = verify(m, _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_lambda_function.fn", "aws_db_instance.db")]), tmp_path)
    assert "ghost: instance names no container" in errs
    assert "ghost: instance node n9 does not exist" in errs
    assert "n1: parent nowhere does not exist" in errs


def test_code_citation_must_match(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    m = _valid()
    m["relationships"][0]["evidence"] = [{"file": "a.py", "line": 1, "contains": "y = 2"}]
    assert any(e.startswith("r1: a.py:1 does not contain") for e in verify(m, None, tmp_path))
    m["relationships"][0]["evidence"] = [{"file": "a.py", "line": 1, "contains": "x = 1"}]
    assert verify(m, None, tmp_path) == []


def test_fact_needs_facts_and_known_id(tmp_path):
    m = _valid()
    m["elements"][2]["evidence"] = FACT
    assert "api: fact f1 needs Terraform facts" in verify(m, None, tmp_path)
    assert "api: fact f1 not found" in verify(m, _facts(), tmp_path)


def test_fact_must_join_the_hosting_nodes(tmp_path):
    m = _tf()
    good = _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_db_instance.db", "aws_lambda_function.fn")])
    assert verify(m, good, tmp_path) == []
    bad = copy.deepcopy(good)
    bad["edges"] = [_edge("aws_sqs_queue.q", "aws_db_instance.db")]
    assert any(e.startswith("r1: fact f1 does not join") for e in verify(m, bad, tmp_path))


def test_terraform_nodes_need_existing_addresses(tmp_path):
    m = _tf()
    m["deployment"]["nodes"][0]["tf"] = []
    errs = verify(m, _facts("aws_db_instance.db", edges=[_edge("a", "b")]), tmp_path)
    assert "n1: needs terraform addresses" in errs
    m = _tf()
    errs = verify(m, _facts("aws_db_instance.db", edges=[_edge("a", "b")]), tmp_path)
    assert "n1: aws_lambda_function.fn is not in the facts" in errs


def test_frames_may_have_no_terraform_addresses(tmp_path):
    m = _tf()
    m["deployment"]["nodes"].insert(0, {"id": "aws", "name": "AWS", "technology": "eu-west-1", "frame": "region",
                                         "evidence": [{"stated": "region from the provider block"}]})
    facts = _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_db_instance.db", "aws_lambda_function.fn")])
    assert not any(e.startswith("aws:") for e in verify(m, facts, tmp_path))


def test_compute_resource_missing_from_deployment_fails(tmp_path):
    m = _tf()
    facts = _facts("aws_lambda_function.fn", "aws_db_instance.db", "aws_lambda_function.other",
                   edges=[_edge("aws_lambda_function.fn", "aws_db_instance.db")])
    assert "aws_lambda_function.other: not on any view and not omitted" in verify(m, facts, tmp_path)


def test_omitted_resource_passes(tmp_path):
    m = _tf()
    m["omitted"] = [{"tf": "aws_lambda_function.other", "reason": "unused"}]
    facts = _facts("aws_lambda_function.fn", "aws_db_instance.db", "aws_lambda_function.other",
                   edges=[_edge("aws_lambda_function.fn", "aws_db_instance.db")])
    assert verify(m, facts, tmp_path) == []


def test_secret_in_text_fails(tmp_path):
    m = _valid()
    m["elements"][2]["description"] = "password = hunter2hunter2"
    m["assumptions"] = [{"about": "db", "guess": "password = hunter2hunter2"}]
    errs = verify(m, None, tmp_path)
    assert {"api: looks like a secret", "db: looks like a secret"} <= set(errs)


def test_no_in_scope_system_is_an_error_not_a_crash(tmp_path):
    m = _valid()
    m["elements"][1]["external"] = True
    assert "model: exactly one in-scope system is needed, found 0" in verify(m, None, tmp_path)


def test_report_first_line():
    assert report([], []).splitlines()[0] == "C4 model: ok"
    assert report(["a: b"], []).splitlines()[0] == "C4 model: 1 problem"


def test_report_lists_stated_only():
    text = report([], ["billing"])
    assert "Stated by the engineer, not found in the repo" in text and "billing" in text


def test_stated_only_lists_containers_without_repo_evidence():
    m = _valid()
    m["elements"][3]["evidence"] = STATED + FACT
    assert stated_only(m) == ["api", "r1"]


def test_stated_only_lists_relationships_and_deployment_nodes():
    m = _tf()
    m["elements"][2]["evidence"] = m["elements"][3]["evidence"] = FACT
    m["relationships"][0]["evidence"] = STATED
    m["deployment"]["nodes"][1]["evidence"] = STATED
    assert stated_only(m) == ["n2", "r1"]


def test_element_fact_must_touch_the_nodes_hosting_its_container(tmp_path):
    m = _tf()
    m["elements"] += [el("c1", "component", "api", technology="Py")]
    m["elements"][2]["evidence"] = FACT
    good = _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_lambda_function.fn", "aws_db_instance.db")])
    assert verify(m, good, tmp_path) == []
    bad = _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_sqs_queue.q", "aws_db_instance.db")])
    errs = verify(m, bad, tmp_path)
    assert "api: fact f1 does not join the deployment nodes hosting it" in errs
    assert "c1: fact f1 does not join the deployment nodes hosting it" in errs


def test_element_not_deployed_in_this_environment_may_cite_any_fact(tmp_path):
    m = _tf()
    m["elements"][2]["evidence"] = FACT
    m["deployment"]["instances"] = [i for i in m["deployment"]["instances"] if i["container"] != "api"]
    m["deployment"]["nodes"] = [n for n in m["deployment"]["nodes"] if n["id"] != "n1"]
    m["omitted"] = [{"tf": "aws_lambda_function.fn", "reason": "dev only"}]
    facts = _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_sqs_queue.q", "aws_db_instance.db")])
    assert not any(e.startswith("api: fact") for e in verify(m, facts, tmp_path))


def test_relationship_ending_at_a_system_with_containers_fails(tmp_path):
    m = _valid()
    m["relationships"].append(rel("r2", "u", "s", "uses"))
    assert "r2: ends at the system s; name the container it reaches" in verify(m, None, tmp_path)


def test_relationship_to_a_system_without_containers_passes(tmp_path):
    m = _valid()
    m["elements"] = [e for e in m["elements"] if e["type"] != "container"]
    m["relationships"] = [rel("r2", "u", "s", "uses")]
    assert verify(m, None, tmp_path) == []


def test_scenario_step_inside_one_container_fails(tmp_path):
    m = _valid()
    m["elements"] += [el("c1", "component", "api", technology="Py", evidence=STATED),
                      el("c2", "component", "api", technology="Py", evidence=STATED)]
    m["relationships"].append(rel("r2", "c1", "c2", "calls"))
    m["scenarios"] = [{"id": "sc", "name": "Sc", "steps": ["r1", "r2"]}]
    assert verify(m, None, tmp_path) == ["sc: step r2 stays inside container api"]


def test_missing_required_keys_are_errors_not_crashes(tmp_path):
    assert verify({"elements": []}, None, tmp_path) == ["model: missing 'relationships'", "model: missing 'source'"]


def test_deployment_node_with_an_unknown_icon_fails(tmp_path):
    m = _tf()
    m["deployment"]["nodes"][0]["service"] = "application_load_balancer"
    facts = _facts("aws_lambda_function.fn", "aws_db_instance.db", edges=[_edge("aws_db_instance.db", "aws_lambda_function.fn")])
    assert "n1: service 'application_load_balancer' is not a draw.io AWS icon, renders as a box" in verify(m, facts, tmp_path)


def test_relationship_no_core_view_draws_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(c4_views, "core", lambda model: [])
    assert verify(_valid(), None, tmp_path) == ["r1: drawn on no Context, Container, Component or Code view"]


def test_rollup_conflict_is_a_verify_error(tmp_path):
    m = _valid()
    m["elements"].append(el("c1", "component", "api", technology="Py", evidence=STATED))
    m["relationships"].append(rel("r2", "c1", "db", "writes"))
    assert verify(m, None, tmp_path) == ["api->db: relationships r1, r2 need a shared summary"]


def test_relationship_needs_a_label(tmp_path):
    m = _valid()
    m["relationships"][0]["label"] = " "
    assert verify(m, None, tmp_path) == ["r1: needs a label"]


def test_relationship_inside_the_system_needs_a_technology(tmp_path):
    m = _valid()
    del m["relationships"][0]["technology"]
    assert verify(m, None, tmp_path) == ["r1: needs a technology, both ends are inside the system"]


def test_relationship_from_a_person_needs_no_technology(tmp_path):
    m = _valid()
    m["relationships"].append({k: v for k, v in rel("r2", "u", "api", "uses").items() if k != "technology"})
    assert verify(m, None, tmp_path) == []


def test_code_inheritance_needs_no_technology(tmp_path):
    m = _valid()
    m["elements"] += [el("c1", "component", "api", technology="Py", evidence=STATED),
                      el("k1", "code", "c1", evidence=STATED), el("k2", "code", "c1", evidence=STATED)]
    m["relationships"].append({k: v for k, v in rel("r2", "k1", "k2", "extends", kind="inherits").items()
                               if k != "technology"})
    assert verify(m, None, tmp_path) == []
