"""AWS permission edges: IAM policies become `iam` edges from the principals that hold them to the resources they name."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from cartographer.tf_policies import doc_statements, policy_doc, unq
from cartographer.tf_values import attrs, text

if TYPE_CHECKING:
    from cartographer.tf_extract import Extractor
    from cartographer.tf_modules import Inst, Res

VAR_ONLY = re.compile(r"\$\{var\.(\w+)\}")
LOCAL_ONLY = re.compile(r"\$\{local\.(\w+)\}")
DATA_DOC = re.compile(r"data\.aws_iam_policy_document\.(\w+)")
ROLE_KEYS = {"role", "execution_role_arn", "role_arn"}
POLICY_TYPES = {"aws_iam_role_policy", "aws_iam_policy"}


def principals(ex: Extractor) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    by_role: dict[str, set[str]] = {}
    by_policy: dict[str, set[str]] = {}
    for r in ex.res:
        body = attrs(r.block.body)
        if r.type == "aws_iam_role_policy_attachment":
            roles = ex.refs(r.inst, body.get("role"))
            for policy in ex.refs(r.inst, body.get("policy_arn")):
                by_policy.setdefault(policy, set()).update(roles)
        elif not r.type.startswith("aws_iam_"):
            for key in ROLE_KEYS:
                for role in ex.leaf_refs(r.inst, body, key):
                    if ex.types.get(role) == "aws_iam_role":
                        by_role.setdefault(role, set()).add(r.address)
    return by_role, by_policy


def statements(inst: Inst, expr: Any) -> tuple[Inst, list[dict]] | None:
    """Statements of a policy expression plus the module instance its references resolve in."""
    s = expr if isinstance(expr, str) else ""
    if (m := LOCAL_ONLY.fullmatch(s)) and m[1] in inst.mod.locals:
        return statements(inst, inst.mod.locals[m[1]])
    if (m := VAR_ONLY.fullmatch(s)) and inst.parent is not None:
        passed = [a[m[1]] for a in inst.args if m[1] in a]
        found = [statements(inst.parent, expr) for expr in passed]
        return next((f for f in found if f), None) if passed else (inst, [])  # never passed: policy unset
    if m := DATA_DOC.search(s):
        blk = inst.mod.data.get(("aws_iam_policy_document", m[1]))
        if blk is None:
            return None
        dynamic = [c for d in blk.body.get("dynamic", []) for v in d.values() for c in v.get("content", [])]
        return inst, list(blk.body.get("statement", [])) + dynamic
    stmts = doc_statements(policy_doc(s, inst.mod.directory))
    return (inst, stmts) if stmts is not None else None


def iam(ex: Extractor, r: Res, by_role: dict[str, set[str]], by_policy: dict[str, set[str]]) -> None:
    body = attrs(r.block.body)
    roles = ex.refs(r.inst, body.get("role")) if r.type == "aws_iam_role_policy" else by_policy.get(r.address, set())
    who = sorted(set().union(*(by_role.get(role) or {role} for role in roles)) or {r.address})
    found = statements(r.inst, body.get("policy"))
    if found is None:
        ex.stats["unparsed_policies"] += 1
        return
    inst, stmts = found
    for raw in stmts:
        st = {unq(k).lower(): v for k, v in raw.items()}
        if unq(st.get("effect", '"Allow"')) != "Allow":
            continue
        acts = st.get("action", st.get("actions", []))
        actions = {unq(a) for a in (acts if isinstance(acts, list) else [acts]) if "${" not in text(a)}
        targets = ex.refs(inst, st.get("resource", st.get("resources", [])))
        if not targets:
            ex.stats["constructed_arns"] += '"*"' not in text(st.get("resource", st.get("resources")))
            for action in actions:
                entry = ex.services.setdefault(action.split(":")[0].lower(), {"actions": set(), "principals": set()})
                entry["actions"].add(action)
                entry["principals"].update(who)
        for src in who:
            for dst in targets:
                ex.add(src, dst, "iam", actions, r)


def permission_edges(ex: Extractor) -> None:
    by_role, by_policy = principals(ex)
    for r in ex.res:
        if r.type in POLICY_TYPES:
            iam(ex, r, by_role, by_policy)
