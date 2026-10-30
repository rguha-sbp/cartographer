"""Stage 1 of tfdiagram: Terraform folder -> facts.json. No HCL evaluation, only parsing and reference scanning."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import hcl2

from cartographer.tf_hints import collect_hints
from cartographer.tf_network import network_facts
from cartographer.tf_policies import OPTS, doc_statements, policy_doc, unq

REF = re.compile(r"(?<![\w.\-])([A-Za-z_]\w*)\.([A-Za-z_][\w-]*)(?:\[[^\]]*\])?(?:\.([A-Za-z_][\w-]*))?")
VAR_ONLY = re.compile(r"\$\{var\.(\w+)\}")
LOCAL_ONLY = re.compile(r"\$\{local\.(\w+)\}")
DATA_DOC = re.compile(r"data\.aws_iam_policy_document\.(\w+)")
HEADER = re.compile(r'^(resource|data)\s+"([^"]+)"\s+"([^"]+)"|^(module|output)\s+"([^"]+)"', re.MULTILINE)
META = {"source", "version", "providers", "for_each", "count", "depends_on"}
SKIP_ATTRS = {"tags", "depends_on", "provider", "lifecycle", "count", "for_each", "tags_all"}
NETWORK_ATTRS = {"vpc_config", "network_configuration", "subnet_ids", "security_group_ids", "subnet_id", "vpc_id"}
ROLE_KEYS = {"role", "execution_role_arn", "role_arn"}
# Types the curator folds into their owner; a `uses` edge touching one only restates the owner's wiring.
SUPPORT = re.compile(
    r"aws_(iam_(role|policy|role_policy|role_policy_attachment|instance_profile)|cloudwatch_log_group|kms_alias"
    r"|lambda_(alias|layer_version|function_event_invoke_config)|s3_bucket_(\w+_configuration|policy|versioning"
    r"|public_access_block|ownership_controls|logging))"
)
POLICY_TYPES = {"aws_iam_role_policy", "aws_iam_policy"}


@dataclass(frozen=True)
class Spec:
    """kind edge from refs of `src` (None = the resource itself) to refs of `dst`, optionally only under `leaf`."""

    kind: str
    src: str | None
    dst: str
    leaf: str | None = None


SPECS: dict[str, list[Spec]] = {
    "aws_cloudwatch_event_target": [Spec("trigger", "rule", "arn")],
    "aws_lambda_event_source_mapping": [Spec("trigger", "event_source_arn", "function_name")],
    "aws_s3_bucket_notification": [
        Spec("trigger", "bucket", a) for a in ("lambda_function", "queue", "topic")
    ],
    "aws_scheduler_schedule": [Spec("trigger", None, "target", "arn")],
    "aws_lambda_permission": [Spec("trigger", "source_arn", "function_name")],
    "aws_cloudfront_distribution": [Spec("route", None, "origin")],
    "aws_lambda_function_url": [Spec("route", None, "function_name")],
}


def text(obj: Any) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, default=str)


def attrs(body: dict) -> dict[str, Any]:
    return {k: v for k, v in body.items() if not k.startswith("__")}


@dataclass
class Block:
    body: dict
    file: str
    line: int


@dataclass
class Module:
    directory: Path
    resources: dict[tuple[str, str], Block] = field(default_factory=dict)
    data: dict[tuple[str, str], Block] = field(default_factory=dict)
    locals: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    calls: dict[str, Block] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)


def parse_module(directory: Path, repo_root: Path) -> Module:
    mod = Module(directory)
    for path in sorted(directory.glob("*.tf")):
        raw = path.read_text()
        rel = str(path.relative_to(repo_root))
        lines = {}
        for m in HEADER.finditer(raw):
            key = m.group(1, 2, 3) if m.group(1) else m.group(4, 5)
            lines[key] = raw.count("\n", 0, m.start()) + 1
        doc = hcl2.loads(raw, serialization_options=OPTS)
        for kind, target in (("resource", mod.resources), ("data", mod.data)):
            for item in doc.get(kind, []):
                for rtype, names in item.items():
                    for name, body in names.items():
                        t, n = unq(rtype), unq(name)
                        target[(t, n)] = Block(body, rel, lines.get((kind, t, n), 0))
        for item in doc.get("module", []):
            for name, body in item.items():
                mod.calls[unq(name)] = Block(body, rel, lines.get(("module", unq(name)), 0))
        for item in doc.get("output", []):
            for name, body in item.items():
                mod.outputs[unq(name)] = body.get("value")
        for item in doc.get("variable", []):
            for name, body in item.items():
                mod.variables[unq(name)] = body.get("default")
        for item in doc.get("locals", []):
            mod.locals.update(attrs(item))
    return mod


@dataclass(eq=False)
class Inst:
    mod: Module
    prefix: str
    args: list[dict[str, Any]]
    parent: Inst | None
    multi: bool
    instances: list[str] | None = None
    children: dict[str, Inst] = field(default_factory=dict)

    def walk(self) -> Iterator[Inst]:
        yield self
        done: set[int] = set()
        for name in sorted(self.children):
            if id(child := self.children[name]) not in done:
                done.add(id(child))
                yield from child.walk()


def local_source(blk: Block) -> str | None:
    source = unq(blk.body.get("source", ""))
    return source if source.startswith(("./", "../")) else None


def build(directory: Path, repo_root: Path, prefix: str, args: list, parent: Inst | None, multi: bool,
          depth: int = 0, instances: list[str] | None = None) -> Inst:
    """Instantiate a module. Calls of one local source in the same parent collapse into one `module.<family>` instance."""
    inst = Inst(parse_module(directory, repo_root), prefix, args, parent, multi, instances)
    by_dir: dict[Path, list[str]] = {}
    for name, blk in inst.mod.calls.items():
        if depth < 8 and (source := local_source(blk)):
            by_dir.setdefault((directory / source).resolve(), []).append(name)
    for target, names in by_dir.items():
        calls = [inst.mod.calls[n] for n in names]
        family = len(names) > 1
        label = names[0]
        if family:
            label = f"{target.name}-family" if target.name in inst.mod.calls and target.name not in names else target.name
        child = build(
            target, repo_root, f"{prefix}module.{label}.",
            [{k: v for k, v in attrs(c.body).items() if k not in META} for c in calls], inst,
            multi or family or any("count" in c.body or "for_each" in c.body for c in calls), depth + 1,
            sorted(names) if family else None,
        )
        inst.children.update(dict.fromkeys(names, child))
    return inst


@dataclass
class Res:
    address: str
    type: str
    inst: Inst
    block: Block
    multi: bool
    extra: dict[str, Any] = field(default_factory=dict)


def remote_info(blk: Block) -> dict[str, str]:
    """Remote module source without ?ref= query or credentials, plus its version when pinned."""
    source = re.sub(r"(://)[^/@]*@", r"\1", unq(blk.body.get("source", ""))).split("?")[0]
    return {"source": source, **({"version": unq(blk.body["version"])} if "version" in blk.body else {})}


class Extractor:
    def __init__(self, infra_dir: Path, repo_root: Path) -> None:
        self.infra_dir = infra_dir
        self.repo_root = repo_root.resolve()
        root = build((repo_root / infra_dir).resolve(), repo_root, "", [], None, False)
        self.res: list[Res] = []
        self.insts = list(root.walk())
        for inst in self.insts:
            for (rtype, name), blk in inst.mod.resources.items():
                self.res.append(Res(f"{inst.prefix}{rtype}.{name}", rtype, inst, blk, inst.multi or self.is_multi(blk)))
            for name, blk in inst.mod.calls.items():
                if name not in inst.children:
                    self.res.append(Res(f"{inst.prefix}module.{name}", "module", inst, blk,
                                    inst.multi or self.is_multi(blk), remote_info(blk)))
        self.res.sort(key=lambda r: r.address)
        self.types = {r.address: r.type for r in self.res}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.services: dict[str, dict[str, set[str]]] = {}
        self.stats = {"unparsed_policies": 0, "constructed_arns": 0, "missing_outputs": 0}

    @staticmethod
    def is_multi(blk: Block) -> bool:
        return "count" in blk.body or "for_each" in blk.body

    def refs(self, inst: Inst, obj: Any, seen: set | None = None) -> set[str]:
        seen = set() if seen is None else seen
        out: set[str] = set()
        for m in REF.finditer(text(obj)):
            head, second, third = m.groups()
            key = (id(inst), head, second, third)
            if key in seen:
                continue
            seen.add(key)
            if head == "var" and inst.parent is not None:
                for args in inst.args:
                    if second in args:
                        out |= self.refs(inst.parent, args[second], seen)
            elif head == "local" and second in inst.mod.locals:
                out |= self.refs(inst, inst.mod.locals[second], seen)
            elif head == "module" and second in inst.children and third:
                child = inst.children[second]
                if third in child.mod.outputs:
                    out |= self.refs(child, child.mod.outputs[third], seen)
                else:
                    self.stats["missing_outputs"] += 1
            elif head == "module" and second in inst.mod.calls and second not in inst.children:
                out.add(f"{inst.prefix}module.{second}")
            elif head == "data" and second == "aws_iam_policy_document" and third:
                blk = inst.mod.data.get((second, third))
                out |= self.refs(inst, blk.body, seen) if blk else set()
            elif (head, second) in inst.mod.resources:
                out.add(f"{inst.prefix}{head}.{second}")
        return out

    def leaf_refs(self, inst: Inst, obj: Any, leaf: str | None) -> set[str]:
        if leaf is None:
            return self.refs(inst, obj)
        if isinstance(obj, dict):
            return set().union(*(self.leaf_refs(inst, v, leaf) if k != leaf else self.refs(inst, v) for k, v in obj.items()))
        if isinstance(obj, list):
            return set().union(*(self.leaf_refs(inst, v, leaf) for v in obj))
        return set()

    def add(self, src: str, dst: str, kind: str, details: set[str], r: Res) -> None:
        if src == dst:
            return
        edge = self.edges.setdefault((src, dst, kind), {"detail": set(), "at": (r.block.file, r.block.line)})
        edge["detail"] |= details
        edge["at"] = min(edge["at"], (r.block.file, r.block.line))

    def principals(self) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        by_role: dict[str, set[str]] = {}
        by_policy: dict[str, set[str]] = {}
        for r in self.res:
            body = attrs(r.block.body)
            if r.type == "aws_iam_role_policy_attachment":
                roles = self.refs(r.inst, body.get("role"))
                for policy in self.refs(r.inst, body.get("policy_arn")):
                    by_policy.setdefault(policy, set()).update(roles)
            elif not r.type.startswith("aws_iam_"):
                for key in ROLE_KEYS:
                    for role in self.leaf_refs(r.inst, body, key):
                        if self.types.get(role) == "aws_iam_role":
                            by_role.setdefault(role, set()).add(r.address)
        return by_role, by_policy

    def statements(self, inst: Inst, expr: Any) -> tuple[Inst, list[dict]] | None:
        """Statements of a policy expression plus the module instance its references resolve in."""
        s = expr if isinstance(expr, str) else ""
        if (m := LOCAL_ONLY.fullmatch(s)) and m[1] in inst.mod.locals:
            return self.statements(inst, inst.mod.locals[m[1]])
        if (m := VAR_ONLY.fullmatch(s)) and inst.parent is not None:
            passed = [a[m[1]] for a in inst.args if m[1] in a]
            found = [self.statements(inst.parent, expr) for expr in passed]
            return next((f for f in found if f), None) if passed else (inst, [])  # never passed: policy unset
        if m := DATA_DOC.search(s):
            blk = inst.mod.data.get(("aws_iam_policy_document", m[1]))
            if blk is None:
                return None
            dynamic = [c for d in blk.body.get("dynamic", []) for v in d.values() for c in v.get("content", [])]
            return inst, list(blk.body.get("statement", [])) + dynamic
        stmts = doc_statements(policy_doc(s, inst.mod.directory))
        return (inst, stmts) if stmts is not None else None

    def iam(self, r: Res, by_role: dict[str, set[str]], by_policy: dict[str, set[str]]) -> None:
        body = attrs(r.block.body)
        roles = self.refs(r.inst, body.get("role")) if r.type == "aws_iam_role_policy" else by_policy.get(r.address, set())
        who = sorted(set().union(*(by_role.get(role) or {role} for role in roles)) or {r.address})
        found = self.statements(r.inst, body.get("policy"))
        if found is None:
            self.stats["unparsed_policies"] += 1
            return
        inst, stmts = found
        for raw in stmts:
            st = {unq(k).lower(): v for k, v in raw.items()}
            if unq(st.get("effect", '"Allow"')) != "Allow":
                continue
            acts = st.get("action", st.get("actions", []))
            actions = {unq(a) for a in (acts if isinstance(acts, list) else [acts]) if "${" not in text(a)}
            targets = self.refs(inst, st.get("resource", st.get("resources", [])))
            if not targets:
                self.stats["constructed_arns"] += '"*"' not in text(st.get("resource", st.get("resources")))
                for action in actions:
                    entry = self.services.setdefault(action.split(":")[0].lower(), {"actions": set(), "principals": set()})
                    entry["actions"].add(action)
                    entry["principals"].update(who)
            for src in who:
                for dst in targets:
                    self.add(src, dst, "iam", actions, r)

    def generic(self, r: Res) -> None:
        body = attrs(r.block.body)
        consumed = {"policy"} if r.type in POLICY_TYPES else set()
        for spec in SPECS.get(r.type, []):
            srcs = self.refs(r.inst, body.get(spec.src)) if spec.src else {r.address}
            dsts = self.leaf_refs(r.inst, body.get(spec.dst), spec.leaf)
            consumed |= {spec.src, spec.dst}
            for src in sorted(srcs):
                for dst in sorted(dsts):
                    self.add(src, dst, spec.kind, {spec.dst}, r)
        for attr, value in body.items():
            if attr in consumed or attr in SKIP_ATTRS or (r.type == "module" and attr in META):
                continue
            kind = "network" if attr in NETWORK_ATTRS else "uses"
            for dst in sorted(self.refs(r.inst, value)):
                if kind == "network" or not (SUPPORT.fullmatch(r.type) or SUPPORT.fullmatch(self.types.get(dst, ""))):
                    self.add(r.address, dst, kind, {attr}, r)

    def run(self) -> dict:
        by_role, by_policy = self.principals()
        for r in self.res:
            self.generic(r)
            if r.type in POLICY_TYPES:
                self.iam(r, by_role, by_policy)
        edges = []
        for i, ((src, dst, kind), e) in enumerate(sorted(self.edges.items())):
            edges.append({"id": f"f{i + 1}", "src": src, "dst": dst, "kind": kind,
                          "detail": ",".join(sorted(e["detail"])), "file": e["at"][0], "line": e["at"][1]})
        return {
            "infra_dir": str(self.infra_dir),
            "resources": [
                {"address": r.address, "type": r.type, "module": r.inst.prefix.rstrip("."), "multi": r.multi,
                 "file": r.block.file, "line": r.block.line, **r.extra,
                 **({"instances": r.inst.instances} if r.inst.instances else {})}
                for r in self.res
            ],
            "edges": edges,
            **collect_hints(self.insts, self.res, self.repo_root),
            **network_facts(self),
            "services": [
                {"service": s, "actions": sorted(v["actions"]), "principals": sorted(v["principals"])}
                for s, v in sorted(self.services.items())
            ],
        }


def extract(infra_dir: Path, repo_root: Path) -> dict:
    return Extractor(infra_dir, repo_root).run()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_root", type=Path)
    ap.add_argument("infra_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()
    ex = Extractor(args.infra_dir, args.repo_root)
    facts = ex.run()
    args.out.write_text(json.dumps(facts, indent=1, sort_keys=True) + "\n")
    print(f"{len(facts['resources'])} resources, {len(facts['edges'])} edges, stats={ex.stats}", file=sys.stderr)


if __name__ == "__main__":
    main()
